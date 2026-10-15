from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .config import ROOT
from .service import InventoryService


def make_server(service, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Do not log user query terms.
            pass

        def send(self, status, data, content_type="application/json; charset=utf-8"):
            def encode(value):
                if isinstance(value, Decimal):
                    return int(value) if value == value.to_integral_value() else str(value)
                raise TypeError(f"Cannot serialize {type(value).__name__}")
            body = json.dumps(data, ensure_ascii=False, allow_nan=False, default=encode).encode("utf-8") if not isinstance(data, bytes) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in hosts:
                self.send(403, {"error": "仅允许本机访问"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}" for host in hosts}:
                self.send(403, {"error": "不允许跨站请求"})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = urlparse(self.path).path
            if path == "/api/status":
                self.send(200, service.status())
            elif path == "/api/config":
                self.send(200, service.config)
            elif path in {"/", "/app.js", "/styles.css", "/favicon.svg"}:
                file = ROOT / "static" / ("index.html" if path == "/" else path[1:])
                self.send(200, file.read_bytes(), (mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8")
            else:
                self.send(404, {"error": "页面不存在"})

        def do_POST(self):
            if not self.allowed():
                return
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.send(415, {"error": "请求必须使用 application/json"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 65536:
                    self.send(413, {"error": "请求为空或过大"})
                    return
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("请求应为 JSON 对象")
                with service.lock:
                    if self.path == "/api/refresh":
                        result = service.refresh()
                    elif self.path == "/api/query":
                        if not isinstance(body.get("symbols"), str):
                            raise ValueError("symbols 必须为文本")
                        result = service.query(body["symbols"], body.get("targets"))
                    elif self.path == "/api/config":
                        result = service.update_config(body)
                    else:
                        self.send(404, {"error": "接口不存在"})
                        return
                self.send(200, result)
            except (ValueError, TypeError) as exc:
                self.send(400, {"error": str(exc)})
            except Exception as exc:
                self.send(500, {"error": f"操作失败：{type(exc).__name__}: {exc}"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Delta1 券源查询")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--demo", action="store_true", help="使用合成演示券单")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    service = InventoryService(demo=args.demo)
    try:
        server = make_server(service, args.port)
    except OSError as exc:
        raise SystemExit(f"端口 {args.port} 无法使用，请关闭已有实例或使用 --port 指定其他端口：{exc}")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Delta1 券源查询 {'[合成演示]' if args.demo else ''} {url}", flush=True)
    print("启动优先读取当日本地券单，无可用副本时自动同步。Ctrl+C 关闭服务。", flush=True)
    threading.Thread(target=service.status, daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
