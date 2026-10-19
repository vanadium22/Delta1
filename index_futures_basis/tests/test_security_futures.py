import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from index_futures_basis.config import DEFAULTS as DEFAULT_CONFIG
from index_futures_basis.security_data import SecurityService, export_result
from index_futures_basis.security_model import SecurityQuery
from index_futures_basis.store import Store
from shared_data import DataPaths


class LocalFutureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = DataPaths.for_repo(Path(self.temp.name))
        self.store = Store(self.paths.basis("wind") / "market.sqlite")
        self.store.save_calendar("2026-10-14", "2026-10-16", ["2026-10-14", "2026-10-15", "2026-10-16"])
        self.store.save_rows("mapping", [("2026-10-14", "IF", 3, "IF2612.CFE"),
                                          ("2026-10-15", "IF", 3, "IF2703.CFE")])
        self.store.save_rows("quotes", [("IF2612.CFE", "2026-10-14", "close", 4000),
                                        ("IF2612.CFE", "2026-10-14", "oi", 0),
                                        ("IF2703.CFE", "2026-10-15", "close", 4100),
                                        ("IF2612.CFE", "2026-10-15", "close", 4020)])
        self.service = SecurityService(self.paths, DEFAULT_CONFIG, "wind")

    def tearDown(self):
        self.temp.cleanup()

    def query(self, code, **kwargs):
        return SecurityQuery(code, "1d", start="2026-10-14", end="2026-10-16", **kwargs)

    def test_normalization_mapping_gaps_statistics_and_zero_oi(self):
        with patch("index_futures_basis.security_data.SecurityProvider", side_effect=AssertionError("network")):
            self.assertEqual(self.service.lookup_name("if02")["code"], "IF02.CFE")
            result = self.service.query(self.query("if02", fields=("close", "oi")))
        self.assertEqual(list(result.frame.close[:2]), [4000, 4100])
        self.assertTrue(pd.isna(result.frame.close.iloc[2]))
        self.assertEqual(result.frame.oi.iloc[0], 0)
        self.assertEqual(result.metadata["contract_mapping"][1]["actual_code"], "IF2703.CFE")
        self.assertIsNone(result.metadata["contract_mapping"][2]["actual_code"])
        self.assertEqual(result.summary["statistics"][0]["mean"], 4050)
        self.assertEqual(result.metadata["requests"], 0)
        export_result(result, Path(self.temp.name) / "export")
        self.assertTrue((Path(self.temp.name) / "export/manifest.json").is_file())

    def test_actual_contract_exact_match_and_reads_daily_updates(self):
        result = self.service.query(self.query("if2612.cfe"))
        self.assertEqual(list(result.frame.close[:2]), [4000, 4020])
        self.store.save_rows("quotes", [("IF2612.CFE", "2026-10-16", "close", 4030)])
        result = self.service.query(self.query("If2612"))
        self.assertEqual(result.frame.close.iloc[-1], 4030)
        self.assertEqual(result.metadata["actual_end"], "2026-10-16")

    def test_real_fallback_demo_isolation_and_missing_fields(self):
        offline = SecurityService(self.paths, DEFAULT_CONFIG, "offline")
        result = offline.query(self.query("if2612", fields=("close", "open")))
        self.assertEqual(result.metadata["source_database"], str(self.store.path))
        self.assertTrue(result.frame.open.isna().all())
        with self.assertRaisesRegex(ValueError, "没有可用"):
            SecurityService(self.paths, DEFAULT_CONFIG, "demo").query(self.query("if2612"))

    def test_no_daily_to_minute_or_snapshot_and_no_force_download(self):
        for frequency in ("1m", "snapshot"):
            query = SecurityQuery("if02", frequency, start="2026-10-14 09:30", end="2026-10-14 15:00")
            with self.assertRaisesRegex(ValueError, "日频"):
                self.service.query(query)
        with self.assertRaisesRegex(ValueError, "只读"):
            self.service.query(self.query("if02"), force=True)
        for code in ("IF04", "XX2612", "IF2612.SH"):
            with self.assertRaises(ValueError):
                self.query(code)
