"""Integration between the report selection and the bookkeeping windows."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog

from script_making.desktop import Window
from script_making.service import ReportService
from script_making.storage import filename, save_files
from script_making.tests.test_reports import fixture


class BookkeepingAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        cache = Path(__file__).resolve().parents[1] / "cache" / "bookkeeping-app-tests"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        root = Path(self.temp.name)
        self.service = ReportService(root / "app")
        source = root / filename("swap", "2000-01-07")
        fixture(source, headers=["交易确认书编号", "合约编号", "标的物代码", "交易对手名称", "标的名义本金额"],
                rows=[["CONF-A", "A", "000001.SZ", "示例客户", 1],
                      ["CONF-B", "B", "000001.SZ", "示例交易台", 2]])
        save_files(self.service.settings.data_path(), {"swap": source}, "2000-01-07", "合成测试")
        self.window = Window(self.service, auto_start=False)
        self.window.show()
        self.window.refresh_catalog()
        self.wait_idle()

    def wait_idle(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.app.processEvents()
            if self.window.worker is None and not self.window.debounce.isActive():
                self.app.processEvents()
                if self.window.worker is None:
                    return
            time.sleep(.01)
        self.fail("后台读取未结束")

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_search_requires_explicit_selection_and_uses_complete_report(self):
        self.assertFalse(self.window.back_search_button.isEnabled())
        self.window.table.selectRow(0)
        self.assertTrue(self.window.back_search_button.isEnabled())
        with patch("script_making.desktop.CandidateDialog") as candidate:
            self.window.back_search_button.click()
            candidate.return_value.exec.assert_called_once()
            store, table, selected, source, _prefs, _parent = candidate.call_args.args
            self.assertEqual(len(table["rows"]), 2)
            self.assertEqual(selected["values"][1], "A")
            self.assertEqual(source["date"], "2000-01-07")
            self.assertEqual(store.path, self.service.settings.paths.root / "bookkeeping" / "manual.sqlite3")
            self.assertFalse(store.path.exists())
        self.window.search.setText("no-result")
        self.wait_idle()
        self.assertFalse(self.window.back_search_button.isEnabled())

    def test_bookkeeping_menu_allows_new_record_without_report_selection(self):
        with patch("script_making.desktop.BookkeepingDialog") as booking:
            self.window.bookkeeping_button.click()
            booking.return_value.exec.assert_called_once()
            self.assertEqual(booking.call_args.kwargs["parent"], self.window)

    def test_review_row_requires_explicit_target_choice_in_same_day_swap_report(self):
        root = Path(self.temp.name)
        review = fixture(root / filename("review", "2000-01-07"), "簿记要素",
                         headers=["协议编号", "标的", "说明"], rows=[["CONF-A", "000001.SZ", "合成"]])
        save_files(self.service.settings.data_path(), {"review": review}, "2000-01-07", "合成测试")
        self.window.refresh_catalog()
        self.wait_idle()
        self.window.switch_kind("review")
        self.wait_idle()
        self.window.table.selectRow(0)
        with patch("script_making.desktop.TargetPicker") as picker, patch("script_making.desktop.CandidateDialog") as candidate:
            picker.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window.back_search_button.click()
            candidate.assert_not_called()
            proposals = picker.call_args.args[0]
            self.assertEqual(proposals["state"], "matched")
            self.assertEqual(proposals["rows"][0]["values"][1], "A")
            picker.return_value.exec.return_value = QDialog.DialogCode.Accepted
            picker.return_value.selected_row = proposals["rows"][0]
            self.window.back_search_button.click()
            candidate.return_value.exec.assert_called_once()
            source = candidate.call_args.args[3]
            self.assertEqual(source["sheet"], "存续合约估值")
            self.assertEqual(source["selected_from"]["sheet"], "簿记要素")


if __name__ == "__main__":
    unittest.main()
