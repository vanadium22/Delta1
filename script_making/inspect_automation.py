"""Read-only company handoff inventory. Does not instantiate Settings or migrate data."""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
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


def task_query_script(matches=()):
    terms = base64.b64encode(json.dumps(['日报', 'script_making', 'daily_report', *matches],
                                      ensure_ascii=False).encode('utf-8')).decode('ascii')
    # Task Scheduler COM avoids loading the ScheduledTasks CIM module. Only
    # Connect/GetFolder/GetFolders/GetTasks and property reads are used.
    # https://learn.microsoft.com/windows/win32/taskschd/displaying-task-names-and-state--scripting-
    return "$terms = ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + terms + "')))\n" + r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$service = New-Object -ComObject Schedule.Service
$service.Connect()
$folders = [Collections.Generic.Queue[object]]::new()
$folders.Enqueue($service.GetFolder('\'))
$rows = [Collections.Generic.List[object]]::new()
$errors = 0
$count = 0
while ($folders.Count) {
    $folder = $folders.Dequeue()
    $count++
    try { foreach ($child in $folder.GetFolders(0)) { $folders.Enqueue($child) } }
    catch { $errors++ }
    try { $tasks = $folder.GetTasks(1) } # Include hidden tasks that this account can read.
    catch { $errors++; continue }
    foreach ($task in $tasks) {
        try {
            [xml]$xml = $task.Xml
            $actions = $xml.SelectNodes('//*[local-name()="Actions"]/*')
            $fields = @([pscustomobject]@{field='task_path'; value=[string]$task.Path})
            $actionDetails = @(foreach ($action in $actions) {
                if ($action.LocalName -eq 'Exec') {
                    $fields += [pscustomobject]@{field='command'; value=[string]$action.Command}
                    $fields += [pscustomobject]@{field='arguments'; value=[string]$action.Arguments}
                    $fields += [pscustomobject]@{field='working_directory'; value=[string]$action.WorkingDirectory}
                    # Arguments can contain credentials or inline scripts. Only
                    # known search terms are returned, never their raw values.
                    [pscustomobject]@{type='Exec'; command=[string]$action.Command;
                        working_directory=[string]$action.WorkingDirectory}
                } else {
                    $fields += [pscustomobject]@{field='other_action'; value=[string]$action.InnerText}
                    [pscustomobject]@{type=$action.LocalName}
                }
            })
            $reasons = @(foreach ($field in $fields) {
                foreach ($term in $terms) {
                    if ($term -and $field.value.IndexOf($term, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                        [pscustomobject]@{field=$field.field; term=$term}
                    }
                }
            })
            if (-not $reasons.Count) { continue }
            $principal = $xml.SelectSingleNode('//*[local-name()="Principal"]')
            $triggers = @($xml.SelectNodes('//*[local-name()="Triggers"]/*') | ForEach-Object {
                [pscustomobject]@{type=$_.LocalName; start=[string]$_.StartBoundary;
                    end=[string]$_.EndBoundary; enabled=([string]$_.Enabled -ne 'false');
                    days_of_week=@($_.ScheduleByWeek.DaysOfWeek.ChildNodes | ForEach-Object { $_.LocalName });
                    interval=[string]$_.Repetition.Interval}
            })
            $rows.Add([pscustomobject]@{id=$task.Path; name=$task.Name;
                path=$folder.Path; state=[int]$task.State; enabled=[bool]$task.Enabled;
                user=[string]$principal.UserId; next_run=[string]$task.NextRunTime;
                last_run=[string]$task.LastRunTime; last_result=$task.LastTaskResult; triggers=$triggers;
                actions=$actionDetails; match_basis=$reasons;
                name_only_match=(@($reasons | Where-Object { $_.field -ne 'task_path' }).Count -eq 0)})
        } catch { $errors++ }
    }
}
[pscustomobject]@{status=$(if ($errors) {'partial'} else {'read_only'});
    complete=($errors -eq 0); unreadable_count=$errors; searched_folders=$count;
    tasks=@($rows.ToArray())} | ConvertTo-Json -Depth 8 -Compress
'''


def unavailable(reason):
    messages = {'timeout': '计划任务查询超时，未能核实；请保留此输出，不要据此新增或启用计划。',
                'interrupted': '用户中断了计划查询，已保留项目检查信息；计划状态仍未核实。',
                'query_failed': '当前账号未能完成计划查询，需核对服务或读取权限。',
                'invalid_output': '计划查询输出不完整或无效，不能据此认定没有计划。',
                'not_windows': '当前不是 Windows，无法核实公司计划。'}
    return {'status': 'unavailable', 'complete': False, 'reason_code': reason,
            'reason': messages[reason], 'tasks': []}


def capture_task_query(command, timeout=20):
    """Bound both query and cleanup, without communicate()'s pipe reader threads."""
    process = None
    result = unavailable('query_failed')
    # Temporary file capture also avoids waiting for inherited pipes to close.
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            code = process.wait(timeout=timeout)
            if code == 0:
                output.seek(0)
                raw = output.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('oversized inventory')
                value = json.loads(raw.decode('utf-8-sig'))
                if (not isinstance(value, dict) or value.get('status') not in ('read_only', 'partial')
                        or type(value.get('complete')) is not bool or not isinstance(value.get('tasks'), list)
                        or value['complete'] != (value['status'] == 'read_only')):
                    raise ValueError('invalid inventory')
                result = value
        except subprocess.TimeoutExpired:
            result = unavailable('timeout')
        except KeyboardInterrupt:
            result = unavailable('interrupted')
        except (ValueError, UnicodeError):
            result = unavailable('invalid_output')
        except OSError:
            result = unavailable('query_failed')
        finally:
            if process is not None and process.poll() is None:
                try:
                    # Only the child created above, never taskkill by process name.
                    process.kill()
                    process.wait(timeout=2)
                    result['query_process_stopped'] = True
                except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                    result['query_process_stopped'] = False
    return result


def inspect_windows_tasks(matches=(), *, progress=True):
    if os.name != 'nt':
        return unavailable('not_windows')
    if progress:
        print('正在只读查询 Windows 计划任务（最多等待 20 秒；失败仍返回项目检查信息）…', file=sys.stderr, flush=True)
    script = base64.b64encode(task_query_script(matches).encode('utf-16le')).decode('ascii')
    try:
        result = capture_task_query(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', script])
    except (OSError, KeyboardInterrupt):
        result = unavailable('query_failed')
    result['scope'] = '仅当前电脑、当前账号可读的匹配任务（含隐藏任务）；不证明不存在其他调度入口。'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读检查日报自动化接入信息，不同步、不创建调度")
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--windows-tasks", action="store_true", help="只读查询当前电脑匹配的Windows计划任务")
    mode.add_argument('--tasks-only', action='store_true', help='只查询计划，不读取项目配置')
    parser.add_argument('--match', action='append', default=[], help='附加匹配路径；只在内存匹配，不打印动作参数')
    args = parser.parse_args(argv)
    try:
        report = inspect_windows_tasks(args.match, progress=False) if args.tasks_only else inspect_project(args.root)
        if args.windows_tasks:
            report["windows_tasks"] = inspect_windows_tasks(args.match)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"mode": "inspection_only", "error_type": type(exc).__name__, "message": "配置检查失败，请核对本机配置。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
