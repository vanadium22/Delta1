"""One background collector, persisted local settings and bounded live logs."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import threading
import uuid
from typing import Callable

from .client import MarketDataClient
from .collector import collect
from .storage import JsonlStore
from .symbols import load_symbols, parse_symbols

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_STATES = {"starting", "running", "stopping"}


class ConflictError(ValueError):
    """A running job owns the configuration until it finishes."""


def write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ObservedStore(JsonlStore):
    def __init__(self, root: Path, observer: Callable):
        super().__init__(root)
        self.observer = observer

    def batch(self, record: dict) -> None:
        super().batch(record)
        self.observer(record)


class ThreadLogHandler(logging.Handler):
    def __init__(self, owner: "DownloadService"):
        super().__init__(logging.INFO)
        self.owner = owner
        self.thread_id = threading.get_ident()

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == self.thread_id:
            self.owner.log(record.levelname, record.getMessage())


class DownloadService:
    def __init__(self, root: Path = PROJECT_ROOT, *, client_factory: Callable = MarketDataClient,
                 collector: Callable = collect):
        self.root = Path(root).resolve()
        self.instance_id = uuid.uuid4().hex
        self.settings_path = self.root / "localsetting" / "realtime_ui.json"
        self.symbols_path = self.root / "localsetting" / "realtime_symbols.json"
        self.lock = threading.RLock()
        self.logs: deque[dict] = deque(maxlen=600)
        self.sequence = 0
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.client_factory, self.collector = client_factory, collector
        self.state = "idle"
        self.error: str | None = None
        self.run_id: str | None = None
        self.run_dir: str | None = None
        self.active_config: dict | None = None
        self.stats = self._empty_stats()
        self.settings = self._load_settings()
        self.log("INFO", "本地服务已就绪。确认标的、采集间隔和保存位置后，点击开始采集。")

    @staticmethod
    def _empty_stats() -> dict:
        return {"polls": 0, "batches": 0, "successful": 0, "unsuccessful": 0,
                "last_response_at": None, "last_latency_ms": None, "started_at": None, "finished_at": None}

    def _load_settings(self) -> dict:
        if self.settings_path.is_file():
            # Corrupt settings must remain visible instead of being silently overwritten.
            return self.validate(json.loads(self.settings_path.read_text(encoding="utf-8-sig")))
        symbols = load_symbols([self.root / "index_strategy/instant_dld/config/symbols.json"])
        return {"symbols": symbols, "interval": 5.0,
                "output_dir": str(self.root / "index_strategy/instant_dld/data")}

    def validate(self, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError("配置必须是 JSON 对象")
        symbols = value.get("symbols")
        if isinstance(symbols, list):
            symbols = parse_symbols(json.dumps(symbols), ".json")
        elif isinstance(symbols, str):
            symbols = parse_symbols(symbols)
        else:
            raise ValueError("请填写标的列表")
        if not symbols:
            raise ValueError("至少需要一个标的")
        raw_interval = value.get("interval")
        if isinstance(raw_interval, bool):
            raise ValueError("采集间隔必须是大于 0 的有限秒数")
        try:
            interval = float(raw_interval)
        except (ValueError, TypeError):
            raise ValueError("采集间隔必须是数字") from None
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("采集间隔必须是大于 0 的有限秒数")
        output = value.get("output_dir")
        if not isinstance(output, str) or not output.strip() or "\x00" in output:
            raise ValueError("请填写有效的数据保存目录")
        path = Path(output.strip()).expanduser()
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if path.exists() and not path.is_dir():
            raise ValueError("保存位置是文件，请填写文件夹路径")
        return {"symbols": symbols, "interval": interval, "output_dir": str(path)}

    def _ensure_idle(self) -> None:
        if self.state in ACTIVE_STATES or (self.worker is not None and self.worker.is_alive()):
            raise ConflictError("采集正在运行，请先停止，再修改配置或重新开始")

    def config(self) -> dict:
        with self.lock:
            return deepcopy(self.settings)

    def save(self, value: dict) -> dict:
        with self.lock:
            self._ensure_idle()
            validated = self.validate(value)
            write_json(self.settings_path, validated)
            self.settings = validated
            self.log("INFO", f"配置已保存：{len(validated['symbols'])} 个标的，每 {validated['interval']:g} 秒一轮。")
            return deepcopy(validated)

    def start(self, value: dict) -> dict:
        with self.lock:
            self._ensure_idle()
            settings = self.save(value)
            write_json(self.symbols_path, settings["symbols"])
            self.stop_event = threading.Event()
            self.state, self.error = "starting", None
            self.run_id = self.run_dir = None
            self.stats = self._empty_stats()
            self.stats["started_at"] = datetime.now().astimezone().isoformat()
            self.active_config = deepcopy(settings)
            self.worker = threading.Thread(target=self._run, args=(settings,), name="delta1-realtime", daemon=True)
            try:
                self.worker.start()
            except RuntimeError as exc:
                self.state, self.error = "failed", str(exc)
                raise
            self.log("INFO", "正在启动采集，使用内网直连并验证 TLS。")
            return self.snapshot()

    def stop(self) -> dict:
        with self.lock:
            if self.state in {"starting", "running"}:
                self.state = "stopping"
                self.stop_event.set()
                self.log("INFO", "已请求停止，等待当前请求完成并保存数据。")
            return self.snapshot()

    def close(self, timeout: float = 45) -> None:
        self.stop()
        worker = self.worker
        if worker is not None:
            worker.join(timeout)

    def log(self, level: str, message: str) -> None:
        with self.lock:
            self.sequence += 1
            self.logs.append({"id": self.sequence, "at": datetime.now().astimezone().isoformat(),
                              "level": level, "message": message})

    def snapshot(self, after: int = 0) -> dict:
        with self.lock:
            return {"instance_id": self.instance_id, "status": self.state, "error": self.error, "run_id": self.run_id,
                    "run_dir": self.run_dir, "active_config": deepcopy(self.active_config),
                    "stats": dict(self.stats), "log_cursor": self.sequence,
                    "logs": [dict(item) for item in self.logs if item["id"] > after]}

    def _batch_saved(self, record: dict) -> None:
        with self.lock:
            self.stats["batches"] += 1
            self.stats["polls"] = max(self.stats["polls"], record["poll"])
            good = record["status"] == "success"
            self.stats["successful" if good else "unsuccessful"] += 1
            self.stats["last_response_at"] = record["received_at"]
            self.stats["last_latency_ms"] = round(record.get("elapsed_seconds", 0) * 1000)
            self.log("INFO" if good else "WARNING",
                     f"批次 {record['batch']}/{record['batch_count']} 已落盘 · {len(record['symbols'])} 个标的 · "
                     f"{record['status']} · {self.stats['last_latency_ms']} ms")

    def _run(self, settings: dict) -> None:
        client = None
        logger = logging.getLogger("index_strategy.instant_dld.collector")
        handler, previous_level = ThreadLogHandler(self), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            client = self.client_factory()
            store = ObservedStore(Path(settings["output_dir"]), self._batch_saved)
            with self.lock:
                self.run_id, self.run_dir = store.run_id, str(store.run_dir)
                if not self.stop_event.is_set():
                    self.state = "running"
            self.log("INFO", f"数据目录：{store.root}；运行编号：{store.run_id}")
            summary = self.collector(client, store, [self.symbols_path], interval=settings["interval"],
                                     stop=self.stop_event)
            with self.lock:
                self.stats["polls"] = summary["polls_started"]
                self.state = "stopped"
            self.log("INFO", f"采集已结束，共保存 {summary['requests_saved']} 个批次。")
        except Exception as exc:
            with self.lock:
                self.state, self.error = "failed", str(exc)
            self.log("ERROR", f"采集停止：{type(exc).__name__}: {exc}")
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                logger.removeHandler(handler)
                logger.setLevel(previous_level)
                with self.lock:
                    self.stats["finished_at"] = datetime.now().astimezone().isoformat()
