import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from shared_data import Catalog, DataPaths, Dataset
from shared_data.io import atomic_json, file_lock, portable_manifest, resolved_manifest, sha256
from shared_data.migration import copy_verified, ensure_migrated
from shared_data.readers import LocalData


class SharedDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"DELTA1_DATA_ROOT": "", "DELTA1_OUTPUTS_ROOT": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.paths = DataPaths.for_repo(self.root)

    def test_paths_do_not_depend_on_current_directory_and_all_modules_share(self):
        roots = [DataPaths.for_module(self.root / m).root for m in ("index_futures_basis", "script_making", "securities_lending", "dashboard")]
        self.assertEqual(roots, [self.root / "data"] * 4)
        nested = self.root / "data" / "qa" / "isolated"
        self.assertEqual(DataPaths.for_module(nested).root, nested / "data")

    def test_local_configuration_and_environment_precedence(self):
        atomic_json(self.root / "localsetting/data.local.json", {"data_root": "outside", "outputs_root": "results"})
        self.assertEqual(DataPaths.for_repo(self.root).root, self.root / "outside")
        with patch.dict(os.environ, {"DELTA1_DATA_ROOT": str(self.root / "override")}):
            self.assertEqual(DataPaths.for_repo(self.root).root, self.root / "override")
            self.assertEqual(DataPaths.for_repo(self.root, data_root=self.root / "explicit").root, self.root / "explicit")

    def test_explicit_module_paths_remain_supported(self):
        app = self.root / "script_making"
        for alias in ("@shared", "data/reports", str(app / "data/reports")):
            self.assertEqual(self.paths.resolve_module_setting(app, alias, self.paths.reports, ("data/reports",)), self.paths.reports)
        self.assertEqual(self.paths.resolve_module_setting(app, "private", self.paths.reports), app / "private")

    def test_manifest_can_move_to_another_machine_and_rejects_escape(self):
        original = self.root / "old"
        original.mkdir()
        file = original / "2026-10-14/report.xlsx"
        file.parent.mkdir()
        file.write_bytes(b"test")
        value = {"files": [{"path": str(file), "source": "original-share", "sha256": sha256(file)}]}
        portable = portable_manifest(value, original)
        self.assertNotIn("path", portable["files"][0])
        self.assertEqual(portable["files"][0]["source"], "original-share")
        moved = self.root / "new"
        shutil.copytree(original, moved)
        resolved = resolved_manifest(portable, moved)
        self.assertTrue(Path(resolved["files"][0]["path"]).is_file())
        portable["files"][0]["relative_path"] = "../escape.xlsx"
        with self.assertRaises(ValueError):
            resolved_manifest(portable, moved)

    def test_copy_is_idempotent_preserves_original_and_rejects_conflicts(self):
        source, target = self.root / "original", self.root / "copied"
        source.write_bytes(b"a")
        self.assertTrue(copy_verified(source, target)["copied"])
        self.assertFalse(copy_verified(source, target)["copied"])
        target.write_bytes(b"b")
        with self.assertRaisesRegex(ValueError, "保留双方"):
            copy_verified(source, target)
        self.assertEqual(source.read_bytes(), b"a")
        self.assertEqual(target.read_bytes(), b"b")

    def test_database_backup_includes_wal_and_preserves_source(self):
        source, target = self.root / "original.sqlite", self.root / "new/market.sqlite"
        con = sqlite3.connect(source)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE quotes(code,day,field,value)")
            con.execute("INSERT INTO quotes VALUES('IF2610.CFE','2026-10-14','close',4000)")
            con.commit()
            original_hash = sha256(source)
            result = copy_verified(source, target)
            self.assertIn("logical_sha256", result)
            self.assertEqual(sha256(source), original_hash)
            with closing(sqlite3.connect(target)) as migrated:
                self.assertEqual(migrated.execute("SELECT value FROM quotes").fetchone()[0], 4000)
            self.assertFalse(copy_verified(source, target)["copied"])
        finally:
            con.close()

    def test_report_migration_rebases_manifest_and_runs_only_once(self):
        app = self.root / "script_making"
        folder = app / "data/reports/2026-10-14"
        folder.mkdir(parents=True)
        file = folder / "日报复核表(2026-10-14)-D1.xlsx"
        file.write_bytes(b"fixture")
        atomic_json(folder / "manifest.json", {"date": "2026-10-14", "files": {"review": {"path": str(file), "sha256": sha256(file)}}})
        old_manifest = (folder / "manifest.json").read_bytes()
        result = ensure_migrated("script_making", app)
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual((folder / "manifest.json").read_bytes(), old_manifest)
        self.assertEqual(LocalData(self.paths).report_file("review", "2026-10-14").read_bytes(), b"fixture")
        saved = json.loads((self.paths.reports / "2026-10-14/manifest.json").read_text(encoding="utf-8"))
        self.assertIn("relative_path", saved["files"]["review"])
        # A former module directory cannot later overwrite the new authoritative copy.
        file.write_bytes(b"changed old file")
        self.assertEqual(ensure_migrated("script_making", app), result)
        self.assertEqual(LocalData(self.paths).report_file("review", "2026-10-14").read_bytes(), b"fixture")

    def test_dataset_identity_separates_daily_minute_and_realtime(self):
        catalog = Catalog(self.paths)
        daily = Dataset("indices", "wind", "1d", storage="sqlite")
        minute = Dataset("indices", "wind", "1m", storage="parquet")
        realtime = Dataset("indices", "wind", "tick", retention="daily_cache", keep_days=2)
        for ds in (daily, minute, realtime):
            catalog.register(ds)
        paths = [catalog.partition(ds.key, "2026-10-14", "000300.SH") for ds in (daily, minute, realtime)]
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual(catalog.get(minute.key)[0].retention, "persistent")
        with self.assertRaises(ValueError):
            catalog.register(Dataset("indices", "wind", "1m", retention="daily_cache", keep_days=1))

    def test_prune_is_opt_in_and_cannot_touch_history_or_today(self):
        catalog = Catalog(self.paths)
        history = Dataset("indices", "wind", "1m", storage="parquet")
        cache = Dataset("indices", "feed", "tick", retention="daily_cache", keep_days=2)
        for ds in (history, cache):
            catalog.register(ds)
            for day in ("2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17"):
                p = catalog.partition(ds.key, day)
                p.mkdir(parents=True)
                (p / "part.dat").write_bytes(b"x")
        plan = catalog.prune(cache.key, today=date(2026, 10, 16))
        self.assertEqual(len(plan["partitions"]), 2)
        self.assertTrue(all(Path(p).exists() for p in plan["partitions"]))
        catalog.prune(cache.key, today=date(2026, 10, 16), apply=True)
        self.assertFalse(any(Path(p).exists() for p in plan["partitions"]))
        self.assertTrue(catalog.partition(cache.key, "2026-10-16").exists())
        self.assertTrue(catalog.partition(history.key, "2026-10-13").exists())
        with self.assertRaisesRegex(ValueError, "永久历史"):
            catalog.prune(history.key, apply=True)

    def test_catalog_rejects_traversal_and_destructive_registration(self):
        for value in ("../x", "x/y", "x\\y", ".."):
            with self.assertRaises(ValueError):
                Dataset(value, "wind", "1m")
        with self.assertRaises(ValueError):
            Catalog(self.paths).register(Dataset("indices", "wind", "tick", retention="daily_cache", keep_days=1), self.paths.root / "market")

    def test_readonly_market_reader_does_not_create_missing_database(self):
        reader = LocalData(self.paths)
        with self.assertRaises(sqlite3.OperationalError):
            reader.daily_quotes("2026-10-14", "2026-10-15")
        self.assertFalse(self.paths.root.exists())
        database = self.paths.basis("wind") / "market.sqlite"
        database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database)) as con:
            con.execute("CREATE TABLE quotes(code,day,field,value)")
            con.executemany("INSERT INTO quotes VALUES(?,?,?,?)", [("IF2610.CFE", "2026-10-14", "close", 4000), ("IC2610.CFE", "2026-10-15", "oi", 1234)])
            con.commit()
        result = reader.daily_quotes("2026-10-14", "2026-10-15", codes=["IF2610.CFE"], fields=["close"])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["frequency"], "1d")

    def test_lock_is_cross_process_and_reentrant(self):
        path = self.root / "shared.lock"
        script = "from shared_data.io import file_lock; from pathlib import Path; import sys\nwith file_lock(Path(sys.argv[1]), timeout=.1): pass"
        with file_lock(path), file_lock(path):
            result = subprocess.run([sys.executable, "-B", "-c", script, str(path)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"TimeoutError", result.stderr)
        with file_lock(path):
            pass
