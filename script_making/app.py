"""Loopback-only web UI and JSON API for locally stored reports."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .query import query_table, read_table, sheet_names
from .storage import (REPORTS, ReportError, Settings, catalog, identify, report_path,
                      save_files, sync_reports, timestamp)

STATIC = Path(__file__).parent / "static"


class Application:
    def __init__(self, root: Path):
        self.settings = Settings(root)
        self.lock = threading.Lock()
        self.job = {"state": "idle"}

    def start_sync(self):
        with self.lock:
            if self.job["state"] == "running":
                return dict(self.job)
            if not self.settings.get().get("source_root"):
                raise ReportError("请先设置共享来源目录。")
            self.job = {"state": "running", "started_at": timestamp()}
        threading.Thread(target=self._sync, daemon=True).start()
        return dict(self.job)

    def _sync(self):
        try:
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "script_making.app",
                 "--root", str(self.settings.root), "--sync-once"],
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
            state = {"state": "error", "error": str(exc) if isinstance(exc, ReportError) else "同步进程失败，请检查 Python 环境和来源目录。"}
        with self.lock:
            self.job = state


def handler_for(application: Application):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalReports/1.0"

        def log_message(self, fmt, *args):
            # Query values, filenames and business records are not written to logs.
            pass

        def permitted(self, mutation=False):
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in allowed:
                self.respond(403, {"error": "仅允许本机访问。"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{value}" for value in allowed}:
                self.respond(403, {"error": "不允许跨站请求。"})
                return False
            return True

        def respond(self, status, value, content_type="application/json; charset=utf-8"):
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def params(self):
            return {key: value[0] for key, value in parse_qs(urlparse(self.path).query).items()}

        def json_body(self):
            if self.headers.get_content_type() != "application/json":
                raise ReportError("请求应使用 application/json。")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ReportError("请求长度无效。") from exc
            if not 0 < length <= 128 * 1024:
                raise ReportError("请求内容为空或过大。")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ReportError("请求应为 JSON 对象。")
            return body

        def do_GET(self):
            if not self.permitted():
                return
            route = urlparse(self.path).path
            try:
                if route == "/api/catalog":
                    self.respond(200, catalog(application.settings))
                elif route == "/api/settings":
                    self.respond(200, {"settings": application.settings.get(),
                                       "saved_dir": str(application.settings.data_path())})
                elif route == "/api/sync":
                    with application.lock:
                        result = dict(application.job)
                    self.respond(200, result)
                elif route == "/api/sheets":
                    params = self.params()
                    kind = params.get("kind", "swap")
                    path = report_path(application.settings, kind, params.get("date", ""))
                    self.respond(200, {"sheets": sheet_names(path), "default_sheet": REPORTS[kind]["sheet"]})
                elif route in ("/", "/index.html", "/app.js", "/style.css"):
                    name = "index.html" if route == "/" else route.lstrip("/")
                    mime = {"html": "text/html", "js": "text/javascript", "css": "text/css"}[name.rsplit(".", 1)[-1]]
                    self.respond(200, (STATIC / name).read_bytes(), mime + "; charset=utf-8")
                elif route == "/api/health":
                    self.respond(200, {"ok": True})
                else:
                    self.respond(404, {"error": "页面不存在。"})
            except (ReportError, OSError, ValueError, KeyError) as exc:
                self.respond(400, {"error": str(exc) if isinstance(exc, ReportError) else "读取失败，请检查本地报表或目录。"})

        def do_POST(self):
            if not self.permitted(True):
                return
            route = urlparse(self.path).path
            try:
                if route == "/api/import":
                    if self.headers.get_content_type() != "application/octet-stream":
                        raise ReportError("请通过页面选择 Excel 文件。")
                    name = unquote(self.headers.get("X-Filename", ""))
                    kind, day = identify(name)
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 150 * 1024 * 1024:
                        raise ReportError("Excel 文件应小于 150 MB。")
                    with application.lock:
                        if application.job["state"] == "running":
                            raise ReportError("正在同步，请完成后再导入。")
                        import_cache = application.settings.root / "cache" / "uploads"
                        import_cache.mkdir(parents=True, exist_ok=True)
                        with tempfile.TemporaryDirectory(dir=import_cache) as temporary:
                            path = Path(temporary) / name
                            remaining = length
                            with path.open("wb") as stream:
                                while remaining:
                                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                                    if not chunk:
                                        raise ReportError("文件上传未完成。")
                                    stream.write(chunk)
                                    remaining -= len(chunk)
                            result = save_files(application.settings.data_path(), {kind: path}, day, "手动导入")
                    self.respond(200, result)
                    return
                body = self.json_body()
                if route == "/api/settings":
                    with application.lock:
                        if application.job["state"] == "running":
                            raise ReportError("同步期间不能修改目录，请稍后再试。")
                        application.settings.update(body)
                    self.respond(200, catalog(application.settings))
                elif route == "/api/sync":
                    self.respond(202, application.start_sync())
                elif route == "/api/query":
                    kind = body.get("kind", "swap")
                    path = report_path(application.settings, kind, body.get("date", ""))
                    sheet = body.get("sheet") or REPORTS[kind]["sheet"]
                    table = read_table(path, sheet)
                    result = query_table(table, body)
                    result.update({"date": body["date"], "sheet": sheet, "filename": path.name})
                    self.respond(200, result)
                else:
                    self.respond(404, {"error": "接口不存在。"})
            except (ReportError, OSError, ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": str(exc) if isinstance(exc, ReportError) else "请求失败，请检查输入及本地文件。"})

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地日报查询")
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--sync-once", action="store_true")
    args = parser.parse_args(argv)
    application = Application(args.root)
    if args.sync_once:
        try:
            result = sync_reports(application.settings.get(), application.settings.data_path())
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
            return 0
        except (ReportError, OSError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(application))
    except OSError:
        print(f"端口 {args.port} 无法使用。可运行 python -m script_making.app --port 8767。", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"日报查询已启动：{url}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
