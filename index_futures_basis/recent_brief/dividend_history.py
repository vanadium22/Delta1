"""Resolve remaining dividend points as of each daily observation."""
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

SOURCE_COLUMNS = ["dividend_source_date", "dividend_effective_at", "dividend_source_sha256",
                  "dividend_source_cell", "dividend_match"]


def align_history(panel, config, paths, explicit):
    files, stores = history_paths(ROOT, config, paths, explicit)
    cutoff_offset = pd.Timedelta(hours=config.get("close_hour", 15), minutes=config.get("close_minute", 5))
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    errors, cached, records, sources = [], {}, [], {}
    for path in stores:
        try:
            for row in DividendStore(path.parent).read():
                key = (row["file_sha256"], row["contract_id"])
                effective = pd.Timestamp(row["effective_from"])
                if effective.tzinfo:
                    effective = effective.tz_convert("Asia/Shanghai").tz_localize(None)
                # If the same file was imported on different machines, use the
                # later observed time when the effective clocks disagree.
                cached[key] = max(cached.get(key, effective), effective)
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    known = panel[panel.calendar_known.eq(True) & panel.instrument_id.ne("")]
    mappings = known.set_index(["trade_date", "continuous_code"]).instrument_id
    for path in files:
        try:
            rows, info = read_continuous_snapshot(path, {**config["dividends"], "allow_missing_values": True},
                                                  include_contracts=True)
        except (OSError, ValueError, KeyError, TypeError, BadZipFile, InvalidFileException) as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        digest = info["sha256"]
        sources.setdefault(digest, {k: info[k] for k in ("path", "sha256", "snapshot_date", "date_cell")})
        for row in rows.itertuples():
            if not np.isfinite(row.dividend_points):
                continue
            actual = row.source_contract
            match = "actual_contract_in_workbook"
            if not actual:
                actual = mappings.get((row.trade_date, row.code), "")
                match = "actual_contract_from_workbook_date_mapping"
            if not re.fullmatch(rf"{row.code[:2]}\d{{4}}\.CFE", str(actual)):
                continue
            effective = cached.get((digest, actual), pd.Timestamp(info["effective_from"]))
            if effective.normalize() < row.trade_date:
                continue
            records.append({"instrument_id": actual, "dividend_points": row.dividend_points,
                            "dividend_source_date": row.trade_date, "dividend_effective_at": effective,
                            "dividend_source_sha256": digest, "dividend_source_cell": info["cells"][row.code],
                            "dividend_match": match})
    left = panel[["trade_date", "instrument_id"]].copy()
    left["order"] = np.arange(len(left))
    left["pricing_at"] = (left.trade_date + cutoff_offset).clip(upper=now)
    if records:
        book = pd.DataFrame(records)
        key = ["instrument_id", "dividend_effective_at"]
        conflicts = book.groupby(key).dividend_points.transform("nunique").gt(1)
        book.loc[conflicts, "dividend_points"] = np.nan
        book.loc[conflicts, "dividend_match"] = "conflicting_same_effective_time"
        book = book.sort_values("dividend_effective_at", kind="stable").drop_duplicates(key)
        matched = pd.merge_asof(left.sort_values("pricing_at"), book, left_on="pricing_at",
                                right_on="dividend_effective_at", by="instrument_id")
        matched = matched.sort_values("order")
    else:
        matched = left.assign(dividend_points=np.nan, dividend_source_date=pd.NaT,
                              dividend_effective_at=pd.NaT, dividend_source_sha256=None,
                              dividend_source_cell=None, dividend_match=None)
    dates = matched.dividend_source_date[matched.dividend_points.notna()]
    current = matched[matched.trade_date.eq(panel.trade_date.max()) & matched.dividend_points.notna()]
    latest = current.dividend_source_date.max()
    used = {sha for sha in matched.dividend_source_sha256.dropna()}
    last_source = sources[current.loc[current.dividend_source_date.eq(latest), "dividend_source_sha256"].iloc[0]] if len(current) else {}
    info = {**last_source, "snapshot_date": str(latest.date()) if pd.notna(latest) else "缺失",
            "application": "dated_actual_contract", "selection": "latest_known_same_contract_at_cutoff",
            "first_used_source_date": str(dates.min().date()) if len(dates) else None,
            "oldest_current_source_date": str(current.dividend_source_date.min().date()) if len(current) else None,
            "files": [sources[sha] for sha in sorted(used)], "source_errors": errors,
            "cutoff_shanghai": f"{config.get('close_hour', 15):02d}:{config.get('close_minute', 5):02d}",
            "date_only_policy": "用可信表内业务日，未归档时不推定日内发布时间"}
    if not records or not len(dates):
        info["reason"] = "无可用于行情日及实际合约的历史分红"
    matched["dividend_match"] = matched.dividend_match.fillna("no_prior_contract_record")
    return matched[["dividend_points", *SOURCE_COLUMNS]].set_axis(panel.index), info
