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


def local_directories(module_root, config, paths):
    cfg = config["dividends"]
    if paths is None:
        return [str(Path(module_root)/p) for p in cfg.get("directories", []) if is_local(p)]
    candidates = [str(paths.resolve_module_setting(module_root,p,paths.dividend_inputs,("inputs","input")))
                  for p in cfg.get("directories", [])]
    candidates.append(str(paths.dividend_inputs))
    # A supplied isolated DataPaths determines the scope; never walk ancestors.
    if hasattr(paths, "repo_root"):
        dashboard = paths.repo_root/"dashboard"
        local = dashboard/"localsetting"
        file = local/"native.json"
        try:
            settings = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
        except (OSError, ValueError):
            settings = {}
        for key in ("dividend_root", "overview_dividend_file"):
            value = settings.get(key)
            if not value or not is_local(value):
                continue
            path = Path(value)
            path = path if path.is_absolute() else dashboard/path
            if path.suffix.lower() == ".xlsx":
                # Only expose that file's directory, still validating workbook B1/B/G.
                path = path.parent
            candidates.append(str(path))
        cache = Path(settings.get("overview_dividend_cache") or local/"overview_dividends")
        cache = cache if cache.is_absolute() else dashboard/cache
        if is_local(cache):
            raw = cache/"raw"
            try:
                candidates.extend(str(day) for day in raw.iterdir()
                                  if re.fullmatch(r"\d{4}-\d{2}-\d{2}",day.name) and day.is_dir())
            except OSError:
                pass
    return list(dict.fromkeys(value for value in candidates if is_local(value)))
