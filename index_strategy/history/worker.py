"""Line-delimited JSON protocol between the desktop and the isolated SDK process."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .downloader import run_download


def classify_error(error):
    """Stable failure scope; raw SDK messages may contain connection details."""
    message = str(error)
    if "没有原始" in message or "没有可用于" in message or "目录中没有" in message:
        return {"category": "unsupported_source", "scope": "job", "retryable": False,
                "message": message[:300]}
    lowered = message.lower()
    if "vpnconnectionerror" in lowered or "sslvpn" in lowered or "dolphindb 登录失败" in lowered:
        return {"category": "connection_failed", "scope": "connection", "retryable": True,
                "message": "SSLVPN 或 DolphinDB 连接失败；请检查连接状态"}
    if isinstance(error, ValueError) or message.startswith("ValueError:"):
        return {"category": "invalid_request_or_source", "scope": "job", "retryable": False,
                "message": "请求参数或来源校验失败；检查品种、频率及输入路径"}
    return {"category": "query_or_worker_failed", "scope": "job", "retryable": True,
            "message": "单项查询或下载失败；有报告时请检查 run.json 的 errors"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--cancel", required=True, type=Path)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    error_details = []
    def emit(event):
        if event.get("type") == "error":
            detail = classify_error(event.get("error", ""))
            error_details.append(detail)
            event = {**event, "error_detail": detail}
        print(json.dumps(event, ensure_ascii=False, default=str), flush=True)
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        report = run_download(request, emit=emit, cancelled=args.cancel.exists)
        emit({"type": "done", "state": report["state"], "files": len(report["files"]),
              "errors": len(report["errors"]), "skipped": len(report["skipped"]),
              "counts": report.get("counts", {}), "sampled": report.get("sampled", 0),
              "requested_items": report.get("requested_items", 0), "elapsed_seconds": report.get("elapsed_seconds", 0),
              "report_file": report.get("report_file"), "error_details": error_details})
        return 1 if report["errors"] else 0
    except Exception as exc:
        emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        emit({"type": "done", "state": "failed", "files": 0, "errors": 1, "skipped": 0,
              "error_details": error_details})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
