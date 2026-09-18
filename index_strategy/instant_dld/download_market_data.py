# -*- coding: utf-8 -*-
"""查询内网最新行情，并保存可用于排查问题的结果。

安装依赖：python -m pip install requests
直接运行：python download_market_data.py
指定股票：python download_market_data.py --symbols 603110.SH 000001.SZ
直连内网：python download_market_data.py --direct
公司 CA：python download_market_data.py --ca-bundle company-ca.pem

输出位于本脚本旁的 market_data_output/每次运行时间/：
  diagnostic_report.json：请求参数、HTTP 状态、完整 JSON 响应或错误信息。
  market_data.json：响应中原样提取的 data（仅 HTTP 成功且存在 data 时）。
  response_body.txt：服务端返回的原文（收到 HTTP 响应时）。

不假设未知字段的含义，不转换成 DataFrame，不填充缺失值。
HTTP 成功且存在 data 不等于业务成功；需结合完整响应判断。
"""

import argparse
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path


URL = (
    "https://otcderivatives.swhysc.com:11443"
    "/market-cache-app/v1/market-cache/post/latest-market-data"
)
DEFAULT_SYMBOLS = ["603110.SH", "000001.SZ"]
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "PostmanRuntime/7.26.8",
}


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="内网最新行情下载与诊断")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--direct", action="store_true", help="忽略环境代理和环境认证配置，直接连接")
    parser.add_argument("--ca-bundle", help="公司可信 CA 证书文件路径（PEM 格式）")
    args = parser.parse_args()

    started_at = datetime.now().astimezone()
    output_dir = (
        Path(__file__).resolve().parent
        / "market_data_output"
        / started_at.strftime("%Y%m%d_%H%M%S_%f")
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "started_at": started_at.isoformat(),
        "python_version": platform.python_version(),
        "url": URL,
        "method": "POST",
        "symbols": args.symbols,
        "connect_timeout_seconds": 10,
        "read_timeout_seconds": 30,
        "use_environment_settings": not args.direct,
        "tls_verification": "custom_ca" if args.ca_bundle else "enabled",
        "status": "not_started",
    }
    exit_code = 1
    started = time.monotonic()
    print("正在查询：", ", ".join(args.symbols))
    print("结果目录：", output_dir)

    try:
        try:
            import requests
        except ImportError:
            report.update(
                status="missing_dependency",
                hint="请先运行 python -m pip install requests，然后重新运行本脚本。",
            )
            return 1

        report["requests_version"] = requests.__version__
        try:
            with requests.Session() as session:
                session.trust_env = not args.direct
                response = session.post(
                    URL,
                    json=args.symbols,
                    headers=HEADERS,
                    timeout=(10, 30),
                    verify=args.ca_bundle or True,
                    allow_redirects=False,
                )
            report["http_status"] = response.status_code
            report["content_type"] = response.headers.get("Content-Type")
            report["response_bytes"] = len(response.content)
            # 保留响应原始字节，避免乱码或转码导致原始内容丢失。
            (output_dir / "response_body.txt").write_bytes(response.content)
            print("HTTP 状态：", response.status_code)

            try:
                payload = response.json()
            except ValueError:
                report.update(
                    status="non_json_response",
                    response_preview=response.text[:4000],
                    hint="响应不是有效 JSON，请结合 HTTP 状态和 response_body.txt 排查。",
                )
            else:
                report["response_json"] = payload
                if not 200 <= response.status_code < 300:
                    report.update(
                        status="http_error",
                        hint="请检查完整响应；401/403 常涉及认证或权限，3xx 表示重定向，5xx 常涉及服务端或网关。",
                    )
                elif not isinstance(payload, dict) or "data" not in payload:
                    report.update(
                        status="missing_data_field",
                        hint="JSON 中不存在预期的顶层 data 字段，请检查完整响应结构。",
                    )
                else:
                    data = payload["data"]
                    save_json(output_dir / "market_data.json", data)
                    report["status"] = "data_extracted"
                    report["data_type"] = type(data).__name__
                    report["data_is_null"] = data is None
                    if isinstance(data, (list, dict)):
                        report["data_length"] = len(data)
                    print("data 内容：")
                    print(json.dumps(data, ensure_ascii=False, indent=2))
                    print("已原样保存 data；业务是否成功仍需结合完整响应判断。")
                    exit_code = 0
        except requests.exceptions.SSLError as exc:
            report.update(status="tls_error", error=str(exc), hint="TLS 证书校验失败。若使用公司 CA，请通过 --ca-bundle 指定可信 PEM 证书；未关闭证书验证。")
        except requests.exceptions.ProxyError as exc:
            report.update(status="proxy_error", error=str(exc), hint="代理连接失败。若公司内网应直连，可尝试添加 --direct 参数。")
        except requests.exceptions.Timeout as exc:
            report.update(status="timeout", error=str(exc), hint="连接或读取超时，请确认公司内网/VPN、11443 端口及服务可用性。")
        except requests.exceptions.ConnectionError as exc:
            report.update(status="connection_error", error=str(exc), hint="连接失败，请检查公司内网/VPN、域名解析和端口连通性。")
        except requests.exceptions.RequestException as exc:
            report.update(status="request_error", error=str(exc))
    except Exception as exc:
        report.update(status="local_error", error_type=type(exc).__name__, error=str(exc))
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save_json(output_dir / "diagnostic_report.json", report)
        print("诊断状态：", report["status"])
        if "error" in report:
            print("错误：", report["error"])
        if "hint" in report:
            print("提示：", report["hint"])
        print("请把此文件发回来：", output_dir / "diagnostic_report.json")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
