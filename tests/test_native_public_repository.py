"""Check public source export boundaries, synchronization and independent startup."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dashboard.build_public_repository import (
    ROOT, FORBIDDEN_TEXT, audit_files, build_repository, export_git_bundle, source_files,
)
from dashboard.native.publication import empty_state, make_bundle, write_publication


class PublicRepositoryTests(unittest.TestCase):
    def test_no_management_code_private_paths_or_version_relationship(self):
        files, build_id = source_files()
        for name in ("app.py", "model.py", "developer_model.py", "collection.py", "factor_worker.py", "factors.py", "dashboard_page.py"):
            self.assertFalse(any(Path(path).name == name for path in files), name)
        for path, content in files.items():
            if Path(path).suffix in {".py", ".md", ".json", ".cmd", ".txt"}:
                self.assertIsNone(FORBIDDEN_TEXT.search(content.decode("utf-8")), path)
        protocol = files["dashboard/native/publication.py"].decode("utf-8")
        self.assertIn("class MarketFeed", protocol)
        for operation in ("write_publication", "encode_state", "make_bundle", "publish_formula", "save_config"):
            self.assertNotIn(operation, protocol)
        release = json.loads(files["release.json"])
        self.assertEqual(release["build_id"], build_id)
        for path, digest in release["files"].items():
            self.assertEqual(hashlib.sha256(files[path]).hexdigest(), digest)

    def test_export_has_an_independent_git_history_and_updates_from_shared_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = build_repository(Path(tmp) / "market")
            def git(*args):
                return subprocess.run(["git", "-C", str(target), *args], check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(git("rev-list", "--count", "HEAD"), "1")
            self.assertEqual(git("remote"), "")
            self.assertEqual(git("status", "--porcelain"), "")
            shared = ROOT / "native" / "theme.py"
            original = shared.read_text(encoding="utf-8")
            # Substitute the source in the exporter without editing the user's checkout.
            from dashboard.build_public_repository import public_python
            def source(name, **kwargs):
                value = public_python(name, **kwargs)
                if name == "theme.py": value += b"PUBLIC_BUILD_MARKER = 1\n"
                return value
            with patch("dashboard.build_public_repository.public_python", side_effect=source):
                build_repository(target)
            self.assertEqual(git("rev-list", "--count", "HEAD"), "2")
            self.assertIn("PUBLIC_BUILD_MARKER", (target / "dashboard/native/theme.py").read_text(encoding="utf-8"))
            self.assertEqual(shared.read_text(encoding="utf-8"), original)

    def test_refuses_to_overwrite_locally_modified_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = build_repository(Path(tmp) / "market")
            (target / "README.md").write_text("local modification", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "modified locally"):
                build_repository(target)
            self.assertEqual((target / "README.md").read_text(encoding="utf-8"), "local modification")

    def test_real_data_cannot_be_embedded_as_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "real.json"
            path.write_text(json.dumps({"demo": False}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "synthetic"):
                source_files(demo_path=path)

    def test_offline_bundle_checks_removed_files_in_earlier_git_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = build_repository(Path(tmp) / "market")
            readme = target / "README.md"
            original = readme.read_bytes()
            def record(message):
                subprocess.run(["git", "-c", "core.hooksPath=.git/empty-hooks", "-C", str(target),
                                "add", "README.md"], check=True, capture_output=True)
                subprocess.run(["git", "-c", "core.hooksPath=.git/empty-hooks", "-c", "commit.gpgsign=false",
                                "-c", "user.name=Delta1 Releases", "-c", "user.email=release@delta1.local",
                                "-C", str(target), "commit", "-m", message], check=True, capture_output=True)
            readme.write_bytes(b"developer workflow should not appear in a public history\n")
            record("Intermediate change")
            readme.write_bytes(original)
            record("Restore public documentation")
            with self.assertRaisesRegex(ValueError, "Private terminology"):
                export_git_bundle(target)

    def test_snapshot_demo_has_no_extra_private_payload_and_runs_after_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            states = [empty_state({"product": p, "frequency": f, "demo": True})
                      for p in ("IF", "IH", "IC", "IM") for f in ("1d", "1m", "1s")]
            bundle = make_bundle(states, demo=True)
            bundle["extra_private"] = "DO_NOT_EXPORT"
            demo = write_publication(root / "input", bundle)
            target = build_repository(root / "market", demo_path=demo)
            clone = root / "clone"
            offline = export_git_bundle(target, root / "market.bundle")
            subprocess.run(["git", "clone", "--quiet", str(offline), str(clone)], check=True, capture_output=True)
            demo_text = (clone / "dashboard/data/demo.json").read_text(encoding="utf-8")
            self.assertNotIn("DO_NOT_EXPORT", demo_text)
            env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT.parent / ".deps/dashboard_native")}
            for variable in ("DELTA1_DATA_ROOT", "SWHY_DELTA1_PUBLISH_ROOT"):
                env.pop(variable, None)
            command = [sys.executable, "-B", "-s", "-X", "utf8", "-m", "dashboard"]
            started = subprocess.run([*command, "--demo", "--startup-check"], cwd=clone, env=env,
                                     capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
            hidden = subprocess.run([*command, "--edition", "developer"], cwd=clone, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(hidden.returncode, 2)
            audit_files({str(p.relative_to(clone)).replace("\\", "/"): p.read_bytes()
                         for p in clone.rglob("*") if p.is_file() and ".git" not in p.parts and "runtime" not in p.parts})


if __name__ == "__main__":
    unittest.main()
