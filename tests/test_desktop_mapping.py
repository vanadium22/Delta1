"""Native main-contract configuration stays responsive and preserves draft settings."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from index_strategy.instant_dld.service import DownloadService

try:
    import tkinter as tk
    from index_strategy.desktop.app import Delta1App
except ImportError:
    Delta1App = None


@unittest.skipIf(Delta1App is None, "Install the desktop environment to run native GUI tests")
class DesktopMappingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        symbols = self.root / "index_strategy/instant_dld/config/symbols.json"
        symbols.parent.mkdir(parents=True)
        symbols.write_text('["AU.SHF"]', encoding="utf-8")
        self.service = DownloadService(self.root)
        try:
            self.app = Delta1App(self.service)
        except tk.TclError as exc:
            if "no display" in str(exc) or "couldn't connect to display" in str(exc):
                self.skipTest("A display or xvfb is required for native GUI tests")
            raise
        self.app.withdraw()
        self.addCleanup(self.close_app)

    def close_app(self):
        self.service.state = "idle"
        self.service.close(5)
        try:
            if self.app.winfo_exists():
                self.app.destroy()
        except tk.TclError:
            pass

    def test_mapping_paths_only_change_after_apply_and_round_trip_in_form(self):
        self.app.geometry("1120x760")
        self.app.deiconify()
        self.app.update()
        button = self.app.mapping_button
        self.assertTrue(button.winfo_ismapped())
        self.assertGreaterEqual(button.winfo_x(), 0)
        self.assertLessEqual(button.winfo_x() + button.winfo_width(), button.master.winfo_width())
        initial = self.app.form_value()
        self.app.show_mapping_settings()
        dialog = self.app._mapping_window
        dialog.mapping_file.set(str(self.root / "different.pkl"))
        dialog.close()
        self.assertEqual(self.app.mapping_file.get(), initial["mapping_file"])
        self.app.show_mapping_settings()
        dialog = self.app._mapping_window
        mapping = str(self.root / "my_mapping.pkl")
        calendar = str(self.root / "my_calendar.pkl")
        dialog.mapping_file.set(mapping)
        dialog.calendar_file.set(calendar)
        dialog.apply_button.invoke()
        value = self.app.form_value()
        self.assertEqual(value["mapping_file"], mapping)
        self.assertEqual(value["calendar_file"], calendar)
        self.assertFalse(self.service.settings_path.exists())
        self.app.save_button.invoke()
        restored = DownloadService(self.root).config()
        self.assertEqual(restored["mapping_file"], mapping)
        self.assertEqual(restored["calendar_file"], calendar)

    def test_preview_reads_in_worker_without_blocking_or_changing_configuration(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        threads = []

        def preview(value):
            threads.append(threading.get_ident())
            entered.set()
            if not release.wait(5):
                raise TimeoutError("preview was not released")
            return [{"symbol": "AU.SHF", "source_symbol": "AU2612.SHF",
                     "mapping_date": "2026-09-17", "trading_date": "2026-09-18"}]

        self.app.show_mapping_settings()
        dialog = self.app._mapping_window
        original = self.app.form_value()
        with patch.object(self.service, "preview_mapping", side_effect=preview):
            started = time.monotonic()
            dialog.preview_button.invoke()
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(entered.wait(2))
            heartbeats = []
            self.app.after(0, lambda: heartbeats.append(True))
            self.app.update()
            self.assertEqual(heartbeats, [True])
            self.assertNotEqual(threads[0], threading.get_ident())
            self.assertEqual(dialog.apply_button.cget("state"), "disabled")
            release.set()
            deadline = time.monotonic() + 2
            while dialog._reading and time.monotonic() < deadline:
                self.app.update()
                time.sleep(.01)
            self.assertFalse(dialog._reading)
        text = dialog.preview_text.get("1.0", "end-1c")
        self.assertIn("AU.SHF  →  AU2612.SHF", text)
        self.assertIn("2026-09-17", text)
        self.assertEqual(self.app.form_value(), original)
        self.assertIsNone(self.service.worker)

    def test_collecting_blocks_mapping_changes_even_with_existing_dialog(self):
        original = self.app.mapping_file.get()
        self.app.show_mapping_settings()
        dialog = self.app._mapping_window
        dialog.mapping_file.set(str(self.root / "new.pkl"))
        self.service.state = "running"
        self.app.refresh(schedule=False)
        self.assertEqual(self.app.mapping_button.cget("state"), "disabled")
        dialog.apply_button.invoke()
        self.assertEqual(self.app.mapping_file.get(), original)
        self.assertIn("停止采集", dialog.status.cget("text"))

    def test_alias_quotes_show_actual_contract_and_mapping_date(self):
        row = {"sequence": 1, "timestamp": 1_789_707_000, "symbol": "AU.SHF",
               "source_symbol": "AU2612.SHF", "mapping_date": "2026-09-17", "quote_time": "09:30:00",
               "close": 900., "volume_total": 100., "volume": None,
               "bid_price_1": 899., "bid_volume_1": 2., "ask_price_1": 901., "ask_volume_1": 3.}
        with patch.object(self.service, "quote_snapshot", return_value=[row]):
            self.app.display_symbol.set("AU.SHF")
            self.app.select_symbol()
        tree = self.app.quote_table.tree
        values = tree.item(tree.get_children()[0], "values")
        self.assertEqual(values[1], "900")
        self.assertEqual(values[9], "AU2612.SHF")
        self.assertEqual(values[10], "2026-09-17")
        self.assertIn("AU.SHF → AU2612.SHF", self.app.quote_hint.cget("text"))


if __name__ == "__main__":
    unittest.main()
