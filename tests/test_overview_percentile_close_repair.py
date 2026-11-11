"""Available closes unblock annual percentiles while real OI gaps remain pending."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import pandas as pd

from dashboard.marketdata import overview_daily as daily
from dashboard.marketdata.overview_percentiles import prepare,evaluate
from tests.test_market_overview import ZERO_DIVIDENDS
from tests.test_overview_data import close_row
from tests.test_overview_percentiles import metadata,daily_data
from tests import test_app_pipeline as pipeline_tests

DAY='2026-11-10'
SYMBOL='IF2611.CFE'


class CloseRepairTests(unittest.TestCase):
    def test_remote_valid_close_is_kept_when_required_oi_is_missing(self):
        session=Mock();session.run.side_effect=[1,pd.DataFrame([dict(symbol=SYMBOL,trade_date=pd.Timestamp(DAY),
            open=100.,high=102.,low=99.,close=101.,volume=10.,amount=2.,oi=None)])]
        client=SimpleNamespace(session=session,bind=Mock())
        with tempfile.TemporaryDirectory() as tmp:
            rows=daily.fetch_batch(client,dict(asset='future',day=DAY,symbols=[SYMBOL],requires_oi=True),tmp)
            self.assertEqual(rows[SYMBOL]['close'],101.)
            self.assertIsNone(rows[SYMBOL]['oi']);self.assertTrue(rows[SYMBOL]['is_final'])

    def position_requests(self,config,root,target,meta):
        saved=daily.read_day(config,root,DAY).get('rows',{}).get(SYMBOL,{})
        if saved.get('oi') is not None:return []
        return [dict(asset='future',day=DAY,symbols=[SYMBOL],requires_oi=True)]

    def test_price_only_is_saved_once_without_repeated_position_progress(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'requests',side_effect=self.position_requests):
            fetch=Mock(return_value={SYMBOL:close_row(SYMBOL,DAY,oi=None)})
            first=daily.fill(Mock(),{},tmp,DAY,{},fetcher=fetch)
            self.assertEqual(first['inserted'],1);self.assertEqual(first['pending_close_rows'],0)
            self.assertEqual(first['pending_oi_rows'],1);self.assertEqual(first['status'],'partial')
            raw=(Path(tmp)/'overview_daily/days'/f'{DAY}.json').read_bytes()
            second=daily.fill(Mock(),{},tmp,DAY,{},fetcher=fetch)
            self.assertEqual(second['inserted'],0);self.assertEqual(second['pending_oi_rows'],1)
            self.assertEqual((Path(tmp)/'overview_daily/days'/f'{DAY}.json').read_bytes(),raw)
            self.assertFalse((Path(tmp)/'overview_daily/archive').exists())
            fetch.return_value={SYMBOL:close_row(SYMBOL,DAY,oi=0)}
            complete=daily.fill(Mock(),{},tmp,DAY,{},fetcher=fetch)
            self.assertEqual(complete['status'],'complete');self.assertEqual(complete['pending_oi_rows'],0)
            self.assertEqual(daily.read_day({},tmp,DAY)['rows'][SYMBOL]['oi'],0)

    def test_added_close_restores_twenty_and_sixty_windows_without_false_oi(self):
        meta=metadata();prices=daily_data(meta,day='2026-11-11')
        prices[SYMBOL]=prices[SYMBOL][prices[SYMBOL].trade_date.astype(str).str[:10].ne(DAY)]
        before=prepare('IF',0,meta,prices,'2026-11-11',dividends=ZERO_DIVIDENDS)
        missing=evaluate(before,0,before['current_symbol'])
        self.assertIsNone(missing['windows']['20']['percentile']);self.assertIsNone(missing['windows']['60']['percentile'])
        self.assertTrue(any(r['day']==DAY for r in missing['windows']['20']['missing']))
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'requests',side_effect=self.position_requests):
            result=daily.fill(Mock(),{},tmp,DAY,meta,fetcher=lambda *a:{SYMBOL:close_row(SYMBOL,DAY,oi=None)})
            row=daily.read_day({},tmp,DAY)['rows'][SYMBOL]
            prices[SYMBOL]=daily.merge_daily(prices[SYMBOL],[dict(row,open_interest=row['oi'])])
        repaired=prepare('IF',0,meta,prices,'2026-11-11',dividends=ZERO_DIVIDENDS)
        values=evaluate(repaired,0,repaired['current_symbol'])
        for window in ('20','60'):
            self.assertTrue(values['windows'][window]['complete'])
            self.assertIsNotNone(values['windows'][window]['percentile'])
        self.assertEqual(result['pending_close_rows'],0);self.assertEqual(result['pending_oi_rows'],1)

    def test_rejected_etf_batch_does_not_block_an_unrelated_future_day(self):
        bad=dict(asset='etf',day=DAY,symbols=['510300.SH'])
        good=dict(asset='future',day='2026-11-09',symbols=[SYMBOL])
        def requests(config,root,target,meta):
            return [bad]+([] if SYMBOL in daily.read_day({},root,'2026-11-09').get('rows',{}) else [good])
        def fetch(client,job,root):
            if job['asset']=='etf':raise ValueError('PRIVATE_RAW_EXCEPTION')
            return {SYMBOL:close_row(SYMBOL,job['day'])}
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'requests',side_effect=requests):
            result=daily.fill(Mock(),{},tmp,DAY,{},fetcher=fetch)
            self.assertIn(SYMBOL,daily.read_day({},tmp,'2026-11-09')['rows'])
        self.assertEqual(result['inserted'],1);self.assertEqual(result['pending_close_rows'],1)
        self.assertEqual(result['failed_batches'][0]['error_type'],'ValueError')
        self.assertNotIn('PRIVATE_RAW_EXCEPTION',json.dumps(result))

    def test_connection_failure_stops_further_queries_and_keeps_all_pending(self):
        jobs=[dict(asset='etf',day=DAY,symbols=['510300.SH']),dict(asset='future',day=DAY,symbols=[SYMBOL])]
        fetch=Mock(side_effect=ConnectionError('PRIVATE_RAW_EXCEPTION'))
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'requests',return_value=jobs):
            result=daily.fill(Mock(),{},tmp,DAY,{},fetcher=fetch)
        fetch.assert_called_once();self.assertEqual(result['inserted'],0)
        self.assertEqual(result['pending_close_rows'],2);self.assertNotIn('PRIVATE_RAW_EXCEPTION',json.dumps(result))


class GapExplanationTests(unittest.TestCase):
    def row(self):
        from tests.test_market_overview_ui import state
        row=deepcopy(state()['market_overview']['futures'][0])
        row['continuous_percentiles']=dict(alias='IF00.CFE',windows={str(n):dict(percentile=None,samples=n-1,expected_eligible=n,
            missing=[dict(day=DAY,symbol=SYMBOL,reason='future_close_missing',missing_symbols=[SYMBOL,'000300.SH'])]) for n in (20,60)})
        return row

    def test_card_tooltip_names_missing_day_and_both_legs(self):
        from dashboard.native.futures_overview_view import FuturesCard
        card=FuturesCard(None)
        try:
            card.render(self.row(),0)
            for widget in (card.rank_value,card.rank60_value):
                self.assertEqual(widget.text(),'缺收盘')
                self.assertIn(DAY,widget.toolTip());self.assertIn(SYMBOL,widget.toolTip())
                self.assertIn('000300.SH',widget.toolTip())
        finally:card.deleteLater();pipeline_tests.APP.processEvents()

    def test_update_page_deduplicates_twenty_and_sixty_close_gaps(self):
        from dashboard.native.data_pipeline import PipelinePage
        helper=pipeline_tests.PipelineTests();window,pipeline=helper.fixture();self.addCleanup(helper.doCleanups)
        window.state=dict(market_overview=dict(futures=[self.row()]))
        page=PipelinePage(pipeline)
        try:
            self.assertIn('分位历史缺收盘：2 个标的/交易日',page.head.text())
            self.assertIn(DAY,page.head.text())
        finally:page.deleteLater();pipeline_tests.APP.processEvents()


if __name__=='__main__':unittest.main()
