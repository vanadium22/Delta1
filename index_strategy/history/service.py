"""Keep SDK isolation, subprocess I/O and cancellation away from Tk callbacks."""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from ..instant_dld.quotes import CHINA

from .downloader import validate


class HistoryService:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(__file__).resolve().parents[2]
        self.settings_path = self.root / "localsetting/history_ui.json"
        self.events = queue.Queue()
        self.thread = None
        self.process = None
        self.cancel_path = None

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def config(self):
        if self.settings_path.exists():
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        return {}

    def recent(self, limit=30):
        folder = self.settings_path.parent / "history_jobs"
        if not folder.exists():
            return []
        files = sorted(folder.glob("*/summary.json"), key=lambda p:p.stat().st_mtime, reverse=True)[:limit]
        results = []
        for path in files:
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                self.events.put({"type": "log", "message": f"无法读取历史请求 {path.name}：{exc}"})
        return results

    def read_events(self, request_id):
        if not isinstance(request_id, str) or len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id):
            raise ValueError("请求编号无效")
        path = self.settings_path.parent / "history_jobs" / request_id / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def start(self, request):
        if self.busy:
            raise ValueError("请先等待当前下载结束")
        value = validate(request)
        isolated = self.root.parent / "dolphindb_data/.venv/Scripts/python.exe"
        interpreter = os.environ.get("SWHY_HISTORY_PYTHON", str(isolated))
        if not Path(interpreter).exists():
            raise ValueError("未找到 DolphinDB 环境；请设置 SWHY_HISTORY_PYTHON 或恢复 dolphindb_data/.venv")
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        request_id = uuid.uuid4().hex
        job = self.settings_path.parent / "history_jobs" / request_id
        job.mkdir(parents=True)
        request_path = job / "request.json"
        request_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        self.cancel_path = job / "cancel.flag"
        started_at = datetime.now(CHINA).isoformat(timespec="seconds")
        def work():
            received_done = False
            summary = {"request_id": request_id, "started_at": started_at, "request": value, "state": "running"}
            def publish(event):
                event = {**event, "request_id": request_id, "event_time": datetime.now(CHINA).isoformat(timespec="seconds")}
                with (job / "events.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                if event.get("type") == "done":
                    summary.update({k:v for k,v in event.items() if k != "type"})
                (job / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, default=str), encoding="utf-8")
                self.events.put(event)
            try:
                publish({"type": "request", "request": value, "started_at": started_at})
                env = os.environ.copy()
                env["PYTHONNOUSERSITE"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                self.process = subprocess.Popen([interpreter, "-B", "-X", "utf8", "-s", "-m",
                    "index_strategy.history.worker", "--request", str(request_path),
                    "--cancel", str(self.cancel_path)], cwd=self.root, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags)
                for line in self.process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = {"type": "log", "message": line.strip()}
                    if event.get("type") == "done":
                        received_done = True
                    publish(event)
                code = self.process.wait()
                if not received_done:
                    raise RuntimeError(f"下载进程意外退出（{code}），请查看任务日志")
            except Exception as exc:
                publish({"type": "error", "error": str(exc)})
                publish({"type": "done", "state": "failed", "files": 0, "errors": 1, "skipped": 0})
            finally:
                self.process = None
        self.thread = threading.Thread(target=work, name="history-download", daemon=True)
        self.thread.start()
        return request_id

    def stop(self):
        if self.busy and self.cancel_path:
            self.cancel_path.touch()

    def drain(self):
        items = []
        for _ in range(100):
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                break
        return items
