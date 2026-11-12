"""Dated closing premium fallback and real two-period AUM of today's top three."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from dashboard.marketdata.overview_reference import premium_display,publish,ranking,load
from dashboard.marketdata.overview_etf_history import read_aum_history,size_changes
from dashboard.native.overview_details import enrich
from tests.test_overview_details import reference


class PremiumDisplayTests(unittest.TestCase):
    def test_intraday_including_real_zero_has_priority_over_closing(self):
        for value in (0.,3.5,-2.):
            row=dict(premium_bp=value,closing_premium_bp=-20.,nav_date='2026-10-23')
            result=premium_display(row,'2026-10-23')
            self.assertEqual(result['display_premium_bp'],value);self.assertEqual(result['display_premium_mode'],'intraday')

    def test_missing_or_invalid_intraday_uses_dated_yesterday_close_without_creating_iopv(self):
        for missing in (None,float('nan'),float('inf')):
            row=dict(premium_bp=missing,iopv=None,closing_premium_bp=-20.,nav_date='2026-10-23')
            result=premium_display(row,'2026-10-23')
            self.assertEqual(result['display_premium_bp'],-20.);self.assertEqual(result['display_premium_mode'],'closing')
            self.assertEqual(result['display_premium_date'],'2026-10-23');self.assertIn('昨日',result['display_premium_label'])
            self.assertIsNone(row['iopv']);self.assertIs(row['premium_bp'],missing)

    def test_older_close_is_dated_without_being_called_yesterday_and_undated_is_unavailable(self):
        result=premium_display(dict(closing_premium_bp=0.,nav_date='2026-10-22'),'2026-10-23')
        self.assertEqual(result['display_premium_bp'],0.);self.assertNotIn('昨日',result['display_premium_label'])
        self.assertIsNone(premium_display(dict(closing_premium_bp=3))['display_premium_bp'])
        self.assertIsNone(premium_display({})['display_premium_bp'])


class AumHistoryTests(unittest.TestCase):
    def old(self):
        value=reference();value['fetched_at']='2026-10-23T09:00:00+08:00'
        group=value['etfs']['IF'];group['as_of']='2026-10-22'
        for row in group['rows']:row['aum_date']='2026-10-22'
        for row,amount in zip(group['rows'],(450e8,250e8,50e8,350e8)):row['aum_cny']=amount
        return value

    def test_same_current_top_three_are_matched_by_code_even_if_prior_rank_was_fourth(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_reference/latest.json';publish(path,self.old());current=publish(path,reference())
            raw={p:p.read_bytes() for p in path.parent.rglob('*.json')}
            history=read_aum_history({},tmp,current);selected,_=ranking(current,'IF',today='2026-10-26')
            result=size_changes('IF',selected,history)
            self.assertEqual([r['symbol'] for r in result],['510301.SH','510302.SH','510303.SH'])
            self.assertEqual([r['aum_change_cny'] for r in result],[50e8,50e8,50e8])
            self.assertEqual([r['aum_previous_date'] for r in result],['2026-10-22']*3)
            self.assertEqual(result[-1]['aum_change_pct'],100.)
            self.assertTrue(all(p.read_bytes()==data for p,data in raw.items()))

    def test_one_period_does_not_invent_zero_change_or_net_creation(self):
        current=reference();selected,_=ranking(current,'IF',today='2026-10-26')
        result=size_changes('IF',selected,dict(snapshots=[]))
        self.assertEqual(len(result),3);self.assertTrue(all(r['aum_change_cny'] is None for r in result))
        self.assertTrue(all(r['aum_previous_date'] is None for r in result))

    def test_later_availability_and_corrupt_archives_cannot_replace_prior_available_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_reference/latest.json';publish(path,self.old());current=publish(path,reference())
            future=self.old();future['fetched_at']='2026-10-27T09:00:00+08:00';future['etfs']['IF']['rows'][0]['aum_cny']=1
            (path.parent/'archive/future.json').write_text(json.dumps(future))
            (path.parent/'archive/broken.json').write_text('CANARY_INVALID_JSON')
            result=size_changes('IF',ranking(current,'IF',today='2026-10-26')[0],read_aum_history({},tmp,current))
            self.assertEqual(result[0]['aum_previous_cny'],450e8)
            self.assertNotIn('CANARY',json.dumps(result))

    def test_duplicate_same_time_prior_conflict_is_not_arbitrarily_chosen(self):
        first=self.old();second=deepcopy(first);second['etfs']['IF']['rows'][0]['aum_cny']=1
        result=size_changes('IF',ranking(reference(),'IF',today='2026-10-26')[0],dict(snapshots=[first,second]))
        self.assertIsNone(result[0]['aum_change_cny']);self.assertIn('冲突',result[0]['reason'])
        self.assertIsNotNone(result[1]['aum_change_cny'])

    def test_archive_scan_is_bounded_and_flags_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_reference/latest.json';publish(path,reference())
            for i in range(70):(path.parent/'archive'/f'2026-10-20-{i:03}.json').write_text('{}')
            result=read_aum_history({},tmp,reference())
            self.assertLessEqual(result['files_read'],64);self.assertTrue(result['truncated'])

    def test_page_reuses_archive_generation_until_a_new_archive_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_reference/latest.json';publish(path,reference())
            reference_value=load({},tmp,now=pd.Timestamp('2026-10-26T10:00:00+08:00').to_pydatetime())
            model=SimpleNamespace(config={},local_root=Path(tmp),live_rows=pd.DataFrame())
            now=pd.Timestamp('2026-10-26T10:00:00+08:00')
            def state():return dict(indices=[],etfs=[],previous_session='2026-10-23')
            with patch('dashboard.marketdata.overview_etf_history.read_aum_history',wraps=read_aum_history) as read:
                data=state();enrich(model,data,reference_value,now)
                enrich(model,state(),reference_value,now);self.assertEqual(read.call_count,1)
                old=self.old();(path.parent/'archive/backfilled.json').write_text(json.dumps(old))
                data=state();enrich(model,data,reference_value,now);self.assertEqual(read.call_count,2)
                self.assertEqual(data['etf_groups']['IF']['size_changes'][0]['aum_change_cny'],50e8)


class EtfUiTests(unittest.TestCase):
    def test_dated_closing_premium_highlights_scale_and_spread_and_lists_only_three_changes(self):
        from tests.test_market_overview_ui import APP
        from dashboard.native.overview_pages import EtfOverviewPage
        rows=[dict(symbol=f'51030{i+1}.SH',root='IF',name='测试ETF'+str(i),rank=i+1,price=4.,change_pct=0.,
            premium_bp=None,iopv=None,closing_premium_bp=-20.,nav_date='2026-10-23',aum_cny=(5-i)*1e8,
            aum_share_pct=20.,aum_date='2026-10-23',spread_bp=2.4,quality={},display_premium_mode='closing',display_premium_label='昨日收盘折溢价') for i in range(3)]
        changes=[dict(symbol=r['symbol'],aum_change_cny=1e8,aum_change_pct=2.,aum_previous_date='2026-10-22',aum_current_date='2026-10-23') for r in rows]
        page=EtfOverviewPage()
        try:
            page.render(rows,dict(IF=dict(rows=rows,ranking=dict(as_of='2026-10-23'),size_changes=changes)),{})
            page.select('IF')
            card=page.fund_cards[0]
            self.assertEqual(card.premium.text(),'-20.0 bp');self.assertIn('昨日',card.iopv.text())
            self.assertIn('2026-10-23',card.closing_premium.text())
            self.assertIn('700',card.scale.styleSheet());self.assertIn('700',card.spread.styleSheet())
            self.assertEqual(card.spread.text(),'2.4');self.assertEqual(card.scale.text(),'5.00');self.assertEqual(card.share.text(),'20.0%')
            self.assertEqual(len(page.fund_cards),3)
            self.assertIn('规模对比',page.capacity.title.text());self.assertIn('名义本金',page.futures_panel.title.text())
            self.assertNotIn('净申购',page.capacity.title.text())
        finally:page.close();page.deleteLater();APP.processEvents()

    def test_summary_latest_dividend_date_is_visible_and_percentile_has_no_estimate_suffix(self):
        from tests.test_market_overview_ui import APP,state
        from dashboard.native.overview_summary import OverviewSummary
        data=state()['market_overview'];data['dividend_latest_business_day']='2026-10-23'
        data['futures'][0]['continuous_percentiles']['windows']['60'].update(percentile=20.,estimated=True,reason='历史分红缺失暂按0 9日')
        page=OverviewSummary()
        try:
            page.render_data(data)
            self.assertIn('2026-10-23',page.dividend_source.text())
            self.assertEqual(page.products['IF'].futures[0].rank60_value.text(),'20.0%')
        finally:page.close();page.deleteLater();APP.processEvents()
