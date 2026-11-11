"""Native controls, plotting breaks, reference extent and offline layout."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication
from dashboard.native.app import configure_style
from dashboard.native.indicator_analysis_view import IndicatorAnalysisPage, chart_data, seconds
from dashboard.marketdata.indicator_analysis import selection, point
from tests.test_indicator_analysis import preview

APP=QApplication.instance() or QApplication([])
configure_style(APP)


def pump():
    for _ in range(5):APP.processEvents();time.sleep(.002)


class IndicatorUiTests(unittest.TestCase):
    def page(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        model=SimpleNamespace(local_root=Path(tmp.name))
        page=IndicatorAnalysisPage(model);self.addCleanup(page.close)
        page.resize(1480,720);page.show();pump()
        return page

    def test_reference_lines_span_entire_plot_with_tz_values(self):
        page=self.page();result=preview();page.render(result)
        chart=page.charts['annual'];stats=result['series']['annual']['statistics']
        for key,line in chart.reference_lines.items():
            x,y=line.getData()
            self.assertEqual(list(x),[seconds(result['start']),seconds(result['end'])])
            self.assertEqual(list(y),[stats[key],stats[key]])

    def test_manual_statistics_window_survives_graph_change_and_restores(self):
        page=self.page();page.auto.setChecked(False);page.stats.setValue(45);page.window.setValue(30)
        self.assertEqual(page.request()['stats'],45)
        saved=json.loads((page.model.local_root/'indicator_ui.json').read_text(encoding='utf8'))
        self.assertEqual(saved['stats'],45)
        other=IndicatorAnalysisPage(page.model);self.addCleanup(other.close)
        self.assertEqual(other.request(),page.request());self.assertFalse(other.auto.isChecked())
        page.auto.setChecked(True);self.assertEqual(page.request()['stats'],15)

    def test_product_slot_overlay_and_view_controls(self):
        page=self.page();page.set_active(True);page.root.setCurrentIndex(3);page.slot.setCurrentIndex(2)
        self.assertEqual(page.model.indicator_analysis_request['root'],'IM')
        self.assertEqual(page.model.indicator_analysis_request['slot'],2)
        result=preview(selection(root='IM',slot=2));page.render(result)
        page.overlay.setCurrentIndex(1)
        self.assertEqual(page.charts['adjusted'].stat_key,'raw')
        page.view.setCurrentIndex(2);pump()
        self.assertTrue(page.charts['adjusted'].isHidden());self.assertFalse(page.charts['calendar_03_02'].isHidden())
        page.set_active(False);self.assertIsNone(page.model.indicator_analysis_request)

    def test_missing_values_and_rolls_are_not_connected(self):
        rows=[point('2026-10-20',['old'],value=1),point('2026-10-21',['new'],value=2),
              point('2026-10-22',['new']),point('2026-10-23',['new'],value=4),point('2026-10-26',['new'],value=5)]
        _,_,connect=chart_data(rows)
        self.assertEqual(list(connect),[False,False,False,True,False])

    def test_wide_and_narrow_reflow_keeps_controls_and_scroll(self):
        page=self.page();page.render(preview())
        for width,height,columns in ((1480,720,2),(830,500,1),(1180,660,1)):
            page.resize(width,height);pump()
            self.assertEqual(page.arrangement[1],columns)
            self.assertEqual(page.scroll.horizontalScrollBar().maximum(),0)
            for control in (page.root,page.slot,page.window,page.stats,page.view):self.assertGreaterEqual(control.height(),36)
            for chart in page.charts.values():
                self.assertGreater(chart.heading.width(),150)
                self.assertLess(chart.heading.height(),55)
        self.assertGreater(page.scroll.verticalScrollBar().maximum(),0)

    def test_page_construction_and_controls_never_acquire_data(self):
        with patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            page=self.page();page.root.setCurrentIndex(1);page.window.setValue(10);page.render(preview(page.request()))
        self.assertEqual(page.stats.value(),5)

    def test_result_from_previous_selection_cannot_replace_new_page(self):
        page=self.page();page.render(preview());page.root.setCurrentIndex(2)
        page.render(preview());self.assertIsNone(page.result)
        for chart in page.charts.values():self.assertIsNone(chart.result)

    def test_frozen_page_preserves_captured_selection_without_saving_preferences(self):
        page=self.page();result=preview(selection(root='IM',slot=3,stats=30));page.freeze(result)
        page.set_active(True)
        self.assertEqual(page.request(),result['selection']);self.assertIsNone(page.model.indicator_analysis_request)
        self.assertFalse(page.root.isEnabled());self.assertTrue(page.history.isHidden())
        self.assertFalse((page.model.local_root/'indicator_ui.json').exists())
        page.overlay.setCurrentIndex(1);self.assertEqual(page.charts['adjusted'].stat_key,'raw')

    def test_production_window_routes_active_tab_and_captures_snapshot(self):
        from dashboard.native.editions_current import PresentationWindow, freeze_window
        from tests.test_market_overview_ui import state as market_state
        page=self.page();page.close()
        model=SimpleNamespace(local_root=page.model.local_root,config={},close=Mock())
        payload=market_state();payload['indicator_analysis']=preview()
        with patch('dashboard.native.market_overview.capture',return_value=payload):
            window=PresentationWindow(model);window.timer.stop();window.show();self.addCleanup(window.close);pump()
            self.assertIn('指标分析',[window.pages.tabText(i) for i in range(window.pages.count())])
            window.pages.setCurrentWidget(window.indicator_page);pump()
            self.assertEqual(model.indicator_analysis_request,selection())
            self.assertEqual(window.indicator_page.result['selection'],selection())
            self.assertEqual(freeze_window(payload)['snapshots'][0]['indicator_analysis'],payload['indicator_analysis'])
            window.pages.setCurrentWidget(window.quotes);pump();self.assertIsNone(model.indicator_analysis_request)
            window.close();pump()


if __name__=='__main__':unittest.main()
