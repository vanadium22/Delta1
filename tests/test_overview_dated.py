"""Dated dividend replay, immutable cache versions and non-trading references."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from dashboard.marketdata.overview_dividends import DatedDividendBook, DividendStore, DerivedCache, records_from_file
from dashboard.marketdata.overview_dividend_sync import stage_inputs, run_sync
from dashboard.marketdata.overview_percentiles import prepare, evaluate, requirements
from dashboard.native.market_overview import futures_values
from dashboard.native.futures_overview import previous_basis_change
from dashboard.native.overview_dividend_job import DividendJob
from tests.test_overview_percentiles import metadata, daily_data, DAY


def record(symbol, points, at, revision=None):
    return dict(contract_id=symbol, points=points, effective_from=at,
        source_business_date=at[:10], effective_date=at[:10], precision='minute',
        file_sha256=revision or at+symbol, revision=revision or at+symbol)


def snapshot(path):
    payload=json.loads(Path(path).read_text(encoding='utf8'))
    return dict(date=payload['day'],file_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        rows=[dict(alias=root+'0'+str(slot)+'.CFE',source_contract=root+month+'.CFE',points=payload['points'])
            for root in ('IF','IH','IC','IM') for slot,month in enumerate(('2611','2612','2703','2706'))])


def source(root, name, day, points):
    path=Path(root)/name
    path.write_text(json.dumps(dict(day=day,points=points)),encoding='utf8')
    return path


class DatedDividendTests(unittest.TestCase):
    def test_exact_contract_zero_and_no_future_or_later_expiry_fallback(self):
        book=DatedDividendBook([record('IF2610.CFE',2,'2026-09-18T00:00:00+08:00'),
            record('IF2611.CFE',0,'2026-10-27T09:00:00+08:00')],metadata())
        self.assertEqual(book.points('IF2611.CFE','2026-10-26'),2)
        self.assertEqual(book.resolve('IF2611.CFE','2026-10-26')['inherited_from'],'IF2610.CFE')
        self.assertEqual(book.points('IF2611.CFE','2026-10-27'),0)
        self.assertIsNone(book.points('IF2608.CFE','2026-07-28'))
        self.assertIsNone(book.points('IH2611.CFE',DAY))
        self.assertIsNone(book.points('IF2610.CFE','2026-10-27'))

    def test_am_pm_and_new_day_revisions_never_reprice_past(self):
        old=record('IF2611.CFE',1,'2026-10-26T09:00:00+08:00')
        am=record('IF2611.CFE',2,'2026-10-27T09:00:00+08:00')
        pm=record('IF2611.CFE',3,'2026-10-27T14:00:00+08:00')
        before=DatedDividendBook([old,am],metadata());after=DatedDividendBook([old,am,pm],metadata())
        self.assertEqual(after.points('IF2611.CFE','2026-10-26'),1)
        self.assertEqual(after.points('IF2611.CFE','2026-10-27T13:59:59+08:00'),2)
        self.assertEqual(after.points('IF2611.CFE','2026-10-27T14:00:00+08:00'),3)
        needed=[dict(symbol='IF2611.CFE',day='2026-10-26')]
        self.assertEqual(before.history_version(needed),after.history_version(needed))

    def test_ambiguous_date_only_values_are_not_arbitrarily_ordered(self):
        at='2026-10-27T00:00:00+08:00'
        book=DatedDividendBook([record('IF2611.CFE',1,at,'a'),record('IF2611.CFE',2,at,'b')],metadata())
        self.assertIsNone(book.points('IF2611.CFE',DAY))
        self.assertIn('冲突',book.resolve('IF2611.CFE',DAY)['reason'])

    def test_store_archives_revisions_deduplicates_and_closes_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp, patch('dashboard.marketdata.overview_dividends.read_snapshot',side_effect=snapshot) as parse:
            root=Path(tmp);path=source(root,'指数基差情况_2026-10-27.xlsx',DAY,1)
            store=DividendStore(root/'cache');morning=datetime.fromisoformat(DAY+'T09:00:00+08:00')
            self.assertEqual(store.import_file(path,now=morning)['inserted'],16)
            self.assertEqual(store.import_file(path,now=morning)['status'],'unchanged');self.assertEqual(parse.call_count,1)
            old_raw=next((root/'cache/raw'/DAY).glob('*.xlsx')).read_bytes()
            source(root,path.name,DAY,2)
            store.import_file(path,now=datetime.fromisoformat(DAY+'T14:00:00+08:00'))
            book=DatedDividendBook(store.read(),metadata())
            self.assertEqual(book.points('IF2611.CFE',DAY+'T13:00:00+08:00'),1)
            self.assertEqual(book.points('IF2611.CFE',DAY+'T14:00:00+08:00'),2)
            self.assertEqual(len(list((root/'cache/raw'/DAY).glob('*.xlsx'))),2)
            self.assertIn(old_raw,[p.read_bytes() for p in (root/'cache/raw'/DAY).glob('*.xlsx')])
            store.path.rename(store.path.with_suffix('.moved'))

    def test_share_unchanged_metadata_does_not_read_or_copy_file_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);share=root/'share';share.mkdir();staging=root/'stage'
            path=source(share,'指数基差情况_2026-10-27.xlsx',DAY,1)
            args=dict(directories=[str(share)],staging=str(staging),pattern='指数基差情况_*.xlsx',
                start='2026-07-01',end=DAY,inventory={},known_hashes=[])
            first=stage_inputs(args);item=first['files'][0]
            args.update(inventory={str(path):{k:item[k] for k in ('token','sha256')}},known_hashes=[item['sha256']])
            with patch.object(Path,'read_bytes',side_effect=AssertionError('unchanged file read')):
                second=stage_inputs(args)
            self.assertEqual(second['unchanged'],1);self.assertEqual(second['files'],[])

    def test_sync_merges_old_and_new_inputs_without_writing_sources(self):
        with tempfile.TemporaryDirectory() as tmp, patch('dashboard.marketdata.overview_dividends.read_snapshot',side_effect=snapshot):
            root=Path(tmp);share=root/'share';share.mkdir();local=root/'local';local.mkdir()
            old=source(local,'old.xlsx','2026-10-26',1);new=source(share,'指数基差情况_2026-10-27_1400.xlsx',DAY,2)
            hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (old,new)}
            config=dict(dividend_root=str(local),overview_dividend_source_dir=str(share))
            result=run_sync(config,root,now=datetime.fromisoformat(DAY+'T16:00:00+08:00'),reader=stage_inputs)
            self.assertEqual(result['status'],'complete');self.assertEqual(result['inserted'],32)
            book=DatedDividendBook(DividendStore(root/'overview_dividends').read(),metadata())
            self.assertEqual(book.points('IF2611.CFE','2026-10-26'),1)
            self.assertEqual(book.points('IF2611.CFE',DAY+'T13:00:00+08:00'),1)
            self.assertEqual(book.points('IF2611.CFE',DAY+'T14:00:00+08:00'),2)
            self.assertEqual(hashes,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes})

    def test_full_continuous_windows_use_old_actual_contract_dividends(self):
        meta=metadata();data=daily_data(meta)
        rows=[record(s,0,'2026-07-01T00:00:00+08:00') for s in meta]
        book=DatedDividendBook(rows,meta)
        for root in ('IF','IH','IC','IM'):
            for slot in range(4):
                history=prepare(root,slot,meta,data,DAY,dividends=book)
                checked=evaluate(history,0,history['current_symbol'])
                self.assertTrue(checked['windows']['60']['complete'])
                self.assertEqual(checked['windows']['60']['percentile'],50)
        history=prepare('IF',0,meta,data,DAY,dividends=book)
        self.assertTrue(any(r['symbol']=='IF2608.CFE' for r in history['rows']))

    def test_cancel_retains_completed_local_import_and_reports_it_honestly(self):
        with tempfile.TemporaryDirectory() as tmp, patch('dashboard.marketdata.overview_dividends.read_snapshot',side_effect=snapshot):
            root=Path(tmp);local=root/'inputs';local.mkdir();source(local,'old.xlsx','2026-10-26',1)
            stop=root/'stop'
            def cancel(request):
                stop.write_text('stop',encoding='utf8');raise InterruptedError()
            result=run_sync(dict(dividend_root=str(local),overview_dividend_source_dir='explicit-fixture'),root,
                now=datetime.fromisoformat(DAY+'T16:00:00+08:00'),stop_file=stop,reader=cancel)
            self.assertEqual(result['status'],'cancelled');self.assertEqual(result['inserted'],16)
            self.assertTrue(result['published']);self.assertFalse(result['configuration_changed'])
            self.assertEqual(len(DividendStore(root/'overview_dividends').read()),16)

    def test_real_publisher_module_launches_private_reader_without_interfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);share=root/'empty share';share.mkdir()
            (root/'native.json').write_text(json.dumps(dict(overview_dividend_source_dir=str(share))),encoding='utf8')
            result=subprocess.run([sys.executable,'-B','-X','utf8','-m','dashboard.marketdata.overview_dividend_sync','--local-root',str(root)],
                capture_output=True,text=True,encoding='utf8',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(result.returncode,0)
            status=json.loads((root/'overview_dividends/status.json').read_text(encoding='utf8'))
            self.assertEqual(status['status'],'source_empty')
            self.assertEqual(status['source_files'],0);self.assertFalse(status['errors'])

    def test_derived_cache_reuses_unchanged_past_and_keeps_new_revision_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=DerivedCache(tmp,writable=True);old=record('IF2611.CFE',1,'2026-10-26T09:00:00+08:00')
            first=cache.calculate('IF2611.CFE','2026-10-26',990,1000,1,25,dividend_record=old);cache.flush()
            cached=DerivedCache(tmp,writable=True)
            with patch('dashboard.marketdata.overview_basis.calculate',side_effect=AssertionError('recomputed history')):
                self.assertEqual(cached.calculate('IF2611.CFE','2026-10-26',990,1000,1,25,dividend_record=old),first)
            self.assertEqual(cached.hits,1)
            newer=cached.calculate('IF2611.CFE',DAY,990,1000,2,24,dividend_record=record('IF2611.CFE',2,DAY+'T09:00:00+08:00'))
            self.assertNotEqual(first['points'],newer['points']);cached.flush()
            self.assertEqual(len(DerivedCache(tmp).rows),2)

    def test_bad_derived_cache_preserves_file_and_keeps_calculation_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'derived.sqlite';path.write_bytes(b'broken cache retained')
            before=path.read_bytes();cache=DerivedCache(tmp,writable=True)
            value=cache.calculate('IF2611.CFE',DAY,990,1000,1,24)
            self.assertIsNotNone(value['annual_pct']);cache.flush()
            self.assertTrue(cache.error_type);self.assertEqual(path.read_bytes(),before)


class NonTradingReferenceTests(unittest.TestCase):
    def test_cached_pair_is_reference_without_relaxing_realtime_quality(self):
        source_time='2026-10-28T15:00:00+08:00';now=pd.Timestamp('2026-10-28T18:00:00+08:00')
        live={s:dict(close=p,prev_close=p-1,source_event_time=source_time,observed_at=source_time)
            for s,p in [('IF2611.CFE',3990.),('000300.SH',4000.)]}
        row=dict(symbol='IF2611.CFE',root='IF');book=DatedDividendBook([record('IF2611.CFE',1,'2026-10-27T09:00:00+08:00')],metadata())
        futures_values(row,live,{},metadata(),now,dividends=book)
        self.assertAlmostEqual(row['annual_pct'],-9/4000*365/23*100)
        self.assertEqual(row['basis_kind'],'cached_pair');self.assertFalse(row['quality']['usable'])
        self.assertEqual(row['pricing_day'],'2026-10-28');self.assertEqual(row['source_at'],source_time)
        live['000300.SH']['observed_at']='2026-10-28T15:00:04+08:00'
        futures_values(row,live,{},metadata(),now,dividends=book)
        self.assertIsNone(row['annual_pct'])

    def test_latest_common_close_overrides_misaligned_individual_latest_days(self):
        daily={s:pd.DataFrame([dict(trade_date=d,event_time=pd.Timestamp(d+'T15:00:00+08:00'),close=p,is_final=True)
            for d in dates]) for s,p,dates in [('IF2611.CFE',990.,['2026-10-23','2026-10-26']),('000300.SH',1000.,['2026-10-23','2026-10-27'])]}
        row=dict(symbol='IF2611.CFE',root='IF')
        book=DatedDividendBook([record('IF2611.CFE',1,'2026-10-22T09:00:00+08:00')],metadata())
        futures_values(row,{},daily,metadata(),pd.Timestamp('2026-10-28T08:00:00+08:00'),dividends=book)
        self.assertEqual(row['pricing_day'],'2026-10-23');self.assertEqual(row['basis_points'],-9)

    def test_yesterday_basis_uses_yesterdays_dividend_version(self):
        book=DatedDividendBook([record('IF2611.CFE',1,'2026-10-26T09:00:00+08:00'),record('IF2611.CFE',3,DAY+'T09:00:00+08:00')],metadata())
        row=dict(symbol='IF2611.CFE',basis_points=-7,prev_close=990,basis_prev_day='2026-10-26')
        self.assertEqual(previous_basis_change(row,dict(prev_close=1000),book),2)

    def test_scheduler_restarts_do_not_repeat_successful_am_or_pm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);process=Mock();process.poll.return_value=None
            job=DividendJob(root);config=dict(overview_dividend_source_dir='explicit-test')
            with patch('dashboard.native.overview_dividend_job.subprocess.Popen',return_value=process) as launch:
                job.tick(config,enabled=True,now=datetime.fromisoformat(DAY+'T09:01:00+08:00'))
                self.assertEqual(launch.call_count,1)
                process.poll.return_value=0
                (root/'overview_dividends/status.json').write_text('{"status":"complete"}',encoding='utf8')
                job.tick(config,enabled=True,now=datetime.fromisoformat(DAY+'T09:02:00+08:00'))
                other=DividendJob(root);other.tick(config,enabled=True,now=datetime.fromisoformat(DAY+'T10:00:00+08:00'))
                self.assertEqual(launch.call_count,1)
                process.poll.return_value=None
                other.tick(config,enabled=True,now=datetime.fromisoformat(DAY+'T15:31:00+08:00'))
                self.assertEqual(launch.call_count,2)
                other.stop();self.assertTrue((root/'overview_dividends/stop.request').exists())
                self.assertFalse(process.terminate.called);self.assertFalse(process.kill.called)


if __name__=='__main__':unittest.main()
