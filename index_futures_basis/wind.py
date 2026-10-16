"""One hidden Wind process per sync; JSON lines, bounded waits and owned cleanup."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import subprocess
import sys
import threading


class WindProvider:
    worker_filename = "wind_worker.py"

    def __init__(self, config):
        self.config, self.process = config, None
        self.responses = queue.Queue()

    def _start(self):
        executable = Path(self.config.get("wind_python") or sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        self.process = subprocess.Popen([str(executable), "-X", "utf8", str(Path(__file__).with_name(self.worker_filename))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def read_lines():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)
        self.reader = threading.Thread(target=read_lines, daemon=True)
        self.reader.start()

    def request(self, operation, **kwargs):
        if self.process is None:
            try:
                self._start()
            except OSError as exc:
                raise ConnectionError(f"无法启动 Wind Python：{exc}") from exc
        try:
            self.process.stdin.write(json.dumps({"operation": operation, **kwargs}) + "\n")
            self.process.stdin.flush()
            line = self.responses.get(timeout=float(self.config["wind_timeout_seconds"]))
            if line is None:
                raise ConnectionError("Wind 进程已退出，请检查解释器和 WindPy")
            result = json.loads(line)
            if result.get("error"):
                if result.get("fatal"):
                    raise ConnectionError(result["error"])
                raise RuntimeError(result["error"])
            return result["data"]
        except queue.Empty as exc:
            self.close()
            raise TimeoutError("Wind 请求超时，已停止本次进程；已保存的批次仍可使用") from exc
        except (BrokenPipeError, OSError) as exc:
            raise ConnectionError(f"Wind 进程连接中断：{exc}") from exc

    def calendar(self, start, end):
        return self.request("calendar", start=start, end=end)

    def mapping(self, code, start, end):
        field = self.config["wind_mapping_field"].strip().lower()
        data = self.request("series", code=code, fields=[field], start=start, end=end)
        return {day: row.get(field) for day, row in data.items()}

    def expiries(self, codes):
        return self.request("expiries", codes=codes, field=self.config["wind_expiry_field"])

    def series(self, code, fields, start, end):
        return self.request("series", code=code, fields=list(fields), start=start, end=end)

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    self.process.stdin.close()
                    self.process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.reader.join(timeout=1)
            self.process.stdout.close()
            self.process = None
            self.responses = queue.Queue()
