"""Read frozen daily closes and only the intraday partitions needed by a run."""
from collections import defaultdict
from dataclasses import replace
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .data import _store, _wide, resolve_paths
from .models import BacktestError, check_cancelled, normalize_symbol, time_bound
from .parallel import process_map, worker_cancel_event
from .timeline import daily_marks, effective_instructions, quote_timeline


FIELDS = ["instrument_id", "frequency", "event_time", "trade_date", "available_at", "recorded_at",
          "revision", "is_final", "close"]


def _read_parts(parts, allow_unverified):
    frames, read_rows = [], 0
    for root, part in parts:
        check_cancelled(worker_cancel_event())
        path = (Path(root) / part["path"]).resolve()
        if not path.is_relative_to(Path(root).resolve()):
            raise BacktestError("Registered part escapes its dataset root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != part["sha256"]:
            raise BacktestError(f"Registered price part hash mismatch: {path}")
        frame = pq.ParquetFile(path).read(columns=FIELDS).to_pandas()
        read_rows += len(frame)
        if len(frame) != part["rows"] or not frame.instrument_id.eq(part["instrument_id"]).all():
            raise BacktestError(f"Registered price part identity/row count mismatch: {path}")
        frames.append(frame)
    if not frames:
        return None, read_rows
    frame = pd.concat(frames, ignore_index=True)
    if not allow_unverified:
        frame = frame.loc[frame.available_at.notna()]
    frame = frame.loc[frame.is_final]
    keys = ["instrument_id", "trade_date" if frame.frequency.iloc[0] == "1d" else "event_time"] if len(frame) else []
    if not len(frame):
        return None, read_rows
    if frame.duplicated(keys + ["revision"]).any():
        conflicts = frame.groupby(keys + ["revision"], dropna=False).close.nunique(dropna=False)
        if (conflicts > 1).any():
            raise BacktestError("Conflicting registered revisions in price input")
    frame = frame.sort_values("revision", kind="stable").drop_duplicates(keys, keep="last")
    frame["instrument_id"] = frame.instrument_id.map(normalize_symbol)
    if frame.duplicated(["instrument_id", "event_time"]).any():
        raise BacktestError("Duplicate close timestamps across selected datasets")
    wide = frame.pivot(index="event_time", columns="instrument_id", values="close").sort_index()
    wide.index = pd.DatetimeIndex(wide.index).tz_convert("Asia/Shanghai").rename("timestamp")
    return wide, read_rows


def _reduce_first_quotes(frame, needed):
    if frame is None or frame.empty:
        return frame
    present = [c for c in needed if c in frame]
    # Retain the complete exceptional day when quotes have gaps; the account
    # then finds its actual first jointly valid quote, without guessing a fill.
    if present and (frame[present].isna() | frame[present].le(0)).any().any():
        return frame
    return frame.iloc[:1]


def _read_day(task):
    day_parts, minute_parts, allow_unverified, sparse, needed = task
    daily, daily_rows = _read_parts(day_parts, allow_unverified)
    minute, minute_rows = _read_parts(minute_parts, allow_unverified)
    if daily is not None and minute is not None:
        daily = daily.combine_first(daily_marks(minute).reindex(index=daily.index))
    if sparse:
        minute = _reduce_first_quotes(minute, needed)
    return daily, minute, daily_rows, minute_rows


def _plans(targets, calendar, precision, available_by_day=None):
    effective, _ = effective_instructions(targets, precision)
    days = pd.DatetimeIndex(calendar).normalize().unique().sort_values()
    minute_days, needed = set(), defaultdict(set)
    previous = set()
    for stamp, row in effective.iterrows():
        active = {s for s, value in row.items() if pd.notna(value) and value != 0}
        if precision == "1d":
            next_day = days.searchsorted(stamp.normalize(), side="right")
            required = previous | active
            # A calendar day supplied only by another contract/index cannot
            # consume a delayed entry's first-minute lookup.
            while available_by_day is not None and next_day < len(days):
                key = str(days[next_day].date())
                if required <= available_by_day.get(key, set()):
                    break
                next_day += 1
            if required and next_day < len(days):
                key = str(days[next_day].date())
                minute_days.add(key)
                needed[key].update(required)
        else:
            minute_days.add(str(stamp.date()))
            next_day = days.searchsorted(stamp.normalize(), side="right")
            if next_day < len(days):
                minute_days.add(str(days[next_day].date()))
        previous = active
    if precision == "auto":
        # Also scan quote days while a nonzero target is carried. Completely
        # flat days with no instructions need only their daily balance row.
        closes = days + pd.Timedelta(hours=15)
        carried = effective.reindex(closes, method="ffill").abs().gt(0).any(axis=1).to_numpy()
        active = carried | np.r_[False, carried[:-1]]
        minute_days.update(str(day.date()) for day in days[active])
    return minute_days, needed


def _wide_inputs(config, targets, run_config, left, right):
    generic = _wide(config.close_path, config, label="close", timezone=run_config.timezone) if config.close_path else None
    minute = (_wide(config.minute_close_path, config, label="minute close", timezone=run_config.timezone)
              if config.minute_close_path else None)
    daily = (_wide(config.daily_close_path, config, label="daily close", timezone=run_config.timezone)
             if config.daily_close_path else None)
    if minute is None:
        minute = generic
    elif generic is not None:
        if generic.index.normalize().duplicated().any() or daily is not None:
            raise BacktestError("close_path plus minute_close_path must provide one distinct daily table, or use daily_close_path")
        daily = generic
    if daily is not None and daily.index.normalize().duplicated().any():
        raise BacktestError("daily_close_path must have at most one close timestamp per day")
    if daily is None:
        daily = daily_marks(minute)
    if minute is None:
        minute = daily.copy()
    daily = daily.combine_first(daily_marks(minute).reindex(index=daily.index))
    effective, _ = effective_instructions(targets, run_config.precision)
    selected = set(effective.columns[effective.abs().gt(0).any(axis=0)]) | {s[:2] + "_spot" for s in targets}
    if not any(c in selected for c in daily.columns):
        selected.update(daily.columns[:1])  # A quote calendar for an entirely flat account.
    daily = daily.loc[:, daily.columns.isin(selected)]
    minute = minute.loc[:, minute.columns.isin(selected)]
    if left is not None:
        daily, minute = daily.loc[daily.index >= left], minute.loc[minute.index >= left]
    if right is not None:
        daily, minute = daily.loc[daily.index <= right], minute.loc[minute.index <= right]
    if daily.empty:
        raise BacktestError("No daily close observations in the selected interval")
    available = defaultdict(set)
    for frame in (daily, minute):
        for day, group in frame.groupby(frame.index.normalize(), sort=False):
            present = group.gt(0) & group.notna()
            available[str(day.date())].update(group.columns[present.any(axis=0)])
    minute_days, needed = _plans(targets, daily.index, run_config.precision, available)
    retained = []
    loaded_rows = len(minute)
    for day, group in minute.groupby(minute.index.normalize(), sort=True):
        key = str(day.date())
        if key not in minute_days:
            continue
        retained.append(_reduce_first_quotes(group, needed[key]) if run_config.precision == "1d" else group)
    intraday = pd.concat(retained) if retained else daily.iloc[:0]
    daily_only = not config.minute_close_path and not minute.index.normalize().duplicated().any() and (
        minute.index == minute.index.normalize() + pd.Timedelta(hours=15)).all()
    return daily, intraday, dict(source="wide_files", daily_rows_read=len(daily), minute_rows_read=loaded_rows,
                                minute_rows_retained=len(intraday), workers=1, daily_only_input=bool(daily_only))


def load_event_market_data(config, targets, run_config, *, cancel_event=None, progress=None):
    """Daily mode retains opening fills plus closes; auto retains risk quotes."""
    check_cancelled(cancel_event)
    paths = resolve_paths(config)
    left = time_bound(run_config.start, timezone=run_config.timezone)
    if left is None:
        left = targets.index.min()
    right = time_bound(run_config.end, end=True, timezone=run_config.timezone)
    data_files = config.close_path or config.minute_close_path or config.daily_close_path
    frozen = []
    if data_files:
        daily, minute, stats = _wide_inputs(config, targets, run_config, left, right)
    else:
        effective, _ = effective_instructions(targets, run_config.precision)
        selected = set(effective.columns[effective.abs().gt(0).any(axis=0)]) | {s[:2] + "_spot" for s in targets}
        daily_parts, minute_parts = defaultdict(list), defaultdict(list)
        owners = {}
        for root in paths["history_roots"]:
            store = _store(root)
            snapshot = store.snapshot()
            descriptor = snapshot.get("descriptor", store.descriptor)
            if descriptor.get("price_adjustment") != "none" or descriptor.get("series_kind") != "concrete":
                raise BacktestError(f"Execution requires raw concrete prices: {root}")
            if descriptor.get("availability_policy") == "unknown" and not config.allow_unverified_availability:
                raise BacktestError("Set allow_unverified_availability=True to explicitly use revised research history")
            frozen.append(dict(root=str(store.root), version=snapshot["version"],
                               availability_policy=descriptor.get("availability_policy")))
            for part in snapshot["parts"]:
                symbol = normalize_symbol(part["instrument_id"])
                if symbol not in selected or part["frequency"] not in {"1d", "1m"}:
                    continue
                day = part["trade_date"]
                if (left is not None and day < str(left.date())) or (right is not None and day > str(right.date())):
                    continue
                key = symbol, part["frequency"], day
                if key in owners and owners[key] != str(store.root):
                    raise BacktestError("Overlapping history_roots contain duplicate bars")
                owners[key] = str(store.root)
                bucket = daily_parts if part["frequency"] == "1d" else minute_parts
                bucket[day].append((str(store.root), part))
        calendar_days = sorted(set(daily_parts) | set(minute_parts))
        if not calendar_days:
            raise BacktestError("No registered daily/minute history in the requested interval")
        calendar = pd.DatetimeIndex(calendar_days).tz_localize(run_config.timezone)
        available = {day: {normalize_symbol(p["instrument_id"]) for _, p in daily_parts[day] + minute_parts[day]}
                     for day in calendar_days}
        minute_days, needed = _plans(targets, calendar, run_config.precision, available)
        jobs, units = [], 0
        for day in calendar_days:
            # If a day has no official daily table, read minutes to obtain that
            # day's last actually observed close, preserving its timestamp.
            daily_symbols = {p["instrument_id"] for _, p in daily_parts[day]}
            minute_symbols = {p["instrument_id"] for _, p in minute_parts[day]}
            missing_daily = minute_symbols - daily_symbols
            minute_refs = minute_parts[day] if day in minute_days or not daily_parts[day] or missing_daily else []
            sparse = run_config.precision == "1d" and bool(daily_parts[day])
            refs = daily_parts[day]
            jobs.append((refs, minute_refs, config.allow_unverified_availability, sparse, needed[day]))
            units += sum(p["rows"] for _, p in refs + minute_refs)
        values, worker_stats = process_map(_read_day, jobs, workers=run_config.workers, work_units=units,
                                          cancel_event=cancel_event, progress=progress, stage="loading_parallel")
        days, minutes = [], []
        daily_rows = minute_rows = 0
        for day_frame, minute_frame, n_day, n_minute in values:
            daily_rows += n_day
            minute_rows += n_minute
            if day_frame is None and minute_frame is not None:
                day_frame = daily_marks(minute_frame)
            if day_frame is not None:
                days.append(day_frame)
            if minute_frame is not None:
                minutes.append(minute_frame)
        if not days:
            raise BacktestError("No usable daily close observations")
        daily = pd.concat(days).sort_index()
        minute = pd.concat(minutes).sort_index() if minutes else daily.iloc[:0]
        stats = dict(source="registered_daily_minute", daily_rows_read=daily_rows,
                     minute_rows_read=minute_rows, minute_rows_retained=len(minute), **worker_stats)
    check_cancelled(cancel_event)
    if minute.empty:
        minute = daily.iloc[:0].copy()
    universe = daily.columns.union(minute.columns)
    daily, minute = daily.reindex(columns=universe), minute.reindex(columns=universe)
    close, fallback = quote_timeline(minute, daily)
    if stats.get("daily_only_input"):
        fallback.loc[minute.index] = minute.notna()
    if left is not None:
        close, fallback, daily = close.loc[close.index >= left], fallback.loc[fallback.index >= left], daily.loc[daily.index >= left]
    if right is not None:
        close, fallback, daily = close.loc[close.index <= right], fallback.loc[fallback.index <= right], daily.loc[daily.index <= right]
    # Reuse reference, multiplier, margin and dividend readers on the small
    # daily matrix. Do not re-read the raw market history or alter its paths.
    auxiliary = replace(config, close_path=None, minute_close_path=None, daily_close_path=None,
                        history_roots=(), data_root=None, dashboard_config_path=None,
                        reference_path=paths["reference_path"], dividend_root=paths["dividend_root"])
    from .data import _reference, _wide as read_wide
    from .models import DEFAULT_MULTIPLIERS, MarketData
    multiplier = (read_wide(auxiliary.multiplier_path, auxiliary, label="multiplier", timezone=run_config.timezone, date_at="00:00")
                  if auxiliary.multiplier_path else {**DEFAULT_MULTIPLIERS, **auxiliary.multipliers})
    margin = (read_wide(auxiliary.margin_rate_path, auxiliary, label="margin_rate", timezone=run_config.timezone, date_at="00:00")
              if auxiliary.margin_rate_path else dict(auxiliary.margin_rates))
    metadata = dict(source=stats["source"], paths=paths, datasets=frozen, warnings=[], price_forward_fill=False,
                    load_statistics=stats, margin_source=str(config.margin_rate_path) if config.margin_rate_path else dict(config.margin_rates))
    if any(d.get("availability_policy") == "unknown" for d in frozen):
        metadata["warnings"].append("Revised research history; historical publication time is unknown, not a PIT replay")
    adjusted = None
    if config.adjusted_close_path:
        adjusted = read_wide(config.adjusted_close_path, config, label="adjusted_close", timezone=run_config.timezone).reindex_like(close)
    elif config.dividend_points_path:
        points = read_wide(config.dividend_points_path, config, label="dividend_points", timezone=run_config.timezone)
        if (points.index == points.index.normalize() + pd.Timedelta(hours=15)).all():
            points.index = points.index.normalize()
            points = points.reindex(close.index.normalize())
            points.index = close.index
        adjusted = close + points.reindex_like(close)
    elif config.dividend_policy != "none":
        from ..marketdata.dividends import read_snapshot
        if not paths["dividend_root"]:
            raise BacktestError("dividend_root is required for a dividend snapshot")
        snapshot = read_snapshot(paths["dividend_root"])
        adjusted = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for row in snapshot["rows"]:
            symbol = row["source_contract"]
            if symbol in close:
                mask = (close.index.normalize() > pd.Timestamp(snapshot["date"]).tz_localize(run_config.timezone)
                        if config.dividend_policy == "asof_snapshot" else np.ones(len(close), dtype=bool))
                adjusted.loc[mask, symbol] = close.loc[mask, symbol] + row["points"]
        metadata["dividend_source"] = dict(path=snapshot["path"], date=snapshot["date"], policy=config.dividend_policy)
        metadata["warnings"].append("Single dividend snapshot; not a daily historical dividend series")
    if adjusted is None:
        metadata["warnings"].append("No dividend-adjusted prices loaded; PnL uses raw close")
    if close.empty or daily.empty:
        raise BacktestError("No prices remain in the requested interval")
    return MarketData(close, multiplier, margin, adjusted, _reference(paths["reference_path"]), metadata, daily, fallback)
