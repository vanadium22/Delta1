"""Editing a chart window never clears or redraws unrelated indicator charts."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication

from dashboard.native.indicator_analysis_view import IndicatorAnalysisPage
from tests.test_indicator_analysis import preview

APP=QApplication.instance() or QApplication([])


class SingleChartRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.page=IndicatorAnalysisPage(SimpleNamespace(local_root=Path(self.temp.name)))
        self.addCleanup(self.page.close)
        self.page.resize(1480,720);self.page.show();APP.processEvents()
        self.page.set_active(True);self.page.render(preview());APP.processEvents()

    def items(self):
        return {key:tuple(chart.plot.listDataItems()) for key,chart in self.page.charts.items()}

    def test_buttons_hidden_and_keyboard_edit_commits_only_after_enter(self):
        page=self.page
        for chart in page.charts.values():
            for control in (chart.window_spin,chart.stats):
                self.assertEqual(control.buttonSymbols(),QAbstractSpinBox.ButtonSymbols.NoButtons)
                self.assertFalse(control.keyboardTracking())
        control=page.charts['annual'].window_spin
        spy=QSignalSpy(page.changed);old=self.items()
        control.setFocus();control.lineEdit().selectAll()
        QTest.keyClicks(control.lineEdit(),'120');APP.processEvents()
        self.assertEqual(spy.count(),0)
        self.assertEqual(control.value(),90)
        self.assertEqual(self.items(),old)
        QTest.keyClick(control.lineEdit(),Qt.Key.Key_Return);APP.processEvents()
        self.assertEqual(spy.count(),1)
        self.assertEqual(control.value(),120)
        self.assertEqual(page._pending_charts,{'annual'})
        for key in set(page.charts)-{'annual'}:self.assertEqual(self.items()[key],old[key])

    def test_matching_result_redraws_only_the_edited_chart(self):
        page=self.page;old=self.items();old_result=page.result
        old_timer=page.draw_timer.timerId()
        with ExitStack() as stack:
            renders={key:stack.enter_context(patch.object(chart,'render',wraps=chart.render))
                     for key,chart in page.charts.items()}
            clears={key:stack.enter_context(patch.object(chart,'clear_result',wraps=chart.clear_result))
                    for key,chart in page.charts.items()}
            page.charts['annual'].window_spin.setValue(120)
            self.assertIs(page.result,old_result)
            self.assertEqual(page.draw_timer.timerId(),old_timer)
            self.assertEqual(clears['annual'].call_count,1)
            self.assertTrue(all(spy.call_count==0 for key,spy in clears.items() if key!='annual'))
            page.render(preview(page.request()));APP.processEvents()
            self.assertEqual(renders['annual'].call_count,1)
            self.assertTrue(all(spy.call_count==0 for key,spy in renders.items() if key!='annual'))
        self.assertFalse(page._pending_charts)
        for key in set(page.charts)-{'annual'}:self.assertEqual(self.items()[key],old[key])
        self.assertEqual(set(page.draw_evidence()['last_draw']['series']),{'annual'})

    def test_manual_statistics_input_commits_on_focus_change_only_for_its_chart(self):
        page=self.page;chart=page.charts['calendar_02_01']
        chart.auto.setChecked(False);page.render(preview(page.request()))
        old=self.items();spy=QSignalSpy(page.changed);control=chart.stats
        control.setFocus();control.lineEdit().selectAll()
        QTest.keyClicks(control.lineEdit(),'41');APP.processEvents()
        self.assertEqual(spy.count(),0);self.assertEqual(control.value(),20)
        chart.window_spin.setFocus();APP.processEvents()
        self.assertEqual(spy.count(),1);self.assertEqual(control.value(),41)
        self.assertEqual(page._pending_charts,{'calendar_02_01'})
        page.render(preview(page.request()))
        for key in set(page.charts)-{'calendar_02_01'}:self.assertEqual(self.items()[key],old[key])

    def test_multiple_edits_reject_stale_result_and_update_only_those_charts(self):
        page=self.page;old=self.items()
        page.charts['annual'].window_spin.setValue(110)
        stale=preview(page.request())
        page.charts['calendar_03_02'].window_spin.setValue(140)
        self.assertEqual(page._pending_charts,{'annual','calendar_03_02'})
        page.render(stale)
        self.assertIsNone(page.charts['annual'].result)
        self.assertIsNone(page.charts['calendar_03_02'].result)
        page.render(preview(page.request()));APP.processEvents()
        self.assertFalse(page._pending_charts)
        for key in ('adjusted','calendar_02_01'):self.assertEqual(self.items()[key],old[key])
        self.assertEqual(set(page.draw_evidence()['last_draw']['series']),{'annual','calendar_03_02'})

    def test_failed_update_preserves_other_charts_and_later_recovers(self):
        page=self.page;old=self.items()
        page.charts['calendar_02_01'].window_spin.setValue(120)
        page.render(dict(selection=page.request(),error='模拟读取错误'))
        self.assertEqual(page._pending_charts,{'calendar_02_01'})
        for key in set(page.charts)-{'calendar_02_01'}:self.assertEqual(self.items()[key],old[key])
        page.render(preview(page.request()))
        self.assertFalse(page._pending_charts)
        self.assertIsNotNone(page.charts['calendar_02_01'].result)
        for key in set(page.charts)-{'calendar_02_01'}:self.assertEqual(self.items()[key],old[key])

    def test_timer_remains_active_and_skips_pending_chart(self):
        page=self.page;page.charts['annual'].window_spin.setValue(120)
        self.assertTrue(page.draw_timer.isActive())
        self.assertEqual(page.draw_timer.interval(),30000)
        page.redraw(reason='timer')
        self.assertIsNone(page.charts['annual'].result)
        event=page.draw_evidence()['timer_draws'][-1]
        self.assertNotIn('annual',event['series'])
        self.assertEqual(set(event['series']),{'raw','adjusted','calendar_03_02','calendar_02_01'})
        page.render(preview(page.request()))
        page.redraw(reason='timer')
        self.assertIn('annual',page.draw_evidence()['timer_draws'][-1]['series'])

    def test_product_change_still_resets_all_charts_and_rejects_old_result(self):
        page=self.page;page.charts['annual'].window_spin.setValue(120)
        stale=preview(page.request())
        page.root.setCurrentIndex(1)
        self.assertIsNone(page.result)
        self.assertFalse(page._pending_charts)
        self.assertTrue(all(chart.result is None for chart in page.charts.values()))
        page.render(stale)
        self.assertIsNone(page.result)

    def test_real_window_worker_keeps_other_charts_unchanged(self):
        from dashboard.native.editions_current import PresentationWindow
        from tests.test_market_overview_ui import state as market_state
        model=SimpleNamespace(local_root=Path(self.temp.name)/'app',config={},close=Mock())
        model.local_root.mkdir()
        def capture(current):
            payload=market_state();choice=getattr(current,'indicator_analysis_request',None)
            if choice:payload['indicator_analysis']=preview(choice)
            return payload
        with patch('dashboard.native.market_overview.capture',side_effect=capture):
            window=PresentationWindow(model);window.timer.stop();window.resize(1480,720);window.show()
            try:
                window.pages.setCurrentWidget(window.indicator_page)
                for _ in range(250):
                    APP.processEvents();QTest.qWait(10)
                    if window.indicator_page.result is not None and not window.busy:break
                page=window.indicator_page
                self.assertIsNotNone(page.result)
                before={key:tuple(chart.plot.listDataItems()) for key,chart in page.charts.items()}
                page.charts['annual'].window_spin.setValue(120)
                for _ in range(250):
                    APP.processEvents();QTest.qWait(10)
                    if not page._pending_charts and not window.busy:break
                self.assertFalse(page._pending_charts)
                self.assertEqual(page.result['selection']['charts']['annual']['window'],120)
                for key in set(page.charts)-{'annual'}:
                    self.assertEqual(tuple(page.charts[key].plot.listDataItems()),before[key])
            finally:window.close();APP.processEvents()


if __name__=='__main__':unittest.main()
