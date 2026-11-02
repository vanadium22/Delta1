"""Read existing registered dashboard data, or user-supplied wide matrices."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .models import (BacktestError, DataConfig, MarketData, DEFAULT_MULTIPLIERS,
                     INDEX_SYMBOLS, check_cancelled, normalize_frame, normalize_symbol, time_bound)


DASHBOARD_ROOT = Path(__file__).resolve().parents[1]


def read_frame(path, *, trusted_pickle=False) -> pd.DataFrame:
    """An explicit timestamp/date column or a stored datetime index is required."""
    path = Path(path).expanduser().resolve()
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
    native_path = Path(config.dashboard_config_path or DASHBOARD_ROOT / "localsetting/native.json").resolve()
    native = {}
    if not config.data_root and not config.history_roots and not config.close_path and native_path.is_file():
        raw = json.loads(native_path.read_text(encoding="utf-8-sig"))
        native = {k: raw.get(k) for k in ("history_roots", "reference_file", "dividend_root")}
    roots = list(config.history_roots or native.get("history_roots") or [])
    if not roots and not config.close_path:
        base = Path(config.data_root).expanduser().resolve() if config.data_root else DASHBOARD_ROOT.parent / "data"
        normalized = base / "market/index_futures/dashboard/normalized"
        for kind in ("cn_index", "cn_index_future"):
            candidates = [normalized / ("backfilled_" + kind), normalized / kind]
            selected = next((p for p in candidates if (p / "current.json").is_file()), None)
            if selected:
                roots.append(selected)
    def resolve(value):
        if not value:
            return None
        return str(Path(value).expanduser().resolve())
    dividend = config.dividend_root or native.get("dividend_root")
    if not dividend and config.data_root:
        dividend = Path(config.data_root) / "dividends/index_futures/inputs"
    return dict(history_roots=[resolve(p) for p in roots],
                reference_path=resolve(config.reference_path or native.get("reference_file")),
                dividend_root=resolve(dividend),
                dashboard_config_path=str(native_path) if native else None)


def _store(root):
    # Only the existing read-only reader is reused, never the collection service.
    from ..marketdata.bars import BarDataset
    return BarDataset(root)


def _reference(path):
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    contracts = {}
    for row in sorted(raw.get("contracts", []), key=lambda r: r.get("known_at", "")):
        symbol = row["instrument_id"]
        previous = contracts.get(symbol)
        if previous and previous.get("known_at") == row.get("known_at") and any(
            previous.get(k) != row.get(k) for k in ("listing_date", "expiry_date")
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
    return normalize_frame(read_frame(path, trusted_pickle=config.trusted_pickle), label=label,
                           timezone=timezone, date_at=date_at)


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
    if config.close_path:
        close = _wide(config.close_path, config, label="close", timezone=timezone)
        metadata["close_path"] = str(Path(config.close_path).resolve())
    else:
        if not paths["history_roots"]:
            raise BacktestError("No history found; set data_root, history_roots, or close_path")
        chunks = []
        for root in paths["history_roots"]:
            check_cancelled(cancel_event)
            if progress:
                progress(dict(stage="loading", message="正在读取本地行情", source=root))
            store = _store(root)
            snapshot = store.snapshot()
            descriptor = snapshot.get("descriptor", store.descriptor)
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
                                             availability_policy=descriptor.get("availability_policy"), rows=len(frame)))
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
    multiplier = (_wide(config.multiplier_path, config, label="multiplier", timezone=timezone, date_at="00:00")
                  if config.multiplier_path else {**DEFAULT_MULTIPLIERS, **config.multipliers})
    margin = (_wide(config.margin_rate_path, config, label="margin_rate", timezone=timezone, date_at="00:00")
              if config.margin_rate_path else dict(config.margin_rates))
    metadata["margin_source"] = str(Path(config.margin_rate_path).resolve()) if config.margin_rate_path else dict(config.margin_rates)
    metadata["multiplier_source"] = str(Path(config.multiplier_path).resolve()) if config.multiplier_path else multiplier
    adjusted = None
    if config.adjusted_close_path:
        adjusted = _wide(config.adjusted_close_path, config, label="adjusted_close", timezone=timezone).reindex_like(close)
        metadata["dividend_source"] = str(Path(config.adjusted_close_path).resolve())
    elif config.dividend_points_path:
        points = _wide(config.dividend_points_path, config, label="dividend_points", timezone=timezone)
        # Daily values apply on that date only, without filling an unobserved day.
        if all(t == t.normalize() + pd.Timedelta(hours=15) for t in points.index):
            points.index = points.index.normalize()
            points = points.reindex(close.index.normalize())
            points.index = close.index
        adjusted = close + points.reindex_like(close)
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
    return MarketData(close, multiplier, margin, adjusted, contracts, metadata)


def audit_data(config: DataConfig | None = None) -> dict:
    """Inspect the frozen active manifests, not orphan parquet files or live services."""
    config = config or DataConfig()
    paths = resolve_paths(config)
    report = dict(paths=paths, frequency=config.frequency, coverage=[], datasets=[],
                  spot_mapping={v: k for k, v in INDEX_SYMBOLS.items()},
                  margin_rate_path=str(config.margin_rate_path) if config.margin_rate_path else None,
                  configured_margin_rates=dict(config.margin_rates), multipliers={**DEFAULT_MULTIPLIERS, **config.multipliers},
                  missing=[], notes=[])
    if config.close_path:
        frame = _wide(config.close_path, config, label="close", timezone="Asia/Shanghai")
        for symbol in frame:
            valid = frame[symbol].dropna()
            report["coverage"].append(dict(symbol=symbol, rows=len(valid), start=str(valid.index.min()), end=str(valid.index.max())))
    for root in paths["history_roots"]:
        store = _store(root)
        snapshot = store.snapshot()
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
    if config.adjusted_close_path or config.dividend_points_path:
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
