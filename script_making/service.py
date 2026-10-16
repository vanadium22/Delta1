"""Local report operations shared by the desktop app and the optional JSON API."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

from .query import query_table, read_table, sheet_names
from .storage import (REPORTS, ReportError, Settings, catalog, identify, report_path,
                      save_files, timestamp)


class ReportService:
    def __init__(self, root: Path):
        self.settings = Settings(root)
        self.lock = threading.Lock()
        self.job = {"state": "idle"}

    def catalog(self):
        return catalog(self.settings)

    def sheets(self, kind: str, day: str):
        return sheet_names(report_path(self.settings, kind, day))

    def query(self, request: dict):
        kind, day = request["kind"], request["date"]
        path = report_path(self.settings, kind, day)
        sheet = request.get("sheet") or REPORTS[kind]["sheet"]
        result = query_table(read_table(path, sheet), request)
        result.update(date=day, sheet=sheet, filename=path.name)
        return result

    def update_settings(self, values: dict):
        with self.lock:
            if self.job["state"] == "running":
                raise ReportError("同步期间不能修改目录，请稍后再试。")
            return self.settings.update(values)

    def import_files(self, paths: list[Path]):
        groups = {}
        for path in paths:
            kind, day = identify(path.name)
            if not 0 < path.stat().st_size <= 150 * 1024 * 1024:
                raise ReportError("Excel 文件应大于 0 且不超过 150 MB。")
            if kind in groups.setdefault(day, {}):
                raise ReportError(f"{day} 选择了重复报表，请每种报表只选择一份。")
            groups[day][kind] = path
        if not groups:
            raise ReportError("请选择需要导入的 Excel。")
        with self.lock:
            if self.job["state"] == "running":
                raise ReportError("正在同步，请完成后再导入。")
            return [save_files(self.settings.data_path(), sources, day, "手动导入")
                    for day, sources in sorted(groups.items())]

    def sync_status(self):
        with self.lock:
            return dict(self.job)

    def start_sync(self):
        with self.lock:
            if self.job["state"] == "running":
                return dict(self.job)
            if not self.settings.get().get("source_root"):
                raise ReportError("请先在「数据与同步」中设置共享来源目录。")
            self.job = {"state": "running", "started_at": timestamp()}
        threading.Thread(target=self._sync, daemon=True).start()
        return self.sync_status()

    def _sync(self):
        try:
            executable = Path(sys.executable)
            if executable.name.lower() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            completed = subprocess.run(
                [str(executable), "-X", "utf8", "-m", "script_making.sync_worker",
                 "--root", str(self.settings.root)],
                cwd=Path(__file__).parent.parent, capture_output=True,
                text=True, encoding="utf-8", timeout=45,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result = json.loads(completed.stdout)
            if not result.get("ok"):
                raise ReportError(result.get("error", "同步失败。"))
            state = {"state": "success", "result": result["result"], "finished_at": timestamp()}
        except subprocess.TimeoutExpired:
            state = {"state": "error", "error": "共享目录访问超过 45 秒。请连接公司网络后重试，本地文件仍可查询。"}
        except (ReportError, OSError, ValueError) as exc:
            state = {"state": "error", "error": str(exc) if isinstance(exc, ReportError)
                     else "同步进程失败，请检查 Python 环境和来源目录。"}
        with self.lock:
            self.job = state
