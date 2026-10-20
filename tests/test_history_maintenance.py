from datetime import date
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch,Mock

import pandas as pd

from dashboard.marketdata.bars import BarDataset,_json_bytes,_atomic_bytes
from dashboard.marketdata.history_publication import maintenance_root,publish,read_publication
from dashboard.marketdata import history_maintenance as hm
from dashboard.marketdata.repository import MarketDataRepository
from dashboard.marketdata.trading_calendar import trading_days,parse_announcement,CalendarUnavailable


def bar(symbol='000300.SH',freq='1m',day='2026-10-16',minute=571,**updates):
    return dict(instrument_id=symbol,source_symbol=symbol,frequency=freq,trade_date=date.fromisoformat(day),
        event_time=pd.Timestamp(day,tz='Asia/Shanghai')+pd.Timedelta(minutes=900 if freq=='1d' else minute),
        recorded_at=pd.Timestamp('2026-10-19T02:00Z'),available_at=None,is_final=True,revision=0,quality_flags=8,
        open=4000.,high=4001.,low=3999.,close=4000.,volume=10.,turnover=40000.,**updates)


class SourceSession:
    """Only the DDB transport is synthetic; routing, fetch and import remain real."""
    def __init__(self, *, drift=False, count_changed=False, duplicate=False):
        self.variables={};self.queries=[];self.routes=set();self.closed=False
        self.drift=drift;self.count_changed=count_changed;self.duplicate=duplicate
        self.connect=Mock(return_value=True)

    def upload(self, values):
        self.variables.update(values)

    def close(self):
        self.closed=True

    def run(self, query):
        from index_strategy.history.catalog import sources,field_map
        self.queries.append(query)
        source=next(s for s in sources() if (s['db'],s['table'])==
            (self.variables['downloadDb'],self.variables['downloadTable']))
        if query.startswith('schema('):
            names=[c['name'] for c in source['columns']]
            return pd.DataFrame({'name':names[1:] if self.drift else names})
        if query.startswith('downloadSource ='):
            return None
        daily=source['frequency']=='1d'
        code=self.variables['downloadCode']
        if ('.' in code)!=daily:
            raise AssertionError('Daily needs full symbol; minute needs exchange-free code')
        self.routes.add((source['kind'],source['frequency']))
        day=pd.Timestamp(self.variables['downloadDate'])
        minutes=[0] if daily else sorted(hm.MINUTES)
        frame=pd.DataFrame({'trading_date':[day]*len(minutes),
            'timestamp':[day+pd.Timedelta(minutes=m) for m in minutes]})
        mapping,_=field_map(source,asset='future' if source['kind']=='ff' else 'index',depth=0,oi=True)
        values=dict(open=4000.,high=4001.,low=3999.,close=4000.,volume=0.,amount=2.,oi=37.,volume_total=0.)
        for name in mapping:frame[name]=values[name]
        if self.duplicate:frame=pd.concat([frame,frame.iloc[:1]],ignore_index=True)
        if query.startswith('exec count(*)'):
            return len(frame)+int(self.count_changed)
        if query.startswith('select '):return frame
        raise AssertionError(query)


class HistoryMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.local=Path(self.tmp.name)/'localsetting';self.local.mkdir()
        self.metadata={}
        for product in hm.UNDERLYINGS:
            for month in ('2610','2611','2612','2703','2706'):
                self.metadata[product+month+'.CFE']=dict(instrument_id=product+month+'.CFE',listing_date='2026-10-19' if month=='2706' else '2026-01-01',
                    expiry_date='2026-10-16' if month=='2610' else '2027-06-18',known_at='2026-10-19T00:00Z')
        self.stores={}
        for key,kind,symbols in [('indexes','cn_index',hm.INDEXES),('futures','cn_index_future',self.metadata)]:
            self.stores[key]=BarDataset.create(Path(self.tmp.name)/'data'/key,dict(dataset_id=key,source_id='test',series_kind='concrete',
                price_adjustment='none',volume_unit='contracts',availability_policy='unknown',
                instruments={s:dict(asset_type=kind,market_region='CN') for s in symbols}))
        ref=self.local/'reference.json';_atomic_bytes(ref,_json_bytes({'contracts':list(self.metadata.values())}))
        self.config=dict(history_roots=[str(s.root) for s in self.stores.values()],reference_file=str(ref),history_start='2026-10-16')
        _atomic_bytes(self.local/'native.json',_json_bytes(self.config))
        self.root=maintenance_root(self.config['history_roots']);self.client=Mock()

    def cycle(self,fetcher=None,**kw):
        return hm.run_cycle(self.local,force=True,direct_factory=lambda _:self.client,
            fetcher=fetcher or self.full_fetch,today='2026-10-19',**kw)

    def full_fetch(self,client,job,destination):
        minutes=[900] if job['frequency']=='1d' else sorted(hm.MINUTES)
        return [bar(job['symbol'],job['frequency'],job['day'],m) for m in minutes],None

    def test_direct_query_to_published_history_all_four_routes(self):
        session=SourceSession()
        sdk=types.SimpleNamespace(session=Mock(return_value=session))
        credentials=dict(host='fixture.invalid',port=1,username='fixture',password='test-only')
        with patch.dict('sys.modules',{'dolphindb':sdk}),\
             patch('socket.create_connection'),\
             patch('index_strategy.history.credentials.load_config',return_value=credentials),\
             patch('index_strategy.history.downloader.Client.__init__') as constructor:
            result=hm.run_cycle(self.local,force=True,today='2026-10-19')
        constructor.assert_not_called()
        self.assertEqual(result['state'],'complete')
        self.assertEqual(result['inserted'],20*241)
        self.assertEqual(len(session.routes),4)
        self.assertTrue(session.closed)
        self.assertEqual(session.connect.call_args.kwargs,dict(readTimeout=15,writeTimeout=10))
        pointer=self.root/'publication.json'
        repo=MarketDataRepository(self.config['history_roots'],publication=pointer,allow_unverified=True)
        snapshots=repo.freeze()
        self.assertEqual(sum(len(s['parts']) for s in snapshots.values()),40)
        for key,store in self.stores.items():
            rows=store._rows(store.snapshot())
            self.assertEqual(len(rows), (16 if key=='futures' else 4)*241)
            for row in rows:
                factor=(10000 if key=='futures' else 1000) if row['frequency']=='1d' else 1
                self.assertEqual(row['turnover'],2*factor)
                self.assertEqual(row['volume'],0)
                self.assertEqual(str(row['trade_date']),'2026-10-16')
                self.assertEqual(row['source_symbol'],row['instrument_id'])
                self.assertIsNotNone(hm.valid_slot(row,row['instrument_id'],row['frequency'],'2026-10-16'))

    def test_direct_query_rejects_schema_drift_and_changed_row_count(self):
        from index_strategy.history.downloader import Client
        for option in ('drift','count_changed'):
            with self.subTest(option=option):
                client=Client.__new__(Client)
                client.session=SourceSession(**{option:True});client.source_cache=set()
                with self.assertRaises(RuntimeError):
                    hm.fetch_job(client,dict(symbol='IF2611.CFE',frequency='1d',day='2026-10-16'),self.root)
        self.assertFalse((self.root/'downloads').exists())

    def test_direct_query_duplicate_rows_do_not_reach_import(self):
        from index_strategy.history.downloader import Client
        client=Client.__new__(Client)
        client.session=SourceSession(duplicate=True);client.source_cache=set()
        with self.assertRaisesRegex(ValueError,'duplicate_source_rows'):
            hm.fetch_job(client,dict(symbol='000300.SH',frequency='1m',day='2026-10-16'),self.root)
        self.assertFalse((self.root/'downloads').exists())

    def test_calendar_holiday_cutoff_after_close_and_unknown_year(self):
        for today,expected in [('2026-10-19','2026-10-16'),('2026-10-17','2026-10-16'),('2026-10-08','2026-09-30'),('2026-02-24','2026-02-13')]:
            days,end=trading_days('2026-01-01',today,self.root)
            self.assertEqual(end,expected);self.assertNotIn(today,days)
        with patch('dashboard.marketdata.trading_calendar.load_year',side_effect=CalendarUnavailable()):
            with self.assertRaises(CalendarUnavailable):trading_days('2027-01-01','2027-01-04',self.root)

    def test_calendar_parser_rejects_partial_notice(self):
        with self.assertRaises(CalendarUnavailable):parse_announcement('2027年部分节假日休市安排（一）元旦：1月1日至1月3日休市。',2027)

    def test_whole_absent_day_new_listing_and_unique_minutes(self):
        row=bar();duplicate={**row,'revision':1}
        self.stores['indexes'].commit([row,duplicate])
        snapshots={k:s.snapshot() for k,s in self.stores.items()}
        coverage,cache=hm.scan(self.stores,snapshots,{})
        jobs,summary=hm.plan(coverage,self.metadata,['2026-10-16'],'2026-10-16','2026-10-16')
        self.assertEqual(len(jobs),40)
        self.assertFalse(any('2706' in j['symbol'] for j in jobs))
        job=next(j for j in jobs if j['symbol']=='000300.SH' and j['frequency']=='1m')
        self.assertEqual(job['missing'],239)
        self.assertEqual(next(s for s in summary if s['symbol']=='000300.SH' and s['frequency']=='1m')['complete_through'],None)

    def test_network_wait_does_not_call_vpn_and_does_not_publish_bars(self):
        with patch('index_strategy.history.credentials.load_config',return_value=dict(host='internal',port=1)),\
             patch('socket.create_connection',side_effect=TimeoutError('SECRET_ENDPOINT')),\
             patch('index_strategy.history.downloader.Client.__init__') as constructor:
            result=hm.run_cycle(self.local,force=True,today='2026-10-19')
        self.assertEqual(result['state'],'waiting_network');constructor.assert_not_called()
        self.assertEqual(result['pending_symbol_days'],40)
        self.assertNotIn('SECRET_ENDPOINT',(self.root/'status.json').read_text(encoding='utf8'))
        self.assertTrue(all(s.snapshot()['version'] is None for s in self.stores.values()))

    def test_complete_publish_idempotency_and_old_frozen_reader(self):
        pointer=self.root/'publication.json';publish(pointer,self.stores,{k:s.snapshot() for k,s in self.stores.items()})
        repo=MarketDataRepository(self.config['history_roots'],publication=pointer,allow_unverified=True)
        old=repo.freeze();result=self.cycle()
        self.assertEqual(result['state'],'complete');self.assertEqual(result['inserted'],20*241)
        self.assertEqual(sum(len(s['parts']) for s in old.values()),0)
        frozen=repo.freeze();self.assertEqual(sum(len(s['parts']) for s in frozen.values()),40)
        versions={k:s['version'] for k,s in frozen.items()}
        fetch=Mock(side_effect=AssertionError('must not refetch'))
        result=self.cycle(fetch)
        self.assertEqual(result['state'],'complete');fetch.assert_not_called()
        self.assertEqual(versions,{k:s['version'] for k,s in repo.freeze().items()})

    def test_source_lag_does_not_starve_other_jobs_and_retry_persists(self):
        calls=[]
        def empty(c,j,d):calls.append(hm.job_key(j));return [],None
        result=self.cycle(empty,limit=1)
        self.assertEqual(result['state'],'partial');first=calls[0]
        hm.run_cycle(self.local,force=False,fetcher=empty,direct_factory=lambda _:self.client,today='2026-10-19')
        # Immediate automatic run respects cycle cooldown.
        self.assertEqual(len(calls),1)
        state=hm.read_json(self.root/'status.json');state['next_retry']=0;_atomic_bytes(self.root/'status.json',_json_bytes(state))
        hm.run_cycle(self.local,force=False,limit=1,fetcher=empty,direct_factory=lambda _:self.client,today='2026-10-19')
        self.assertNotEqual(calls[-1],first)
        self.assertEqual(hm.read_json(self.root/'jobs.json')[first]['attempts'],1)

    def test_conflicts_preserve_existing_bar_and_mark_review(self):
        store=self.stores['indexes'];store.commit([bar()]);before=store.snapshot()['version']
        job=dict(symbol='000300.SH',frequency='1m',day='2026-10-16')
        changed={**bar(),'close':4001.}
        with self.assertRaises(hm.SourceConflict):hm.merge_missing(store,store.snapshot(),job,[changed,bar(minute=572)])
        self.assertEqual(store.snapshot()['version'],before)

    def test_explicit_preservation_fills_only_missing_keys_and_keeps_source_notes(self):
        store=self.stores['indexes'];original={**bar(),'close':4001.}
        store.commit([original]);before=store.snapshot()['version']
        strict=self.cycle();self.assertEqual(strict['pending_symbol_days'],1)
        result=self.cycle(preserve_existing=True)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['inserted'],239)
        rows=hm.latest_rows(store._rows(store.snapshot()))
        self.assertEqual(rows[hm._row_key(original)]['close'],4001.)
        notes=hm.read_json(self.root/'quality_notes.json')['entries']
        self.assertEqual(len(notes),1);self.assertEqual(notes[0]['field_counts'],{'close':1})
        self.assertEqual(notes[0]['added_missing_rows'],239)
        self.assertEqual(store._rows(store.snapshot(before))[0]['close'],4001.)
        self.assertEqual(self.cycle()['source_discrepancies'],1)

    def test_crash_before_joint_publish_never_exposes_half_batch_and_can_resume(self):
        pointer=self.root/'publication.json';publish(pointer,self.stores,{k:s.snapshot() for k,s in self.stores.items()})
        with patch.object(hm,'publish',side_effect=OSError('simulated interruption')):
            result=self.cycle(limit=2)
        self.assertEqual(result['state'],'failed')
        self.assertTrue(all(s.snapshot()['version'] is None for s in self.stores.values()))
        self.assertTrue(all(s['version'] is None for s in read_publication(pointer,self.stores).values()))
        self.assertEqual(self.cycle()['state'],'complete')

    def test_wrong_date_download_never_reaches_current(self):
        def future(c,j,d):return [bar(j['symbol'],j['frequency'],'2026-10-19')],None
        result=self.cycle(future,limit=1)
        self.assertEqual(result['inserted'],0)
        self.assertEqual(next(iter(hm.read_json(self.root/'jobs.json').values()))['reason'],'validation_failed')

    def test_credentials_fail_closed_no_error_text_and_no_automatic_login_retry(self):
        def bad(_):raise hm.CredentialsUnavailable('password=SECRET')
        result=hm.run_cycle(self.local,force=True,direct_factory=bad,today='2026-10-19')
        self.assertEqual(result['state'],'waiting_credentials');self.assertIsNone(result['next_retry'])
        self.assertNotIn('SECRET',(self.root/'status.json').read_text(encoding='utf8'))
        factory=Mock();hm.run_cycle(self.local,direct_factory=factory,today='2026-10-19');factory.assert_not_called()

    def test_pause_before_scan_and_independent_lock(self):
        _atomic_bytes(self.local/'history_control.json',_json_bytes({'paused':True}))
        self.assertEqual(self.cycle()['state'],'paused')
        _atomic_bytes(self.local/'history_control.json',_json_bytes({'paused':False}))
        with hm._writer_lock(self.root):
            with self.assertRaises(OSError):self.cycle()

    def test_calendar_unavailable_never_connects(self):
        factory=Mock()
        with patch.object(hm,'trading_days',side_effect=CalendarUnavailable()):
            result=hm.run_cycle(self.local,force=True,direct_factory=factory,today='2026-10-19')
        self.assertEqual(result['state'],'waiting_calendar');factory.assert_not_called()

    def test_actual_fetch_converter_hash_units_and_partial_minutes(self):
        def frame(day='2026-10-16'):
            return pd.DataFrame([dict(trading_date=pd.Timestamp(day),timestamp=pd.Timestamp(day+' 09:31'),
                open=4000.,high=4001.,low=3999.,close=4000.,volume=10.,amount=40000.)])
        job=dict(symbol='000300.SH',frequency='1m',day='2026-10-16')
        client=Mock();client.fetch.return_value=(frame(),dict(units={'amount':'元','volume':'手'},unit_factors={'amount':1}))
        rows,item=hm.fetch_job(client,job,self.root)
        self.assertEqual(len(rows),1);self.assertTrue(Path(item['file']).is_file())
        job['frequency']='1d';rows,_=hm.fetch_job(client,job,self.root)
        self.assertEqual(hm.valid_slot(rows[0],'000300.SH','1d','2026-10-16'),900)
        client.fetch.return_value=(frame(),dict(units={'amount':'千元','volume':'手'}))
        with self.assertRaises(ValueError):hm.fetch_job(client,job,self.root)
        client.fetch.return_value=(frame('2026-10-19'),dict(units={'amount':'元','volume':'手'}))
        with self.assertRaises(ValueError):hm.fetch_job(client,job,self.root)

    def test_staged_batch_recovers_after_joint_pointer_but_before_compatibility_pointer(self):
        pointer=self.root/'publication.json';publish(pointer,self.stores,{k:s.snapshot() for k,s in self.stores.items()})
        original=hm.sync_current;calls=[]
        def fail_after_publish(stores,snapshots):
            calls.append(1)
            if len(calls)==2:raise OSError('crash after joint pointer')
            original(stores,snapshots)
        with patch.object(hm,'sync_current',side_effect=fail_after_publish):result=self.cycle(limit=1)
        self.assertEqual(result['state'],'failed')
        self.assertTrue(any(s['version'] for s in read_publication(pointer,self.stores).values()))
        self.assertTrue(all(s.snapshot()['version'] is None for s in self.stores.values()))
        self.assertEqual(self.cycle()['state'],'complete')

    def test_direct_session_does_not_construct_vpn_owner(self):
        from types import SimpleNamespace
        session=Mock();session.connect.return_value=True
        with patch('index_strategy.history.credentials.load_config',return_value=dict(host='test',port=1,username='fake',password='fake')),\
             patch('socket.create_connection'),patch.dict('sys.modules',{'dolphindb':SimpleNamespace(session=lambda **kw:session)}),\
             patch('index_strategy.history.downloader.Client.__init__') as constructor:
            client=hm.open_direct(self.local/'missing.json');client.close()
        constructor.assert_not_called();session.close.assert_called_once()

    def test_scan_checkpoints_survive_restart_and_no_file_reparse_when_unchanged(self):
        self.stores['indexes'].commit([bar()]);snaps={k:s.snapshot() for k,s in self.stores.items()};saved=[]
        first,cache=hm.scan(self.stores,snaps,{},checkpoint=lambda c:saved.append(c))
        self.assertTrue(saved)
        with patch.object(self.stores['indexes'],'_rows',side_effect=AssertionError('unchanged partition reread')):
            second,_=hm.scan(self.stores,snaps,cache)
        self.assertEqual(first,second)

    def test_query_failure_uses_global_backoff_even_with_other_pending_jobs(self):
        def failing(*_):raise RuntimeError('secret SQL text')
        result=self.cycle(failing)
        self.assertEqual(result['queries'],1)
        self.assertGreaterEqual(result['next_retry'],hm.time.time()+295)
        self.assertNotIn('secret SQL',(self.root/'status.json').read_text(encoding='utf8'))

    def test_unfinished_source_uses_short_retry_not_manual_review(self):
        def pending(*_):raise hm.SourcePending()
        result=self.cycle(pending,limit=1)
        job=next(iter(hm.read_json(self.root/'jobs.json').values()))
        self.assertEqual(job['reason'],'source_lag')
        self.assertLess(job['retry_at'],hm.time.time()+301)
        self.assertEqual(result['inserted'],0)

    def test_external_writer_divergence_is_never_overwritten(self):
        pointer=self.root/'publication.json';publish(pointer,self.stores,{k:s.snapshot() for k,s in self.stores.items()})
        external=self.stores['indexes'].commit([bar()])['version']
        result=self.cycle()
        self.assertEqual(result['state'],'review')
        self.assertEqual(self.stores['indexes'].snapshot()['version'],external)
        self.assertIsNone(read_publication(pointer,self.stores)['indexes']['version'])

    def test_cross_day_rechecks_cutoff_and_new_contract_without_waiting_old_cooldown(self):
        self.assertEqual(self.cycle()['state'],'complete')
        called=[]
        def fetch(c,j,d):called.append(j);return self.full_fetch(c,j,d)
        result=hm.run_cycle(self.local,force=False,direct_factory=lambda _:self.client,fetcher=fetch,today='2026-10-20')
        self.assertEqual(result['state'],'complete');self.assertEqual(result['target'],'2026-10-19')
        self.assertTrue(any('2706' in j['symbol'] for j in called))
        self.assertTrue(all(j['day']=='2026-10-19' and '2610' not in j['symbol'] for j in called))


if __name__=='__main__':unittest.main()
