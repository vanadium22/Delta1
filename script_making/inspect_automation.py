"""Read-only company handoff inventory. Does not instantiate Settings or migrate data."""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def inspect_project(root):
    from shared_data.paths import DataPaths
    root = Path(root).resolve()
    values = {}
    path = root / "config.local.json"
    if path.exists():
        values = json.loads(path.read_text(encoding="utf-8-sig"))
    paths = DataPaths.for_module(root)
    base = paths.resolve_module_setting(root, os.environ.get("SCRIPT_MAKING_DATA", values.get("data_dir", "@shared")),
                                        paths.reports, ("data/reports",))
    # Deliberately do not enumerate a network destination or open any workbook.
    network_data = str(base).startswith(("\\\\", "//"))
    files = [] if network_data or not base.is_dir() else [str(p.relative_to(base)) for p in base.glob("*/manifest.json")]
    evidence = {}
    if not network_data:
        for key, status_path in (("pnl", base / "downloads/pnl/status.json"),
                                 ("strategy", base / "downloads/strategy/status.json"),
                                 ("daily_job", base / "statistics/daily_runs/latest.json")):
            if status_path.is_file():
                try:
                    content = json.loads(status_path.read_text(encoding="utf-8"))
                    evidence[key] = {field: content.get(field) for field in ("state", "started_at", "finished_at", "elapsed_seconds")}
                except (OSError, ValueError, AttributeError):
                    evidence[key] = {"state": "unreadable"}
    return {
        "mode": "inspection_only", "time_zone": "Asia/Shanghai",
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "module_directory": str(root), "working_directory": str(root.parent),
        "interpreter_observed_on_this_computer": sys.executable,
        "company_interpreter": "待在公司执行本检查确认；源码候选为 D:\\conda\\envs\\swhy_delta1\\python.exe",
        "local_config_present": path.is_file(),
        "sources_configured": {key: bool(os.environ.get("SCRIPT_MAKING_SOURCE", values.get(key)) if key == "source_root" else values.get(key))
                               for key in ("source_root", "pnl_source", "strategy_source")},
        "data_directory": str(base), "network_data_enumeration_skipped": network_data,
        "local_pair_manifest_count": len(files),
        "observed_execution_metadata": evidence,
        "entries": {name: (root / name).is_file() for name in ("start.cmd", "run_daily.cmd", "daily_job.py", "sync_worker.py")},
        "internal_triggers": ["打开桌面App自动同步一次", "界面手动同步", "单次CLI显式 --run"],
        "internal_calendar_scheduler": False,
        "existing_company_schedule": {"exists": "用户确认存在", "name": None, "enabled": None,
                                      "next_run": None, "last_run": None, "owner": "待公司 Work Automation 对话核实"},
        "environment_names": ["REPORT_APP_PYTHON", "SWHY_DELTA1_PYTHON", "SCRIPT_MAKING_SOURCE",
                              "SCRIPT_MAKING_DATA", "DELTA1_DATA_ROOT", "DELTA1_OUTPUTS_ROOT", "QT_QPA_PLATFORM"],
        "side_effects": {"sync": False, "workbook_read": False, "send_email": False,
                         "modify_schedule": False, "install_environment": False},
    }


def inspect_windows_tasks():
    if os.name != "nt":
        return {"status": "unavailable", "tasks": []}
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$rows = @(Get-ScheduledTask | Where-Object {
    ($_.TaskName -match '日报|script_making') -or
    (($_.Actions.Execute -join ' ') -match 'script_making') -or
    (($_.Actions.Arguments -join ' ') -match 'script_making')
} | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    [PSCustomObject]@{name=$_.TaskName; path=$_.TaskPath; state=[string]$_.State;
        enabled=$_.Settings.Enabled; next_run=[string]$info.NextRunTime;
        last_run=[string]$info.LastRunTime; last_result=$info.LastTaskResult}
})
ConvertTo-Json -Depth 5 -InputObject $rows -Compress
'''
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, encoding="utf-8", timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            return {"status": "unavailable", "reason": "当前账号无法读取计划任务，需公司核查。", "tasks": []}
        return {"status": "read_only", "scope": "仅当前电脑；匹配日报/script_making，不能证明不存在其他命名的入口", "tasks": json.loads(result.stdout)}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "tasks": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读检查日报自动化接入信息，不同步、不创建调度")
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--windows-tasks", action="store_true", help="只读查询当前电脑匹配的Windows计划任务")
    args = parser.parse_args(argv)
    try:
        report = inspect_project(args.root)
        if args.windows_tasks:
            report["windows_tasks"] = inspect_windows_tasks()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"mode": "inspection_only", "error_type": type(exc).__name__, "message": "配置检查失败，请核对本机配置。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
