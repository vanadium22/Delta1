from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from .swap_report import check_swap, sync_swap
from script_making.storage import filename


class SwapReportTests(unittest.TestCase):
    def test_sync_latest_fallback_and_date_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "reports"
            def make(day, value):
                folder = base / day
                folder.mkdir(parents=True)
                path = folder / filename("swap", day)
                book = Workbook()
                book.active.title = "收益总览"
                book.active["K5"] = value
                book.create_sheet("存续合约估值")
                book.save(path)
                book.close()
                return path

            old = make("2026-11-18", datetime(2026, 11, 18))
            new = make("2026-11-19", datetime(2026, 11, 18))
            future = make("2026-11-20", datetime(2026, 11, 20))

            class FakeSettings:
                def __init__(self, folder):
                    self.root = folder
                def data_path(self):
                    return base

            with patch("account_daily_pnl.swap_report.Settings", FakeSettings), \
                    patch("account_daily_pnl.swap_report.subprocess.run") as worker:
                worker.return_value.returncode = 0
                worker.return_value.stdout = json.dumps({"ok": True, "result": {"date": "2026-11-19"}})
                result = check_swap(root, "2026-11-19")
                self.assertEqual(result["date"], "2026-11-18")
                self.assertEqual(result["path"], str(old.resolve()))
                self.assertIn("K5", result["notes"][0])
                self.assertNotEqual(result["path"], str(future.resolve()))
                self.assertIn("2026-11-19", worker.call_args.args[0])
                book = Workbook()
                book.active.title = "收益总览"
                book.active["K5"] = datetime(2026, 11, 19)
                book.create_sheet("存续合约估值")
                book.save(new)
                book.close()
                self.assertEqual(check_swap(root, "2026-11-19", local_only=True)["date"], "2026-11-19")
                self.assertEqual(worker.call_count, 1)

    def test_syncs_swap_without_requiring_review_file_and_reuses_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source" / "2026-11-19"
            source.mkdir(parents=True)
            book = Workbook()
            book.active.title = "收益总览"
            book.active["K5"] = datetime(2026, 11, 19)
            book.create_sheet("存续合约估值")
            book.save(source / filename("swap", "2026-11-19"))
            book.close()

            class FakeSettings:
                def get(self):
                    return {"source_root": str(source.parent)}
                def data_path(self):
                    return root / "archive"

            first = sync_swap(FakeSettings(), "2026-11-19")
            self.assertEqual(first["date"], "2026-11-19")
            self.assertTrue((root / "archive" / "2026-11-19" / filename("swap", "2026-11-19")).is_file())
            self.assertTrue(sync_swap(FakeSettings(), "2026-11-19")["reused"])
