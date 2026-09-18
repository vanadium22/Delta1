"""Polling with live symbol reloads, sequential batches and no catch-up burst."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import logging
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable, Protocol

from .client import MarketDataClient
from .symbols import SymbolFileError, load_symbols

LOG = logging.getLogger(__name__)


class CollectionStore(Protocol):
    run_id: str
    run_dir: Path

    def manifest(self, value: dict) -> None: ...
    def batch(self, record: dict) -> None: ...
    def event(self, kind: str, **details) -> None: ...


def next_deadline(previous: float, now: float, interval: float) -> tuple[float, int]:
    target = previous + interval
    skipped = max(0, math.ceil((now - target) / interval))
    return target + skipped * interval, skipped


def collect(
    client: MarketDataClient,
    store: CollectionStore,
    symbol_files: list[Path],
    *,
    interval: float = 5,
    batch_size: int = 200,
    max_polls: int = 0,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("interval 必须是大于 0 的有限秒数")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size 必须是正整数")
    if type(max_polls) is not int or max_polls < 0:
        raise ValueError("max_polls 必须是非负整数（0 表示持续运行）")
    symbols = load_symbols(symbol_files)
    stop = stop if stop is not None else threading.Event()
    counts: Counter[str] = Counter()
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_id": store.run_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "status": "running",
        "interval_seconds": interval,
        "batch_size": batch_size,
        "max_polls": max_polls,
        "symbol_files": [str(Path(path).resolve()) for path in symbol_files],
        "initial_symbols": symbols[:],
        "url": client.url,
        "use_environment_settings": client.session.trust_env,
        "tls_verification": client.verify,
        "request_timeouts": list(client.timeout),
        "polls_started": 0,
    }
    store.manifest(summary)
    store.event("started", symbols=symbols)
    deadline = clock()
    try:
        while not stop.is_set() and (not max_polls or summary["polls_started"] < max_polls):
            if stop.wait(max(0, deadline - clock())):
                break
            summary["polls_started"] += 1
            poll = summary["polls_started"]
            try:
                updated = load_symbols(symbol_files)
            except SymbolFileError as exc:
                store.event("symbol_reload_error", poll=poll, error=str(exc), action="keep_last_valid_symbols")
                LOG.warning("标的文件暂不可用，沿用上一版：%s", exc)
            else:
                if updated != symbols:
                    symbols = updated
                    store.event("symbols_changed", poll=poll, symbols=symbols)
                    LOG.info("标的已更新：%s 个", len(symbols))
            total_batches = math.ceil(len(symbols) / batch_size)
            poll_counts: Counter[str] = Counter()
            for index, offset in enumerate(range(0, len(symbols), batch_size), 1):
                if stop.is_set():
                    break
                result = client.fetch(symbols[offset:offset + batch_size])
                result.update(poll=poll, batch=index, batch_count=total_batches)
                store.batch(result)
                counts[result["status"]] += 1
                poll_counts[result["status"]] += 1
                if result["status"] != "success":
                    LOG.warning("轮次 %s 批次 %s/%s：%s，缺失=%s，错误=%s", poll, index, total_batches,
                                result["status"], result.get("missing_symbols", []), result.get("error", ""))
            LOG.info("轮次 %s，标的 %s 个，批次结果 %s", poll, len(symbols), dict(poll_counts))
            if stop.is_set() or (max_polls and poll >= max_polls):
                break
            deadline, skipped = next_deadline(deadline, clock(), interval)
            if skipped:
                store.event("schedule_skipped", poll=poll, skipped_intervals=skipped)
                LOG.warning("本轮耗时超过轮询间隔，跳过 %s 个时点", skipped)
        summary["status"] = "stopped" if stop.is_set() else "completed"
    except BaseException:
        summary["status"] = "failed"
        raise
    finally:
        summary.update(
            finished_at=datetime.now().astimezone().isoformat(),
            batch_status_counts=dict(counts),
            requests_saved=sum(counts.values()),
        )
        try:
            store.manifest(summary)
        except OSError:
            LOG.exception("运行摘要无法写入：%s", store.run_dir)
            if summary["status"] != "failed":
                raise
    return summary
