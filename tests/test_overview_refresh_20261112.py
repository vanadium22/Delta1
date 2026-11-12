"""Same-window statistics, refresh behavior, dated comparisons and safe evidence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QLabel

from dashboard.marketdata.indicator_analysis import selection
from dashboard.marketdata.overview_percentiles import evaluate
from dashboard.marketdata.overview_industry_changes import compare,load
from dashboard.marketdata.overview_reference import publish
from dashboard.native.futures_overview import details
from dashboard.native.futures_overview_view import FuturesCard,percentile_color
from dashboard.native.indicator_analysis import IndicatorAnalysisEngine
from dashboard.native.indicator_analysis_view import IndicatorAnalysisPage
from dashboard.native.overview_charts import ProductCharts
from dashboard.native.overview_pages import EtfOverviewPage
from dashboard.overview_check import main as overview_main
from tests.test_indicator_analysis import fixture,preview
from tests.test_market_overview import ZERO_DIVIDENDS,observation,NOW
from tests.test_overview_details import reference
from tests.test_market_overview_ui import APP,pump


def history():
    return dict(alias='IF00.CFE',pricing_day='2026-10-27',current_symbol='IF2611.CFE',
        current_mapping_error=False,rows=[dict(day=f'2026-08-{i:03d}',excluded=False,annual_pct=float(i),
        reason=None,symbol='IF2611.CFE',dividend_estimated_zero=False) for i in range(1,61)])


class WindowStatisticsTests(unittest.TestCase):
    def test_20_and_60_mean_median_use_same_exact_existing_windows(self):
        result=evaluate(history(),50,'IF2611.CFE')['windows']
        self.assertEqual((result['20']['mean'],result['20']['median']),(50.5,50.5))
        self.assertEqual((result['60']['mean'],result['60']['median']),(30.5,30.5))
        self.assertEqual(result['20']['samples'],20);self.assertEqual(result['60']['samples'],60)
        self.assertEqual(result['20']['percentile'],47.5)

    def test_missing_invalidates_window_but_excluded_t_never_replenishes(self):
        value=history();value['rows'][-1].update(annual_pct=None,excluded=True,reason='T_LT_5')
        result=evaluate(value,50,'IF2611.CFE')['windows']['20']
        self.assertTrue(result['complete']);self.assertEqual(result['samples'],19)
        self.assertEqual((result['mean'],result['median']),(50.,50.))
        value['rows'][-2].update(annual_pct=None,reason='future_close_missing')
        result=evaluate(value,50,'IF2611.CFE')['windows']['20']
        self.assertFalse(result['complete']);self.assertIsNone(result['mean']);self.assertIsNone(result['median'])

    def test_current_missing_retains_reference_means_and_low_high_tails_are_symmetric(self):
        result=evaluate(history(),None,'IF2611.CFE')['windows']['20']
        self.assertEqual(result['mean'],50.5);self.assertIsNone(result['percentile'])
        self.assertEqual(percentile_color(0)[1],1);self.assertEqual(percentile_color(100)[1],1)
        self.assertEqual(percentile_color(10)[1],percentile_color(90)[1]);self.assertEqual(percentile_color(50)[1],0)
        self.assertEqual(percentile_color(None)[1],0)

    def test_compact_card_promotes_slot_and_shows_means_and_dates(self):
        row=dict(root='IF',symbol='IF2611.CFE',slot=0,price=4000,expiry='2026-11-20',days=24,
                 continuous_percentiles=evaluate(history(),50,'IF2611.CFE'))
        card=FuturesCard(None,compact=True)
        try:
            card.render(row,0)
            self.assertEqual(card.badge.text(),'IF 00 · 当月');self.assertEqual(card.heading.text(),'IF2611')
            self.assertTrue(card.previous_value.isHidden());self.assertEqual(card.means[20].text(),'50.50%')
            self.assertEqual(card.medians[60].text(),'30.50%');self.assertIn('2026-08-',card.window_dates[20].toolTip())
        finally:card.close();card.deleteLater();APP.processEvents()


class IndicatorRefreshTests(unittest.TestCase):
    def test_live_statistics_continue_while_chart_waits_for_30_second_redraw(self):
        with tempfile.TemporaryDirectory() as tmp:
            page=IndicatorAnalysisPage(SimpleNamespace(local_root=Path(tmp)));page.resize(1480,720);page.show();pump()
            try:
                page.set_active(True);self.assertEqual(page.draw_timer.interval(),30000);self.assertTrue(page.draw_timer.isActive())
                first=preview();page.render(first);chart=page.charts['annual']
                second=deepcopy(first);second['series']['annual']['statistics']['z']=12.5
                second['series']['annual']['current']['value']=6.75
                second['series']['annual']['rows'][-1]['value']=6.75
                page.render(second)
                self.assertIs(chart.result,first);self.assertEqual(chart.metrics['z'][1].text(),'12.50')
                page.redraw();self.assertIs(chart.result,second)
                self.assertEqual(chart.result['series']['annual']['rows'][-1]['value'],6.75)
                page.set_active(False);self.assertFalse(page.draw_timer.isActive())
            finally:page.close();APP.processEvents()

    def make_engine(self,tmp,day):
        request=selection();planned,meta,tables,_=fixture(request,day=day)
        for table in tables.values():table.pop(day,None)
        model=SimpleNamespace(config={},local_root=Path(tmp),_overview_latest={})
        repo=SimpleNamespace(read_window=lambda s,*a,**k:pd.DataFrame(tables.get(s,{}).values()))
        return request,planned,meta,IndicatorAnalysisEngine(model),repo

    def test_postclose_missing_today_replans_all_stats_to_real_prior_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,_,meta,engine,repo=self.make_engine(tmp,'2026-11-11')
            result=engine.snapshot(request,now=pd.Timestamp('2026-11-11T15:47:30+08:00'),completed='2026-11-11',
                                   metadata=meta,dividends=ZERO_DIVIDENDS,repo=repo,frozen={})
            self.assertTrue(result['reference_fallback']);self.assertEqual(result['pricing_day'],'2026-11-10')
            self.assertEqual(result['completed_target'],'2026-11-11');self.assertNotIn('2026-11-10',result['reference_days'])
            self.assertTrue(all(result['series'][k]['current']['day']=='2026-11-10' for k in result['series']))
            self.assertIsNotNone(result['series']['annual']['statistics']['percentile'])

    def test_reference_day_dividend_missing_is_never_replaced_by_historical_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,_,meta,engine,repo=self.make_engine(tmp,'2026-11-11')
            book=SimpleNamespace(resolve=lambda s,at:None,version='missing',info={},reason='')
            result=engine.snapshot(request,now=pd.Timestamp('2026-11-11T15:47:30+08:00'),completed='2026-11-11',
                                   metadata=meta,dividends=book,repo=repo,frozen={})
            self.assertIsNotNone(result['series']['raw']['current']['value'])
            self.assertIsNone(result['series']['annual']['current']['value'])
            self.assertEqual(result['series']['annual']['current']['reason'],'dividend_missing_or_conflict')
            self.assertFalse(result['series']['annual']['current']['zero_dividend_symbols'])

    def test_near_expiry_exclusion_never_falls_back_to_old_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,_,meta,engine,repo=self.make_engine(tmp,'2026-10-15')
            result=engine.snapshot(request,now=pd.Timestamp('2026-10-15T15:47:30+08:00'),completed='2026-10-15',
                                   metadata=meta,dividends=ZERO_DIVIDENDS,repo=repo,frozen={})
            self.assertEqual(result['pricing_day'],'2026-10-15');self.assertFalse(result['reference_fallback'])
            self.assertEqual(result['series']['annual']['current']['reason'],'T_LT_5')


class IndustryChangesTests(unittest.TestCase):
    def test_compare_is_percentage_points_and_warns_if_classification_changes(self):
        current=reference()['indices']['IF'];old=deepcopy(current);old['as_of']='2026-10-22'
        old['rows'][0]['weight_pct']=45;old['rows'][1]['weight_pct']=35
        result=compare(current,old)
        changes={r['name']:r['change_pp'] for r in result['rows']}
        self.assertEqual(changes['电子'],5);self.assertEqual(changes['银行'],-5)
        old['rows'][0]['industry']=None
        result=compare(current,old);self.assertEqual(result['reclassified'],1);self.assertIn('分类',result['reason'])

    def test_incomplete_or_incompatible_weight_data_remains_missing(self):
        current=reference()['indices']['IF'];old=deepcopy(current);old['as_of']='2026-10-22'
        for patch_values in ({'weights_complete':False},{'industry_standard':'不同标准'},{'index_id':'000016.SH'}):
            candidate=dict(old,**patch_values)
            self.assertEqual(compare(current,candidate)['rows'],[])

    def test_archive_comparison_skips_nav_only_duplicates_and_future_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_reference/latest.json'
            prior=reference();prior['fetched_at']='2026-10-23T15:00:00+08:00';prior['indices']['IF']['as_of']='2026-10-22'
            prior['indices']['IF']['rows'][0]['weight_pct']=45;prior['indices']['IF']['rows'][1]['weight_pct']=35
            publish(path,prior)
            duplicate=reference();duplicate['fetched_at']='2026-10-25T12:00:00+08:00';publish(path,duplicate)
            current=reference();publish(path,current)
            future=deepcopy(prior);future['fetched_at']='2026-10-27T12:00:00+08:00';publish(path,future)
            value=load({},tmp,current,{'IF':current['indices']['IF']})['IF']
            self.assertEqual(value['previous_date'],'2026-10-22');self.assertEqual(value['current_date'],'2026-10-23')
            self.assertEqual(next(r['change_pp'] for r in value['rows'] if r['name']=='电子'),5)

    def test_estimate_may_compare_to_its_exact_official_anchor_but_not_other_weights(self):
        old=reference()['indices']['IF'];current=deepcopy(old)
        current.update(as_of='2026-10-26',official_as_of=old['as_of'],weight_method='fixed_quantity_estimate')
        for row in current['rows']:row['official_weight_pct']=row['weight_pct']
        current['rows'][0]['weight_pct']+=1;current['rows'][1]['weight_pct']-=1
        result=compare(current,old)
        self.assertTrue(result['rows']);self.assertIn('估算',result['reason'])
        self.assertEqual(result['previous_weight_method'],'provided_reference')
        altered=deepcopy(old);altered['rows'][0]['weight_pct']+=.01
        self.assertEqual(compare(current,altered)['rows'],[])

    def test_previous_daily_estimate_is_preferred_and_preserves_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=reference();anchor=source['indices']['IF'];current=deepcopy(anchor);old=deepcopy(anchor)
            current.update(as_of='2026-10-27',official_as_of=anchor['as_of'],weight_method='fixed_quantity_estimate')
            old.update(as_of='2026-10-26',official_as_of=anchor['as_of'],weight_method='fixed_quantity_estimate')
            current['rows'][0]['weight_pct']+=1;current['rows'][1]['weight_pct']-=1
            with patch('dashboard.marketdata.overview_weights.roll',return_value=old) as roll:
                value=load({},tmp,source,{'IF':current},previous_day='2026-10-26')['IF']
            self.assertEqual(value['previous_date'],'2026-10-26');self.assertEqual(value['current_date'],'2026-10-27')
            self.assertIn('两次均为',value['reason']);self.assertEqual(roll.call_count,1)


class OverviewGraphsAndEtfTests(unittest.TestCase):
    def test_position_distribution_requires_four_same_date_values(self):
        rows=[dict(root='IF',symbol='IF'+str(i),slot=i,price=4000,volume=10*(i+1),quality={'usable':True},
                   yesterday_open_interest=100*(i+1),yesterday_oi_date='2026-11-10') for i in range(4)]
        live={r['symbol']:observation() for r in rows};live['000300.SH']=observation()
        group=details(rows,[dict(root='IF',symbol='000300.SH')],live,pd.DataFrame(),NOW,dividends=ZERO_DIVIDENDS)['IF']
        self.assertEqual([r['share_pct'] for r in group['position_distribution']],[10,20,30,40])
        self.assertEqual(group['position_date'],'2026-11-10')
        rows[-1]['yesterday_oi_date']='2026-11-09'
        group=details(rows,[dict(root='IF',symbol='000300.SH')],live,pd.DataFrame(),NOW,dividends=ZERO_DIVIDENDS)['IF']
        self.assertEqual(group['position_distribution'],[]);self.assertEqual(len(group['distribution']),4)

    def test_position_prefers_synchronized_live_oi_and_labels_daily_fallback(self):
        rows=[dict(root='IF',symbol='IF'+str(i),slot=i,price=4000,volume=10,quality={'usable':True},
                   yesterday_open_interest=100*(i+1),yesterday_oi_date='2026-10-23') for i in range(4)]
        live={r['symbol']:observation(open_interest=v) for r,v in zip(rows,[10,10,20,60])}
        live['000300.SH']=observation()
        group=details(rows,[dict(root='IF',symbol='000300.SH')],live,pd.DataFrame(),NOW,dividends=ZERO_DIVIDENDS)['IF']
        self.assertEqual([r['share_pct'] for r in group['position_distribution']],[10,10,20,60])
        self.assertEqual(group['position_mode'],'current_http');self.assertIn('实时',group['position_reason'])
        live[rows[0]['symbol']]['open_interest']=0
        group=details(rows,[dict(root='IF',symbol='000300.SH')],live,pd.DataFrame(),NOW,dividends=ZERO_DIVIDENDS)['IF']
        self.assertEqual([r['share_pct'] for r in group['position_distribution']],[10,20,30,40])
        self.assertEqual(group['position_mode'],'completed_daily');self.assertIn('2026-10-23',group['position_reason'])

    def test_term_chart_keeps_valid_points_when_one_pair_is_missing_or_misaligned(self):
        chart=ProductCharts('IF','沪深300')
        rows=[dict(symbol='IF'+str(i),slot=i,days=10+30*i,annual_pct=float(i),pricing_day='2026-10-26',basis_kind='realtime',
                   basis_future_source_at=NOW.isoformat(),basis_spot_source_at=NOW.isoformat()) for i in range(4)]
        try:
            rows[1]['annual_pct']=None;chart.render(rows,{})
            self.assertEqual([r['slot'] for r in chart.curve_points],[0,2,3])
            curve=chart.curve.listDataItems()[0];self.assertEqual(list(curve.opts['connect']),[False,True,False])
            rows[3]['basis_future_source_at']=(NOW-pd.Timedelta(seconds=4)).isoformat();chart.render(rows,{})
            self.assertEqual([r['slot'] for r in chart.curve_points],[0,2])
        finally:chart.close();chart.deleteLater();APP.processEvents()

    def test_distribution_labels_do_not_overlap_their_bars(self):
        chart=ProductCharts('IF','沪深300');chart.resize(700,320);chart.show();pump()
        try:
            captions={label.text():label for label in chart.findChildren(QLabel)}
            self.assertLess(captions['成交'].geometry().right(),chart.volume.geometry().left())
            self.assertLess(captions['持仓'].geometry().right(),chart.position.geometry().left())
        finally:chart.close();chart.deleteLater();APP.processEvents()

    def test_etf_default_table_uses_current_groups_and_opens_detail(self):
        page=EtfOverviewPage();groups={}
        for j,root in enumerate(('IF','IH','IC','IM')):
            rows=[dict(root=root,symbol=f'{510300+j*10+i:06}.SH',name=root+'ETF'+str(i),price=4+i/10,
                       change_pct=0,closing_premium_bp=-1,nav_date='2026-11-10',aum_cny=1e8,aum_date='2026-11-10',
                       aum_share_pct=10,spread_bp=2,amount_cny=100000,source_at='2026-11-11T10:00:00+08:00') for i in range(3)]
            groups[root]=dict(rows=rows,ranking=dict(as_of='2026-11-10'))
        try:
            page.render([],groups,{})
            self.assertIsNone(page.selected_root);self.assertEqual(page.all_table.rowCount(),12)
            self.assertEqual(page.all_table.item(0,0).text(),'IF');self.assertEqual(page.all_table.item(0,3).text(),'4.000')
            self.assertIn('2026-11-10',page.all_table.item(0,5).toolTip())
            page.open_summary_row(3,0);self.assertEqual(page.selected_root,'IH');self.assertEqual(len(page.visible_rows),3)
            page.select(None);self.assertEqual(page.all_table.rowCount(),12)
            extra=dict(root='IF',symbol='515000.SH',name='额外订阅ETF',price=3.6)
            page.render([*groups['IF']['rows'],extra],groups,{})
            self.assertEqual(page.all_table.rowCount(),13)
            self.assertEqual(page.all_table.item(3,2).text(),'515000.SH')
            self.assertEqual(page.all_table.item(3,6).text(),'—')
        finally:page.close();page.deleteLater();APP.processEvents()


class SafeDiagnosticsTests(unittest.TestCase):
    def test_overview_nonfinite_is_null_with_safe_normalization_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'overview.json'
            payload=dict(schema='overview-company-check-v1',x=float('nan'),y=np.int64(3),network_requested=False)
            with patch('dashboard.overview_check.collect',return_value=payload):
                code=overview_main(['--local-root',tmp,'--output',str(output)])
            data=json.loads(output.read_text(encoding='utf8'))
            self.assertEqual(code,0);self.assertIsNone(data['x']);self.assertEqual(data['y'],3)
            self.assertEqual(data['serialization_status'],'normalized_nonfinite_or_scalar')

    def test_unserializable_object_generates_safe_error_not_partial_json_or_secret(self):
        class Private:
            def __repr__(self):return 'CANARY_PRIVATE_OBJECT'
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'overview.json'
            with patch('dashboard.overview_check.collect',return_value={'value':Private()}):
                code=overview_main(['--local-root',tmp,'--output',str(output)])
            raw=output.read_text(encoding='utf8');data=json.loads(raw)
            self.assertEqual(code,1);self.assertEqual(data['error_type'],'ReportSerializationError')
            self.assertNotIn('CANARY',raw)

    @unittest.skipUnless(os.name=='nt','Windows PowerShell native process behavior')
    def test_stderr_warning_does_not_abort_overview_and_safe_report_contains_no_raw_text(self):
        repository=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profile';profile.mkdir();(profile/'native.json').write_text('{}')
            stub=root/'fake_python.py'
            stub.write_text("import json, pathlib, sys\na=sys.argv[1:]\nout=pathlib.Path(a[a.index('--output')+1])\n"
                "pre='dashboard.app_check' in a\nv={'ok':True,'profile':str(pathlib.Path(a[a.index('--local-root')+1])/'native.json')} if pre else {'schema':'overview-company-check-v1','diagnostic_profile':{'local_root':a[a.index('--local-root')+1]}}\n"
                "out.write_text(json.dumps(v),encoding='utf8')\n"
                "sys.stderr.write('Warning: CANARY_RAW_SECRET\\n') if not pre else None\n",encoding='utf8')
            wrapper=root/'fake_python.cmd';wrapper.write_text('@"'+sys.executable+'" -B "'+str(stub)+'" %*\r\n',encoding='utf8')
            env=dict(os.environ,SWHY_DELTA1_PYTHON=str(wrapper))
            cmd=['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','Bypass',
                 '-File',str(repository/'dashboard/diagnose_presentation.ps1'),'-LocalRoot',str(profile),'-OutputDirectory',str(root/'reports'),'-Overview','-NoPause']
            done=subprocess.run(cmd,cwd=repository,env=env,capture_output=True,text=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(done.returncode,0,done.stderr)
            found=re.search(r'^Report: (.+)$',done.stdout,re.M);self.assertIsNotNone(found,done.stdout)
            raw=Path(found[1].strip()).read_text(encoding='utf-8-sig');report=json.loads(raw)
            self.assertEqual(report['overview_exit_code'],0);self.assertTrue(report['overview_stderr']['warning'])
            self.assertTrue(Path(report['overview_report']).is_file());self.assertNotIn('CANARY',raw)


if __name__=='__main__':unittest.main()
