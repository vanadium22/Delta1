"""Revision adoption and external-scheduler adapter tested with synthetic data only."""
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from shared_data.io import file_lock
from script_making.daily_job import run_once
from script_making.downloads import archive_path, sync_download
from script_making.inspect_automation import inspect_project
from script_making.statistics_charts import chart_image
from script_making.storage import ReportError, filename, sha256, sync_reports
from script_making.tests import test_statistics as sample_tests
from script_making.tests.test_statistics import pnl_book, risk_book
from script_making.tests.test_reports import fixture


class RevisionTests(unittest.TestCase):
    setUp = sample_tests.StatisticsTests.setUp
    tearDown = sample_tests.StatisticsTests.tearDown
    snapshot = sample_tests.StatisticsTests.snapshot

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_shared_pair_republished_on_startup_with_backups(self):
        source = self.root / "share"
        day = "2026-10-19"
        sources = {kind: fixture(source / day / filename(kind, day), sheet=sheet)
                   for kind, sheet in (("swap", "存续合约估值"), ("review", "簿记要素"))}
        target = self.root / "pair-data"
        values = {"source_root": str(source)}
        first = sync_reports(values, target, date(2026, 10, 21), only_missing=True)
        old = sha256(Path(first["files"]["swap"]["path"]))
        fixture(sources["swap"], rows=[["new", "合成修订", 123]])
        revised = sync_reports(values, target, date(2026, 10, 21), only_missing=True)
        self.assertEqual(revised["updated"], ["swap"])
        self.assertEqual(sha256(Path(revised["files"]["swap"]["path"])), sha256(sources["swap"]))
        backup = next((target / "_revisions").rglob("*.xlsx"))
        self.assertEqual(sha256(backup), old)
        with patch("script_making.storage.shutil.copyfile", side_effect=AssertionError("duplicate copy")):
            self.assertTrue(sync_reports(values, target, date(2026, 10, 21), only_missing=True)["reused"])


    def test_pair_publish_failure_rolls_back_both_files(self):
        source, target, day = self.root / "share", self.root / "target", "2026-10-19"
        sources = {kind: fixture(source / day / filename(kind, day), sheet=sheet)
                   for kind, sheet in (("swap", "存续合约估值"), ("review", "簿记要素"))}
        values = {"source_root": str(source)}
        sync_reports(values, target, date(2026, 10, 21))
        before = {kind: sha256(target / day / path.name) for kind, path in sources.items()}
        for kind, path in sources.items():
            fixture(path, sheet="存续合约估值" if kind == "swap" else "簿记要素", rows=[["new", "合成", 123]])
        real_replace = os.replace
        def fail_second(src, dst):
            if Path(dst) == target / day / sources["review"].name:
                raise PermissionError("simulated Excel lock")
            return real_replace(src, dst)
        with patch("script_making.storage.os.replace", side_effect=fail_second):
            with self.assertRaisesRegex(ReportError, "恢复原文件"):
                sync_reports(values, target, date(2026, 10, 21))
        self.assertEqual(before, {kind: sha256(target / day / path.name) for kind, path in sources.items()})


    def test_newest_share_partition_wins_and_invalid_latest_is_not_adopted(self):
        source = self.root / "share"
        first = risk_book(source / "D1策略台日报_2026-10-19.xlsx", "2026-10-19")
        second = risk_book(source / "2026" / first.name, "2026-10-19", rows=[["600001.SH", "合成修订", 42, 3, 1, 900000]])
        os.utime(first, (100, 100))
        os.utime(second, (200, 200))
        self.service.update_settings({"strategy_source": str(source)})
        result = sync_download(self.service.settings, "strategy", date(2026, 10, 21))
        self.assertEqual(result["errors"], [])
        local = archive_path(self.service.settings, "strategy") / "2026-10-19" / first.name
        self.assertEqual(sha256(local), sha256(second))
        old_hash = sha256(local)
        first.write_bytes(b"corrupt newest")
        os.utime(first, (300, 300))
        result = sync_download(self.service.settings, "strategy", date(2026, 10, 21))
        self.assertTrue(result["errors"])
        self.assertEqual(sha256(local), old_hash)


    def pnl_history_path(self, day):
        return archive_path(self.service.settings, "pnl") / day / f"盈亏统计_{day}_new_adjust.xlsx"

    def test_pnl_history_differences_bad_points_and_revision_cache(self):
        pnl_book(self.pnl_history_path("2025-12-31"), "2025-12-31", 999999)
        for day, value in (("2026-01-05", 100), ("2026-02-02", 300), ("2026-03-02", 200)):
            pnl_book(self.pnl_history_path(day), day, value)
        bad = self.pnl_history_path("2026-04-01")
        bad.parent.mkdir()
        bad.write_bytes(b"bad")
        with patch("script_making.statistics.today", return_value=date(2026, 10, 21)):
            snap = self.snapshot()
            self.assertEqual(set(snap["history"]), {"pnl"})
            points = snap["history"]["pnl"]["points"]
            self.assertEqual([p["date"] for p in points], ["2026-01-05", "2026-02-02", "2026-03-02", "2026-04-01", "2026-10-16", "2026-10-19"])
            self.assertEqual([p["change"] for p in points], [None, "200", "-100", None, None, "234.56"])
            self.assertIsNone(points[3]["current"])
            image = chart_image(snap)
            self.assertEqual((image.width(), image.height()), (1600, 780))
            pnl_book(self.pnl_history_path("2026-01-05"), "2026-01-05", 50)
            changed = self.snapshot()
            self.assertEqual(changed["history"]["pnl"]["points"][0]["current"], "50")
            self.assertEqual(changed["history"]["pnl"]["points"][1]["change"], "250")

    def test_pnl_history_full_year_cutoff_and_automatic_year_rollover(self):
        for i in range(40):
            day = (date(2026, 8, 1) + timedelta(days=i)).isoformat()
            pnl_book(self.pnl_history_path(day), day, i * 100)
        pnl_book(self.pnl_history_path("2026-10-20"), "2026-10-20", 999)
        for day, value in (("2027-01-05", 10), ("2027-01-06", 25)):
            pnl_book(self.pnl_history_path(day), day, value)
        with patch("script_making.statistics.today", return_value=date(2026, 10, 21)):
            snap = self.snapshot()
        points = snap["history"]["pnl"]["points"]
        self.assertEqual(len(points), 42)
        self.assertEqual(points[0]["date"], "2026-08-01")
        self.assertIsNone(points[0]["change"])
        self.assertEqual(points[-1]["date"], "2026-10-19")
        self.assertTrue(all(key.startswith("history:pnl:") for key in snap["sources"] if key.startswith("history:")))
        self.selections.update(pnl="2027-01-06", previous="2027-01-05")
        with patch("script_making.statistics.today", return_value=date(2027, 1, 7)):
            new = self.snapshot()["history"]["pnl"]
        self.assertEqual(new["year"], 2027)
        self.assertEqual([p["change"] for p in new["points"]], [None, "15"])


    def test_inspection_has_no_writes_no_mail_values_and_no_business_imports(self):
        root = self.root / "nonexistent" / "script_making"
        report = inspect_project(root)
        self.assertFalse(root.exists())
        self.assertFalse(report["side_effects"]["sync"])
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "script_making.daily_job", "--root", str(root)],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["mode"], "inspection_only")
        self.assertFalse(root.exists())


    def test_single_run_local_only_reuses_bundle_and_changed_source_creates_revision(self):
        with patch("script_making.daily_job.sync_once", side_effect=AssertionError("must remain offline")):
            code, result = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
            self.assertEqual(code, 0, result)
            self.assertEqual(result["state"], "success")
            directory = Path(result["export_directory"])
            self.assertEqual({p.name for p in directory.glob("*.png")}, {"pnl1.png", "risk.png"})
            code, repeated = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
            self.assertEqual(repeated["state"], "reused")
            self.assertEqual(repeated["export_directory"], str(directory))
            # A complete old renderer cache must not be reused by this renderer.
            import hashlib
            from script_making.storage import atomic_json
            snap = json.loads((directory / "统计记录.json").read_text(encoding="utf-8"))
            identity = {key: value for key, value in snap.items() if key not in ("id", "created_at")}
            old_key = hashlib.sha256(json.dumps({"version": 2, "snapshot": identity}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            completed = self.service.settings.data_path() / "statistics/daily_runs/completed"
            current_index = completed / (result["fingerprint"] + ".json")
            atomic_json(completed / (old_key + ".json"), json.loads(current_index.read_text(encoding="utf-8")))
            current_index.unlink()
            code, refreshed = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
            self.assertEqual(code, 0, refreshed)
            self.assertEqual(refreshed["state"], "success")
            self.assertNotEqual(refreshed["export_directory"], str(directory))
            self.assertTrue((directory / "邮件草稿.eml").exists())
            directory = Path(refreshed["export_directory"])
            (directory / "risk.png").write_bytes(b"corrupt")
            code, repaired = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
            self.assertEqual(code, 0, repaired)
            self.assertEqual(repaired["state"], "success")
            self.assertNotEqual(repaired["export_directory"], str(directory))
            index = self.service.settings.data_path() / "statistics" / "daily_runs" / "completed" / (repaired["fingerprint"] + ".json")
            value = json.loads(index.read_text(encoding="utf-8"))
            value["files"].pop("邮件草稿.eml")
            index.write_text(json.dumps(value), encoding="utf-8")
            code, rebuilt = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
            self.assertEqual(code, 0, rebuilt)
            self.assertEqual(rebuilt["state"], "success")


    def test_partial_sync_does_not_generate_draft_and_missing_prior_is_incomplete(self):
        with patch("script_making.daily_job.sync_once", return_value={"errors": ["synthetic failure"]}) as sync:
            code, result = run_once(self.service.settings.root, date(2026, 10, 21))
            self.assertEqual(code, 2)
            self.assertEqual(sync.call_count, 3)
            self.assertNotIn("export_directory", result)
        self.previous_path.unlink()
        code, result = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 2)
        self.assertFalse(result["send_email"])
        self.assertTrue((self.service.settings.data_path() / "statistics" / "daily_runs" / "latest.json").exists())

    def test_render_failure_returns_one_without_sendable_draft(self):
        with patch("script_making.statistics_export.save_image", side_effect=OSError("synthetic render failure")):
            code, result = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 1)
        self.assertEqual(result["state"], "failed")
        self.assertNotIn("export_directory", result)
        self.assertFalse(result["send_email"])
        exports = self.service.settings.data_path() / "statistics/exports"
        self.assertFalse(list(exports.rglob("*.eml")))
        self.assertEqual(len(list(exports.rglob("导出未完成.txt"))), 1)


    def test_full_pipeline_with_fake_share_children_and_local_lock(self):
        # Existing synthetic files supply valid statistics; fake share results test orchestration.
        def fake_sync(root, as_of, kind):
            return {"errors": [], "date": "2026-10-14", "source_latest": "2026-10-19"}
        with patch("script_making.daily_job.sync_once", side_effect=fake_sync) as sync:
            code, result = run_once(self.service.settings.root, date(2026, 10, 21))
            self.assertEqual(code, 0, result)
            self.assertEqual([call.args[2] for call in sync.call_args_list], ["pair", "pnl", "strategy"])
        import threading
        ready, release = threading.Event(), threading.Event()
        def hold():
            with file_lock(self.service.settings.data_path() / "statistics" / ".daily_job.lock"):
                ready.set()
                release.wait(5)
        thread = threading.Thread(target=hold)
        thread.start()
        ready.wait(5)
        try:
            code, result = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
            self.assertEqual(code, 3)
            self.assertEqual(result["state"], "busy")
        finally:
            release.set()
            thread.join()

    def test_runner_uses_this_share_check_dates_not_newer_stale_local(self):
        future = self.service.settings.data_path() / "2026-10-20" / filename("swap", "2026-10-20")
        risk_book(future, "2026-10-20")
        with patch("script_making.daily_job.sync_once", return_value={"errors": [], "date": "2026-10-14", "source_latest": "2026-10-19"}):
            code, result = run_once(self.service.settings.root, date(2026, 10, 21))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["report_dates"]["swap"], "2026-10-14")
        with patch("script_making.daily_job.sync_once", return_value={"errors": []}):
            code, result = run_once(self.service.settings.root, date(2026, 10, 21))
        self.assertEqual(code, 2)
        self.assertNotIn("export_directory", result)

    def test_cli_runs_real_children_against_synthetic_local_sources(self):
        sources = {kind: self.root / "synthetic-share" / kind for kind in ("pair", "pnl", "strategy")}
        copies = [(self.swap_path, sources["pair"] / "2026-10-14" / self.swap_path.name),
                  (self.pnl_path, sources["pnl"] / "2026" / self.pnl_path.name),
                  (self.previous_path, sources["pnl"] / "2026" / self.previous_path.name),
                  (self.strategy_path, sources["strategy"] / "2026" / self.strategy_path.name)]
        for source, target in copies:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        fixture(sources["pair"] / "2026-10-14" / filename("review", "2026-10-14"), sheet="簿记要素")
        target = self.root / "empty-downloads"
        self.service.update_settings({"source_root": str(sources["pair"]), "pnl_source": str(sources["pnl"]),
                                      "strategy_source": str(sources["strategy"]), "data_dir": str(target)})
        environment = os.environ.copy()
        for name in ("SCRIPT_MAKING_SOURCE", "SCRIPT_MAKING_DATA", "DELTA1_DATA_ROOT", "DELTA1_OUTPUTS_ROOT"):
            environment.pop(name, None)
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "script_making.daily_job",
                                 "--root", str(self.service.settings.root), "--run", "--as-of", "2026-10-21"],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
                                encoding="utf-8", env=environment, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["state"], "success")
        self.assertEqual(len(list(Path(output["export_directory"]).glob("*.png"))), 2)
        record = json.loads((target / "statistics" / "daily_runs" / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(record["report_dates"], self.selections)
        self.assertTrue(all(item["state"] == "success" for item in record["sync"].values()))
        self.assertEqual(len(list(target.rglob("*.xlsx"))), 5)
