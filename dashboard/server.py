"""Loopback-only dashboard server; no external hosting or CDN required."""
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
from urllib.request import urlopen
import webbrowser

from .service import DashboardService

STATIC = Path(__file__).resolve().parent / "static"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, service):
        self.service = service
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def trusted(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        return self.headers.get("Host", "").lower() in allowed and self.headers.get("Origin") in {None, *("http://" + x for x in allowed)}

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
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

    def do_GET(self):
        if not self.trusted():
            self.send(403, {"error": "仅允许本机页面访问"})
            return
        route = urlsplit(self.path)
        try:
            service = self.server.service
            if route.path in ASSETS:
                name, content_type = ASSETS[route.path]
                self.send(200, (STATIC / name).read_bytes(), content_type)
            elif route.path == "/favicon.ico":
                self.send(204, b"", "image/x-icon")
            elif route.path == "/api/bootstrap":
                self.send(200, {"application": "delta1-dashboard", "local_root": str(service.local_root),
                                "token": self.server.token, **service.bootstrap()})
            elif route.path == "/api/state":
                self.send(200, service.snapshot())
            elif route.path == "/api/universe":
                self.send(200, service.universe())
            elif route.path == "/api/history":
                query = parse_qs(route.query)
                self.send(200, service.history(query.get("day", [None])[0], query.get("factor", [None])[0]))
            else:
                self.send(404, {"error": "页面不存在"})
        except (ValueError, OSError) as exc:
            self.send(400, {"error": str(exc)})
        except Exception:
            logging.exception("Dashboard GET failed")
            self.send(500, {"error": "读取失败，请查看看板日志"})

    def do_POST(self):
        if not self.trusted() or not secrets.compare_digest(self.headers.get("X-Delta1-Token", ""), self.server.token):
            self.send(403, {"error": "页面会话已失效，请刷新"})
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("需要 JSON 请求")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100000:
                raise ValueError("请求超过大小限制或为空")
            self.connection.settimeout(10)
            value = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("请求必须为对象")
            route = urlsplit(self.path).path
            service = self.server.service
            if route == "/api/config":
                response = {"config": service.save_config(value)}
            elif route == "/api/formulas/preview":
                response = service.preview(value)
            elif route == "/api/formulas/publish":
                response = {"formula": service.publish(value)}
            elif route == "/api/formulas/toggle":
                response = {"formula": service.toggle(value.get("id"), value.get("enabled"))}
            elif route == "/api/collection/start":
                response = service.collect(once=bool(value.get("once", False)))
            elif route == "/api/collection/stop":
                response = service.gateway.stop()
            elif route == "/api/results/flush":
                response = service.flush()
            elif route == "/api/shutdown":
                response = {"status": "stopping"}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send(404, {"error": "接口不存在"})
                return
            self.send(200, response)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            self.send(400, {"error": str(exc)})
        except OSError as exc:
            self.send(500, {"error": "本机文件操作失败：" + str(exc)})
        except Exception:
            logging.exception("Dashboard POST failed")
            self.send(500, {"error": "操作失败，请查看看板日志"})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Delta1 独立行情看板")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--local-root", type=Path, help="独立本机配置目录")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("端口需在 1–65535 之间")
    address = f"http://127.0.0.1:{args.port}"
    if args.open:
        # Reopening the launcher should focus the running app, not contend for its lock.
        try:
            with urlopen(address + "/api/bootstrap", timeout=2) as response:
                existing = json.load(response)
            expected_root = (args.local_root or STATIC.parent / "localsetting").resolve()
            if existing.get("application") == "delta1-dashboard" and Path(existing["local_root"]) == expected_root:
                webbrowser.open(address)
                return 0
        except (OSError, ValueError, KeyError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = None
    try:
        service = DashboardService(args.local_root)
        with DashboardServer(args.port, service) as server:
            address = f"http://127.0.0.1:{server.server_port}"
            print(address, flush=True)
            if args.open:
                webbrowser.open(address)
            def stop(*_):
                threading.Thread(target=server.shutdown, daemon=True).start()
            for signum in (signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, stop)
            server.serve_forever(poll_interval=0.2)
    except (OSError, ValueError) as exc:
        logging.error("看板无法启动：%s", exc)
        return 1
    finally:
        if service:
            service.close()
    return 0
