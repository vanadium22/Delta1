import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QDateTime
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
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertIsNone(self.window.worker)

    def tearDown(self):
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
