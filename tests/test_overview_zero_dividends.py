"""Historical actual-contract D coverage and compatibility with old saved displays."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import pandas as pd

from dashboard.marketdata.overview_percentiles import prepare,evaluate,requirements,apply
from dashboard.marketdata.overview_dividends import DatedDividendBook,DerivedCache
from dashboard.native.market_overview import futures_values
from tests.test_overview_percentiles import metadata,daily_data,DAY,NOW
from tests.test_overview_dated import record
from tests.test_market_overview import observation


class HistoricalDividendCoverageTests(unittest.TestCase):
    def test_new_shared_workbook_is_discovered_and_only_changes_later_same_contract_rows(self):
        from openpyxl import Workbook
        from dashboard.marketdata.overview_basis import historical_dividend, input_token, load_dividends
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            inputs=root/'inputs';history=inputs/'2026'/'10';history.mkdir(parents=True)
            paths=SimpleNamespace(dividend_inputs=inputs,dividend_archive=root/'archive')
            meta=metadata();config={}
            def save(path, when, rows):
                book=Workbook();sheet=book.active;sheet.title='Sheet1'
                sheet['B1']=pd.Timestamp(when).to_pydatetime()
                sheet['G3']='分红'
                for i,(alias,contract,points) in enumerate(rows,4):
                    sheet.cell(i,2,alias);sheet.cell(i,3,contract);sheet.cell(i,7,points)
                book.save(path);book.close()
            save(inputs/'first.xlsx','2026-10-23',
                 [('IF00.CFE','IF2611.CFE',8),('IF01.CFE','IF2612.CFE',0)])
            with patch('dashboard.marketdata.paths.PATHS',paths):
                before=input_token(config,meta,DAY,root)
                original=load_dividends(config,meta,DAY,root)
                save(history/'later.xlsx','2026-10-26 15:06',
                     [('IF00.CFE','IF2611.CFE',5),('IF01.CFE','IF2612.CFE',None)])
                after=input_token(config,meta,DAY,root)
                updated=load_dividends(config,meta,DAY,root)
            self.assertNotEqual(before,after)
            self.assertIsNone(historical_dividend(updated,'IF2611.CFE','2026-10-22').get('points'))
            self.assertEqual(historical_dividend(updated,'IF2611.CFE','2026-10-26')['points'],8)
            self.assertEqual(historical_dividend(updated,'IF2611.CFE',DAY)['points'],5)
            self.assertEqual(historical_dividend(updated,'IF2612.CFE',DAY)['points'],0)
            self.assertIsNone(historical_dividend(updated,'IF2703.CFE',DAY).get('points'))
            self.assertEqual(original.history_version([dict(symbol='IF2611.CFE',day='2026-10-26')]),
                             updated.history_version([dict(symbol='IF2611.CFE',day='2026-10-26')]))

    def test_four_products_four_slots_keep_dated_gaps_without_estimates(self):
        meta=metadata();data=daily_data(meta);book=DatedDividendBook([],meta)
        for root in ('IF','IH','IC','IM'):
            for slot in range(4):
                history=prepare(root,slot,meta,data,DAY,dividends=book)
                self.assertEqual(len({r['day'] for r in history['rows']}),60)
                value=evaluate(history,0,history['current_symbol'])
                for window in value['windows'].values():
                    self.assertFalse(window['complete']);self.assertIsNone(window['percentile'])
                    self.assertEqual(window['missing_counts']['dividend_missing'],window['expected_eligible'])
                    self.assertFalse(window['estimated']);self.assertFalse(window['dividend_observations_complete'])
                self.assertTrue(all(r['dividend_points'] is None for r in history['rows'] if not r['excluded']))
        self.assertEqual(book.records,[])

    def test_explicit_real_zero_is_not_flagged_as_missing_and_one_missing_day_is(self):
        meta=metadata();data=daily_data(meta);missing='2026-10-26'
        book=SimpleNamespace(resolve=lambda s,d:None if d==missing else dict(points=0.,revision='real-zero',source_kind='fixture'),version='v',info={})
        history=prepare('IF',1,meta,data,DAY,dividends=book)
        result=evaluate(history,0,history['current_symbol'])
        self.assertEqual(result['windows']['60']['zero_dividend_dates'],[])
        self.assertIsNone(result['windows']['60']['percentile'])
        self.assertEqual(result['windows']['60']['missing'][0]['day'],missing)
        self.assertEqual(history['rows'][-2]['dividend_points'],0)

    def test_backfilled_historical_record_replaces_gap_with_new_cache_version(self):
        meta=metadata();data=daily_data(meta);before=DatedDividendBook([],meta)
        with tempfile.TemporaryDirectory() as tmp:
            cache=DerivedCache(tmp,writable=True)
            old=prepare('IF',3,meta,data,DAY,dividends=before,cache=cache)
            sample=old['rows'][0];self.assertIsNone(sample['annual_pct'])
            cache.flush();old_keys=set(cache.rows)
            after=DatedDividendBook([record(sample['symbol'],2,sample['day']+'T00:00:00+08:00')],meta)
            self.assertNotEqual(before.history_version(requirements(meta,DAY)['rows']),after.history_version(requirements(meta,DAY)['rows']))
            revised=prepare('IF',3,meta,data,DAY,dividends=after,cache=cache)
            self.assertFalse(revised['rows'][0]['dividend_estimated_zero'])
            self.assertAlmostEqual(revised['rows'][0]['annual_pct'],100*2/4000*365/sample['days'])
            cache.flush();self.assertTrue(old_keys<set(DerivedCache(tmp).rows))
            self.assertFalse((Path(tmp)/'records.sqlite').exists())

    def test_new_current_dividend_does_not_reprice_past_history(self):
        meta=metadata();data=daily_data(meta);before=DatedDividendBook([],meta)
        after=DatedDividendBook([record(s,99,DAY+'T00:00:00+08:00') for s in meta],meta)
        old=prepare('IF',3,meta,data,DAY,dividends=before)
        new=prepare('IF',3,meta,data,DAY,dividends=after)
        self.assertEqual(old['rows'],new['rows'])
        self.assertEqual(before.history_version(requirements(meta,DAY)['rows']),after.history_version(requirements(meta,DAY)['rows']))

    def test_conflicting_real_records_do_not_become_zero(self):
        meta=metadata();data=daily_data(meta)
        rows=[record(s,p,'2026-07-01T00:00:00+08:00',s+str(p)) for s in meta for p in (1,2)]
        history=prepare('IF',1,meta,data,DAY,dividends=DatedDividendBook(rows,meta))
        value=evaluate(history,0,history['current_symbol'])['windows']['60']
        self.assertFalse(value['complete']);self.assertIsNone(value['percentile'])
        self.assertEqual(value['zero_dividend_count'],0);self.assertGreater(value['missing_counts']['dividend_missing'],0)

    def test_prices_and_mapping_gaps_still_block_and_current_missing_d_stays_missing(self):
        meta=metadata();data=daily_data(meta);book=DatedDividendBook([],meta)
        history=prepare('IF',1,meta,data,DAY,dividends=book);last=history['rows'][-1]
        frame=data[last['symbol']];data[last['symbol']]=frame[frame.trade_date.ne(last['day'])]
        value=evaluate(prepare('IF',1,meta,data,DAY,dividends=book),0,history['current_symbol'])['windows']['60']
        self.assertFalse(value['complete']);self.assertEqual(value['missing_counts']['future_close_missing'],1)
        meta.pop('IF2609.CFE')
        value=evaluate(prepare('IF',1,meta,daily_data(),DAY,dividends=book),0,history['current_symbol'])['windows']['60']
        self.assertGreater(value['missing_counts']['mapping_missing'],0);self.assertIsNone(value['percentile'])
        row=dict(symbol='IF2611.CFE',root='IF',price=4000);live={row['symbol']:observation(at=NOW),'000300.SH':observation(at=NOW)}
        futures_values(row,live,{},metadata(),NOW,dividends=book)
        self.assertEqual(row['price'],4000)
        self.assertIsNone(row['annual_pct']);self.assertIsNone(row['dividend_points'])

    def test_independent_midrank_uses_historical_daily_values_excludes_current_day(self):
        meta=metadata();data=daily_data(meta,annual_by_slot=(-4,-2,0,2))
        book=DatedDividendBook([record(s,0,'2026-07-01T00:00:00+08:00',s) for s in meta],meta)
        history=prepare('IF',2,meta,data,DAY,dividends=book)
        data[history['current_symbol']]=pd.concat([data.get(history['current_symbol'],pd.DataFrame()),pd.DataFrame([dict(trade_date=DAY,close=999999.,is_final=True)])])
        self.assertEqual(prepare('IF',2,meta,data,DAY,dividends=book)['rows'],history['rows'])
        self.assertTrue(all(r['day']<DAY for r in history['rows']))
        eligible=[r for r in history['rows'] if not r['excluded']]
        for i,row in enumerate(eligible):row['annual_pct']=float(i%7-3)
        value=evaluate(history,.5,history['current_symbol'])
        for size in (20,60):
            values=[r['annual_pct'] for r in history['rows'][-size:] if not r['excluded']]
            expected=100*(sum(v<.5 for v in values)+.5*sum(v==.5 for v in values))/len(values)
            self.assertEqual(value['windows'][str(size)]['percentile'],expected)

    def test_offline_audit_reports_missing_dividends_and_incomplete_windows(self):
        from tests.test_overview_audit import profile
        from dashboard.marketdata.overview_audit import collect
        from dashboard.dividend_check import audit
        with tempfile.TemporaryDirectory() as tmp:
            config,meta=profile(tmp);book=DatedDividendBook([],meta);data=daily_data(meta)
            repo=Mock();repo.symbols.return_value={};repo.read_window.side_effect=lambda s,*a,**kw:data.get(s,pd.DataFrame())
            with patch('dashboard.marketdata.overview_audit.inspect_history',return_value=(repo,{},dict(inventory=[]))),\
                 patch('dashboard.marketdata.overview_basis.load_dividends',return_value=book),\
                 patch('dashboard.native.market_overview.load_dividends',return_value=book),\
                 patch('requests.sessions.Session.request',side_effect=AssertionError('offline')):
                result=collect(config,tmp,now=NOW);dividends=audit(config,tmp,now=NOW.to_pydatetime())
            self.assertEqual(len(result['summary']['continuous_windows_incomplete']),32)
            self.assertEqual(result['summary']['continuous_windows_estimated'],[])
            self.assertGreater(len(result['continuous_annual']['dividend_missing']),0)
            self.assertFalse(dividends['history_dividends_complete'])
            self.assertTrue(all(r['points'] is None for r in dividends['current_dividends'].values()))
            self.assertFalse(result['summary']['company_acceptance_passed'])
            self.assertNotIn('CANARY_CONFIG_SECRET',json.dumps(result))

    def test_card_shows_estimated_percentile_and_actual_d_source_date(self):
        from tests.test_market_overview_ui import APP,state
        from dashboard.native.futures_overview_view import FuturesCard
        row=deepcopy(state()['market_overview']['futures'][0])
        row.update(dividend_points=.25,dividend_snapshot='2026-10-23',pricing_day='2026-10-26')
        row['continuous_percentiles']['windows']['60'].update(percentile=37.5,estimated=True,zero_dividend_count=9,reason='历史缺分红暂按0估算 9日')
        card=FuturesCard(None)
        try:
            card.render(row,0);APP.processEvents()
            self.assertEqual(card.rank60_value.text(),'37.5%')
            self.assertIn('9日',card.rank60_value.toolTip());self.assertIn('沿用 2026-10-23',card.dividend_note.text())
        finally:card.close();card.deleteLater();APP.processEvents()
