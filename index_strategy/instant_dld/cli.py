"""Command-line entry point for continuous or bounded market polling."""
from __future__ import annotations

import argparse
import logging
import math
import os
from pathlib import Path
import signal
import sqlite3
import sys
import threading

from .client import DEFAULT_URL, MarketDataClient
from .collector import collect
from .realtime_store import DEFAULT_OUTPUT, RealtimeStore
from .symbols import load_symbols

HERE = Path(__file__).resolve().parent


def positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("秒数必须是大于 0 的有限数值")
    return number


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="按秒轮询内网行情，实时事务入库并按标的/年月保存 Parquet")
    result.add_argument("--interval", "--frequency", type=positive_seconds, default=5, help="每轮开始间隔，秒（默认 5）")
    result.add_argument("--symbols-file", "--symbols-files", nargs="+", type=Path,
                        default=[HERE / "config" / "symbols.json"], help="一个或多个 JSON/TXT/LIST 标的文件")
    result.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="保存目录（默认 Z:/Project_data/realtime_market）")
    result.add_argument("--batch-size", type=int, default=200, help="单次请求最大标的数（默认 200，可按接口容量调整）")
    limit = result.add_mutually_exclusive_group()
    limit.add_argument("--max-polls", type=int, default=0, help="完成多少轮后退出；0 表示持续运行")
    limit.add_argument("--once", action="store_const", const=1, dest="max_polls", help="只运行一轮")
    network = result.add_mutually_exclusive_group()
    network.add_argument("--direct", action="store_false", dest="use_environment", help="直连内网（默认）")
    network.add_argument("--use-env-proxy", action="store_true", dest="use_environment", help="启用环境代理、环境 CA 和 netrc 配置")
    result.set_defaults(use_environment=False)
    result.add_argument("--url", default=os.environ.get("SWHY_MARKET_DATA_URL", DEFAULT_URL))
    result.add_argument("--connect-timeout", type=positive_seconds, default=10)
    result.add_argument("--read-timeout", type=positive_seconds, default=30)
    result.add_argument("--ca-bundle", type=Path, help="可信公司 CA 文件；始终验证 TLS")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.batch_size < 1 or args.max_polls < 0:
        arguments.error("--batch-size 必须大于 0；--max-polls 不能为负")
    if args.ca_bundle and not args.ca_bundle.is_file():
        arguments.error("--ca-bundle 文件不存在")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    previous_handlers = {}
    client = None
    try:
        # A bad initial configuration must fail before starting an HTTP request.
        load_symbols(args.symbols_file)
        client = MarketDataClient(args.url, use_environment=args.use_environment,
                                  connect_timeout=args.connect_timeout, read_timeout=args.read_timeout,
                                  ca_bundle=args.ca_bundle)
        with RealtimeStore(args.output_dir) as store:
            logging.info("结果目录：%s；运行编号：%s；按 Ctrl+C 停止", store.root, store.run_id)
            if threading.current_thread() is threading.main_thread():
                for signum in (signal.SIGINT, signal.SIGTERM):
                    previous_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
            summary = collect(client, store, args.symbols_file, interval=args.interval,
                              batch_size=args.batch_size, max_polls=args.max_polls, stop=stop)
        logging.info("结束：%s；已保存 %s 个请求；摘要：%s", summary["status"],
                     summary["requests_saved"], store.db_path)
        return 2 if any(status != "success" and count for status, count in summary["batch_status_counts"].items()) else 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        logging.error("无法继续采集：%s", exc)
        return 1
    finally:
        if client is not None:
            client.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
