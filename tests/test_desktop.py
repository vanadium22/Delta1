"""Exercise real desktop widgets with simulated requests and native dialogs mocked."""
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from functools import partial

from index_strategy.instant_dld.service import DownloadService
from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.reader import RealtimeReader

try:
    import tkinter as tk
    from index_strategy.desktop.app import Delta1App
except ImportError:
    Delta1App = None


class BlockingClient:
    url = "https://example.invalid/market"
    session = SimpleNamespace(trust_env=False)
    timeout = (10, 30)
    verify = True

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def fetch(self, symbols):
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("test request was not released")
        return {"received_at": datetime.now().astimezone().isoformat(), "elapsed_seconds": .014,
                "symbols": symbols, "status": "success", "http_status": 200,
                "response": {"respSuccess": True, "code": "0", "data": {
                    symbol: {"latestPrice": 10 + index, "tradedQuantities": 1000 + index, "quoteTimestamp": 93000,
                             "b1Price": 9 + index, "b1Stocks": 100, "s1Price": 11 + index, "s1Stocks": 200}
                    for index, symbol in enumerate(symbols)}}}

    def close(self):
        self.closed = True


@unittest.skipIf(Delta1App is None, "Install the desktop environment to run native GUI tests")
class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        symbols = self.root / "index_strategy/instant_dld/config/symbols.json"
        symbols.parent.mkdir(parents=True)
        symbols.write_text('["000001.SZ", "603110.SH"]', encoding="utf-8")
        self.client = BlockingClient()
        self.service = DownloadService(self.root, client_factory=lambda: self.client)
        try:
            self.app = Delta1App(self.service)
        except tk.TclError as exc:
            if "no display" in str(exc) or "couldn't connect to display" in str(exc):
                self.skipTest("A display or xvfb is required for native GUI tests")
            raise
        self.app.withdraw()
        self.addCleanup(self.close_app)
        self.app.output_dir.set(str(self.root / "行情数据"))

    def close_app(self):
        self.client.release.set()
        self.service.close(5)
        try:
            if self.app.winfo_exists():
                self.app.destroy()
        except tk.TclError:
            pass

    def finish(self):
        self.client.release.set()
        self.service.worker.join(3)
        self.assertFalse(self.service.worker.is_alive())
        self.app.refresh(schedule=False)

    def report_text(self):
        tree = self.app.status_table.tree
        return str([tree.item(row, "values") for row in tree.get_children()])

    def run_summary(self):
        with RealtimeReader(self.root / "行情数据").connect() as connection:
            return dict(connection.execute("SELECT * FROM runs WHERE run_id=?", (self.service.run_id,)).fetchone())

    def test_edit_save_and_restore_settings_without_network(self):
        self.app.symbols.delete("1.0", "end")
        self.app.symbols.insert("1.0", "['000001.sz', '603110.SH', '000001.SZ']")
        self.app.interval.set("0.5")
        self.app.save_button.invoke()
        saved = DownloadService(self.root).config()
        self.assertEqual(saved["symbols"], ["000001.SZ", "603110.SH"])
        self.assertEqual(saved["interval"], .5)
        self.assertEqual(saved["output_dir"], str(self.root / "行情数据"))
        self.assertEqual(self.app.metric_values["symbols"].cget("text"), "2")
        self.assertIsNone(self.service.worker)

    def test_invalid_interval_is_visible_and_cannot_start(self):
        self.app.interval.set("nan")
        self.app.start_button.invoke()
        self.assertIsNone(self.service.worker)
        self.assertIn("有限秒数", self.app.feedback.cget("text"))
        self.assertFalse(self.service.settings_path.exists())

    def test_minimum_window_keeps_symbol_editor_and_actions_visible(self):
        self.app.geometry("1080x730")
        self.app.deiconify()
        self.app.update()
        self.assertTrue(self.app.symbols.winfo_ismapped())
        self.assertGreaterEqual(self.app.symbols.winfo_height(), 100)
        for control in (self.app.symbols, self.app.start_button, self.app.stop_button, self.app.status_table, self.app.quote_table):
            with self.subTest(control=type(control).__name__):
                self.assertTrue(control.winfo_ismapped())
                x = control.winfo_rootx() - control.master.winfo_rootx()
                y = control.winfo_rooty() - control.master.winfo_rooty()
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + control.winfo_width(), control.master.winfo_width())
                self.assertLessEqual(y + control.winfo_height(), control.master.winfo_height())

    def test_import_multiple_files_export_and_reject_bad_file_atomically(self):
        first, second = self.root / "one.json", self.root / "two.list"
        first.write_text('["600000.SH", "000001.SZ"]', encoding="utf-8")
        second.write_text("['000002.sz', '600000.SH']", encoding="utf-8")
        with patch("index_strategy.desktop.app.filedialog.askopenfilenames", return_value=(str(first), str(second))):
            self.app.import_button.invoke()
        expected = ["000001.SZ", "603110.SH", "600000.SH", "000002.SZ"]
        self.assertEqual(self.app.form_value()["symbols"].splitlines(), expected)
        target = self.root / "export.json"
        with patch("index_strategy.desktop.app.filedialog.asksaveasfilename", return_value=str(target)):
            self.app.export_button.invoke()
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), expected)
        second.write_text("['INVALID']", encoding="utf-8")
        with patch("index_strategy.desktop.app.filedialog.askopenfilenames", return_value=(str(first), str(second))):
            self.app.import_button.invoke()
        self.assertEqual(self.app.form_value()["symbols"].splitlines(), expected)
        self.assertIn("有效", self.app.feedback.cget("text"))

    def test_native_folder_dialog_updates_path_and_cancel_preserves_it(self):
        chosen = str(self.root / "新的保存位置")
        with patch("index_strategy.desktop.app.filedialog.askdirectory", return_value=chosen) as dialog:
            self.app.browse_button.invoke()
        self.assertEqual(self.app.output_dir.get(), chosen)
        self.assertTrue(Path(dialog.call_args.kwargs["initialdir"]).is_dir())
        with patch("index_strategy.desktop.app.filedialog.askdirectory", return_value=""):
            self.app.browse_button.invoke()
        self.assertEqual(self.app.output_dir.get(), chosen)

    def test_start_stop_keeps_ui_responsive_and_finishes_current_batch(self):
        self.app.start_button.invoke()
        self.assertTrue(self.client.entered.wait(2))
        self.assertEqual(self.app.start_button.cget("state"), "disabled")
        self.assertEqual(self.app.interval_entry.cget("state"), "disabled")
        heartbeat = []
        self.app.after(0, lambda: heartbeat.append("alive"))
        self.app.update()
        self.assertEqual(heartbeat, ["alive"])
        self.app.stop_button.invoke()
        self.assertEqual(self.service.state, "stopping")
        self.assertEqual(self.app.start_button.cget("state"), "disabled")
        self.finish()
        self.assertTrue(self.client.closed)
        self.assertEqual(self.app.start_button.cget("state"), "normal")
        self.assertEqual(self.app.metric_values["batches"].cget("text"), "1")
        self.assertIn("保存 2/2", self.report_text())
        summary = self.run_summary()
        self.assertEqual(summary["status"], "stopped")
        files = list((self.root / "行情数据/data").glob("*/*/*/*.parquet"))
        self.assertEqual(len(files), 2)
        self.assertEqual(list(RealtimeReader(self.root / "行情数据").read_since()["symbol"]), ["000001.SZ", "603110.SH"])
        self.assertEqual(self.app.display_symbol.get(), "000001.SZ")
        tree = self.app.quote_table.tree
        self.assertEqual(tree.item(tree.get_children()[0], "values")[1], "10")
        self.app.display_symbol.set("603110.SH")
        self.app.select_symbol()
        self.assertEqual(tree.item(tree.get_children()[0], "values")[1], "11")

    def test_close_waits_without_blocking_then_destroys_after_saving(self):
        self.app.start_button.invoke()
        self.assertTrue(self.client.entered.wait(2))
        with patch.object(self.app, "destroy", wraps=self.app.destroy) as destroy:
            started = time.monotonic()
            self.app.request_close()
            self.assertLess(time.monotonic() - started, .5)
            destroy.assert_not_called()
            self.assertEqual(self.service.state, "stopping")
            self.finish()
            destroy.assert_called_once()
        summary = self.run_summary()
        self.assertEqual(summary["requests_saved"], 1)
        self.assertTrue(self.client.closed)

    def test_worker_failure_is_shown_and_allows_retry(self):
        def unavailable():
            raise OSError("simulated storage failure")
        self.service.client_factory = unavailable
        self.app.start_button.invoke()
        self.finish()
        self.assertIn("运行失败", self.app.status_label.cget("text"))
        self.assertIn("simulated storage failure", self.app.feedback.cget("text"))
        self.assertEqual(self.app.start_button.cget("state"), "normal")

    def test_navigation_and_clearing_log_window_preserve_collection_state(self):
        self.app.nav_trading.invoke()
        self.assertEqual(self.app.page_title.cget("text"), "交易数据下载")
        self.app.nav_realtime.invoke()
        self.assertEqual(self.app.page_title.cget("text"), "实时数据下载")
        self.service.log("WARNING", "first warning")
        self.app.refresh(schedule=False)
        self.assertIn("first warning", self.report_text())
        self.app.clear_logs()
        self.app.refresh(schedule=False)
        self.assertEqual(self.app.status_table.tree.get_children(), ())
        self.assertTrue(self.service.snapshot()["logs"])
        self.service.log("INFO", "new log")
        self.app.refresh(schedule=False)
        self.assertIn("new log", self.report_text())

    def test_failed_symbol_is_named_and_never_shown_as_new_market_data(self):
        self.service.collector = partial(collect, max_polls=1)
        self.client.release.set()
        original = self.client.fetch
        def partial_response(symbols):
            record = original(symbols)
            record["response"]["data"].pop("603110.SH")
            record["status"] = "partial"
            return record
        self.client.fetch = partial_response
        self.app.start_button.invoke()
        self.finish()
        self.assertIn("部分失败", self.report_text())
        self.assertIn("603110.SH", self.report_text())
        self.assertEqual(len(self.app.quote_table.tree.get_children()), 1)
        self.app.display_symbol.set("603110.SH")
        self.app.select_symbol()
        self.assertEqual(len(self.app.quote_table.tree.get_children()), 0)


if __name__ == "__main__":
    unittest.main()
