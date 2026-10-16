"""Exercise real Qt signals, worker completion, selection invalidation and file export."""
import os
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QPushButton

from index_futures_basis.desktop import Window, WindowProfileDialog
from index_futures_basis.service import BasisService
from shared_data.io import sha256


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = BasisService(Path(self.temp.name), "demo")
        self.window = Window(self.service, auto_start=False)
        self.window.show()

    def wait_idle(self):
        deadline = time.monotonic() + 20
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)  # Yield the GIL to the worker as well as pumping Qt.
        self.app.processEvents()
        self.assertIsNone(self.window.worker, "后台任务未结束")

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_query_copy_and_selection_changes_clear_old_values(self):
        with patch("index_futures_basis.service.WindProvider", side_effect=AssertionError("network")):
            self.window.load_local()
            self.wait_idle()
            self.assertEqual(self.window.query_result["current_contract"], "IC2703.CFE")
            self.assertEqual(self.window.stats.rowCount(), 3)
            self.window.stats.copy()
            self.assertIn("中位数", self.app.clipboard().text())
            self.assertIn("3个月", self.app.clipboard().text())
            self.window.root.setCurrentText("IM")
            self.assertIsNone(self.window.query_result)
            self.assertEqual(self.window.stats.rowCount(), 0)
            self.window.query()
            self.wait_idle()
            self.assertEqual(self.window.query_result["root"], "IM")

    def test_import_to_shared_dividends_preserves_archive_and_rejects_changed_source(self):
        self.service.mode = "offline"
        source = Path(self.temp.name) / "基差情况_2026-10-16.xlsx"
        source.write_bytes(b"validated source")
        expected = sha256(source)
        target = self.service.dividend_directories()[0] / source.name
        target.parent.mkdir(parents=True)
        target.write_bytes(b"previous snapshot")
        previous_hash = sha256(target)
        with patch("index_futures_basis.desktop.QFileDialog.getOpenFileName", return_value=(str(source), "")), \
             patch("index_futures_basis.desktop.read_continuous_snapshot", return_value=(None, {"sha256": expected})), \
             patch.object(self.window, "run_task", side_effect=lambda label, operation, done: operation(None)):
            self.window.import_dividend()
            self.assertEqual(target.read_bytes(), b"validated source")
            self.assertEqual((self.service.dividend_archive / f"{previous_hash}.xlsx").read_bytes(), b"previous snapshot")
            source.write_bytes(b"changed after validation")
            with self.assertRaisesRegex(ValueError, "读取后发生变化"):
                self.window.import_dividend()
            self.assertEqual(target.read_bytes(), b"validated source")
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_failed_query_does_not_leave_exportable_previous_result(self):
        self.window.load_local()
        self.wait_idle()
        self.window.latest.setChecked(False)
        self.window.date.setDate(QDate(2030, 1, 1))
        self.window.query()
        self.wait_idle()
        self.assertIsNone(self.window.query_result)
        self.assertEqual(self.window.history.rowCount(), 0)
        self.assertIn("未完成", self.window.progress_label.text())
        self.window.export_query()
        self.assertEqual(self.window.progress_label.text(), "请先完成查询")

    def test_ih_term_metrics_disable_slot_and_show_matching_history_windows(self):
        self.window.root.setCurrentText("IH")
        for metric in ("fixed_60d", "fixed_90d", "calendar_02_00", "calendar_03_02"):
            with self.subTest(metric=metric):
                self.window.metric_combo.setCurrentIndex(self.window.metric_combo.findData(metric))
                self.assertFalse(self.window.slot.isEnabled())
                self.assertIsNone(self.window.query_result)
                self.window.query()
                self.wait_idle()
                self.assertEqual(self.window.query_result["metric"], metric)
                self.assertEqual(self.window.query_result["root"], "IH")
                self.assertFalse(self.window.slot.isEnabled())
                expected = ["3个月", "6个月", "12个月"]
                self.assertEqual([self.window.stats.item(i, 0).text() for i in range(len(expected))], expected)
                self.assertEqual(self.window.stats.rowCount(), len(expected))
                self.assertIn("插值" if metric.startswith("fixed_") else "现货指数", self.window.query_note.text())
        self.window.metric_combo.setCurrentIndex(self.window.metric_combo.findData("annualized_basis_pct"))
        self.assertTrue(self.window.slot.isEnabled())
        self.assertIsNone(self.window.query_result)

    def test_charts_run_in_worker_and_query_csv_preserves_source(self):
        self.window.export("figures", ["IC_年化基差分位蜡烛图"])
        self.wait_idle()
        self.assertFalse(self.window.image_pixmap.isNull())
        self.assertTrue(self.window.image_path.exists())
        self.assertIn("demo", self.window.image_note.text())
        self.assertEqual(self.window.tabs.currentIndex(), 2)
        target = Path(self.temp.name) / "query.csv"
        with patch("index_futures_basis.desktop.QFileDialog.getSaveFileName", return_value=(str(target), "CSV")):
            self.window.export_query()
            self.wait_idle()
        text = target.read_text(encoding="utf-8-sig")
        self.assertIn(self.window.query_result["fingerprint"], text)
        self.assertIn("IC2703.CFE", text)

    def test_switch_mode_clears_demo_and_does_not_implicitly_sync(self):
        self.window.load_local()
        self.wait_idle()
        demo_path = self.service.store.path
        with patch("index_futures_basis.service.WindProvider", side_effect=AssertionError("network")):
            self.window.mode.setCurrentIndex(self.window.mode.findData("wind"))
            self.wait_idle()
        self.assertNotEqual(self.window.service.store.path, demo_path)
        self.assertIsNone(self.window.query_result)
        self.assertEqual(self.window.stats.rowCount(), 0)
        self.assertIn("Wind 正式数据", self.window.status_label.text())

    def test_close_waits_for_owned_worker_and_requests_cancel(self):
        started = threading.Event()
        def operation(progress):
            started.set()
            self.service.cancel.wait(2)
        self.window.run_task("测试后台关闭", operation, lambda result: None, cancellable=True)
        self.assertTrue(started.wait(2))
        self.window.close()
        self.assertTrue(self.service.cancel.is_set())
        self.wait_idle()
        self.assertFalse(self.window.isVisible())

    def test_report_fallback_is_visible_in_warning_and_completion_status(self):
        folder = Path(self.temp.name) / "saved_report"
        folder.mkdir()
        message = "更新未成功，已回退至前一交易日2026-10-07；原因：指数收盘价缺失"
        (folder / "run_manifest.json").write_text(json.dumps({"actual_end": "2026-10-07",
            "market_update_check": {"state": "fallback", "message": message}}), encoding="utf-8")
        with patch.object(self.service, "export", return_value=str(folder)), \
             patch("index_futures_basis.desktop.QMessageBox.warning") as warning:
            self.window.export("report")
            self.wait_idle()
        self.assertEqual(warning.call_count, 1)
        self.assertIn(message, warning.call_args.args[2])
        self.assertIn(message, self.window.progress_label.text())

    def test_local_report_button_skips_refresh_and_shows_partial_completion(self):
        folder = Path(self.temp.name) / "partial_report"
        folder.mkdir()
        (folder / "run_manifest.json").write_text(json.dumps({"actual_end": "2026-10-08",
            "data_availability": {"partial": True}, "local_only": True}), encoding="utf-8")
        with patch.object(self.service, "export", return_value=str(folder)) as export:
            button = next(b for b in self.window.findChildren(QPushButton) if b.text() == "仅用本地生成 Word")
            button.click()
            self.wait_idle()
        self.assertFalse(export.call_args.kwargs["refresh"])
        self.assertIn("缺失部分留空", self.window.progress_label.text())

    def test_valuation_controls_keep_query_and_images_separate(self):
        self.window.load_local()
        self.wait_idle()
        self.window.chart_valuation.setCurrentIndex(self.window.chart_valuation.findData("raw"))
        self.assertEqual(self.window.query_valuation.currentData(), "adjusted")
        self.window.query_valuation.setCurrentIndex(self.window.query_valuation.findData("raw"))
        self.assertIsNone(self.window.query_result)
        with patch.object(self.service, "dividend_input", side_effect=AssertionError("dividends")):
            self.window.query()
            self.wait_idle()
        self.assertEqual(self.window.query_result["provenance"]["valuation"], "raw")
        self.assertIn("不调整分红", self.window.query_note.text())
        folder = Path(self.temp.name) / "raw_figures"
        folder.mkdir()
        (folder / "run_manifest.json").write_text(json.dumps({"actual_end": "2026-10-08", "valuation": "raw"}), encoding="utf-8")
        with patch.object(self.service, "export", return_value=str(folder)) as export:
            self.window.export("figures", ["跨期03-02_绝对基差"])
            self.wait_idle()
        self.assertEqual(export.call_args.kwargs["valuation"], "raw")
        self.window.query_valuation.setCurrentIndex(self.window.query_valuation.findData("adjusted"))
        self.assertIsNone(self.window.query_result)
        self.assertEqual(self.window.chart_valuation.currentData(), "raw")

    def test_local_market_page_reads_without_dividends_and_clears_stale_results(self):
        page = self.window.market_page
        self.window.tabs.setCurrentWidget(page)
        page.root.setCurrentIndex(page.root.findData("IC"))
        page.kind.setCurrentIndex(page.kind.findData("spot"))
        with patch.object(self.service, "dividend_input", side_effect=AssertionError("dividends")), \
             patch.object(self.service, "sync", side_effect=AssertionError("network")):
            self.window.refresh_active_page()
            self.wait_idle()
            self.assertEqual(set(page.result["data"].code), {"000905.SH"})
            page.table.copy()
            self.assertIn("000905.SH", self.app.clipboard().text())
            page.export()
            self.wait_idle()
        self.assertTrue(list(self.service.exports_root.glob("local_market_data/*/data.csv")))
        page.code.setText("000300.SH")
        self.assertIsNone(page.result)
        self.assertEqual(page.table.model().rowCount(), 0)
        self.assertFalse(page.export_button.isEnabled())
        self.window.query_active_page()
        self.wait_idle()
        self.assertTrue(page.result["data"].empty)
        self.assertIn("0条", page.info.text())

    def test_report_failure_explicitly_says_no_report_created(self):
        with patch.object(self.service, "export", side_effect=ValueError("前一交易日数据也不完整；未生成报告")), \
             patch("index_futures_basis.desktop.QMessageBox.warning") as warning:
            self.window.export("report")
            self.wait_idle()
        self.assertEqual(warning.call_args.args[1], "报告未生成")
        self.assertIn("数据也不完整", warning.call_args.args[2])
        self.assertIn("未生成报告", self.window.progress_label.text())

    def test_window_dialog_rejects_invalid_input_and_saves_figures_separately(self):
        dialog = WindowProfileDialog(None, "figures", self.window)
        dialog.fields["fixed_60_quantile_months"].setText("3, 3, 12")
        dialog.accept()
        self.assertIn("不能重复", dialog.error.text())
        self.assertEqual(dialog.result(), 0)
        dialog.set_values(None)
        self.assertEqual(dialog.values()["fixed_90_quantile_months"], [3, 6, 12])
        dialog.deleteLater()
        def edit(dialog):
            dialog.fields["fixed_60_months"].setText("6, 2")
            dialog.fields["fixed_60_quantile_months"].setText("1, 4, 9")
            dialog.accept()
            return dialog.result()
        with patch.object(WindowProfileDialog, "exec", edit):
            self.window.edit_output_windows("figures")
        self.assertNotEqual(self.service.output_windows("figures"), self.service.output_windows("report"))
        self.assertGreaterEqual(self.window.chart.findText("60天固定期限_近2个月"), 0)
        self.window.chart.setCurrentText("60天固定期限_分位蜡烛图")
        self.assertIn("1/4/9", self.window.chart_window_note.text())
        self.window.export("figures", [self.window.chart.currentText()])
        self.wait_idle()
        self.assertFalse(self.window.image_pixmap.isNull())
        self.assertIn("1/4/9", self.window.image_note.text())
        saved = BasisService(self.service.root, "demo")
        self.assertEqual(saved.output_windows("figures")["fixed_60_quantile_months"], [1, 4, 9])
        self.assertEqual(saved.output_windows("report")["fixed_60_quantile_months"], [3, 6, 12])
