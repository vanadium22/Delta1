import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from index_futures_basis.config import load_config
from index_futures_basis.recent_brief.dividend_sources import history_paths
from index_futures_basis.recent_brief.share_history import collect
from shared_data import DataPaths


class ShareHistoryTests(unittest.TestCase):
    def test_archives_original_pending_codes_by_business_day_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = DataPaths.for_repo(root)
            config = load_config()

            def save(year, name, day, value):
                target = root/"share"/year/name
                target.parent.mkdir(parents=True, exist_ok=True)
                book = Workbook()
                sheet = book.active
                sheet.title = "Sheet1"
                sheet["B1"], sheet["G3"] = day, "分红"
                sheet["B4"], sheet["C4"], sheet["G4"] = "IF00.CFE", "Fetching...", value
                book.save(target)
                book.close()
                return target

            first = save("2025", "指数基差情况_2025-12-20.xlsx", "2025-11-24", 5)
            second = save("2026", "指数基差情况_2026-01-20.xlsx", "2026-01-20", 0)
            save("2026", "指数基差情况_2026-01-21.xlsx", "2026-01-21", 10)
            (second.parent/"指数基差情况_损坏.xlsx").write_bytes(b"not a workbook")
            (second.parent/"指数基差情况_副本.xlsx").write_bytes(second.read_bytes())
            lines = []
            for _ in range(2):
                collect(paths, config, "2025-11-24", "2026-01-20", str(second.parent), root, lines.append)
            files, _ = history_paths(root/"index_futures_basis", config, paths)
            self.assertCountEqual([path.read_bytes() for path in files], [first.read_bytes(), second.read_bytes()])
            report = "\n".join(lines)
            self.assertIn("新归档表日  2025-11-24", report)
            self.assertIn("新归档表日  2026-01-20", report)
            self.assertIn("跳过 Excel", report)
