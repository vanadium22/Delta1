"""Read existing registered dashboard data, or user-supplied wide matrices."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .models import (BacktestError, DataConfig, MarketData, DEFAULT_MULTIPLIERS,
                     INDEX_SYMBOLS, check_cancelled, check_market_source, normalize_frame, normalize_symbol, time_bound)


DASHBOARD_ROOT = Path(__file__).resolve().parents[1]


def read_frame(path, *, trusted_pickle=False) -> pd.DataFrame:
    """An explicit timestamp/date column or a stored datetime index is required."""
    from .models import check_source_paths
    check_source_paths(path)
    path = Path(path).expanduser().resolve()
    check_source_paths(path)
    if not path.is_file():
        raise BacktestError(f"Input does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif suffix in {".csv", ".tsv"}:
        frame = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",", encoding="utf-8-sig")
    elif suffix == ".feather":
        frame = pd.read_feather(path)
    elif suffix in {".pkl", ".pickle"}:
        if not trusted_pickle:
            raise BacktestError(f"Pickle requires trusted_pickle=True for this locally trusted input: {path}")
        frame = pd.read_pickle(path)
    else:
        raise BacktestError(f"Unsupported input format {suffix}: use parquet/csv/tsv/feather or trusted pickle")
    if not isinstance(frame, pd.DataFrame):
        raise BacktestError(f"Expected DataFrame in {path}")
    for column in ("timestamp", "date", "datetime", "event_time", "Unnamed: 0"):
        if column in frame.columns:
            frame = frame.set_index(column)
            break
    if isinstance(frame.index, pd.RangeIndex):
        raise BacktestError(f"Missing timestamp/date column or stored index in {path}")
    return frame


def resolve_paths(config: DataConfig) -> dict:
    """Select existing paths without modifying native.json or inheriting credentials."""
    native_path = Path(config.dashboard_config_path).resolve() if config.dashboard_config_path else None
    native = {}
    supplied = config.close_path or config.minute_close_path or config.daily_close_path
    if native_path is not None:
        if not native_path.is_file():
            raise BacktestError(f"Configured legacy dashboard configuration does not exist: {native_path}")
        raw = json.loads(native_path.read_text(encoding="utf-8-sig"))
        native = {k: raw.get(k) for k in ("history_roots", "reference_file", "dividend_root")}
    roots = list(config.history_roots or native.get("history_roots") or [])
    if not roots and not supplied:
        if not config.data_root:
            raise BacktestError("No data source configured: set data_root, history_roots or wide price paths; implicit native discovery is disabled")
        base = Path(config.data_root).expanduser().resolve()
        normalized = base / "market/index_futures/dashboard/normalized"
        for kind in ("cn_index", "cn_index_future"):
            candidates = [normalized / kind]
            selected = None
            for candidate in candidates:
                if not (candidate / "current.json").is_file():
                    continue
                check_market_source(_store(candidate).descriptor)
                selected = candidate
                break
            if selected:
                roots.append(selected)
    def resolve(value):
        if not value:
            return None
        base = native_path.parent if native_path else Path(config.data_root or Path.cwd())
        return str((base / Path(value).expanduser()).resolve())
    dividend = config.dividend_root or native.get("dividend_root")
    if not dividend and config.data_root:
        dividend = Path(config.data_root) / "dividends/index_futures/inputs"
    from .models import check_source_paths
    check_source_paths([roots, config.reference_path or native.get("reference_file"), dividend])
    resolved_roots = [resolve(p) for p in roots]
    if len({Path(p) for p in resolved_roots}) != len(resolved_roots):
        raise BacktestError("Duplicate history_roots paths")
    files = {name: str(Path(getattr(config, name)).resolve()) for name in config.__dataclass_fields__
             if name.endswith("_path") and getattr(config, name)}
    return dict(history_roots=resolved_roots,
                reference_path=resolve(config.reference_path or native.get("reference_file")),
                dividend_root=resolve(dividend),
                dashboard_config_path=str(native_path) if native else None, files=files,
                dataset_id=config.dataset_id, data_version=config.data_version, source_id=config.source_id,
                history_versions=dict(config.history_versions))


def frozen_snapshot(store, config):
    snapshot = store.snapshot(config.history_versions.get(str(store.root.resolve())))
    check_market_source(snapshot.get("descriptor", store.descriptor))
    return snapshot


def input_manifest(config, paths, close):
    """Small reproducibility manifest; no market values or credential-bearing config."""
    files = {}
    declared = dict(paths.get("files", {}))
    if paths.get("reference_path"):
        declared["reference_path"] = paths["reference_path"]
    for name, value in declared.items():
        if name == "dashboard_config_path":
            files[name] = dict(path=value)
            continue
        path = Path(value)
        if not path.is_file():
            raise BacktestError(f"Configured input does not exist: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        files[name] = dict(path=value, bytes=path.stat().st_size, sha256=digest.hexdigest())
    coverage = []
    for symbol in close:
        valid = close[symbol].dropna()
        coverage.append(dict(symbol=symbol, rows=len(valid), start=str(valid.index.min()), end=str(valid.index.max())))
    return dict(dataset_id=config.dataset_id, data_version=config.data_version, source_id=config.source_id,
                paths=paths, files=files, coverage=coverage, dividend_mode=config.dividend_mode,
                daily_label_time=config.daily_label_time, timezone="Asia/Shanghai")


def _store(root):
    # Only the existing read-only reader is reused, never the collection service.
    from ..marketdata.bars import BarDataset
    return BarDataset(root)


def _reference(path):
    if not path:
        return {}
    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = raw.get("contracts", []) if isinstance(raw, dict) else raw
    elif path.suffix.lower() in {".parquet", ".csv", ".tsv"}:
        rows = (pd.read_parquet(path) if path.suffix.lower() == ".parquet" else
                pd.read_csv(path, sep="\t" if path.suffix.lower() == ".tsv" else ",")).to_dict("records")
        required = {"instrument_id", "root", "listing_date", "expiry_date"}
        if not rows or any(required - set(row) or any(pd.isna(row[k]) for k in required) for row in rows):
            raise BacktestError("Standard reference requires instrument_id, root, listing_date and expiry_date in every row")
    else:
        raise BacktestError("Contract reference must use parquet, csv, tsv or legacy JSON")
    contracts = {}
    for original in sorted(rows, key=lambda r: str(r.get("known_at", ""))):
        row = {k: v for k, v in original.items() if pd.notna(v)}
        symbol = normalize_symbol(row.get("instrument_id", row.get("symbol", "")))
        if not symbol.endswith(".CFE"):
            raise BacktestError("Contract reference requires actual futures codes")
        row["instrument_id"] = symbol
        if row.get("root", symbol[:2]) != symbol[:2]:
            raise BacktestError(f"Contract root conflicts with actual symbol: {symbol}")
        row["root"] = symbol[:2]
        for key in ("listing_date", "expiry_date"):
            if row.get(key):
                row[key] = str(pd.Timestamp(row[key]).date())
        if row.get("listing_date") and row.get("expiry_date") and row["listing_date"] > row["expiry_date"]:
            raise BacktestError(f"Invalid listing/expiry interval: {symbol}")
        previous = contracts.get(symbol)
        if previous and previous.get("known_at") == row.get("known_at") and any(
            previous.get(k) != row.get(k) for k in ("listing_date", "expiry_date", "root", "multiplier")
        ):
            raise BacktestError(f"Conflicting reference versions for {symbol} in {path}")
        contracts[symbol] = row
    return contracts


def parameter_frame(value, close: pd.DataFrame, *, kind: str, timezone="Asia/Shanghai") -> pd.DataFrame:
    """Reference parameters may carry forward from effective time, never prices."""
    if isinstance(value, pd.DataFrame):
        source = normalize_frame(value, label=kind, timezone=timezone, date_at="00:00")
        # Forward propagation is an explicit effective-until-replaced parameter policy.
        # Carry the last effective row. An explicitly missing value stays missing,
        # including after that row, instead of resurrecting an older rate.
        result = source.reindex(index=close.index, method="ffill").reindex(columns=close.columns)
        for symbol in result.columns:
            if symbol.endswith("_spot"):
                result[symbol] = 1.0
        return result
    result = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for symbol in close.columns:
        if symbol.endswith("_spot"):
            result[symbol] = 1.0  # fully funded synthetic index units
            continue
        rate = value.get(symbol, value.get(symbol[:2]))
        if rate is not None:
            result[symbol] = float(rate)
    return result


def _wide(path, config, *, label, timezone, date_at="15:00"):
    raw = read_frame(path, trusted_pickle=config.trusted_pickle)
    if date_at == "15:00":
        date_at = config.daily_label_time
    frame = normalize_frame(raw, label=label, timezone=timezone, date_at=date_at)
    if date_at is not None:
        clock = pd.Timedelta(date_at + (":00" if len(date_at) == 5 else ""))
        frame.index = frame.index.where(frame.index != frame.index.normalize(), frame.index + clock)
    if frame.index.duplicated().any():
        raise BacktestError(f"{label} has duplicate timestamps after date label conversion")
    return frame.sort_index()


def align_dividend_points(points, close):
    days = points.index.normalize()
    daily = (points.index == days) | (points.index == days + pd.Timedelta(hours=15))
    if daily.all():
        if days.duplicated().any():
            raise BacktestError("Daily dividend points must contain one row per date")
        points = points.copy(deep=False)
        points.index = days
        points = points.reindex(close.index.normalize())
        points.index = close.index
    return points.reindex_like(close)


def load_market_data(config: DataConfig | None = None, *, symbols=None, start=None, end=None,
                     timezone="Asia/Shanghai", cancel_event=None, progress=None) -> MarketData:
    config = config or DataConfig()
    check_cancelled(cancel_event)
    paths = resolve_paths(config)
    selected = set(normalize_symbol(s) for s in symbols) if symbols is not None else None
    if selected is not None:
        selected.update(s[:2] + "_spot" for s in list(selected))
    left, right = time_bound(start, timezone=timezone), time_bound(end, end=True, timezone=timezone)
    metadata = dict(source="wide_files" if config.close_path else "dashboard_registered_history",
                    paths=paths, datasets=[], warnings=[], price_forward_fill=False)
    price_path = config.close_path or (config.daily_close_path if config.frequency == "1d" else config.minute_close_path)
    price_path = price_path or config.minute_close_path or config.daily_close_path
    if price_path:
        close = _wide(price_path, config, label="close", timezone=timezone,
                      date_at=None if price_path == config.minute_close_path else config.daily_label_time)
        if price_path == config.daily_close_path and close.index.normalize().duplicated().any():
            raise BacktestError("daily_close_path must contain at most one close timestamp per day")
        metadata["close_path"] = str(Path(price_path).resolve())
    else:
        if not paths["history_roots"]:
            raise BacktestError("No history found; set data_root, history_roots, or close_path")
        chunks = []
        for root in paths["history_roots"]:
            check_cancelled(cancel_event)
            if progress:
                progress(dict(stage="loading", message="正在读取本地行情", source=root))
            store = _store(root)
            snapshot = frozen_snapshot(store, config)
            descriptor = snapshot.get("descriptor", store.descriptor)
            check_market_source(descriptor)
            if descriptor.get("price_adjustment") != "none" or descriptor.get("series_kind") != "concrete":
                raise BacktestError(f"Executable close requires unadjusted concrete series: {root}")
            available = descriptor["instruments"]
            source_symbols = [s for s in available if selected is None or normalize_symbol(s) in selected]
            if not source_symbols:
                continue
            unverified = descriptor.get("availability_policy") == "unknown"
            if unverified and not config.allow_unverified_availability:
                raise BacktestError("Existing history has unknown historical availability; set "
                                    "allow_unverified_availability=True to explicitly use revised research history")
            frame = store.read_bars(source_symbols, config.frequency, start=left, end=right,
                                    fields=["close"], version=snapshot["version"],
                                    allow_unverified_availability=config.allow_unverified_availability)
            check_cancelled(cancel_event)
            if not frame.empty:
                chunks.append(frame[["event_time", "instrument_id", "close"]])
            metadata["datasets"].append(dict(root=str(store.root), version=snapshot["version"],
                                             availability_policy=descriptor.get("availability_policy"), source_id=descriptor.get("source_id"), rows=len(frame)))
            if unverified:
                metadata["warnings"].append("Revised research history; historical publication time is unknown, not a PIT replay")
        if not chunks:
            raise BacktestError(f"No close observations for the selected symbols, frequency and interval: {paths['history_roots']}")
        long = pd.concat(chunks, ignore_index=True)
        long["instrument_id"] = long.instrument_id.map(normalize_symbol)
        if long.duplicated(["event_time", "instrument_id"]).any():
            raise BacktestError("Overlapping history_roots contain duplicate bars; choose one active dataset per source")
        close = normalize_frame(long.pivot(index="event_time", columns="instrument_id", values="close"),
                                label="close", timezone=timezone)
    if selected is not None:
        close = close.loc[:, close.columns.isin(selected)]
    if left is not None:
        close = close.loc[close.index >= left]
    if right is not None:
        close = close.loc[close.index <= right]
    if close.empty:
        raise BacktestError("No prices remain in the requested interval")
    for symbol in close.columns:
        invalid = close[symbol].notna() & (close[symbol] <= 0)
        if invalid.any():
            raise BacktestError(f"Non-positive close for {symbol} at {close.index[invalid][0]}")
    contracts = _reference(paths["reference_path"])
    multiplier = load_multipliers(config, contracts, timezone=timezone)
    margin = (_wide(config.margin_rate_path, config, label="margin_rate", timezone=timezone, date_at="00:00")
              if config.margin_rate_path else dict(config.margin_rates))
    metadata["margin_source"] = str(Path(config.margin_rate_path).resolve()) if config.margin_rate_path else dict(config.margin_rates)
    metadata["multiplier_source"] = multiplier_source(config)
    adjusted = None
    if config.adjusted_close_path:
        adjusted = _wide(config.adjusted_close_path, config, label="adjusted_close", timezone=timezone).reindex_like(close)
        metadata["dividend_source"] = str(Path(config.adjusted_close_path).resolve())
    elif config.dividend_points_path:
        points = _wide(config.dividend_points_path, config, label="dividend_points", timezone=timezone)
        # Daily values apply on that date only, without filling an unobserved day.
        adjusted = close + align_dividend_points(points, close)
        metadata["dividend_source"] = str(Path(config.dividend_points_path).resolve())
    elif config.dividend_policy != "none":
        from ..marketdata.dividends import read_snapshot
        if not paths["dividend_root"]:
            raise BacktestError("dividend_root is required for a dividend snapshot")
        snapshot = read_snapshot(paths["dividend_root"])
        adjusted = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for row in snapshot["rows"]:
            symbol = row["source_contract"]  # concrete code, never the rolling alias or the sheet's E-column date
            if symbol in close:
                mask = pd.Series(True, index=close.index)
                if config.dividend_policy == "asof_snapshot":
                    # A date-only snapshot has no verified intraday release time; use from the next calendar day.
                    mask = close.index.normalize() > pd.Timestamp(snapshot["date"]).tz_localize(timezone)
                adjusted.loc[mask, symbol] = close.loc[mask, symbol] + row["points"]
        metadata["dividend_source"] = dict(path=snapshot["path"], date=snapshot["date"],
                                           hash=snapshot["content_hash"], policy=config.dividend_policy)
        metadata["warnings"].append("Single dividend snapshot; incomplete contract coverage, not a daily historical dividend series")
        if config.dividend_policy == "fixed_scenario":
            metadata["warnings"].append("Fixed dividend scenario may use a later snapshot for earlier dates; scenario use only")
    if adjusted is None:
        metadata["warnings"].append("No dividend-adjusted prices loaded; raw close PnL is available")
    else:
        for symbol in close.columns:
            if symbol.endswith("_spot"):
                adjusted[symbol] = close[symbol]
    metadata["warnings"] = list(dict.fromkeys(metadata["warnings"]))
    check_cancelled(cancel_event)
    remaining = (_wide(config.days_to_expiry_path, config, label="days_to_expiry", timezone=timezone, date_at="00:00")
                 if config.days_to_expiry_path else None)
    metadata.update(input_manifest(config, paths, close))
    return MarketData(close, multiplier, margin, adjusted, contracts, metadata, days_to_expiry=remaining)


def load_multipliers(config, contracts, *, timezone="Asia/Shanghai"):
    if config.multiplier_path:
        return _wide(config.multiplier_path, config, label="multiplier", timezone=timezone, date_at="00:00")
    reference = {s: float(r["multiplier"]) for s, r in contracts.items() if r.get("multiplier") is not None}
    for symbol in reference:
        if symbol[:2] in config.multipliers:
            reference[symbol] = float(config.multipliers[symbol[:2]])
    return {**DEFAULT_MULTIPLIERS, **reference, **config.multipliers}


def multiplier_source(config):
    return dict(path=config.multiplier_path, policy="table exclusive; otherwise explicit symbol > explicit root > reference symbol > built-in root",
                builtin=dict(DEFAULT_MULTIPLIERS), overrides=dict(config.multipliers))


def audit_data(config: DataConfig | None = None) -> dict:
    """Inspect the frozen active manifests, not orphan parquet files or live services."""
    config = config or DataConfig()
    paths = resolve_paths(config)
    report = dict(paths=paths, frequency=config.frequency, coverage=[], datasets=[],
                  dataset_id=config.dataset_id, data_version=config.data_version, dividend_mode=config.dividend_mode,
                  spot_mapping={v: k for k, v in INDEX_SYMBOLS.items()},
                  margin_rate_path=str(config.margin_rate_path) if config.margin_rate_path else None,
                  configured_margin_rates=dict(config.margin_rates), multipliers={**DEFAULT_MULTIPLIERS, **config.multipliers},
                  missing=[], notes=[])
    table_paths = list(dict.fromkeys(str(p) for p in (config.minute_close_path, config.close_path, config.daily_close_path) if p))
    if table_paths:
        frames = [_wide(p, config, label="close", timezone="Asia/Shanghai",
                        date_at=None if p == config.minute_close_path else config.daily_label_time) for p in table_paths]
        frame = frames[0]
        for extra in frames[1:]:
            frame = frame.combine_first(extra)
        for symbol in frame:
            valid = frame[symbol].dropna()
            report["coverage"].append(dict(symbol=symbol, rows=len(valid), start=str(valid.index.min()), end=str(valid.index.max())))
    for root in paths["history_roots"] if not table_paths else []:
        store = _store(root)
        check_market_source(store.descriptor)
        snapshot = frozen_snapshot(store, config)
        grouped = defaultdict(list)
        for part in snapshot["parts"]:
            if part["frequency"] == config.frequency:
                grouped[normalize_symbol(part["instrument_id"])].append(part)
        report["datasets"].append(dict(root=str(store.root), version=snapshot["version"],
                                       availability_policy=store.descriptor.get("availability_policy")))
        for symbol, parts in sorted(grouped.items()):
            report["coverage"].append(dict(symbol=symbol, rows=sum(p["rows"] for p in parts),
                                            days=len({p["trade_date"] for p in parts}),
                                            start=min(p["min_time"] for p in parts), end=max(p["max_time"] for p in parts)))
    reference = _reference(paths["reference_path"])
    report["reference_contract_count"] = len(reference)
    report["reference_fields"] = sorted(set().union(*(r.keys() for r in reference.values()))) if reference else []
    if not config.margin_rate_path and not config.margin_rates:
        report["missing"].append("Historical margin rates: supply margin_rate_path or explicitly assumed margin_rates")
    if config.dividend_mode == "ignore":
        report["notes"].append("Explicit research assumption: D=0; missing observations have not been filled")
    elif config.adjusted_close_path or config.dividend_points_path:
        dividend_path = Path(config.adjusted_close_path or config.dividend_points_path).resolve()
        report["dividend_input"] = dict(path=str(dividend_path), exists=dividend_path.is_file())
        if not dividend_path.is_file():
            report["missing"].append("Configured dividend input file does not exist")
    elif paths["dividend_root"]:
        from ..marketdata.dividends import read_snapshot
        snapshot = read_snapshot(paths["dividend_root"])
        report["dividend_snapshot"] = dict(date=snapshot["date"], path=snapshot["path"], rows=snapshot["rows"])
        report["missing"].append("Complete daily dividend-adjusted prices; existing data is a single snapshot")
    else:
        report["missing"].append("Dividend-adjusted prices or dividend points")
    if not report["coverage"]:
        report["missing"].append("No registered price data at the requested frequency")
    report["notes"].append("Coverage is manifest-declared; run a bounded backtest to validate the selected price cells")
    report["notes"].append("No historical availability proof; existing revised history needs explicit opt-in")
    return report
