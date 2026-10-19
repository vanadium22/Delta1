"""A small reference implementation of the dashboard_bars_v1 contract.

One dataset has one source/series/adjustment/unit policy. Files are immutable;
readers freeze a registered manifest and writers atomically replace current.json.
This is a reference store, not the production collector or a full PIT database.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

VERSION = "dashboard_bars_v1"
UTC = timezone.utc
BAR_SCHEMA = pa.schema([
    ("instrument_id", pa.string()), ("frequency", pa.string()),
    ("event_time", pa.timestamp("ns", "UTC")),
    ("bar_start", pa.timestamp("ns", "UTC")), ("trade_date", pa.date32()),
    ("session_id", pa.string()), ("source_symbol", pa.string()),
    *[(name, pa.float64()) for name in (
        "open", "high", "low", "close", "volume", "turnover", "open_interest",
        "settlement", "prev_close")],
    ("is_final", pa.bool_()), ("revision", pa.int64()),
    ("available_at", pa.timestamp("ns", "UTC")),
    ("recorded_at", pa.timestamp("ns", "UTC")),
    ("quality_flags", pa.uint32()), ("source_quality_flags", pa.uint32()),
    ("sample_count", pa.uint32()),
], metadata={b"schema_version": VERSION.encode()})
REQUIRED = {"instrument_id", "frequency", "event_time", "trade_date",
            "is_final", "revision", "recorded_at", "available_at", "quality_flags"}
NUMERIC = {"open", "high", "low", "close", "volume", "turnover", "open_interest",
           "settlement", "prev_close"}
TIME_FIELDS = {"event_time", "bar_start", "available_at", "recorded_at"}
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
INDEX_FUTURE = re.compile(r"(?:IF|IH|IC|IM)[0-9]{4}\.CFE\Z")


def utc_timestamp(value):
    value = pd.Timestamp(value)
    if pd.isna(value) or value.tzinfo is None:
        raise ValueError("时间必须包含时区，不能猜测本地时间")
    return value.tz_convert("UTC")


def normalize_bars(rows):
    """Validate rows without filling prices, volume, bar starts or availability."""
    result = []
    for original in rows:
        missing, extra = REQUIRED - original.keys(), original.keys() - set(BAR_SCHEMA.names)
        if missing or extra:
            raise ValueError(f"字段不符合 {VERSION}: missing={sorted(missing)}, extra={sorted(extra)}")
        row = {name: original.get(name) for name in BAR_SCHEMA.names}
        if not isinstance(row["instrument_id"], str) or not SAFE_ID.fullmatch(row["instrument_id"]):
            raise ValueError("instrument_id 必须是安全的规范代码，不能包含路径")
        if row["frequency"] not in {"1d", "1m", "1s"}:
            raise ValueError("此版本只接受 1d / 1m / 1s bar；轮询观测不能冒充 bar")
        for name in TIME_FIELDS:
            if row[name] is not None:
                row[name] = utc_timestamp(row[name])
        if row["event_time"] is None or row["recorded_at"] is None:
            raise ValueError("event_time / recorded_at 不能为空")
        if isinstance(row["trade_date"], str):
            row["trade_date"] = date.fromisoformat(row["trade_date"])
        if not isinstance(row["trade_date"], date) or isinstance(row["trade_date"], datetime):
            raise ValueError("trade_date 必须是交易日 date 或 YYYY-MM-DD")
        if type(row["is_final"]) is not bool or type(row["revision"]) is not int or row["revision"] < 0:
            raise ValueError("is_final 必须为 bool，revision 必须为非负整数")
        for name in ("quality_flags", "source_quality_flags", "sample_count"):
            if row[name] is not None and (type(row[name]) is not int or not 0 <= row[name] < 2**32):
                raise ValueError(f"{name} 必须是 uint32")
        if row["quality_flags"] is None:
            raise ValueError("quality_flags 不能为空")
        for name in NUMERIC:
            value = row[name]
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{name} 必须为有限数值或 null")
                row[name] = float(value)
        for name in ("volume", "turnover", "open_interest"):
            if row[name] is not None and row[name] < 0:
                raise ValueError(f"{name} 不能为负；未知值请留 null")
        if row["bar_start"] is not None:
            duration = (row["event_time"] - row["bar_start"]).total_seconds()
            if duration <= 0 or (row["frequency"] != "1d" and duration != {"1m": 60, "1s": 1}[row["frequency"]]):
                raise ValueError("bar_start 与区间结束时间不符合频率")
        if row["available_at"] is not None and row["available_at"] < row["event_time"]:
            raise ValueError("available_at 不能早于 bar 结束")
        if row["high"] is not None and row["low"] is not None:
            if row["high"] < row["low"]:
                raise ValueError("high 不能小于 low")
            if any(row[n] is not None and not row["low"] <= row[n] <= row["high"] for n in ("open", "close")):
                raise ValueError("open / close 不在 low / high 范围内")
        result.append(row)
    return pa.Table.from_pylist(result, schema=BAR_SCHEMA)


def _json_value(value):
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _json_bytes(value):
    return json.dumps(value, default=_json_value, sort_keys=True,
                      ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows readers / antivirus can briefly deny DELETE sharing. Keep the
        # old complete file visible and retry the atomic rename, never truncate.
        for attempt in range(12):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 11:
                    raise
                time.sleep(min(0.025 * 2 ** attempt, 0.3))
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def _writer_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / "writer.lock").open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _row_key(row):
    # A daily timestamp may itself be corrected; its logical key is trade_date.
    stamp = row["trade_date"] if row["frequency"] == "1d" else row["event_time"]
    return row["instrument_id"], row["frequency"], stamp


def _payload(row):
    # Re-fetching identical data today does not create a new revision.
    return _json_bytes({k: v for k, v in row.items() if k != "recorded_at"})


def validate_instruments(instruments):
    if not isinstance(instruments, dict) or not instruments:
        raise ValueError("必须定义国内指数 / 股指期货标的注册表")
    for symbol, info in instruments.items():
        if not isinstance(symbol, str) or not SAFE_ID.fullmatch(symbol) or not isinstance(info, dict) or info.get("market_region") != "CN":
            raise ValueError("本模块只接收注册的国内标的")
        kind = info.get("asset_type")
        if kind not in {"cn_index", "cn_index_future"}:
            raise ValueError("本模块范围仅为 A 股指数和股指期货")
        if kind == "cn_index_future" and (not INDEX_FUTURE.fullmatch(symbol) or not 1 <= int(symbol.split('.')[0][-2:]) <= 12):
            raise ValueError("股指期货 bar 必须使用 IF/IH/IC/IM 的具体年月合约")


class BarDataset:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self._verified_parts = {}

    def _path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("目录索引包含越界路径")
        return path

    @classmethod
    def create(cls, root, descriptor):
        required = {"dataset_id", "source_id", "series_kind", "price_adjustment",
                    "volume_unit", "availability_policy", "instruments"}
        if not required <= descriptor.keys():
            raise ValueError(f"dataset.json 缺少 {sorted(required-descriptor.keys())}")
        if not isinstance(descriptor["dataset_id"], str) or not SAFE_ID.fullmatch(descriptor["dataset_id"]):
            raise ValueError("dataset_id 格式无效")
        validate_instruments(descriptor["instruments"])
        descriptor = {**descriptor, "schema_version": VERSION, "timezone": "UTC",
                      "timestamp_semantics": "bar_end"}
        store = cls(root)
        with _writer_lock(store.root):
            path = store.root / "dataset.json"
            if path.exists():
                if json.loads(path.read_text(encoding="utf-8")) != descriptor:
                    raise ValueError("已有数据集身份、复权或单位口径不同，请创建另一 dataset_id / 目录")
            else:
                _atomic_bytes(path, _json_bytes(descriptor))
        return store

    @property
    def descriptor(self):
        return json.loads((self.root / "dataset.json").read_text(encoding="utf-8"))

    def register_instruments(self, instruments):
        """Append new contracts without changing existing instrument semantics.

        Listing/expiry and historical knowledge still belong in a separate,
        verified reference dataset. A registration is not listing evidence.
        """
        validate_instruments(instruments)
        with _writer_lock(self.root):
            descriptor = self.descriptor
            combined = dict(descriptor["instruments"])
            for symbol, info in instruments.items():
                if symbol in combined and combined[symbol] != info:
                    raise ValueError("已注册标的口径不能原地修改，请创建新数据集")
                combined[symbol] = info
            if combined != descriptor["instruments"]:
                _atomic_bytes(self.root / "dataset.json", _json_bytes({**descriptor,"instruments":combined}))
        return combined

    def snapshot(self, version=None):
        if version is None:
            pointer = self.root / "current.json"
            if not pointer.exists():
                return {"version": None, "parts": [], "checkpoint": {}}
            ref = json.loads(pointer.read_text(encoding="utf-8"))
        else:
            if not re.fullmatch(r"[0-9a-f]{32}", version):
                raise ValueError("version 格式无效")
            ref = {"manifest": f"versions/{version}.json"}
        data = self._path(ref["manifest"]).read_bytes()
        if ref.get("sha256") and hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("manifest 哈希不匹配")
        manifest = json.loads(data)
        if manifest["dataset_id"] != self.descriptor["dataset_id"]:
            raise ValueError("manifest 数据集身份不一致")
        return manifest

    def _rows(self, manifest, symbols=None, frequency=None, start=None, end=None, columns=None):
        rows = []
        for part in manifest["parts"]:
            if symbols is not None and part["instrument_id"] not in symbols:
                continue
            if frequency and part["frequency"] != frequency:
                continue
            if start is not None and utc_timestamp(part["max_time"]) < start:
                continue
            if end is not None and utc_timestamp(part["min_time"]) > end:
                continue
            filters = []
            if start is not None:
                filters.append(("event_time", ">=", pa.scalar(start, type=pa.timestamp("ns", "UTC"))))
            if end is not None:
                filters.append(("event_time", "<=", pa.scalar(end, type=pa.timestamp("ns", "UTC"))))
            path = self._path(part["path"])
            stat = path.stat()
            token = (stat.st_size, stat.st_mtime_ns, part["sha256"])
            if self._verified_parts.get(str(path)) != token:
                if hashlib.sha256(path.read_bytes()).hexdigest() != part["sha256"]:
                    raise ValueError(f"行情分片哈希不匹配: {path}")
                self._verified_parts[str(path)] = token
            rows.extend(pq.read_table(path, columns=columns,
                                      filters=filters or None).to_pylist())
        return rows

    def commit(self, rows, checkpoint=None, *, publish=True, base_version=None):
        incoming = normalize_bars(rows).to_pylist()
        if not incoming:
            return {"version": self.snapshot()["version"], "inserted": 0}
        descriptor = self.descriptor  # Require explicit identity before writing.
        for row in incoming:
            if row["instrument_id"] not in descriptor["instruments"]:
                raise ValueError("标的未注册，拒绝写入非本次范围的数据")
        with _writer_lock(self.root):
            previous = self.snapshot(base_version)
            relevant = {(r["instrument_id"], r["frequency"], r["trade_date"].isoformat()) for r in incoming}
            ranges = {}
            for row in incoming:
                pair = row["instrument_id"], row["frequency"]
                lo, hi = ranges.get(pair, (row["event_time"], row["event_time"]))
                ranges[pair] = min(lo, row["event_time"]), max(hi, row["event_time"])
            def touches(part):
                if (part["instrument_id"], part["frequency"], part["trade_date"]) in relevant:
                    return True
                interval = ranges.get((part["instrument_id"], part["frequency"]))
                return (part["frequency"] != "1d" and interval is not None
                        and utc_timestamp(part["min_time"]) <= interval[1]
                        and utc_timestamp(part["max_time"]) >= interval[0])
            subset = {**previous, "parts": [p for p in previous["parts"]
                      if touches(p)]}
            seen = {(_row_key(r), r["revision"]): _payload(r) for r in self._rows(subset)}
            accepted = []
            for row in incoming:
                key, payload = (_row_key(row), row["revision"]), _payload(row)
                if key in seen:
                    if seen[key] != payload:
                        raise ValueError("相同逻辑键和 revision 出现不同内容；请核验来源并明确递增 revision")
                    continue
                seen[key] = payload
                accepted.append(row)
            if not accepted:
                return {"version": previous["version"], "inserted": 0}
            groups = {}
            for row in accepted:
                key = row["instrument_id"], row["frequency"], row["trade_date"]
                groups.setdefault(key, []).append(row)
            parts = list(previous["parts"])
            for (symbol, frequency, day), items in sorted(groups.items()):
                items.sort(key=lambda r: (r["event_time"], r["revision"]))
                table = pa.Table.from_pylist(items, schema=BAR_SCHEMA)
                sink = pa.BufferOutputStream()
                pq.write_table(table, sink, compression="zstd")
                data = sink.getvalue().to_pybytes()
                digest = hashlib.sha256(data).hexdigest()
                relative = f"data/{frequency}/{symbol}/{day:%Y/%m}/{day}.{digest}.parquet"
                target = self._path(relative)
                if not target.exists():
                    _atomic_bytes(target, data)
                parts.append({"path": relative, "sha256": digest, "rows": len(items),
                              "instrument_id": symbol, "frequency": frequency,
                              "trade_date": day.isoformat(), "min_time": items[0]["event_time"].isoformat(),
                              "max_time": items[-1]["event_time"].isoformat()})
            version = uuid.uuid4().hex
            manifest = {"schema_version": VERSION, "dataset_id": self.descriptor["dataset_id"],
                        "descriptor": self.descriptor,
                        "version": version, "previous_version": previous["version"],
                        "committed_at": datetime.now(UTC).isoformat(), "parts": parts,
                        "checkpoint": checkpoint if checkpoint is not None else previous["checkpoint"]}
            data = _json_bytes(manifest)
            relative = f"versions/{version}.json"
            _atomic_bytes(self._path(relative), data)
            if publish:
                _atomic_bytes(self.root / "current.json", _json_bytes({"version": version,
                              "manifest": relative, "sha256": hashlib.sha256(data).hexdigest()}))
            return {"version": version, "inserted": len(accepted)}

    def read_bars(self, symbols, frequency, *, start=None, end=None, as_of=None,
                  knowledge_at=None, fields=None, include_partial=False,
                  allow_unverified_availability=False, version=None):
        """Latest eligible revision; end/as_of are inclusive UTC bar-end bounds.

        as_of is market availability time. knowledge_at additionally restricts
        ingestion knowledge. Without it, this is revised research history, not PIT.
        Unknown availability is excluded unless the caller explicitly opts in.
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        if frequency not in {"1d", "1m", "1s"}:
            raise ValueError("frequency 无效")
        start, end = (utc_timestamp(v) if v is not None else None for v in (start, end))
        as_of = utc_timestamp(as_of) if as_of is not None else None
        knowledge_at = utc_timestamp(knowledge_at) if knowledge_at is not None else None
        manifest = self.snapshot(version)
        # Filter eligibility before choosing a revision: a future revision must
        # not hide a prior revision that was already available at as_of.
        columns = None
        if fields is not None:
            unknown = set(fields) - set(BAR_SCHEMA.names)
            if unknown:
                raise ValueError(f"未知字段: {sorted(unknown)}")
            columns = list(dict.fromkeys(["instrument_id", "frequency", "event_time", "trade_date",
                            "available_at", "recorded_at", "revision", "is_final", *fields]))
        source, query_start, query_end = manifest, start, end
        if frequency == "1d" and (start is not None or end is not None):
            # All revisions of a daily key must participate even if a corrected
            # close label moves beyond the requested event-time window.
            candidates = {(p["instrument_id"],p["trade_date"]) for p in manifest["parts"]
                if p["instrument_id"] in symbols and p["frequency"]==frequency
                and (start is None or utc_timestamp(p["max_time"])>=start)
                and (end is None or utc_timestamp(p["min_time"])<=end)}
            source = {**manifest,"parts":[p for p in manifest["parts"]
                      if (p["instrument_id"],p["trade_date"]) in candidates]}
            query_start,query_end = None,None
        rows = self._rows(source, set(symbols), frequency, query_start, query_end, columns)
        latest = {}
        for row in rows:
            if as_of is not None and row["event_time"] > as_of:
                continue
            if knowledge_at is not None and row["recorded_at"] > knowledge_at:
                continue
            if row["available_at"] is None:
                if not allow_unverified_availability:
                    continue
            elif as_of is not None and row["available_at"] > as_of:
                continue
            key = _row_key(row)
            if key not in latest or row["revision"] > latest[key]["revision"]:
                latest[key] = row
        values = [r for r in latest.values() if (include_partial or r["is_final"])
                  and (start is None or r["event_time"]>=start)
                  and (end is None or r["event_time"]<=end)]
        values.sort(key=lambda r: (r["event_time"], r["instrument_id"]))
        frame = pa.Table.from_pylist(values, schema=BAR_SCHEMA).to_pandas()
        if fields is not None:
            frame = frame[list(dict.fromkeys(["instrument_id", "frequency", "event_time", "trade_date", *fields]))]
        frame.attrs.update(dataset=manifest.get("descriptor",self.descriptor), version=manifest["version"],
                           availability_unverified=allow_unverified_availability,
                           ingestion_cutoff_applied=knowledge_at is not None)
        return frame
