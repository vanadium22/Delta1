"""One-shot external-scheduler adapter. Defaults to inspection; never sends mail."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from uuid import uuid4

from .inspect_automation import inspect_project, inspect_windows_tasks


def sync_once(root, as_of, kind):
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    command = [str(executable), "-X", "utf8", "-m", "script_making.sync_worker", "--root", str(root), "--as-of", as_of.isoformat()]
    if kind != "pair":
        command += ["--kind", kind]
    environment = os.environ.copy()
    for name in ("SCRIPT_MAKING_SOURCE", "SCRIPT_MAKING_DATA", "DELTA1_DATA_ROOT", "DELTA1_OUTPUTS_ROOT"):
        environment.pop(name, None)
    result = subprocess.run(command, cwd=Path(__file__).parent.parent, capture_output=True, text=True,
                            encoding="utf-8", timeout=45 if kind == "pair" else 120, env=environment,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    value = json.loads(result.stdout)
    if result.returncode or not value.get("ok"):
        raise RuntimeError(value.get("error", "同步子进程失败"))
    return value["result"]


def run_once(root, as_of, *, local_only=False):
    from shared_data.io import file_lock
    from .service import ReportService
    from .statistics import build_snapshot, load_config
    from .storage import Settings, atomic_json, sha256, timestamp
    settings = Settings(root)
    values = settings.get()
    base = settings.data_path(values)
    root = settings.root
    runs = base / "statistics" / "daily_runs"
    run_id = uuid4().hex
    record = {"run_id": run_id, "state": "running", "started_at": timestamp(),
              "as_of": as_of.isoformat(), "local_only": local_only, "sync": {}, "send_email": False}
    started = time.monotonic()

    class FrozenSettings:
        def __init__(self):
            self.root = root

        def get(self):
            return dict(values)

        def data_path(self, ignored=None):
            return base

    try:
        with file_lock(base / "statistics" / ".daily_job.lock", timeout=0):
            atomic_json(runs / (run_id + ".json"), record)
            try:
                if not local_only:
                    cache = root / "cache" / "daily_jobs"
                    cache.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(dir=cache) as temporary:
                        frozen_root = Path(temporary)
                        atomic_json(frozen_root / "config.local.json", {**values, "data_dir": str(base)})
                        for kind in ("pair", "pnl", "strategy"):
                            try:
                                result = sync_once(frozen_root, as_of, kind)
                                record["sync"][kind] = {"state": "partial" if result.get("errors") else "success", "result": result}
                            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                                record["sync"][kind] = {"state": "error", "error": str(exc)}
                            atomic_json(runs / (run_id + ".json"), record)
                    if any(value["state"] != "success" for value in record["sync"].values()):
                        record.update(state="incomplete", reason="存在未完成的同步，本次不发布可能陈旧的邮件附件。")
                        return 2, record
                service = ReportService(root)
                service.settings = FrozenSettings()
                catalog = service.query_catalog()
                selections = {kind: next((entry["date"] for entry in catalog["dates"]
                                         if kind in entry["files"] and entry["date"] < as_of.isoformat()), None)
                              for kind in ("pnl", "swap", "strategy")}
                if not local_only:
                    selections = {"swap": record["sync"]["pair"]["result"].get("date"),
                                  "pnl": record["sync"]["pnl"]["result"].get("source_latest"),
                                  "strategy": record["sync"]["strategy"]["result"].get("source_latest")}
                    if not all(selections.values()):
                        record.update(state="incomplete", reason="本次未发现完整的公盘来源日期，不用旧本地文件代替。")
                        return 2, record
                selections["previous"] = next((entry["date"] for entry in catalog["dates"]
                                                if "pnl" in entry["files"] and selections["pnl"]
                                                and entry["date"] < selections["pnl"]), None)
                config = load_config(root)
                snapshot = build_snapshot(service, selections, config)
                record["statistics_record"] = str(base / "statistics" / "records" / (snapshot["id"] + ".json"))
                record["report_dates"] = selections
                if (snapshot["errors"] or not snapshot["pnl"] or snapshot["pnl"]["change"] is None
                        or any(history["errors"] for history in snapshot["history"].values())):
                    record.update(state="incomplete", reason="统计或上期数值不完整；已记录诊断，本次不生成可发送草稿。")
                    return 2, record
                identity = {key: value for key, value in snapshot.items() if key not in ("id", "created_at")}
                fingerprint = hashlib.sha256(json.dumps({"version": 2, "snapshot": identity}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                completed = runs / "completed" / (fingerprint + ".json")
                if completed.exists():
                    try:
                        previous = json.loads(completed.read_text(encoding="utf-8"))
                        folder = Path(previous["export_directory"])
                        required = {"pnl1.png", "risk.png",
                                    "邮件草稿.eml", "邮件正文.txt", "统计记录.json", "邮件设置.json"}
                        files = previous["files"]
                        if (isinstance(files, dict) and required.issubset(files)
                                and all(Path(name).name == name for name in files)
                                and folder.resolve().is_relative_to((base / "statistics" / "exports").resolve())
                                and not (folder / "导出未完成.txt").exists() and all(
                                (folder / name).is_file() and sha256(folder / name) == digest
                                for name, digest in files.items())):
                            record.update(state="reused", export_directory=str(folder), fingerprint=fingerprint)
                            return 0, record
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                # Qt loads only in explicit run mode; no GUI, external scheduler or mail transport.
                os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
                from PySide6.QtWidgets import QApplication
                from PySide6.QtGui import QFontDatabase
                from .statistics_export import export_bundle, render_pages
                app = QApplication.instance() or QApplication([])
                font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
                if font.is_file():
                    QFontDatabase.addApplicationFont(str(font))
                folder = export_bundle(base / "statistics" / "exports", snapshot, render_pages(snapshot), config)
                atomic_json(completed, {"export_directory": str(folder), "files": {p.name: sha256(p) for p in folder.iterdir() if p.is_file()}})
                record.update(state="success", export_directory=str(folder), fingerprint=fingerprint)
                return 0, record
            except Exception as exc:
                record.update(state="failed", error_type=type(exc).__name__, reason=str(exc))
                return 1, record
            finally:
                record["finished_at"] = timestamp()
                record["elapsed_seconds"] = round(time.monotonic() - started, 3)
                atomic_json(runs / (run_id + ".json"), record)
                atomic_json(runs / "latest.json", record)
    except TimeoutError:
        return 3, {"state": "busy", "reason": "已有单次日报任务运行，本次未重复启动。", "send_email": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="单次日报同步、统计和邮件草稿；默认仅检查，不内置调度")
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true", help="只读检查，默认模式")
    mode.add_argument("--run", action="store_true", help="显式执行一次同步、统计与草稿导出，不发送邮件")
    parser.add_argument("--as-of", type=date.fromisoformat, help="北京时间截止日期，不含该日，默认今天")
    parser.add_argument("--local-only", action="store_true", help="仅与 --run 合用，使用已有本地文件，不访问共享来源")
    parser.add_argument("--windows-tasks", action="store_true", help="仅检查模式，只读查看当前电脑匹配的Windows计划")
    args = parser.parse_args(argv)
    if args.local_only and not args.run:
        parser.error("--local-only 需要显式 --run")
    if args.windows_tasks and args.run:
        parser.error("--windows-tasks 只能用于检查模式")
    try:
        if not args.run:
            result = inspect_project(args.root)
            if args.windows_tasks:
                result["windows_tasks"] = inspect_windows_tasks()
            code = 0
        else:
            from .storage import today
            code, result = run_once(args.root, args.as_of or today(), local_only=args.local_only)
        # Detailed failure diagnostics stay in local run records; console output
        # excludes source paths, addresses and spreadsheet values.
        output = result if not args.run else {key: result[key] for key in
                                             ("state", "run_id", "export_directory", "statistics_record", "elapsed_seconds", "send_email") if key in result}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError) as exc:
        print(json.dumps({"state": "failed", "error_type": type(exc).__name__, "send_email": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
