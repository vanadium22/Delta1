"""Company feedback: visible compact layout and inspectable redraw provenance."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtCore import QPoint,QPointF,Qt

from dashboard.marketdata.indicator_analysis import draw_summary
from dashboard.marketdata.overview_industry_changes import load,summary as industry_summary
from dashboard.marketdata.overview_reference import publish
from dashboard.native.editions_current import PresentationWindow
from dashboard.native.indicator_analysis_view import IndicatorAnalysisPage
from dashboard.overview_check import app_reports
from tests.test_indicator_analysis import preview
from tests.test_market_overview_ui import APP,pump,state
from tests.test_overview_details import reference


class SinglePageTests(unittest.TestCase):
    def test_all_four_charts_and_sixteen_contracts_fit_wide_view_without_overlap(self):
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.native.market_overview.capture',return_value=state()),\
             patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            model=SimpleNamespace(local_root=Path(tmp),config={},close=Mock())
            window=PresentationWindow(model);window.timer.stop();window.resize(1536,864);window.show();pump(.5)
            try:
                page=window.quotes;self.assertEqual(page.scroll.verticalScrollBar().maximum(),0)
                self.assertGreater(page.scroll.display_scale,.5)
                self.assertEqual(len(page.cards),16);self.assertEqual(set(page.charts),{'IF','IH','IC','IM'})
                viewport=page.scroll.viewport().rect()
                for row in page.products.values():
                    self.assertEqual(row.flow.columns,4)
                    positions=[card.geometry() for card in row.futures]
                    self.assertEqual(len({rect.y() for rect in positions}),1)
                    self.assertTrue(all(not a.intersects(b) for i,a in enumerate(positions) for b in positions[i+1:]))
                    self.assertTrue(all(rect.bottom()<row.flow.height() for rect in positions))
                    origin=row.chart.mapTo(page.body,QPoint(0,0))
                    bottom=QPointF(origin.x()+row.chart.width()-2,origin.y()+row.chart.height()-2)
                    point=page.scroll.mapFromScene(page.scroll.proxy.mapToScene(bottom))
                    self.assertTrue(viewport.contains(point),str(point))
                for width in (1000,1050,1100,1150,1200,1536):
                    window.resize(width,800);pump(.06)
                    self.assertEqual(page.scroll.horizontalScrollBar().maximum(),0)
            finally:window.close();pump();self.assertTrue(model.close.called)

    def test_etf_summary_has_larger_font_stripes_and_fits_twelve_rows(self):
        from dashboard.native.overview_pages import EtfOverviewPage
        page=EtfOverviewPage();rows=[]
        for j,root in enumerate(('IF','IH','IC','IM')):
            for i in range(3):rows.append(dict(root=root,symbol=f'{510300+j*10+i:06}.SH',name=root+'ETF'+str(i),
                price=4,change_pct=-1 if i==0 else 1,premium_bp=1,aum_cny=1e8,aum_date='2026-11-10',
                source_at='2026-11-12T10:00:00+08:00'))
        page.resize(1536,700);page.show();page.render(rows);pump(.25)
        try:
            table=page.all_table;self.assertEqual(table.rowCount(),12);self.assertTrue(table.alternatingRowColors())
            self.assertIn('font-size:18px',table.styleSheet());self.assertGreaterEqual(table.verticalHeader().defaultSectionSize(),40)
            self.assertEqual(table.verticalScrollBar().maximum(),0);self.assertEqual(page.scroll.verticalScrollBar().maximum(),0)
            self.assertNotEqual(table.item(0,4).foreground().color(),table.item(1,4).foreground().color())
        finally:page.close();APP.processEvents()


class DrawEvidenceTests(unittest.TestCase):
    def test_real_timer_records_two_updated_snapshots_and_larger_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            page=IndicatorAnalysisPage(SimpleNamespace(local_root=Path(tmp)));page.resize(1480,720);page.show();pump()
            try:
                page.set_active(True);self.assertEqual(page.draw_timer.interval(),30000)
                self.assertEqual(page.draw_timer.timerType(),Qt.TimerType.PreciseTimer)
                first=preview();first['as_of']='2026-10-27T10:00:00+08:00'
                first['series']['annual']['current']['value']=1.25;first['series']['annual']['statistics']['z']=.1
                page.render(first)
                marks=[item for item in page.charts['annual'].plot.listDataItems() if item.opts.get('symbol')=='o']
                self.assertEqual(len(marks),1);self.assertEqual(marks[0].opts['symbolSize'],11)
                page.draw_timer.setInterval(100)
                for _ in range(10):
                    pump(.1)
                    if page.draw_evidence()['timer_draws']:break
                page.draw_timer.stop();first_event=draw_summary(page.draw_evidence())['timer_draws'][-1]
                second=deepcopy(first);second['as_of']='2026-10-27T10:00:02+08:00'
                second['series']['annual']['current']['value']=2.5;second['series']['annual']['statistics']['z']=.2
                page.render(second);page.draw_timer.start()
                for _ in range(10):
                    pump(.1)
                    if page.draw_evidence()['timer_draws'][-1]['series']['annual']['current']==2.5:break
                page.draw_timer.stop()
                evidence=draw_summary(page.draw_evidence());events=evidence['timer_draws']
                self.assertGreaterEqual(len(events),2)
                self.assertEqual([first_event['series']['annual']['current'],events[-1]['series']['annual']['current']],[1.25,2.5])
                self.assertEqual([first_event['series']['annual']['z'],events[-1]['series']['annual']['z']],[.1,.2])
                self.assertTrue(all(event['draw_at'] and event['reason']=='timer' for event in events))
            finally:page.close();APP.processEvents()

    def test_safe_report_keeps_only_bounded_redraw_and_industry_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'runs'/'one'/'status.json';path.parent.mkdir(parents=True)
            event=dict(draw_at='2026-11-12T10:00:30+08:00',calculation_at='2026-11-12T10:00:29+08:00',
                reason='timer',selection=dict(root='IC',slot=3,window=90,stats=20),mode='realtime',pricing_day='2026-11-12',
                series={'annual':dict(source_at='2026-11-12T10:00:28+08:00',current=-7,z=.7,percentile=65,private='CANARY')},private='CANARY')
            value=dict(schema='app-update-evidence-v1',local_root=str(root),indicator_draw=dict(active=True,frozen=False,
                interval_ms=30000,last_draw=event,timer_draws=[event]*6),
                index_industry_changes={'IC':dict(rows=[dict(name='CANARY')],reason='暂无上一份可比权重快照',
                    diagnostics=dict(archive_groups=0,current_members=500,unclassified_members=49))})
            path.write_text(json.dumps(value),encoding='utf8')
            result=app_reports(root,root/'runs')['matching_profile'][0]
            self.assertEqual(len(result['indicator_draw']['timer_draws']),3)
            self.assertEqual(result['indicator_draw']['last_draw']['series']['annual']['z'],.7)
            self.assertEqual(result['index_industry_changes']['IC']['diagnostics']['unclassified_members'],49)
            self.assertNotIn('CANARY',json.dumps(result))

    def test_pipeline_report_contains_actual_draw_and_industry_provenance(self):
        from tests.test_app_pipeline import PipelineTests
        case=PipelineTests();window,pipeline=case.fixture()
        try:
            window.indicator_page=SimpleNamespace(draw_evidence=lambda:dict(active=True,frozen=False,interval_ms=30000,last_draw=None,timer_draws=[]))
            window.state=dict(market_overview=dict(index_details={'IC':dict(industry_change=dict(rows=[],reason='暂无可比快照',
                diagnostics=dict(current_members=500,unclassified_members=49)))}))
            report=pipeline.report()
            self.assertEqual(report['indicator_draw']['interval_ms'],30000)
            self.assertEqual(report['index_industry_changes']['IC']['diagnostics']['unclassified_members'],49)
        finally:case.doCleanups()


class IndustryEvidenceTests(unittest.TestCase):
    def test_duplicate_and_incompatible_archives_have_distinct_visible_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_reference/latest.json';current=reference();publish(path,current)
            result=load({},tmp,current,{'IF':current['indices']['IF']})['IF']
            self.assertEqual(result['rows'],[]);self.assertIn('相同权重',result['reason'])
            self.assertGreater(result['diagnostics']['duplicate_groups'],0)
            prior=deepcopy(current);prior['fetched_at']='2026-10-24T10:00:00+08:00'
            prior['indices']['IF']['as_of']='2026-10-22';prior['indices']['IF']['industry_standard']='其他分类'
            publish(path,prior)
            result=load({},tmp,current,{'IF':current['indices']['IF']})['IF']
            self.assertEqual(result['rows'],[]);self.assertIn('分类口径',result['reason'])
            safe=industry_summary(result);self.assertGreater(safe['diagnostics']['incompatible_groups'],0)
            self.assertNotIn('rows',safe);self.assertEqual(safe['row_count'],0)


if __name__=='__main__':unittest.main()
