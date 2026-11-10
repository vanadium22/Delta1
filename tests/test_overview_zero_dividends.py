"""User-approved historical zero estimates, kept separate from real D records."""
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


class HistoricalZeroTests(unittest.TestCase):
    def test_four_products_four_slots_have_one_dated_sample_and_zero_estimate_ranks(self):
        meta=metadata();data=daily_data(meta);book=DatedDividendBook([],meta)
        for root in ('IF','IH','IC','IM'):
            for slot in range(4):
                history=prepare(root,slot,meta,data,DAY,dividends=book)
                self.assertEqual(len({r['day'] for r in history['rows']}),60)
                value=evaluate(history,0,history['current_symbol'])
                for window in value['windows'].values():
                    self.assertTrue(window['complete']);self.assertEqual(window['percentile'],50)
                    self.assertEqual(window['zero_dividend_count'],window['expected_eligible'])
                    self.assertTrue(window['estimated']);self.assertFalse(window['dividend_observations_complete'])
                self.assertTrue(all(r['dividend_points']==0 for r in history['rows'] if not r['excluded']))
        self.assertEqual(book.records,[])

    def test_explicit_real_zero_is_not_flagged_as_missing_and_one_missing_day_is(self):
        meta=metadata();data=daily_data(meta);missing='2026-10-26'
        book=SimpleNamespace(resolve=lambda s,d:None if d==missing else dict(points=0.,revision='real-zero',source_kind='fixture'),version='v',info={})
        history=prepare('IF',1,meta,data,DAY,dividends=book)
        result=evaluate(history,0,history['current_symbol'])
        self.assertEqual(result['windows']['60']['zero_dividend_dates'],[missing])
        self.assertEqual(result['windows']['60']['percentile'],50)
        self.assertEqual(sum(r['dividend_estimated_zero'] for r in history['rows']),1)

    def test_backfilled_historical_record_replaces_estimate_with_new_cache_version(self):
        meta=metadata();data=daily_data(meta);before=DatedDividendBook([],meta)
        with tempfile.TemporaryDirectory() as tmp:
            cache=DerivedCache(tmp,writable=True)
            old=prepare('IF',3,meta,data,DAY,dividends=before,cache=cache)
            sample=old['rows'][0];self.assertTrue(sample['dividend_estimated_zero'])
            cache.flush();old_keys=set(cache.rows)
            after=DatedDividendBook([record(sample['symbol'],2,sample['day']+'T00:00:00+08:00')],meta)
            self.assertNotEqual(before.history_version(requirements(meta,DAY)['rows']),after.history_version(requirements(meta,DAY)['rows']))
            revised=prepare('IF',3,meta,data,DAY,dividends=after,cache=cache)
            self.assertFalse(revised['rows'][0]['dividend_estimated_zero'])
            self.assertAlmostEqual(revised['rows'][0]['annual_pct'],100*2/4000*365/sample['days'])
            cache.flush();self.assertTrue(old_keys<set(DerivedCache(tmp).rows))
            self.assertFalse((Path(tmp)/'records.sqlite').exists())

    def test_new_current_dividend_does_not_reprice_past_estimates(self):
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
        meta=metadata();data=daily_data(meta,annual_by_slot=(-4,-2,0,2));book=DatedDividendBook([],meta)
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

    def test_offline_audit_separates_calculable_estimates_from_observed_dividend_coverage(self):
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
            self.assertEqual(result['summary']['continuous_windows_incomplete'],[])
            self.assertEqual(len(result['summary']['continuous_windows_estimated']),32)
            self.assertGreater(len(result['continuous_annual']['zero_dividend_assumptions']),0)
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
