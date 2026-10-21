"""Native Qt interactions with synthetic workbooks; no company systems."""
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from script_making.desktop import Window, Worker
from script_making.download_widgets import DownloadsDialog, open_location
from script_making.downloads import archive_path, sync_download
from script_making.desktop_theme import STYLE
from script_making.desktop_widgets import ColumnsDialog, DetailDialog, SettingsDialog
from script_making.query import query_table
from script_making.service import ReportService
from script_making.storage import ReportError, filename, save_files
from script_making.tests.test_reports import fixture


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.table = {"columns": [{"id": "c0", "name": "混合金额", "type": "text"}],
                      "rows": [["001000"], ["5%"], ["-1e-10"], ["不适用"], [None]],
                      "source_rows": [2, 3, 4, 5, 6]}

    def test_explicit_numeric_format_for_mixed_text_and_zero(self):
        result = query_table(self.table, {"filters": [{"column": "c0", "value_type": "number",
                             "op": "range", "min": "0", "max": "0.06"}]})
        self.assertEqual([r["excel_row"] for r in result["rows"]], [3, 4])
        result = query_table(self.table, {"filters": [{"column": "c0", "value_type": "number", "op": "zero"}]})
        self.assertEqual([r["excel_row"] for r in result["rows"]], [4])
        self.assertEqual(self.table["columns"][0]["type"], "text")
        self.assertEqual(self.table["rows"][0][0], "001000")

    def test_numeric_identifier_can_use_text_search_and_invalid_type_rejected(self):
        table = {"columns": [{"id": "c0", "name": "数字", "type": "number"}],
                 "rows": [[120045], [777]], "source_rows": [1, 2]}
        result = query_table(table, {"filters": [{"column": "c0", "value_type": "text", "op": "contains", "value": "004"}]})
        self.assertEqual(result["matched"], 1)
        with self.assertRaisesRegex(ReportError, "内容格式"):
            query_table(table, {"filters": [{"column": "c0", "value_type": "unknown", "op": "eq", "value": "1"}]})

    def test_manual_date_format_excludes_invalid_date_text(self):
        self.table["rows"] = [["2026-10-14"], ["2026-10-99"], ["2026-09-01"], ["不适用"], [None]]
        result = query_table(self.table, {"filters": [{"column": "c0", "value_type": "date", "op": "range",
                                                     "min": "2026-10-01", "max": "2026-12-31"}]})
        self.assertEqual([r["excel_row"] for r in result["rows"]], [2])


class DesktopTests(unittest.TestCase):
    def test_download_panel_manual_retry_and_open_selected_location(self):
        from script_making.tests.test_downloads import sample
        from datetime import date
        source = self.root / "new-source"
        path = sample(source, "pnl", "2026-10-19")
        self.service.update_settings({"pnl_source": str(source)})
        sync_download(self.service.settings, "pnl", date(2026, 10, 21))
        with patch.object(self.window, "start_download") as start:
            dialog = DownloadsDialog(self.service, self.window.start_download, self.window)
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.panels["pnl"]["files"].count(), 1)
            dialog.panels["pnl"]["sync"].click()
            start.assert_called_once_with("pnl")
            with patch("script_making.download_widgets.open_location") as reveal:
                dialog.reveal("pnl")
                expected = archive_path(self.service.settings, "pnl") / "2026-10-19" / path.name
                reveal.assert_called_once_with(str(expected))
            dialog.reject()
            self.assertFalse(dialog.timer.isActive())

    def test_current_file_location_and_missing_directory_error(self):
        self.load()
        with patch("script_making.desktop.open_location") as reveal:
            self.window.location_button.click()
            self.assertTrue(Path(reveal.call_args.args[0]).is_file())
        with self.assertRaisesRegex(ReportError, "尚不存在"):
            open_location(self.root / "absent")

    def test_close_waits_for_independent_download(self):
        self.load()
        self.service.download_jobs["pnl"] = {"state": "running"}
        self.window.download_timer.start()
        self.window.close()
        self.assertTrue(self.window._closing)
        self.assertTrue(self.window.isVisible())
        self.service.download_jobs["pnl"] = {"state": "error", "error": "离线测试"}
        self.window.poll_downloads()
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_parser_error_is_not_reported_as_permission(self):
        def fail():
            raise AttributeError("synthetic parser failure")
        worker = Worker((1, fail, None, "", False))
        worker.run()
        self.assertIn("解析失败", worker.outcome[1])
        self.assertNotIn("权限", worker.outcome[1])

    def test_startup_checks_once_and_refresh_does_not_repeat_sync(self):
        self.window._auto_sync_pending = True
        with patch.object(self.service, "start_sync", return_value={"state": "running"}) as start, \
             patch.object(self.service, "start_download", wraps=self.service.start_download) as download:
            self.window.refresh_catalog()
            deadline = time.monotonic() + 10
            while not start.called and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            start.assert_called_once_with(only_missing=True)
            self.service.job = {"state": "error", "error": "离线测试"}
            self.window.poll_sync()
            self.wait_idle()
            self.window.refresh_catalog()
            self.wait_idle()
            start.assert_called_once()
            self.assertEqual([call.args[0] for call in download.call_args_list], ["pnl", "strategy"])
        self.assertIsNotNone(self.window.result)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.cache = Path(__file__).resolve().parents[1] / "cache" / "desktop-tests"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.cache)
        self.root = Path(self.temp.name)
        self.service = ReportService(self.root / "app")
        self.sources = {
            "swap": fixture(self.root / "input" / filename("swap", "2000-01-07"),
                            headers=["交易确认书编号", "交易对手名称", "混合金额", "数量"],
                            rows=[["TEST-A", "示例证券投资总部", "5%", 120045],
                                  ["TEST-B", "示例客户", "-1e-10", 777],
                                  ["TEST-C", "示例客户", "不适用", 1000],
                                  ["TEST-D", "示例客户", None, 0]]),
            "review": fixture(self.root / "input" / filename("review", "2000-01-07"), "簿记要素"),
        }
        save_files(self.service.settings.data_path(), self.sources, "2000-01-07", "合成测试")
        self.window = Window(self.service, auto_start=False)
        self.window.show()
        self.app.processEvents()

    def wait_idle(self, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if (self.window.worker is None and not self.window.debounce.isActive()
                    and not self.window._syncing and not self.service.downloads_running()):
                self.app.processEvents()
                if self.window.worker is None:
                    return
            time.sleep(.01)
        self.fail("后台操作未结束")

    def load(self):
        self.window.refresh_catalog()
        self.wait_idle()
        self.assertIsNotNone(self.window.result, self.window.error.text())

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        assert self.root.resolve().is_relative_to(self.cache.resolve())
        self.temp.cleanup()

    def test_native_startup_never_opens_browser_or_binds_port(self):
        with patch("webbrowser.open", side_effect=AssertionError("browser")), \
             patch.object(socket.socket, "bind", side_effect=AssertionError("listener")):
            self.load()
        self.assertEqual(self.window.result["total"], 4)
        self.assertEqual(self.window.sheet_combo.currentText(), "存续合约估值")

    def test_text_search_manual_numeric_format_and_eps(self):
        self.load()
        row = self.window.filters[0]
        row.value.setText("证投")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 1)
        row.column.setCurrentIndex(row.column.findData("c2"))
        self.assertEqual(row.value_type.currentData(), "text")
        row.value_type.setCurrentIndex(row.value_type.findData("number"))
        row.value.setText("0")
        row.upper.setText("0.06")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 2)
        row.op.setCurrentIndex(row.op.findData("zero"))
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 1)
        self.window.epsilon.setText("0")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 0)

    def test_change_format_resets_incompatible_conditions_and_preserves_values(self):
        self.load()
        row = self.window.filters[0]
        row.column.setCurrentIndex(row.column.findData("c3"))
        row.value.setText("120000")
        row.upper.setText("130000")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 1)
        row.value_type.setCurrentIndex(row.value_type.findData("text"))
        self.assertEqual(row.op.currentData(), "fuzzy")
        self.assertEqual(row.value.text(), "")
        self.assertEqual(row.upper.text(), "")
        row.value.setText("004")
        self.wait_idle()
        self.assertEqual(self.window.result["rows"][0]["values"][3], 120045)

    def test_invalid_eps_clears_old_result_and_recovers(self):
        self.load()
        self.window.epsilon.setText("-1")
        self.assertIsNone(self.window.result)
        self.wait_idle()
        self.assertIsNone(self.window.result)
        self.assertIn("ε", self.window.error.text())
        self.window.epsilon.setText("1e-8")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 4)
        self.assertTrue(self.window.error.isHidden())

    def test_report_switch_discards_slow_stale_query(self):
        self.load()
        original = self.service.query
        started, release = threading.Event(), threading.Event()

        def slow(request):
            if request["kind"] == "swap":
                started.set()
                release.wait(5)
            return original(request)

        with patch.object(self.service, "query", side_effect=slow):
            self.window.query()
            self.assertTrue(started.wait(2))
            self.window.switch_kind("review")
            self.assertIsNone(self.window.result)
            release.set()
            self.wait_idle()
        self.assertEqual(self.window.result["sheet"], "簿记要素")
        self.assertEqual(self.window.result["total"], 2)

    def test_switch_before_catalog_finishes_keeps_catalog_loading(self):
        self.window.refresh_catalog()
        self.window.switch_kind("review")
        self.wait_idle()
        self.assertEqual(self.window.result["sheet"], "簿记要素")

    def test_pagination_sort_copy_and_details_use_original_rows(self):
        fixture(self.sources["swap"], rows=[[f"TEST-{i:03d}", "示例", i] for i in range(125)])
        # The source fixture changed; use a fresh local destination for this test.
        self.service.update_settings({"data_dir": "data/paging"})
        save_files(self.service.settings.data_path(), self.sources, "2000-01-07", "合成测试")
        self.load()
        self.assertEqual(self.window.result["pages"], 3)
        self.window.turn_page(1)
        self.wait_idle()
        self.assertEqual(self.window.model.rows[0]["excel_row"], 53)
        self.window.sort_column(2)
        self.wait_idle()
        self.window.sort_column(2)
        self.wait_idle()
        self.assertEqual(self.window.result["rows"][0]["values"][2], 124)
        self.window.table.selectRow(0)
        self.window.table.copy()
        self.assertIn("TEST-124", self.app.clipboard().text())
        detail = DetailDialog(self.window.columns, self.window.result["rows"][0], "合成测试", self.window)
        detail.copy_all()
        self.assertIn("124", self.app.clipboard().text())
        self.assertEqual(detail.model.rowCount(), 3)
        detail.close()

    def test_native_settings_directory_picker_and_persistence(self):
        self.load()
        dialog = SettingsDialog(self.service.settings, self.window)
        chosen = str(self.root / "new-source")
        with patch("script_making.desktop_widgets.QFileDialog.getExistingDirectory", return_value=chosen):
            dialog.choose_folder(dialog.source)
        dialog.destination.setText("data/changed")
        dialog.epsilon.setText("1e-6")
        dialog.validate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.service.update_settings(dialog.values)
        self.window.refresh_catalog()
        self.wait_idle()
        self.assertIsNone(self.window.result)
        self.assertIn("尚未保存", self.window.empty.text())
        self.assertEqual(ReportService(self.service.settings.root).settings.get()["source_root"], chosen)
        self.assertEqual(self.window.epsilon.text(), "1e-06")

    def test_columns_keep_at_least_one_and_hidden_values_still_search(self):
        self.load()
        dialog = ColumnsDialog(self.window.columns, [], "swap", self.window)
        dialog.apply()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.select(["c0"])
        dialog.apply()
        self.assertEqual(dialog.selected(), ["c0"])
        self.window.visible = dialog.selected()
        self.window._apply_columns()
        self.window.search.setText("证投")
        self.wait_idle()
        self.assertEqual(self.window.result["matched"], 1)
        self.assertTrue(self.window.table.isColumnHidden(1))

    def test_import_through_native_file_picker(self):
        newer = [fixture(self.root / "new" / filename(kind, "2000-01-10"), sheet)
                 for kind, sheet in (("swap", "存续合约估值"), ("review", "簿记要素"))]
        with patch("script_making.desktop.QFileDialog.getOpenFileNames", return_value=([str(p) for p in newer], "")):
            self.window.choose_import()
        self.wait_idle()
        self.assertEqual(self.window.result["date"], "2000-01-10")
        self.assertEqual(self.window.origin.text(), "手动导入")
        self.assertTrue(self.service.catalog()["dates"][0]["complete"])

    def test_sync_success_and_failure_keep_native_query_usable(self):
        source = self.root / "shared"
        for kind, sheet in (("swap", "存续合约估值"), ("review", "簿记要素")):
            fixture(source / "2000-01-10" / filename(kind, "2000-01-10"), sheet)
        self.service.update_settings({"source_root": str(source)})
        self.load()
        self.window.start_sync()
        self.assertFalse(self.window.settings_button.isEnabled())
        self.wait_idle()
        self.assertEqual(self.window.result["date"], "2000-01-10")
        self.assertEqual(self.window.origin.text(), "共享目录下载")
        self.service.update_settings({"source_root": str(self.root / "missing")})
        self.window.start_sync()
        self.wait_idle()
        self.assertIn("无法访问", self.window.error.text())
        self.assertEqual(self.window.result["date"], "2000-01-10")
        self.assertTrue(self.window.settings_button.isEnabled())

    def test_close_waits_for_worker_without_destroying_running_thread(self):
        self.load()
        release, started = threading.Event(), threading.Event()

        def slow():
            started.set()
            release.wait(5)
            return {}

        self.window._submit(slow, lambda _: self.fail("closed window applied stale result"), "测试任务")
        self.assertTrue(started.wait(2))
        self.window.close()
        self.assertTrue(self.window._closing)
        self.assertTrue(self.window.isVisible())
        release.set()
        self.wait_idle()
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
