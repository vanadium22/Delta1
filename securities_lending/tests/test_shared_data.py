import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from shared_data.io import sha256
from shared_data.readers import LocalData
from securities_lending.config import DEFAULTS, atomic_json
from securities_lending.service import InventoryService
from securities_lending.sync import synchronize


class SharedInventoryTests(unittest.TestCase):
    def test_old_absolute_manifest_reuses_inventory_without_download_and_prices_stay_live(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            root = repo / "securities_lending"
            day = "2026-10-14"
            source = repo / "source" / day / f"申万内部券单{day}.xlsx"
            source.parent.mkdir(parents=True)
            book = Workbook()
            book.active.title = "库存券单"
            book.active.append(["证券代码", "证券简称", "实际可融股数", "可融股数", "参考费率", "来源", "期限"])
            book.active.append(["000001.SZ", "合成银行", 500, 300, .05, "互换", 14])
            book.save(source)
            book.close()
            config = {**DEFAULTS, "source_root": str(repo / "source"), "wind_enabled": False}
            atomic_json(root / "config.local.json", config)
            old = root / "data/live"
            manifest = synchronize(config, day, old)
            manifest["file_glob"] = config["file_glob"]
            atomic_json(old / day / "latest.json", manifest)  # Actual pre-upgrade absolute paths.
            old_hash = sha256(old / day / "latest.json")
            source.unlink()
            with patch("securities_lending.service.synchronize", side_effect=AssertionError("download")):
                service = InventoryService(root, clock=lambda: day)
                status = service.status()
                self.assertEqual(status["state"], "local")
                with patch.object(service.provider, "market", side_effect=[({}, {"000001.SZ": {"price": "10"}}, []), ({}, {"000001.SZ": {"price": "20"}}, [])]) as prices:
                    a = service.query("000001", {"000001.SZ": "1000"})
                    b = service.query("000001", {"000001.SZ": "2000"})
                    self.assertEqual(prices.call_count, 2)
                self.assertEqual(InventoryService(root, clock=lambda: day).status()["files"], status["files"])
            self.assertEqual(service.data_root, repo / "data/lending/live")
            self.assertEqual(status["downloaded_at"], manifest["downloaded_at"])
            self.assertEqual(sha256(old / day / "latest.json"), old_hash)
            self.assertTrue(Path(manifest["files"][0]["path"]).exists())
            stored = json.loads((service.data_root / day / "latest.json").read_text(encoding="utf-8"))
            self.assertIn("relative_path", stored["files"][0])
            self.assertNotIn("path", stored["files"][0])
            self.assertEqual(LocalData(service.paths).lending_files(day)["files"][0]["path"], status["files"][0]["path"])
