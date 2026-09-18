"""Loopback-only HTTP server for the local collection console."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import secrets
import signal
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .service import ConflictError, DownloadService
from ..instant_dld.symbols import parse_symbols

STATIC = Path(__file__).resolve().parent / "static"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, service: DownloadService):
        self.service = service
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), ConsoleHandler)


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer

    def log_message(self, *_args) -> None:
        pass

    def _trusted_request(self) -> bool:
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin")
        return host in allowed and (origin is None or origin in {f"http://{value}" for value in allowed})

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, value: dict) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if not self._trusted_request():
            self._json(403, {"error": "仅允许本机页面访问"})
            return
        parsed = urlsplit(self.path)
        if parsed.path in ASSETS:
            name, content_type = ASSETS[parsed.path]
            self._send(200, (STATIC / name).read_bytes(), content_type)
        elif parsed.path == "/api/bootstrap":
            self._json(200, {"token": self.server.token, "config": self.server.service.config(),
                             "state": self.server.service.snapshot()})
        elif parsed.path == "/api/state":
            try:
                cursor = int(parse_qs(parsed.query).get("after", ["0"])[0])
                if cursor < 0:
                    raise ValueError
            except ValueError:
                self._json(400, {"error": "日志游标无效"})
                return
            self._json(200, self.server.service.snapshot(cursor))
        elif parsed.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "页面不存在"})

    def do_POST(self) -> None:
        if not self._trusted_request() or not secrets.compare_digest(self.headers.get("X-Delta1-Token", ""), self.server.token):
            self._json(403, {"error": "页面会话已失效，请刷新页面"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "需要 JSON 请求"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024 * 1024:
                self._json(413, {"error": "请求内容为空或超过 1 MB"})
                return
            self.connection.settimeout(10)
            value = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("请求必须是 JSON 对象")
            route = urlsplit(self.path).path
            if route == "/api/config":
                response = {"config": self.server.service.save(value)}
            elif route == "/api/start":
                response = {"state": self.server.service.start(value), "config": self.server.service.config()}
            elif route == "/api/stop":
                response = {"state": self.server.service.stop()}
            elif route == "/api/symbols/parse":
                files = value.get("files")
                if not isinstance(files, list) or not 1 <= len(files) <= 50:
                    raise ValueError("请选择 1–50 个标的文件")
                merged = {}
                for item in files:
                    if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("text"), str):
                        raise ValueError("标的文件格式无效")
                    for symbol in parse_symbols(item["text"], Path(item["name"]).suffix):
                        merged[symbol] = None
                if not merged:
                    raise ValueError("文件中没有标的")
                response = {"symbols": list(merged)}
            else:
                self._json(404, {"error": "接口不存在"})
                return
            self._json(200, response)
        except ConflictError as exc:
            self._json(409, {"error": str(exc)})
        except (ValueError, UnicodeError) as exc:
            self._json(400, {"error": str(exc)})
        except OSError as exc:
            self._json(500, {"error": f"本机文件操作失败：{exc}"})
        except Exception:
            logging.exception("Frontend request failed")
            self._json(500, {"error": "本地服务发生错误，请查看服务日志"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delta1 本地数据下载控制台")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535 之间")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = None
    try:
        service = DownloadService()
        with ConsoleServer(args.port, service) as server:
            address = f"http://127.0.0.1:{server.server_port}"
            print(f"Delta1: {address}", flush=True)
            if args.open:
                webbrowser.open(address)
            previous = {}
            if threading.current_thread() is threading.main_thread():
                def request_shutdown(*_args):
                    threading.Thread(target=server.shutdown, daemon=True).start()
                for signum in (signal.SIGINT, signal.SIGTERM):
                    previous[signum] = signal.signal(signum, request_shutdown)
            try:
                server.serve_forever(poll_interval=0.2)
            finally:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
    except (OSError, ValueError) as exc:
        logging.error("界面无法启动：%s", exc)
        return 1
    finally:
        if service is not None:
            service.close()
    return 0
