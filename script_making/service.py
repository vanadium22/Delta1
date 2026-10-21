"""Local report operations shared by the desktop app and the optional JSON API."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

from .query import query_table, read_table, sheet_names
from .storage import (REPORTS, ReportError, Settings, catalog, identify, report_path,
                      save_files, timestamp, atomic_json)
from .downloads import DOWNLOADS, archive_path, local_files

ALL_REPORTS = {**REPORTS, **DOWNLOADS}


class ReportService:
    def __init__(self, root: Path):
        self.settings = Settings(root)
        self.lock = threading.Lock()
        self.job = {"state": "idle"}
        self.download_jobs = {kind: {"state": "idle"} for kind in DOWNLOADS}

    def downloads_running(self):
        with self.lock:
            return any(job["state"] == "running" for job in self.download_jobs.values())

    def download_status(self, kind):
        with self.lock:
            return dict(self.job if kind in REPORTS else self.download_jobs[kind])

    def download_catalog(self, kind):
        if kind in REPORTS:
            data = self.catalog()
            files = []
            for entry in data["dates"]:
                if kind in entry["files"]:
                    info = dict(entry["files"][kind], date=entry["date"])
                    info["size"] = Path(info["path"]).stat().st_size
                    files.append(info)
            return {"saved_dir": data["saved_dir"], "files": files, "status": self.sync_status()}
        base = archive_path(self.settings, kind)
        state = self.download_status(kind)
        if state["state"] == "idle":
            try:
                state = json.loads((base / "status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return {"saved_dir": str(base), "files": local_files(base, kind), "status": state}

    def start_download(self, kind):
        if kind not in DOWNLOADS:
            raise ReportError("未知下载来源。")
        with self.lock:
            if self.download_jobs[kind]["state"] == "running":
                return dict(self.download_jobs[kind])
            self.download_jobs[kind] = {"state": "running", "started_at": timestamp()}
        threading.Thread(target=self._sync, kwargs={"kind": kind}, daemon=True).start()
        return self.download_status(kind)

    def catalog(self):
        return catalog(self.settings)

    def query_catalog(self):
        data = self.catalog()
        dates = {entry["date"]: entry for entry in data["dates"]}
        for kind in DOWNLOADS:
            for entry in local_files(archive_path(self.settings, kind), kind):
                day = dates.setdefault(entry["date"], {"date": entry["date"], "complete": False, "files": {}})
                day["files"][kind] = dict(entry, origin="本地已保存日报")
        data["dates"] = sorted(dates.values(), key=lambda entry: entry["date"], reverse=True)
        data["reports"] = ALL_REPORTS
        return data

    def path_for(self, kind, day):
        if kind in REPORTS:
            return report_path(self.settings, kind, day)
        if kind not in DOWNLOADS:
            raise ReportError("未知报表类型。")
        entry = next((item for item in local_files(archive_path(self.settings, kind), kind)
                      if item["date"] == day), None)
        if entry is None:
            raise ReportError("所选日期尚无本地报表，请先同步或刷新目录。")
        return Path(entry["path"])

    def sheets(self, kind: str, day: str):
        return sheet_names(self.path_for(kind, day))

    def query(self, request: dict):
        kind, day = request["kind"], request["date"]
        path = self.path_for(kind, day)
        sheet = request.get("sheet") or ALL_REPORTS[kind]["sheet"]
        result = query_table(read_table(path, sheet), request)
        result.update(date=day, sheet=sheet, filename=path.name)
        return result

    def update_settings(self, values: dict):
        with self.lock:
            if self.job["state"] == "running" or any(j["state"] == "running" for j in self.download_jobs.values()):
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

    def start_sync(self, *, only_missing=False):
        with self.lock:
            if self.job["state"] == "running":
                return dict(self.job)
            if not self.settings.get().get("source_root"):
                raise ReportError("请先在「数据与同步」中设置共享来源目录。")
            self.job = {"state": "running", "started_at": timestamp()}
        threading.Thread(target=self._sync, kwargs={"only_missing": only_missing}, daemon=True).start()
        return self.sync_status()

    def _sync(self, *, only_missing=False, kind=None):
        try:
            executable = Path(sys.executable)
            if executable.name.lower() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            completed = subprocess.run(
                [str(executable), "-X", "utf8", "-m", "script_making.sync_worker",
                 "--root", str(self.settings.root), *(["--only-missing"] if only_missing else []),
                 *(["--kind", kind] if kind else [])],
                cwd=Path(__file__).parent.parent, capture_output=True,
                text=True, encoding="utf-8", timeout=120 if kind else 45,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result = json.loads(completed.stdout)
            if not result.get("ok"):
                raise ReportError(result.get("error", "同步失败。"))
            state = {"state": "success", "result": result["result"], "finished_at": timestamp()}
            if kind and result["result"].get("errors"):
                state["state"] = "partial"
        except subprocess.TimeoutExpired:
            state = {"state": "error", "error": f"共享目录访问超过 {120 if kind else 45} 秒。请连接公司网络后重试，本地文件仍可查询。"}
        except (ReportError, OSError, ValueError) as exc:
            state = {"state": "error", "error": str(exc) if isinstance(exc, ReportError)
                     else "同步进程失败，请检查 Python 环境和来源目录。"}
        state.setdefault("finished_at", timestamp())
        if kind:
            try:
                atomic_json(archive_path(self.settings, kind) / "status.json", state)
            except OSError:
                pass
        with self.lock:
            if kind:
                self.download_jobs[kind] = state
            else:
                self.job = state
