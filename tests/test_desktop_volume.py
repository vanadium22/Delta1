"""Show interval volume with its observation duration, never as a fixed one-second bar."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from index_strategy.instant_dld.service import DownloadService

try:
    import tkinter as tk
    from index_strategy.desktop.app import Delta1App
except ImportError:
    Delta1App = None


@unittest.skipIf(Delta1App is None, "Install the desktop environment to run native GUI tests")
class DesktopVolumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        symbols = self.root / "index_strategy/instant_dld/config/symbols.json"
        symbols.parent.mkdir(parents=True)
        symbols.write_text('["AU.SHF", "000001.SZ"]', encoding="utf-8")
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
        self.service.close(5)
        try:
            if self.app.winfo_exists():
                self.app.destroy()
        except tk.TclError:
            pass

    def row(self, sequence=1, **updates):
        row = {"sequence": sequence, "timestamp": 1_789_745_644, "symbol": "AU.SHF",
               "source_symbol": "AU2610.SHF", "mapping_date": "2026-09-18", "quote_time": "23:34:03",
               "close": 941.32, "volume_total": 80053., "volume": 6.,
               "volume_start": 1_789_745_642, "volume_interval_seconds": 2.00149,
               "bid_price_1": 941.3, "bid_volume_1": 2., "ask_price_1": 941.34, "ask_volume_1": 5.}
        return row | updates

    def test_increment_and_actual_interval_precede_cumulative_and_preserve_units(self):
        self.app.interval.set("2")
        with patch.object(self.service, "quote_snapshot", return_value=[self.row()]):
            self.app.select_symbol()
        tree = self.app.quote_table.tree
        self.assertEqual(tuple(tree.cget("displaycolumns"))[:4],
                         ("timestamp", "close", "volume", "volume_interval_seconds"))
        item = tree.get_children()[0]
        self.assertEqual(tree.set(item, "volume"), "6")
        self.assertEqual(tree.set(item, "volume_total"), "80,053")
        self.assertEqual(tree.set(item, "volume_interval_seconds"), "2.001")
        self.assertEqual(tree.heading("volume_total", "text"), "累计成交量")
        self.assertIn("AU.SHF → AU2610.SHF", self.app.quote_hint.cget("text"))
        self.assertIn("非固定1秒成交量", self.app.quote_hint.cget("text"))
        self.assertEqual(self.app.interval.get(), "2")

    def test_reset_baseline_and_legacy_missing_interval_show_dash_and_zero_stays_zero(self):
        legacy = self.row(3)
        legacy.pop("volume_interval_seconds")
        rows = [self.row(volume=None, volume_interval_seconds=None),
                self.row(2, volume=0., volume_interval_seconds=2.), legacy]
        with patch.object(self.service, "quote_snapshot", return_value=rows):
            self.app.select_symbol()
        tree = self.app.quote_table.tree
        first, second, third = tree.get_children()
        self.assertEqual(tree.set(first, "volume"), "—")
        self.assertEqual(tree.set(first, "volume_interval_seconds"), "—")
        self.assertEqual(tree.set(first, "volume_total"), "80,053")
        self.assertEqual(tree.set(second, "volume"), "0")
        self.assertEqual(tree.set(second, "volume_interval_seconds"), "2.000")
        self.assertEqual(tree.set(third, "volume_interval_seconds"), "—")
        with patch.object(self.service, "quote_snapshot", return_value=[]):
            self.app.display_symbol.set("000001.SZ")
            self.app.select_symbol()
        self.assertIn("非固定1秒成交量", self.app.quote_hint.cget("text"))


if __name__ == "__main__":
    unittest.main()
