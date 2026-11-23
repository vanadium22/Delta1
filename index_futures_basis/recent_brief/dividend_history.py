"""Resolve remaining dividend points as of each daily observation."""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path
import re
import sqlite3
from zipfile import BadZipFile

import numpy as np
import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from dashboard.marketdata.overview_dividends import DividendStore
from ..analytics import read_continuous_snapshot
from ..config import ROOT
from .dividend_sources import history_paths

SOURCE_COLUMNS = ["dividend_source_contract", "dividend_source_date", "dividend_effective_at",
                  "dividend_source_sha256", "dividend_source_cell", "dividend_match", "dividend_is_estimated"]
CURVE_COLUMNS = ["dividend_interpolation", "dividend_anchor_date", "dividend_anchor_points",
                 "dividend_end_date", "dividend_end_points", "dividend_end_source_date",
                 "dividend_end_source_sha256", "dividend_end_source_cell"]
PREVIOUS_CONTRACT = "estimated_from_previous_contract"
PREFERRED_DONORS = {"IF2607.CFE": "IF2606.CFE"}
PENDING_CONTRACT = {"", "FETCHING...", "FETCHING…", "#GETTING_DATA", "#GETTING_DATA!"}
WORKBOOK_ERRORS = (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError, SyntaxError,
                   BadZipFile, InvalidFileException)


def fill_from_previous_contract(matched, book):
    """Borrow a dated workbook observation from the closest earlier contract month."""
    contracts = defaultdict(list)
    histories = {}
    for contract, group in book.groupby("instrument_id", sort=True):
        contracts[contract[:2]].append(contract)
        histories[contract] = (group.dividend_effective_at.tolist(), list(group.itertuples(index=False)))

    missing = matched.dividend_match.isna() & matched.calendar_known.eq(True) & matched.instrument_id.ne("")
    estimates = {}
    for row in matched.loc[missing].itertuples():
        earlier = contracts[row.instrument_id[:2]]
        boundary = bisect_left(earlier, row.instrument_id)
        if row.instrument_id in PREFERRED_DONORS:
            candidates = [PREFERRED_DONORS[row.instrument_id]]
        else:
            candidates = reversed(earlier[:boundary])
        for contract in candidates:
            if contract not in histories:
                continue
            times, versions = histories[contract]
            index = bisect_right(times, row.pricing_at) - 1
            if index >= 0 and pd.notna(versions[index].dividend_points):
                estimates[row.Index] = versions[index]._asdict()
                break
    if estimates:
        replacements = pd.DataFrame.from_dict(estimates, orient="index").drop(columns="instrument_id")
        replacements["dividend_match"] = PREVIOUS_CONTRACT
        matched.update(replacements)


def interpolate_history(matched, book, cutoff_offset):
    """Smooth retrospective observations using anchors known by the report cutoff."""
    cutoff_at = matched.pricing_at.max()
    cutoff_day = cutoff_at.normalize()
    known = matched.calendar_known.eq(True) & matched.trade_date.le(cutoff_day)
    sessions = matched.loc[known, "trade_date"].drop_duplicates().sort_values().tolist()

    def effective_day(stamp):
        day = stamp.normalize()
        earliest = day + pd.Timedelta(days=1) if stamp - day > cutoff_offset else day
        if sessions and day >= sessions[0]:
            position = bisect_left(sessions, earliest)
            if position < len(sessions):
                return pd.Timestamp(sessions[position])
        return earliest

    histories = {}
    available = book[book.dividend_effective_at.le(matched.loc[known, "pricing_at"].max())]
    for contract, group in available.groupby("instrument_id"):
        histories[contract] = (group.dividend_effective_at.tolist(), list(group.itertuples(index=False)))

    borrowed = matched[matched.dividend_match.eq(PREVIOUS_CONTRACT)]
    borrowed_starts = borrowed.groupby(
        ["instrument_id", "dividend_source_contract", "dividend_effective_at"]).trade_date.transform("min")
    valid = known & matched.dividend_points.notna()
    changes = {}
    for row in matched[valid].itertuples():
        start = borrowed_starts.get(row.Index, effective_day(row.dividend_effective_at))
        if start >= row.trade_date:
            continue
        times, versions = histories.get(row.instrument_id, ([], []))
        following = bisect_right(times, row.pricing_at)
        anchor = versions[following] if following < len(versions) else None
        if anchor is not None:
            if pd.isna(anchor.dividend_points):
                continue
            end = effective_day(anchor.dividend_effective_at)
            if pd.notna(row.expiry_date) and end > row.expiry_date:
                anchor = None
        if anchor is None:
            end = row.expiry_date
            if pd.isna(end) or end > cutoff_day:
                continue
        if end < row.trade_date or end <= start:
            continue
        end_points = anchor.dividend_points if anchor is not None else 0.0
        if row.dividend_points == end_points:
            continue
        weight = (row.trade_date - start) / (end - start)
        changes[row.Index] = {
            "dividend_points": row.dividend_points + weight * (end_points - row.dividend_points),
            "dividend_interpolation": "between_snapshots" if anchor is not None else "to_expiry",
            "dividend_anchor_date": start, "dividend_anchor_points": row.dividend_points,
            "dividend_end_date": end, "dividend_end_points": end_points,
            "dividend_end_source_date": anchor.dividend_source_date if anchor is not None else pd.NaT,
            "dividend_end_source_sha256": anchor.dividend_source_sha256 if anchor is not None else None,
            "dividend_end_source_cell": anchor.dividend_source_cell if anchor is not None else None,
        }
    curve = pd.DataFrame.from_dict(changes, orient="index")
    matched["dividend_points"] = curve.get("dividend_points", pd.Series(dtype=float)).combine_first(
        matched.dividend_points)
    return matched.join(curve.reindex(columns=CURVE_COLUMNS))


def align_history(panel, config, paths, explicit, *, frozen_inputs=None, earlier_mappings=None):
    files, stores = history_paths(ROOT, config, paths, explicit)
    cutoff_offset = pd.Timedelta(hours=config.get("close_hour", 15), minutes=config.get("close_minute", 5))
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    errors, cached, records, sources = [], {}, [], {}
    inventory = []
    workbook_config = {**config["dividends"], "allow_missing_values": True}
    for path in stores:
        try:
            for row in DividendStore(path.parent).read():
                key = (row["file_sha256"], row["contract_id"])
                effective = pd.Timestamp(row["effective_from"]).as_unit("ns")
                if pd.isna(effective):
                    raise ValueError("分红缓存生效时间为空")
                if effective.tzinfo:
                    effective = effective.tz_convert("Asia/Shanghai").tz_localize(None)
                # If the same file was imported on different machines, use the
                # later observed time when the effective clocks disagree.
                cached[key] = max(cached.get(key, effective), effective)
        except (OSError, ValueError, KeyError, TypeError, OverflowError, sqlite3.Error) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    known = panel[panel.calendar_known.eq(True) & panel.instrument_id.ne("")]
    mappings = known.set_index(["trade_date", "continuous_code"]).instrument_id
    earlier_mappings = earlier_mappings or {}
    for path in files:
        entry = {"path": str(path)}
        inventory.append(entry)
        try:
            source_bytes = path.read_bytes()
            rows, info = read_continuous_snapshot(path, workbook_config, include_contracts=True,
                                                  source_bytes=source_bytes)
            sheet_effective = pd.Timestamp(info["effective_from"]).as_unit("ns")
        except WORKBOOK_ERRORS as exc:
            errors.append({"path": str(path), "error": str(exc)})
            entry["error"] = f"{type(exc).__name__}: {exc}"
            continue
        digest = info["sha256"]
        entry.update(sha256=digest, snapshot_date=info["snapshot_date"], slots=len(rows),
                     valid_points=int(rows.dividend_points.notna().sum()))
        if digest in sources:
            entry["duplicate_of"] = sources[digest]["path"]
            continue
        sources[digest] = {k: info[k] for k in ("path", "sha256", "snapshot_date", "date_cell")}
        before = len(records)
        fallback = 0
        rejected = Counter()
        for row in rows.itertuples():
            if not np.isfinite(row.dividend_points):
                continue
            actual = row.source_contract
            match = "actual_contract_in_workbook"
            if actual in PENDING_CONTRACT or actual == row.code:
                actual = mappings.get((row.trade_date, row.code), "") or earlier_mappings.get(
                    (info["snapshot_date"], row.code), "")
                match = "actual_contract_from_workbook_date_mapping"
                if not actual:
                    rejected["no_business_day_mapping"] += 1
                    continue
            if not re.fullmatch(rf"{row.code[:2]}\d{{4}}\.CFE", str(actual)):
                rejected["invalid_contract_code"] += 1
                continue
            effective = cached.get((digest, actual), sheet_effective)
            if effective.normalize() < row.trade_date:
                rejected["invalid_effective_date"] += 1
                continue
            records.append({"instrument_id": actual, "dividend_points": row.dividend_points,
                            "dividend_source_date": row.trade_date, "dividend_effective_at": effective,
                            "dividend_source_sha256": digest, "dividend_source_cell": info["cells"][row.code],
                            "dividend_match": match})
            fallback += match == "actual_contract_from_workbook_date_mapping"
        entry.update(bound_rows=len(records) - before, mapped_from_history=fallback,
                     rejected_rows=dict(rejected))
        if frozen_inputs is not None and entry["bound_rows"]:
            frozen_inputs[digest] = source_bytes
    estimate = config["dividends"].get("estimate_from_previous_contract", True)
    smooth = config["dividends"].get("interpolate_history", True)
    left = panel[["trade_date", "instrument_id", "calendar_known", "expiry_date"]].copy()
    left["order"] = np.arange(len(left))
    left["pricing_at"] = (left.trade_date + cutoff_offset).clip(upper=now)
    if records:
        book = pd.DataFrame(records)
        key = ["instrument_id", "dividend_effective_at"]
        conflicts = book.groupby(key).dividend_points.transform("nunique").gt(1)
        book.loc[conflicts, "dividend_points"] = np.nan
        book.loc[conflicts, "dividend_match"] = "conflicting_same_effective_time"
        book = book.sort_values("dividend_effective_at", kind="stable").drop_duplicates(key)
        # pandas 3 preserves input precision; merge_asof requires identical units.
        left["pricing_at"] = left.pricing_at.astype("datetime64[ns]")
        book["dividend_effective_at"] = book.dividend_effective_at.astype("datetime64[ns]")
        book["dividend_source_contract"] = book.instrument_id
        matched = pd.merge_asof(left.sort_values("pricing_at"), book, left_on="pricing_at",
                                right_on="dividend_effective_at", by="instrument_id")
        if estimate:
            fill_from_previous_contract(matched, book)
        if smooth:
            matched = interpolate_history(matched, book, cutoff_offset)
        matched = matched.sort_values("order")
    else:
        matched = left.assign(dividend_points=np.nan, dividend_source_contract=None, dividend_source_date=pd.NaT,
                              dividend_effective_at=pd.NaT, dividend_source_sha256=None,
                              dividend_source_cell=None, dividend_match=None)
    if "dividend_interpolation" not in matched:
        matched[CURVE_COLUMNS] = None
    matched["dividend_is_estimated"] = (matched.dividend_match.eq(PREVIOUS_CONTRACT)
                                         | matched.dividend_interpolation.notna())
    dates = matched.dividend_source_date[matched.dividend_points.notna()]
    current = matched[matched.trade_date.eq(panel.trade_date.max()) & matched.dividend_points.notna()]
    latest = current.dividend_source_date.max()
    used = set(matched.dividend_source_sha256.dropna()) | set(matched.dividend_end_source_sha256.dropna())
    if frozen_inputs is not None:
        for sha in frozen_inputs.keys() - used:
            del frozen_inputs[sha]
    last_source = sources[current.loc[current.dividend_source_date.eq(latest), "dividend_source_sha256"].iloc[0]] if len(current) else {}
    info = {**last_source, "snapshot_date": str(latest.date()) if pd.notna(latest) else "缺失",
            "application": "dated_actual_contract", "selection": "latest_known_same_contract_at_cutoff",
            "estimate_policy": "closest_earlier_same_product_contract_as_of" if estimate else "disabled",
            "history_policy": "retrospective_linear_between_observations_or_to_expiry" if smooth else "as_of_only",
            "first_used_source_date": str(dates.min().date()) if len(dates) else None,
            "oldest_current_source_date": str(current.dividend_source_date.min().date()) if len(current) else None,
            "files": [sources[sha] for sha in sorted(used)], "source_errors": errors, "input_inventory": inventory,
            "cutoff_shanghai": f"{config.get('close_hour', 15):02d}:{config.get('close_minute', 5):02d}",
            "date_only_policy": "用可信表内业务日，未归档时不推定日内发布时间"}
    if not records or not len(dates):
        info["reason"] = "无可用于行情日及实际合约的历史分红"
    matched["dividend_match"] = matched.dividend_match.fillna("no_prior_contract_record")
    return matched[["dividend_points", *SOURCE_COLUMNS, *CURVE_COLUMNS]].set_axis(panel.index), info
