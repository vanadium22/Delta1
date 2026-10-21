"""Synthetic filesystem/server layouts; never contacts a company server."""
import json
import shutil
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from script_making.downloads import (DOWNLOADS, archive_path, discover, file_date,
                                     local_files, source_path, sync_download, validate_report)
from script_making.query import read_table, query_table
from script_making.service import ReportService
from script_making.storage import ReportError, Settings, sha256
from script_making.tests.test_reports import fixture


def sample(folder, kind, day, body_date=None):
    name = f"盈亏统计_{day}_new_adjust.xlsx" if kind == "pnl" else f"D1策略台日报_{day}.xlsx"
    if kind == "pnl":
        return fixture(folder / name, "累积盈亏统计", headers=[None, "日期"],
                       rows=[[None, None], [None, body_date or day]])
    return fixture(folder / name, "总表", headers=[None] * 9 + ["日期"],
                   rows=[[None] * 10] * 3 + [[None] * 9 + [body_date or day]])


class DownloadTests(unittest.TestCase):
    def setUp(self):
        cache = Path(__file__).resolve().parents[1] / "cache" / "download-tests"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root / "app")
        self.source = self.root / "source"
        self.source.mkdir()
        self.settings.update({"pnl_source": str(self.source), "strategy_source": str(self.source)})

    def tearDown(self):
        self.temp.cleanup()

    def test_server_prefix_and_annual_override(self):
        values = {"source_root": r"\\example-server\share\jrcx\for_jrcx\OTC-Quant\pybct\mtc\output"}
        path = str(source_path(values, "pnl")).replace("\\", "/")
        self.assertEqual(path, "//example-server/share/jrcx/for_jrcx/OTC-Quant/pybct/TZQ/盈亏统计_new")
        self.assertEqual(source_path({"strategy_source": str(self.source / "2025")}, "strategy"), self.source)
        with self.assertRaisesRegex(ReportError, "服务器前缀"):
            source_path({}, "pnl")

    def test_pnl_extended_history_delayed_latest_and_repeated_sync(self):
        for day in ("2026-10-13", "2026-10-14", "2026-10-16", "2026-10-19", "2026-10-21", "2026-10-22"):
            sample(self.source / "2026", "pnl", day)
        result = sync_download(self.settings, "pnl", date(2026, 10, 21))
        self.assertEqual(result["saved"], ["2026-10-13", "2026-10-14", "2026-10-16", "2026-10-19"])
        self.assertEqual(result["source_latest"], "2026-10-19")
        base = archive_path(self.settings, "pnl")
        paths = [Path(item["path"]) for item in local_files(base, "pnl")]
        before = [(p.stat().st_mtime_ns, sha256(p)) for p in paths]
        with patch("script_making.downloads.shutil.copyfile", side_effect=AssertionError("unchanged file copied")):
            again = sync_download(self.settings, "pnl", date(2026, 10, 21))
        self.assertEqual(again["saved"], [])
        self.assertEqual(len(again["reused"]), 4)
        self.assertEqual(before, [(p.stat().st_mtime_ns, sha256(p)) for p in paths])
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(all(not Path(v["path"]).is_absolute() for v in manifest["files"].values()))

    def test_pnl_backfills_current_year_and_strategy_keeps_week(self):
        days = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(40)]
        for day in days:
            sample(self.source / "2026", "pnl", day)
        sample(self.source / "2025", "pnl", "2025-12-31")
        sample(self.source / "2026", "pnl", "2026-10-21")
        result = sync_download(self.settings, "pnl", date(2026, 10, 21))
        self.assertEqual(result["saved"], days)
        sample(self.source / "2026", "strategy", "2026-09-01")
        sample(self.source / "2026", "strategy", "2026-10-19")
        self.assertEqual(sync_download(self.settings, "strategy", date(2026, 10, 21))["saved"], ["2026-10-19"])
        sample(self.source / "2027", "pnl", "2027-01-04")
        result = sync_download(self.settings, "pnl", date(2027, 1, 5))
        self.assertEqual(result["saved"], ["2027-01-04"])
        self.assertEqual(len(local_files(archive_path(self.settings, "pnl"), "pnl")), 41)

    def test_long_gap_backfill_and_recent_late_arrival(self):
        sample(self.source, "strategy", "2026-10-19")
        sync_download(self.settings, "strategy", date(2026, 10, 21))
        for day in ("2026-10-20", "2026-10-23", "2026-10-29"):
            sample(self.source / "2026", "strategy", day)
        result = sync_download(self.settings, "strategy", date(2026, 11, 2))
        self.assertEqual(result["saved"], ["2026-10-20", "2026-10-23", "2026-10-29"])
        sample(self.source, "strategy", "2026-10-28")
        result = sync_download(self.settings, "strategy", date(2026, 11, 3))
        self.assertIn("2026-10-28", result["saved"])

    def test_root_year_month_day_layout_cross_year_and_directory_mismatch(self):
        sample(self.source / "2025" / "12" / "31", "strategy", "2025-12-31")
        sample(self.source / "2026" / "202601" / "20260102", "strategy", "2026-01-02")
        sample(self.source, "strategy", "2026-01-03")
        sample(self.source / "2025", "strategy", "2026-01-01")
        sample(self.source / "unrelated", "strategy", "2026-01-04")
        found, errors = discover(self.source, "strategy", date(2025, 12, 30), date(2026, 1, 5))
        self.assertEqual(sorted(found), [date(2025, 12, 31), date(2026, 1, 2), date(2026, 1, 3)])
        self.assertEqual(len(errors), 1)
        self.assertIsNone(file_date("~$D1策略台日报_2026-01-03.xlsx", "strategy"))
        self.assertIsNone(file_date("D1策略台日报_2026-02-30.xlsx", "strategy"))

    def test_duplicate_sources_conflict_and_original_protection(self):
        original = sample(self.source, "strategy", "2026-10-19")
        annual = self.source / "2026" / original.name
        annual.parent.mkdir()
        shutil.copyfile(original, annual)
        first = sync_download(self.settings, "strategy", date(2026, 10, 21))
        self.assertEqual(first["errors"], [])
        local = Path(local_files(archive_path(self.settings, "strategy"), "strategy")[0]["path"])
        digest = sha256(local)
        annual.write_bytes(b"different")
        result = sync_download(self.settings, "strategy", date(2026, 10, 21))
        self.assertTrue(result["errors"])
        self.assertEqual(sha256(local), digest)
        original.write_bytes(b"different")
        result = sync_download(self.settings, "strategy", date(2026, 10, 21))
        self.assertTrue(result["errors"])
        self.assertEqual(sha256(local), digest)

    def test_invalid_date_and_failed_day_retry_beyond_week(self):
        bad = sample(self.source, "pnl", "2026-10-15", "2026-10-14")
        sample(self.source, "pnl", "2026-10-19")
        result = sync_download(self.settings, "pnl", date(2026, 10, 21))
        self.assertEqual(result["saved"], ["2026-10-19"])
        self.assertIn("日期", result["errors"][0])
        sample(self.source, "pnl", "2026-10-15")
        result = sync_download(self.settings, "pnl", date(2026, 11, 5))
        self.assertIn("2026-10-15", result["saved"])
        self.assertTrue(bad.exists())

    def test_missing_local_repaired_and_changed_local_backed_up(self):
        sample(self.source, "pnl", "2026-10-19")
        sync_download(self.settings, "pnl", date(2026, 10, 21))
        base = archive_path(self.settings, "pnl")
        local = Path(local_files(base, "pnl")[0]["path"])
        local.unlink()
        self.assertEqual(sync_download(self.settings, "pnl", date(2026, 11, 5))["saved"], ["2026-10-19"])
        local.write_bytes(b"local changes")
        result = sync_download(self.settings, "pnl", date(2026, 11, 6))
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["updated"], ["2026-10-19"])
        self.assertEqual(sha256(local), sha256(self.source / local.name))
        self.assertEqual(next((base / "_revisions").rglob("*.xlsx")).read_bytes(), b"local changes")

    def test_empty_initial_check_does_not_advance(self):
        self.assertEqual(sync_download(self.settings, "pnl", date(2026, 10, 21))["saved"], [])
        sample(self.source, "pnl", "2026-10-16")
        self.assertEqual(sync_download(self.settings, "pnl", date(2026, 10, 22))["saved"], ["2026-10-16"])

    def test_copy_failure_does_not_publish_file(self):
        sample(self.source, "pnl", "2026-10-19")
        with patch("script_making.downloads.shutil.copyfile", side_effect=OSError("simulated disconnect")):
            result = sync_download(self.settings, "pnl", date(2026, 10, 21))
        self.assertTrue(result["errors"])
        self.assertEqual(local_files(archive_path(self.settings, "pnl"), "pnl"), [])
        self.assertEqual(sync_download(self.settings, "pnl", date(2026, 10, 21))["saved"], ["2026-10-19"])

    def test_settings_preserve_source_overrides(self):
        self.settings.update({"epsilon": .001})
        self.assertEqual(self.settings.get()["pnl_source"], str(self.source))
        self.assertEqual(Settings(self.settings.root).get()["strategy_source"], str(self.source))

    def test_service_real_child_process_sources_independent_and_restart_status(self):
        # Dates close to the test run's Beijing date; subprocess uses its own clock.
        from script_making.storage import today
        from datetime import timedelta
        day = (today() - timedelta(days=2)).isoformat()
        sample(self.source, "strategy", day)
        service = ReportService(self.settings.root)
        service.update_settings({"pnl_source": str(self.root / "missing")})
        service.start_download("pnl")
        service.start_download("strategy")
        with self.assertRaisesRegex(ReportError, "同步期间"):
            service.update_settings({"data_dir": "other"})
        deadline = time.monotonic() + 20
        while service.downloads_running() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(service.downloads_running())
        self.assertEqual(service.download_status("pnl")["state"], "error")
        self.assertEqual(service.download_status("strategy")["state"], "success")
        reopened = ReportService(self.settings.root).download_catalog("strategy")
        self.assertEqual(reopened["files"][0]["date"], day)
        self.assertIn("finished_at", reopened["status"])


class WorksheetTests(unittest.TestCase):
    def test_empty_first_column_keeps_excel_row_numbers_and_summary_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Headers below a leading empty column; data row also has no A cell.
            path = fixture(root / "sparse.xlsx", "其他明细", headers=[None, "名称", "金额", "日期"],
                           rows=[[None, "示例", 10, "2026-10-19"], [None] * 4,
                                 [None, "另一行", 20, "2026-10-20"]])
            table = read_table(path, "其他明细")
            self.assertEqual(table["source_rows"], [2, 4])
            self.assertEqual(query_table(table, {"sort": {"column": "c2", "direction": "desc"}})["rows"][0]["excel_row"], 4)
            summary = fixture(root / "summary.xlsx", "收益总览", headers=[None, "总览"],
                              rows=[[None, 10], ["说明", 0]])
            table = read_table(summary, "收益总览")
            self.assertEqual(table["layout"], "grid")
            self.assertEqual(table["source_rows"], [1, 2, 3])
            self.assertEqual([col["name"] for col in table["columns"]], ["A", "B"])
            self.assertEqual(table["rows"][-1], ["说明", 0])


if __name__ == "__main__":
    unittest.main()
