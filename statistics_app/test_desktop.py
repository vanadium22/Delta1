import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from script_making.service import ReportService
from statistics_app.desktop import StatisticsWindow, main


class StatisticsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_standalone_reuses_existing_service_and_skips_auto_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ReportService(Path(tmp))
            with patch.object(service, "query_catalog", return_value={"dates": [
                {"date": "2026-10-28", "files": {"pnl": {}}}
            ]}), patch("script_making.statistics_widgets.build_snapshot") as generate:
                window = StatisticsWindow(service, auto_generate=False)
                window.show()
                self.app.processEvents()
                self.assertIs(window.page.service, service)
                self.assertEqual(window.page.dates["pnl"].currentData(), "2026-10-28")
                generate.assert_not_called()
                self.assertFalse((Path(tmp) / "statistics.local.json").exists())
                window.close()

    def test_close_waits_for_running_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ReportService(Path(tmp))
            with patch.object(service, "query_catalog", return_value={"dates": []}), \
                 patch("script_making.statistics_widgets.build_snapshot", side_effect=lambda *args: (time.sleep(.2), {})[1]):
                window = StatisticsWindow(service, auto_generate=False)
                window.show()
                window.page.generate()
                self.assertIsNotNone(window.page.worker)
                window.close()
                self.assertTrue(window.isVisible())
                limit = time.monotonic() + 3
                while window.isVisible() and time.monotonic() < limit:
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertFalse(window.isVisible())
                self.assertIsNone(window.page.worker)

    def test_startup_check_uses_requested_root_without_generating(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("script_making.statistics_widgets.build_snapshot") as generate:
                self.assertEqual(main(["--root", tmp, "--startup-check"]), 0)
                generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
