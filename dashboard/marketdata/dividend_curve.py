"""Shared remaining-dividend rules for the brief and native dashboard."""
from bisect import bisect_left, bisect_right
from collections import defaultdict

import numpy as np
import pandas as pd

SOURCE_COLUMNS = ["dividend_source_contract", "dividend_source_date", "dividend_effective_at",
                  "dividend_source_sha256", "dividend_source_cell", "dividend_match", "dividend_is_estimated"]
CURVE_COLUMNS = ["dividend_interpolation", "dividend_anchor_date", "dividend_anchor_points",
                 "dividend_end_date", "dividend_end_points", "dividend_end_source_date",
                 "dividend_end_source_sha256", "dividend_end_source_cell"]
PREVIOUS_CONTRACT = "estimated_from_previous_contract"
PREFERRED_DONORS = {"IF2607.CFE": "IF2606.CFE"}
PENDING_CONTRACT = {"", "FETCHING...", "FETCHING…", "#GETTING_DATA", "#GETTING_DATA!"}


def earlier_contracts(contracts, symbol):
    if symbol in PREFERRED_DONORS:
        return (PREFERRED_DONORS[symbol],)
    return reversed(contracts[:bisect_left(contracts, symbol)])


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
        for contract in earlier_contracts(earlier, row.instrument_id):
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
        start = effective_day(row.dividend_effective_at)
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
            start = borrowed_starts.get(row.Index, start)
        # A borrowed snapshot and a later observed value define the historical
        # interval by their dates, even if the contract first appears mid-interval.
        if not start < row.trade_date <= end:
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


def match_curve(left, records, cutoff_offset, *, estimate=True, smooth=True):
    """Align concrete contracts by time, then estimate and reconstruct historical points."""
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
    return matched
