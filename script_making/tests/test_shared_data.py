import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from shared_data.io import sha256
from shared_data.readers import LocalData
from script_making.service import ReportService
from script_making.storage import Settings, filename, save_files


class SharedReportTests(unittest.TestCase):
    def test_existing_pair_is_migrated_read_and_reopened_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            root = repo / "script_making"
            day = "2026-10-14"
            sources = {}
            for kind, sheet in (("swap", "存续合约估值"), ("review", "簿记要素")):
                path = repo / "source" / filename(kind, day)
                path.parent.mkdir(exist_ok=True)
                book = Workbook()
                book.active.title = sheet
                if kind == "swap":
                    book.active.append(["合成日报"])
                book.active.append(["合约", "数量"])
                book.active.append(["TEST-001", 100])
                book.save(path)
                book.close()
                sources[kind] = path
            old = root / "data/reports"
            result = save_files(old, sources, day, "合成迁移测试")
            manifest = old / day / "manifest.json"
            manifest_hash = sha256(manifest)
            root.joinpath("config.local.json").write_text(json.dumps({"data_dir": "data/reports"}), encoding="utf-8")
            with patch("script_making.service.subprocess.run", side_effect=AssertionError("network")):
                service = ReportService(root)
                catalog = service.catalog()
                self.assertTrue(catalog["dates"][0]["complete"])
                query = service.query({"kind": "swap", "date": day})
                self.assertEqual(query["total"], 1)
                self.assertEqual(ReportService(root).query({"kind": "review", "date": day})["total"], 1)
            self.assertEqual(service.settings.data_path(), repo / "data/reports/swap")
            for entry in result["files"].values():
                original = Path(entry["path"])
                copied = service.settings.data_path() / day / original.name
                self.assertEqual(sha256(original), sha256(copied))
            self.assertEqual(sha256(manifest), manifest_hash)
            current = json.loads((service.settings.data_path() / day / "manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("path", current["files"]["swap"])
            self.assertEqual(LocalData(service.settings.paths).report_file("swap", day), service.settings.data_path() / day / filename("swap", day))
