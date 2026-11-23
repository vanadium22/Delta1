"""Collect dated dividend inputs from the company share on explicit request."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from dashboard.marketdata.bars import _atomic_bytes
from dashboard.marketdata.overview_dividend_sync import read_json, source_directories
from dashboard.marketdata.overview_windpy import run_readonly_worker
from ..analytics import read_continuous_snapshot
from .dividend_history import WORKBOOK_ERRORS
from .dividend_sources import profile_files


def share_settings(paths, override):
    for profile in profile_files(paths):
        try:
            config = json.loads(profile.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(config, dict):
            break
    else:
        config = {}
    if override:
        config["overview_dividend_source_dir"] = override
    return config


def read_share(directory, stage, options):
    request = dict(options, directories=[directory], staging=str(stage))
    command = [sys.executable, "-B", "-X", "utf8", "-m", "dashboard.marketdata.overview_dividend_sync", "--reader"]
    try:
        result = run_readonly_worker(command, request, stage/"stop", timeout=45)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    partial = read_json(stage/"progress.json")
    return {**partial, "complete": False, "reader_failed": True}


def collect(paths, config, start, end, override, scratch, write):
    settings = share_settings(paths, override)
    directories = source_directories(settings, start, end)
    archive = paths.dividend_archive/"share_history"
    known = ({p.name for p in archive.iterdir() if len(p.name) == 64 and any(p.glob("*.xlsx"))}
             if archive.is_dir() else set())
    workbook_config = {**config["dividends"], "allow_missing_values": True}
    write(f"从公司公盘补收 {start} 至 {end} 的分红 Excel")
    if not directories:
        write("  公盘来源为空，继续使用本地数据")
    for directory in directories:
        with TemporaryDirectory(prefix="share-", dir=scratch) as temp:
            options = {"start": start, "end": end, "known_hashes": sorted(known), "budget": 30,
                       "pattern": settings.get("overview_dividend_pattern") or "*基差情况*.xlsx"}
            fetched = read_share(directory, Path(temp), options)
            imported, errors = [], []
            for item in fetched.get("files", []):
                if item["path"] is None:
                    continue
                path = Path(item["path"])
                try:
                    raw = path.read_bytes()
                    rows, info = read_continuous_snapshot(path, workbook_config,
                                                          include_contracts=True, source_bytes=raw)
                    day, digest = info["snapshot_date"], info["sha256"]
                    if digest != item["sha256"] or not rows.dividend_points.notna().any():
                        raise ValueError("文件哈希不符或 G 列没有可用分红点数")
                    if start <= day <= end and digest not in known:
                        _atomic_bytes(archive/digest/path.name, raw)
                        known.add(digest)
                        imported.append(day)
                except WORKBOOK_ERRORS as exc:
                    errors.append(f"{path.name} {type(exc).__name__}: {exc}")
            write(f"  {directory}  候选 {fetched.get('matched', 0)} 份  新增 {len(imported)} 份")
            if imported:
                write("    新归档表日  " + "、".join(sorted(set(imported))))
            if not fetched.get("complete"):
                write("    公盘读取未完成，继续生成简报")
            for error in fetched.get("errors", []):
                write(f"    公盘读取提示  {error['stage']} {error['error_type']} {error.get('winerror') or ''}")
            for error in errors:
                write(f"    跳过 Excel  {error}")
