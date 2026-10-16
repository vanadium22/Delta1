"""Copy-once migration. Originals are retained; conflicts never overwrite data."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from .io import atomic_json, file_lock, portable_manifest, resolved_manifest, sha256
from .paths import DataPaths

MODULES = ("index_futures_basis", "script_making", "securities_lending")


def linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _files(root):
    if not root.is_dir():
        return []
    result = []
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = [name for name in folders if not linked(Path(directory) / name)]
        for name in sorted(files):
            path = Path(directory) / name
            if not linked(path) and not name.startswith("~$") and not name.endswith((".tmp", ".lock", "-wal", "-shm", "-journal")):
                result.append(path)
    return sorted(result)


def _database_digest(connection):
    digest = hashlib.sha256()
    for line in connection.iterdump():
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _copy_database(source, target):
    with file_lock(source.with_suffix(".lock"), timeout=0):
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old:
            old.execute("BEGIN")
            original = _database_digest(old)
            if target.exists():
                with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as new:
                    if _database_digest(new) != original:
                        raise ValueError(f"迁移目标已存在不同数据库，保留双方：{target}")
                return {"logical_sha256": original, "copied": False}
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                with closing(sqlite3.connect(temporary)) as new:
                    old.backup(new)
                    if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or _database_digest(new) != original:
                        raise ValueError(f"数据库迁移校验失败：{source}")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return {"logical_sha256": original, "copied": True}


def copy_verified(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        return {"source": str(source), "destination": str(target), "copied": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".sqlite":
        detail = _copy_database(source, target)
    else:
        original = sha256(source)
        if target.exists():
            if sha256(target) != original:
                raise ValueError(f"迁移目标已存在不同内容，保留双方：{target}")
            detail = {"copied": False, "sha256": original}
        else:
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                before = source.stat()
                shutil.copy2(source, temporary)
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or sha256(temporary) != original or sha256(source) != original:
                    raise ValueError(f"迁移期间源文件变化：{source}")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            detail = {"copied": True, "sha256": original}
    return {"source": str(source), "destination": str(target), "bytes": target.stat().st_size, **detail}


def _manifest(source, target, old_base, new_base):
    old = json.loads(source.read_text(encoding="utf-8-sig"))
    value = resolved_manifest(old, old_base)
    files = value.get("files", [])
    entries = files.values() if isinstance(files, dict) else files
    for entry in entries:
        original = Path(entry["path"]).resolve()
        # Reject a corrupt/foreign pointer rather than silently accepting a different file.
        relative = original.relative_to(old_base.resolve())
        local = (new_base / relative).resolve()
        if not local.is_relative_to(new_base.resolve()) or not local.is_file() or sha256(local) != entry["sha256"]:
            raise ValueError(f"旧清单文件校验失败：{source} -> {original}")
        entry["path"] = str(local)
    value = portable_manifest(value, new_base)
    if target.exists():
        current = json.loads(target.read_text(encoding="utf-8-sig"))
        if current != value:
            raise ValueError(f"目标已有不同清单，保留双方：{target}")
    else:
        atomic_json(target, value)
    return {"source": str(source), "destination": str(target), "bytes": target.stat().st_size,
            "source_sha256": sha256(source), "sha256": sha256(target), "path_rebased": True}


def migration_plan(module, root, paths):
    """Only operational inputs; QA, legacy scripts and generated exports stay put."""
    root = Path(root).resolve()
    moves = []
    def tree(source, destination, *, manifest=None, industry=None):
        for file in _files(source):
            relative = file.relative_to(source)
            dest = destination / relative
            if industry is not None and file.name == "industries.json":
                dest = industry / relative
            moves.append({"source": file, "destination": dest,
                          "manifest": file.name == manifest, "old_base": source, "new_base": destination})
    if module == "index_futures_basis":
        for mode in ("wind", "offline", "demo"):
            base = root / "data" / mode
            # Move source archives with their owning database; shared dividends have one archive.
            for name in ("market.sqlite", "config.local.json"):
                if (base / name).is_file():
                    moves.append({"source": base / name, "destination": paths.basis(mode) / name, "manifest": False})
            tree(base / "sources", paths.basis(mode) / "sources")
            archive = paths.demo(module) / "dividends" if mode == "demo" else paths.dividend_archive
            tree(base / "dividends", archive)
        legacy = root.parent / "research" / "index_futures_basis"
        for source in (root / "inputs", root / "input", legacy / "inputs", legacy / "input"):
            for file in _files(source):
                if file.suffix.lower() in {".xlsx", ".json"}:
                    moves.append({"source": file, "destination": paths.dividend_inputs / file.name, "manifest": False})
    elif module == "script_making":
        tree(root / "data" / "reports", paths.reports, manifest="manifest.json")
        for file in (root / "materials").glob("*模板*.xlsx"):
            moves.append({"source": file, "destination": paths.root / "templates" / module / file.name, "manifest": False})
    elif module == "securities_lending":
        for mode in ("live", "demo"):
            source, dest = root / "data" / mode, paths.lending(mode == "demo")
            tree(source, dest, manifest="latest.json", industry=paths.industries(mode == "demo"))
        tree(root / "data" / "demo_source", paths.demo(module) / "source")
        # Demo settings/contact notes belong to the demo application, outside dated snapshots.
        for move in moves:
            if move["source"].parent == root / "data" / "demo":
                move["destination"] = paths.demo(module) / move["source"].name
    else:
        raise ValueError(f"Unknown module: {module}")
    # Copy data before publishing any rebased manifest.
    return sorted(moves, key=lambda m: bool(m["manifest"]))


def ensure_migrated(module, root, paths=None):
    root = Path(root).resolve()
    paths = paths or DataPaths.for_module(root)
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    marker = paths.root / "_migrations" / f"{module}-{identity}.json"
    with file_lock(paths.root / "_migrations" / (module + ".lock")):
        if marker.exists():
            return json.loads(marker.read_text(encoding="utf-8"))
        entries = []
        for move in migration_plan(module, root, paths):
            if move["manifest"]:
                entries.append(_manifest(move["source"], move["destination"], move["old_base"], move["new_base"]))
            else:
                entries.append(copy_verified(move["source"], move["destination"]))
        result = {"version": 1, "module": module, "original_root": str(root), "data_root": str(paths.root),
                  "completed_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                  "originals_retained": True, "files": entries}
        atomic_json(marker, result)
        return result
