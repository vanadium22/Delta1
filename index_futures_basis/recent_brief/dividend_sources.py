"""Discover only declared local dividend inputs and the existing saved dashboard cache."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


def is_local(path):
    if str(path).startswith(("\\\\", "//")):
        return False
    if os.name == "nt" and Path(path).drive:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(Path(path).drive+"\\") != 4
    return True


def profile_files(paths):
    if not hasattr(paths, 'repo_root'):
        return []
    base = paths.repo_root/'dashboard/localsetting'
    return [base/p/'native.json' for p in ('app', 'numeric_excel', '')]


def configured_directories(module_root, config, paths):
    folders = config["dividends"].get("directories", [])
    if paths is None:
        return [str(Path(module_root)/p) for p in folders if is_local(p)]
    return [str(paths.resolve_module_setting(module_root, p, paths.dividend_inputs, ("inputs", "input")))
            for p in folders]


def local_directories(module_root, config, paths):
    candidates = configured_directories(module_root, config, paths)
    if paths is None:
        return candidates
    candidates.append(str(paths.dividend_inputs))
    if hasattr(paths, "dividend_archive"):
        candidates.append(str(paths.dividend_archive))
    # A supplied isolated DataPaths determines the scope; never walk ancestors.
    if hasattr(paths, "repo_root"):
        for file in profile_files(paths):
            try:
                settings = json.loads(file.read_text(encoding="utf-8-sig")) if file.is_file() else {}
            except (OSError, ValueError):
                settings = {}
            for key in ("dividend_root", "overview_dividend_file", "overview_dividend_source_dir"):
                value = settings.get(key)
                if not value or not is_local(value):
                    continue
                path = Path(value)
                path = path if path.is_absolute() else paths.repo_root/path
                if path.suffix.lower() == ".xlsx":
                    path = path.parent
                candidates.append(str(path))
            cache = Path(settings.get("overview_dividend_cache") or file.parent/"overview_dividends")
            cache = cache if cache.is_absolute() else paths.repo_root/cache
            if is_local(cache):
                candidates.append(str(cache))
                raw = cache/"raw"
                try:
                    candidates.extend(str(day) for day in sorted(raw.iterdir())
                                      if re.fullmatch(r"\d{4}-\d{2}-\d{2}",day.name) and day.is_dir())
                except OSError:
                    pass
    return list(dict.fromkeys(value for value in candidates if is_local(value)))


def history_paths(module_root, config, paths, explicit=None):
    if explicit:
        source = Path(explicit).resolve()
        directories = [source] if source.is_dir() else []
        if not directories:
            return [source], []
        recursive = {source}
    else:
        directories = list(map(Path, local_directories(module_root, config, paths)))
        recursive = set(map(Path, configured_directories(module_root, config, paths)))
        recursive.update(Path(folder) for key in ("dividend_inputs", "dividend_archive")
                         if (folder := getattr(paths, key, None)) is not None)
    files = []
    for directory in directories:
        if directory in recursive:
            files.extend(sorted(directory.rglob("*.xlsx")))
        else:
            files.extend(sorted(directory.glob("*.xlsx")))
            files.extend(sorted((directory / "history").rglob("*.xlsx")))
    sources = list(dict.fromkeys(p.resolve() for p in files if not p.name.startswith(("~$", "."))))
    stores = list(dict.fromkeys(p / "records.sqlite" for p in directories))
    return sources, stores
