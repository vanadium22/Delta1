"""Dataset identity and retention are independent of storage format and consumers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

from .io import atomic_json, file_lock
from .paths import DataPaths, component, contained


@dataclass(frozen=True)
class Dataset:
    name: str
    source: str
    frequency: str  # snapshot / tick / 1m / 5m / 1d; never inferred from filenames
    mode: str = "live"
    storage: str = "files"  # files / sqlite / parquet
    retention: str = "persistent"  # only daily_cache may be pruned
    keep_days: int | None = None
    schema_version: int = 1
    timezone: str = "Asia/Shanghai"

    def __post_init__(self):
        for value in (self.name, self.source, self.frequency, self.mode):
            component(value)
        if self.mode not in {"live", "offline", "demo"} or self.storage not in {"files", "sqlite", "parquet"}:
            raise ValueError("Unsupported dataset mode/storage")
        if self.retention not in {"persistent", "daily_cache"}:
            raise ValueError("Unsupported retention policy")
        if self.retention == "daily_cache" and (type(self.keep_days) is not int or self.keep_days < 1):
            raise ValueError("Daily caches require keep_days >= 1")
        if self.retention == "persistent" and self.keep_days is not None:
            raise ValueError("Historical datasets cannot have automatic expiry")
        if type(self.schema_version) is not int or self.schema_version < 1 or self.timezone != "Asia/Shanghai":
            raise ValueError("Invalid schema version/timezone")

    @property
    def key(self):
        return ".".join((self.name, self.source, self.frequency, self.mode))


class Catalog:
    def __init__(self, paths: DataPaths):
        self.paths = paths

    def _record_path(self, key):
        return self.paths.root / "_catalog" / (component(key) + ".json")

    def register(self, dataset: Dataset, path: Path | None = None):
        prefix = "cache/market" if dataset.retention == "daily_cache" else "market"
        if dataset.mode != "live":
            prefix = f"{dataset.mode}/{prefix}"
        default = Path(prefix) / dataset.name / dataset.source / dataset.frequency
        path = contained(self.paths.root, default) if path is None else Path(path).resolve()
        relative = path.relative_to(self.paths.root.resolve()).as_posix()
        contained(self.paths.root, relative)
        if dataset.retention == "daily_cache" and not path.is_relative_to(contained(self.paths.root, prefix)):
            raise ValueError("Daily cache must be inside the dedicated cache tree")
        record = {"api_version": 1, "dataset": asdict(dataset), "relative_path": relative}
        target = self._record_path(dataset.key)
        with file_lock(target.with_suffix(".lock")):
            if target.exists():
                old = json.loads(target.read_text(encoding="utf-8"))
                if old != record:
                    raise ValueError(f"Dataset contract already exists: {dataset.key}; explicit migration required")
            else:
                atomic_json(target, record)
        return record

    def get(self, key):
        record = json.loads(self._record_path(key).read_text(encoding="utf-8"))
        if record.get("api_version") != 1:
            raise ValueError("Unsupported catalog API version")
        dataset = Dataset(**record["dataset"])
        if dataset.key != key:
            raise ValueError("Dataset identity mismatch")
        path = contained(self.paths.root, record["relative_path"])
        return dataset, path

    def list(self):
        return [self.get(p.stem)[0] for p in sorted((self.paths.root / "_catalog").glob("*.json"))]

    def partition(self, key, trading_date: str, symbol: str | None = None):
        _, root = self.get(key)
        day = date.fromisoformat(trading_date).isoformat()
        if day != trading_date:
            raise ValueError("Trading date must be YYYY-MM-DD")
        return contained(root, Path(day) / component(symbol)) if symbol else contained(root, day)

    def partitions(self, key, start: str, end: str):
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("Reversed date range")
        _, root = self.get(key)
        return [p for p in sorted(root.glob("????-??-??"))
                if p.is_dir() and not p.is_symlink() and start <= p.name <= end
                and date.fromisoformat(p.name).isoformat() == p.name]

    def prune(self, key, *, today: date | None = None, apply=False):
        """Opt-in cleanup; no application startup deletes data. Never prune history."""
        dataset, root = self.get(key)
        if dataset.retention != "daily_cache":
            raise ValueError("永久历史数据不允许清理")
        cache_root = self.paths.root / ("cache/market" if dataset.mode == "live" else f"{dataset.mode}/cache/market")
        if not root.is_relative_to(cache_root.resolve()) or root == cache_root.resolve():
            raise ValueError("Cache path is outside the dedicated cache tree")
        today = today or datetime.now(timezone(timedelta(hours=8))).date()
        cutoff = today - timedelta(days=dataset.keep_days - 1)
        selected = []
        # Publishers must use this same lock when writing a cache partition.
        with file_lock(root / ".writer.lock"):
            for child in sorted(root.glob("????-??-??")):
                if not child.is_dir() or child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                    continue
                try:
                    day = date.fromisoformat(child.name)
                except ValueError:
                    continue
                if day >= cutoff:
                    continue
                target = contained(root, child.name)
                # Reparse points anywhere in a partition are never traversed/deleted.
                if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in target.rglob("*")):
                    raise ValueError("Cache partition contains a linked path")
                selected.append(str(target))
                if apply:
                    shutil.rmtree(target)
        return {"dataset": key, "before": cutoff.isoformat(), "applied": apply, "partitions": selected}
