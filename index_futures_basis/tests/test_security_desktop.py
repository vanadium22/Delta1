import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from index_futures_basis.desktop import Window
from index_futures_basis.service import BasisService


class SecurityDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DELTA1_DATA_ROOT": str(Path(self.temp.name) / "data"),
                                          "DELTA1_OUTPUTS_ROOT": str(Path(self.temp.name) / "outputs")})
        self.env.start()
        self.window = Window(BasisService(Path(self.temp.name), "demo"), auto_start=False)
        self.window.resize(1240, 800)
        self.page = self.window.security_page
        self.window.tabs.setCurrentWidget(self.page)
        self.window.show()
        self.page.start.setDateTime(QDateTime.fromString("2026-10-14 09:30", "yyyy-MM-dd HH:mm"))
        self.page.end.setDateTime(QDateTime.fromString("2026-10-14 09:35", "yyyy-MM-dd HH:mm"))

    def wait(self):
        deadline = time.monotonic() + 30
        while (self.window.worker is not None or self.page.name_worker is not None) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertIsNone(self.window.worker)
        self.assertIsNone(self.page.name_worker)

    def tearDown(self):
        self.page.name_timer.stop()
        self.wait()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.env.stop()
        self.temp.cleanup()

    def test_minute_query_chart_copy_export_and_invalidation(self):
        self.page.frequency.setCurrentIndex(1)
        self.page.twap.setChecked(True)
        self.page.vwap.setChecked(True)
        self.page.volume_unit.setCurrentIndex(self.page.volume_unit.findData("share"))
        self.page.amount_unit.setCurrentIndex(self.page.amount_unit.findData("yuan"))
        with patch("index_futures_basis.security_data.SecurityProvider", side_effect=AssertionError("network")):
            self.page.query()
            self.wait()
        self.assertIsNotNone(self.page.result, self.page.info.text())
        self.assertEqual(len(self.page.result.frame), 5)
        self.assertIn("TWAP", self.page.metrics.text())
        self.assertIn("VWAP", self.page.metrics.text())
        self.assertNotEqual(self.page.metric_values["twap"].text(), "—")
        self.assertNotEqual(self.page.metric_values["vwap"].text(), "—")
        self.assertIn("5/5", self.page.metric_hints["twap"].text())
        self.assertTrue(self.page.png.startswith(b"\x89PNG"))
        self.page.data_table.copy()
        self.assertIn("09:31", self.app.clipboard().text())
        with patch("index_futures_basis.security_desktop.QFileDialog.getExistingDirectory", return_value=self.temp.name):
            self.page.export()
            self.wait()
        self.assertEqual(len(list(Path(self.temp.name).glob("*_600519.SH_*/chart.png"))), 1)
        self.page.code.setText("000001.SZ")
        self.assertIsNone(self.page.result)
        self.assertEqual(self.page.data_table.model().rowCount(), 0)
        self.assertFalse(self.page.export_button.isEnabled())

    def test_snapshot_single_value_disables_window_and_uses_latest_label(self):
        self.page.frequency.setCurrentIndex(2)
        self.assertFalse(self.page.start.isEnabled())
        self.assertFalse(self.page.twap.isEnabled())
        self.assertIn("最新成交价", self.page.fields["close"].text())
        self.page.query()
        self.wait()
        self.assertIsNotNone(self.page.result, self.page.info.text())
        self.assertEqual(self.page.data_table.model().rowCount(), 1)
        self.assertEqual(self.page.png, b"")
        self.assertIn("最新成交价", self.page.metrics.text())

    def test_frequency_and_security_changes_reset_units_and_shortcuts_use_active_page(self):
        self.page.volume_unit.setCurrentIndex(1)
        self.page.amount_unit.setCurrentIndex(1)
        self.page.frequency.setCurrentIndex(1)
        self.assertEqual(self.page.volume_unit.currentData(), "unknown")
        self.assertEqual(self.page.amount_unit.currentData(), "unknown")
        self.page.volume_unit.setCurrentIndex(1)
        self.page.code.setText("000001.SZ")
        self.assertEqual(self.page.volume_unit.currentData(), "unknown")
        with patch.object(self.page, "query") as query, patch.object(self.window, "sync") as sync:
            self.window.refresh_active_page()
            self.window.query_active_page()
            self.assertEqual(query.call_count, 2)
            sync.assert_not_called()

    def test_failed_query_and_mode_switch_clear_result(self):
        self.page.query()
        self.wait()
        self.assertIsNotNone(self.page.result)
        with patch("index_futures_basis.security_data.DemoSecurityProvider.request", side_effect=RuntimeError("模拟权限失败")):
            self.page.query(force=True)
            self.wait()
        self.assertIsNone(self.page.result)
        self.assertFalse(self.page.export_button.isEnabled())
        self.assertIn("权限失败", self.page.info.text())
        self.window.mode.setCurrentIndex(self.window.mode.findData("offline"))
        self.wait()
        self.assertIsNone(self.page.result)
        self.assertFalse(self.page.refresh_button.isEnabled())

    def test_today_button_and_shortcut_use_beijing_date_and_default_metrics(self):
        self.page.frequency.setCurrentIndex(1)
        self.assertTrue(self.page.twap.isChecked())
        self.assertTrue(self.page.vwap.isChecked())
        # UTC is still the previous date: the selector explicitly requests Shanghai time.
        fixed = datetime.fromisoformat("2026-10-17T00:15:00+08:00")
        with patch("index_futures_basis.security_desktop.datetime") as clock:
            clock.now.return_value = fixed
            self.page.today_button.click()
            self.assertEqual(self.page.start.dateTime().toString("yyyy-MM-dd HH:mm"), "2026-10-17 09:30")
            self.assertEqual(self.page.end.dateTime().toString("yyyy-MM-dd HH:mm"), "2026-10-17 15:00")
            self.page.start.setDateTime(self.page.start.dateTime().addDays(-2))
            self.page.code.setFocus()
            self.app.processEvents()
            QTest.keyClick(self.page.code, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(self.page.start.dateTime().toString("yyyy-MM-dd HH:mm"), "2026-10-17 09:30")
            self.assertEqual(clock.now.call_args.args[0].utcoffset(None).total_seconds(), 28800)
        self.page.frequency.setCurrentIndex(2)
        self.assertFalse(self.page.today_shortcut.isEnabled())
        self.assertTrue(self.page.today_button.isHidden())

    def test_missing_vwap_units_and_index_restriction_are_visible(self):
        self.page.frequency.setCurrentIndex(1)
        self.page.query()
        self.wait()
        self.assertNotEqual(self.page.metric_values["twap"].text(), "—")
        self.assertEqual(self.page.metric_values["vwap"].text(), "—")
        self.assertIn("单位", self.page.metric_hints["vwap"].text())
        self.page.code.setText("000300.SH")
        self.assertFalse(self.page.vwap.isEnabled())
        self.page.query()
        self.wait()
        self.assertIn("指数不适用", self.page.metric_hints["vwap"].text())

    def test_auto_name_lookup_debounces_and_stale_reply_cannot_label_new_code(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def lookup(service, code, frequency):
            calls.append(code)
            if code == "600006.SH":
                entered.set()
                release.wait(5)
            return {"code": code, "name": "合成名称" + code[:6], "source": "模拟Wind"}
        with patch("index_futures_basis.security_desktop.SecurityService.lookup_name", new=lookup):
            self.page.code.setText("600")
            QTest.qWait(650)
            self.assertEqual(calls, [])
            self.page.code.setText("600006.SH")
            QTest.qWait(650)
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.page.code.isEnabled())
            self.page.code.setText("600007.SH")
            self.assertNotIn("600006", self.page.security_name.text())
            release.set()
            self.wait()
            QTest.qWait(650)
            self.wait()
            self.assertEqual(calls, ["600006.SH", "600007.SH"])
            self.assertIn("600007.SH · 合成名称600007", self.page.security_name.text())
            self.assertNotIn("600006", self.page.security_name.text())

    def test_name_lookup_failure_clears_old_pair_and_close_waits_for_worker(self):
        with patch("index_futures_basis.security_desktop.SecurityService.lookup_name", side_effect=RuntimeError("模拟名称权限失败")):
            self.page.code.setText("600006.SH")
            self.page.name_timer.stop()
            self.page.lookup_name()
            self.wait()
            self.assertIn("未核验成功", self.page.security_name.text())
            self.assertIn("权限失败", self.page.security_name.toolTip())
        release = threading.Event()
        def delayed(*args):
            release.wait(5)
            return {"code": "600006.SH", "name": "延迟名称", "source": "模拟Wind"}
        with patch("index_futures_basis.security_desktop.SecurityService.lookup_name", side_effect=delayed):
            self.page.lookup_name()
            self.window.close()
            self.assertTrue(self.window.closing)
            self.assertIsNotNone(self.page.name_worker)
            release.set()
            self.wait()
            self.assertFalse(self.window.isVisible())

    def test_query_waits_for_name_lookup_and_then_displays_metrics(self):
        release = threading.Event()
        def delayed(*args):
            release.wait(5)
            return {"code": "600006.SH", "name": "合成演示证券", "source": "合成演示"}
        with patch("index_futures_basis.security_desktop.SecurityService.lookup_name", side_effect=delayed):
            self.page.code.setText("600006.SH")
            self.page.frequency.setCurrentIndex(1)
            self.page.name_timer.stop()
            self.page.lookup_name()
            self.page.query()
            self.assertIsNone(self.window.worker)
            self.assertIn("完成后自动查询", self.page.info.text())
            release.set()
            self.wait()
            self.assertIsNotNone(self.page.result, self.page.info.text())
            self.assertEqual(self.page.result.query.code, "600006.SH")
            self.assertNotEqual(self.page.metric_values["twap"].text(), "—")
