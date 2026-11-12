"""Partial, dated industry-weight changes without fabricating missing observations."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from dashboard.native.bootstrap import configure_qt
configure_qt()
from dashboard.marketdata.overview_industry_changes import partial_compare,estimate_from_returns,load,summary
from dashboard.marketdata.overview_contributions import contributions
from dashboard.marketdata.overview_reference import publish
from dashboard.native.overview_details import enrich
from dashboard.native.overview_pages import IndexOverviewPage
from tests.test_market_overview_ui import APP,pump
from tests.test_market_overview import NOW,observation


def group(rows,day='2026-10-30',complete=True):
    return dict(index_id='000905.SH',source='WindPy WSET indexconstituent',as_of=day,
        industry_standard='申万一级',weights_complete=complete,
        weight_method='source_reference' if complete else 'incomplete_reference',rows=rows)


def estimate_detail():
    source='2026-11-12T09:59:58+08:00'
    return dict(snapshot_at='2026-11-12T10:00:00+08:00',source_at=source,pricing_day='2026-11-12',mode='rolling',
        industry_standard='申万一级',weight_method='source_reference',actual_return_pct=.5,
        rows=[dict(symbol='600001.SH',industry='电子',weight_pct=40.,weight_date='2026-10-30',change_pct=2.,source_at=source),
              dict(symbol='600002.SH',industry='银行',weight_pct=30.,weight_date='2026-10-30',change_pct=-1.,source_at=source),
              dict(symbol='600003.SH',industry='医药',weight_pct=20.,weight_date='2026-10-30',change_pct=None,source_at=None),
              dict(symbol='600004.SH',industry=None,weight_pct=None,weight_date=None,change_pct=1.,source_at=source)])


class PartialHistoryTests(unittest.TestCase):
    def test_only_same_code_dated_weights_are_compared_without_inventing_missing(self):
        current=group([dict(symbol='600001.SH',weight_pct=20.,industry='电子'),
            dict(symbol='600002.SH',weight_pct=30.,industry='银行'),dict(symbol='600003.SH',weight_pct=10.,industry='医药'),
            dict(symbol='600004.SH',weight_pct=20.,industry='消费'),dict(symbol='600005.SH',weight_pct=20.,industry='银行')])
        previous=group([dict(symbol='600001.SH',weight_pct=18.,industry='电子',reference_date='2026-09-30'),
            dict(symbol='600002.SH',weight_pct=32.,industry=None,reference_date='2026-09-30'),
            dict(symbol='600003.SH',weight_pct=None,industry='医药',reference_date='2026-09-30'),
            dict(symbol='600004.SH',weight_pct=21.,industry='其他',reference_date='2026-09-30'),
            dict(symbol='600005.SH',weight_pct=19.,industry='银行',reference_date='2026-10-30')],complete=False)
        result=partial_compare(current,previous);by_name={r['name']:r for r in result['rows']}
        self.assertEqual(result['paired_members'],2);self.assertEqual(result['current_members'],5)
        self.assertEqual(result['paired_current_weight'],50);self.assertEqual(result['paired_previous_weight'],50)
        self.assertEqual(result['reclassified_excluded'],1);self.assertEqual(result['unclassified_paired'],1)
        self.assertEqual(by_name['电子']['change_pp'],2);self.assertEqual(by_name['待分类']['change_pp'],-2)
        self.assertNotIn('医药',by_name);self.assertIn('非完整指数',result['reason'])

    def test_incomplete_weights_without_real_prior_dates_or_matching_source_stay_missing(self):
        current=group([dict(symbol='600001.SH',weight_pct=100.,industry='电子')])
        prior=group([dict(symbol='600001.SH',weight_pct=99.,industry='电子')],complete=False)
        self.assertIsNone(partial_compare(current,prior))
        prior['rows'][0]['reference_date']='2026-09-30';prior['source']='different provider'
        self.assertIsNone(partial_compare(current,prior))
        prior['source']=current['source'];prior['rows'][0]['reference_date']='2026-11-01'
        self.assertIsNone(partial_compare(current,prior))

    def test_archived_mixed_request_date_uses_each_older_source_date(self):
        current_rows=[dict(symbol=f'{600000+i:06}.SH',weight_pct=.2,industry='电子',reference_date='2026-10-30') for i in range(500)]
        old_rows=[dict(symbol=r['symbol'],weight_pct=.19 if i<80 else None,industry='电子',reference_date='2026-10-20')
                  for i,r in enumerate(current_rows)]
        current=group(current_rows);previous=group(old_rows,day='2026-11-10',complete=False)
        previous.update(membership_complete=True,membership_as_of='2026-11-10')
        old=dict(schema='overview-reference-v1',fetched_at='2026-11-10T16:00:00+08:00',indices={'IC':previous})
        now=dict(schema='overview-reference-v1',fetched_at='2026-11-12T09:00:00+08:00',indices={'IC':current})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_reference/latest.json';publish(path,old);publish(path,now)
            result=load({},tmp,now,{'IC':current})['IC']
        self.assertEqual(result['comparison_kind'],'partial_history');self.assertEqual(result['paired_members'],80)
        self.assertEqual(result['previous_date'],'2026-10-20');self.assertEqual(result['current_date'],'2026-10-30')
        self.assertAlmostEqual(result['rows'][0]['change_pp'],.8)
        self.assertGreater(result['diagnostics']['partial_groups'],0)


class ReturnEstimateTests(unittest.TestCase):
    def test_estimate_uses_real_price_returns_index_denominator_and_known_weights(self):
        result=estimate_from_returns(estimate_detail(),'2026-11-11');rows={r['name']:r for r in result['rows']}
        self.assertEqual(result['comparison_kind'],'return_estimate');self.assertEqual(result['paired_members'],2)
        self.assertEqual(result['anchor_weight'],70);self.assertEqual(result['current_members'],4)
        self.assertAlmostEqual(result['paired_current_weight'],(40*1.02+30*.99)/1.005)
        self.assertAlmostEqual(rows['电子']['change_pp'],40*(1.02/1.005-1))
        self.assertAlmostEqual(rows['银行']['change_pp'],30*(.99/1.005-1))
        self.assertEqual(result['anchor_date_range'],['2026-10-30','2026-10-30'])
        self.assertIn('非官方',result['reason']);self.assertNotIn('医药',rows)

    def test_missing_index_return_uses_explicit_covered_basket_estimate(self):
        detail=estimate_detail();detail['actual_return_pct']=None
        result=estimate_from_returns(detail,'2026-11-11')
        self.assertEqual(result['denominator_source'],'已覆盖成分加权涨跌估算')
        self.assertAlmostEqual(sum(r['change_pp'] for r in result['rows']),0.,places=10)
        self.assertEqual(result['anchor_weight'],70)

    def test_future_stale_or_missing_inputs_are_not_silently_used(self):
        detail=estimate_detail();detail['stale']=True
        detail['rows'][0]['source_at']='2026-11-12T10:00:01+08:00'
        detail['rows'][1]['weight_date']='2026-11-12'
        self.assertIsNone(estimate_from_returns(detail,'2026-11-11'))
        detail=estimate_detail();detail['stale']=True
        result=estimate_from_returns(detail,'2026-11-11')
        self.assertTrue(result['stale']);self.assertIn('已停更',result['reason'])

    def test_completed_daily_uses_pricing_day_not_later_file_write_day(self):
        detail=estimate_detail();detail.update(mode='completed_daily',snapshot_at='2026-11-12T09:00:00+08:00',pricing_day='2026-11-11')
        for row in detail['rows']:
            if row['source_at']:row['source_at']='2026-11-11T15:00:00+08:00'
        result=estimate_from_returns(detail,'2026-11-10')
        self.assertEqual(result['current_date'],'2026-11-11');self.assertEqual(result['previous_date'],'2026-11-10')

    def test_real_contribution_pipeline_with_company_sized_universes_and_missing_data(self):
        for size,index in ((500,'000905.SH'),(1000,'000852.SH')):
            with self.subTest(size=size):
                members=[dict(symbol=f'{600000+i:06}.SH',weight_pct=100/size,
                    industry=None if i<49 else '电子') for i in range(size)]
                current=group(members,day='2026-10-23');current['index_id']=index
                quotes={r['symbol']:observation(101+(i%3),100) for i,r in enumerate(members[:-1])}
                quotes[index]=observation(101,100)
                snapshot=dict(snapshot_id='cycle',reference_version='v1',finished_at=NOW.isoformat(),quotes=quotes)
                detail=contributions(current,snapshot,dict(symbol=index,prev_close=100),NOW,'2026-10-23','v1')
                result=estimate_from_returns(detail,'2026-10-23')
                self.assertEqual(result['paired_members'],size-1);self.assertEqual(result['current_members'],size)
                self.assertAlmostEqual(result['anchor_weight'],100*(size-1)/size)
                self.assertEqual(result['denominator_source'],'同快照指数涨跌')
                self.assertTrue(any(r['name']=='待分类' for r in result['rows']))

    def test_timestamp_coverage_uses_chronological_not_text_order(self):
        detail=estimate_detail()
        detail['rows'][0]['source_at']='2026-11-12T01:59:58+00:00'
        detail['rows'][1]['source_at']='2026-11-12T09:59:57+08:00'
        result=estimate_from_returns(detail,'2026-11-11')
        self.assertEqual(result['source_at'],'2026-11-12T09:59:57+08:00')

    def test_rolled_weight_uses_rolled_date_not_original_reference_date(self):
        current=group([dict(symbol='600001.SH',weight_pct=100,industry='电子',reference_date='2026-10-16')],
                      day='2026-10-23')
        current.update(weight_method='fixed_quantity_estimate',official_as_of='2026-10-16')
        snapshot=dict(snapshot_id='cycle',reference_version='v1',finished_at=NOW.isoformat(),
                      quotes={'600001.SH':observation(102,100),'000905.SH':observation(101,100)})
        detail=contributions(current,snapshot,dict(symbol='000905.SH',prev_close=100),NOW,'2026-10-23','v1')
        result=estimate_from_returns(detail,'2026-10-23')
        self.assertEqual(result['anchor_date_range'],['2026-10-23','2026-10-23'])
        self.assertEqual(result['previous_weight_method'],'fixed_quantity_estimate')

    def test_pipeline_displays_estimate_when_old_weights_are_incomplete(self):
        detail=estimate_detail();day=pd.Timestamp('2026-11-12T10:00:02+08:00')
        index=dict(root='IC',symbol='000905.SH',prev_close=6000,quality={'usable':True},series=[])
        reference=dict(data=dict(schema='overview-reference-v1',fetched_at='2026-11-12T09:00:00+08:00',indices={}),
                       version='fixture',due=False,error=None)
        previous=dict(rows=[],reason='上一份权重不完整',diagnostics=dict(incompatible_groups=5),archive_truncated=False)
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(config={},local_root=Path(tmp),live_rows=pd.DataFrame())
            payload=dict(indices=[index],etfs=[],previous_session='2026-11-11',completed_session='2026-11-11')
            with patch('dashboard.native.overview_details.contributions',return_value=detail),\
                 patch('dashboard.marketdata.overview_industry_changes.load',return_value={'IC':previous}):
                enrich(model,payload,reference,day,equity_snapshot=dict(snapshot_id='one'))
            result=payload['index_details']['IC']['industry_change']
            self.assertEqual(result['comparison_kind'],'return_estimate');self.assertEqual(result['diagnostics']['incompatible_groups'],5)
            self.assertEqual(result['historical_fallback_reason'],'上一份权重不完整')
            safe=summary(result);self.assertEqual(safe['paired_members'],2);self.assertNotIn('rows',safe)

    def test_complete_history_wins_and_partial_history_yields_to_broader_sample(self):
        day=pd.Timestamp('2026-11-12T10:00:02+08:00')
        index=dict(root='IC',symbol='000905.SH',prev_close=6000,quality={'usable':True},series=[])
        reference=dict(data=dict(fetched_at='2026-11-12T09:00:00+08:00',indices={}),version='fixture',due=False,error=None)
        for kind,weight,expected in (('complete_history',10,'complete_history'),
                                     ('partial_history',10,'return_estimate'),
                                     ('partial_history',80,'partial_history')):
            with self.subTest(kind=kind,weight=weight),tempfile.TemporaryDirectory() as tmp:
                previous=dict(rows=[dict(name='电子',change_pp=1)],comparison_kind=kind,
                              paired_current_weight=weight,reason='历史样本',diagnostics={})
                model=SimpleNamespace(config={},local_root=Path(tmp),live_rows=pd.DataFrame())
                payload=dict(indices=[index],etfs=[],previous_session='2026-11-11',completed_session='2026-11-11')
                with patch('dashboard.native.overview_details.contributions',return_value=estimate_detail()),\
                     patch('dashboard.marketdata.overview_industry_changes.load',return_value={'IC':previous}):
                    enrich(model,payload,reference,day,equity_snapshot=dict(snapshot_id='one'))
                self.assertEqual(payload['index_details']['IC']['industry_change']['comparison_kind'],expected)

    def test_page_makes_estimation_and_coverage_visible(self):
        value=estimate_from_returns(estimate_detail(),'2026-11-11');page=IndexOverviewPage()
        try:
            page.selected_root='IC';page.details={'IC':dict(industries=[],industry_change=value)}
            page.show_detail();page.resize(1450,900);page.show();pump()
            self.assertIn('估算',page.weight_change_panel.title.text())
            self.assertIn('2/4',page.weight_change_panel.note.text())
            self.assertTrue(page.weight_changes.rows);self.assertIn('非官方',page.weight_change_panel.toolTip())
        finally:page.close();APP.processEvents()

    def test_chart_keeps_small_unclassified_group_visible(self):
        page=IndexOverviewPage()
        try:
            rows=[dict(name='行业'+str(i),change_pp=10-i) for i in range(9)]
            rows.append(dict(name='待分类',change_pp=.1))
            page.weight_changes.render(dict(rows=rows))
            self.assertIn('待分类',[r['name'] for r in page.weight_changes.rows])
            self.assertAlmostEqual(sum(r['change_pp'] for r in page.weight_changes.rows),sum(r['change_pp'] for r in rows))
        finally:page.close();APP.processEvents()


if __name__=='__main__':unittest.main()
