"""Automatic, auditable cards: levels, exact-session changes and rolling ranks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import activity_totals, session_quantiles


def _before(series, end, lag):
    days = sorted(series.loc[series.trade_date.lt(end), "trade_date"].unique())
    return pd.Timestamp(days[-lag]) if len(days) >= lag else None


def _difference(group, end, previous, field, relative=False):
    if previous is None:
        return np.nan
    now, old = group[group.trade_date.eq(end)], group[group.trade_date.eq(previous)]
    interval = group[group.trade_date.between(previous, end)]
    if now.empty or old.empty or ("calendar_known" in interval and not interval.calendar_known.eq(True).all()):
        return np.nan
    a, b = now[field].iloc[0], old[field].iloc[0]
    if not np.isfinite(a) or not np.isfinite(b) or (relative and b == 0):
        return np.nan
    return (a/b-1)*100 if relative else a-b


def series_metrics(series, end, key, current_quantiles=None):
    """Changes refer to continuous slots/pairs; rank changes compare each day's own window."""
    end = pd.Timestamp(end)
    dates = {lag: _before(series, end, lag) for lag in (1, 5)}
    ranks = {0: current_quantiles if current_quantiles is not None else session_quantiles(series, end, key)}
    ranks.update({lag: session_quantiles(series, day, key) for lag, day in dates.items() if day is not None})
    lookup = {lag: q.set_index(["root", key]).percentile for lag, q in ranks.items()}
    rows = []
    for (root, identity), group in series.groupby(["root", key]):
        now = group[group.trade_date.eq(end)]
        if now.empty:
            continue
        now = now.iloc[0]
        percentile = lookup[0].get((root, identity), np.nan)
        row = {"trade_date": end, "root": root, key: identity,
               "contract": now.get("instrument_id", f"{now.get('left_contract', '')}/{now.get('right_contract', '')}"),
               "days_to_expiry": now.get("days_to_expiry", np.nan),
               "basis_current": now.basis_points, "annual_current": now.annualized_basis_pct,
               "percentile": percentile}
        for lag, day in dates.items():
            row[f"basis_change_{lag}d"] = _difference(group, end, day, "basis_points")
            # Annualized values are in percent. 1 percentage point = 100 basis points.
            row[f"annual_change_{lag}d_bp"] = 100*_difference(group, end, day, "annualized_basis_pct")
            previous_rank = lookup.get(lag, pd.Series(dtype=float)).get((root, identity), np.nan)
            interval = group[group.trade_date.between(day, end)] if day is not None else group.iloc[:0]
            row[f"percentile_change_{lag}d"] = (percentile-previous_rank
                if day is not None and interval.calendar_known.eq(True).all() else np.nan)
            row[f"roll_{lag}d"] = bool(interval.loc[interval.trade_date.gt(day), "roll_day"].any()) if day is not None else False
        rows.append(row)
    return pd.DataFrame(rows)


def total_metrics(panel, end):
    totals = activity_totals(panel)
    known = panel.groupby(["trade_date", "root"], as_index=False).calendar_known.all()
    totals = totals.merge(known, on=["trade_date", "root"], validate="one_to_one")
    end = pd.Timestamp(end)
    dates = {lag: _before(totals, end, lag) for lag in (1, 5)}
    reference_days = sorted(totals.loc[totals.trade_date.lt(end), "trade_date"].unique())[-20:]
    rows = []
    for root, group in totals.groupby("root"):
        now = group[group.trade_date.eq(end)]
        if now.empty:
            continue
        now = now.iloc[0]
        history = group[group.trade_date.isin(reference_days)]
        values = history.loc[history.calendar_known.eq(True), "volume"].dropna()
        median = values.median() if len(values) >= 10 else np.nan
        row = {"trade_date": end, "root": root, "volume_current": now.volume,
               "oi_current": now.open_interest, "volume_20d_median": median,
               "volume_reference_n": len(values),
               "volume_multiple": now.volume/median if np.isfinite(median) and median > 0 else np.nan}
        for lag, day in dates.items():
            for field, prefix in (("volume", "volume"), ("open_interest", "oi")):
                row[f"{prefix}_change_{lag}d"] = _difference(group, end, day, field)
                row[f"{prefix}_change_{lag}d_pct"] = _difference(group, end, day, field, relative=True)
        rows.append(row)
    return pd.DataFrame(rows)


def highlights(single, cross, totals):
    """The report's four summary cards are selected from computed metrics, not prose."""
    cards = []
    for frame, field, title, units, decimals, scale in (
        (single, "basis_change_5d", "单合约 · 5日基差变动最大", "点", 1, 1),
        (single, "annual_change_1d_bp", "单合约 · 当日年化变动最大", "bp", 0, 1),
        (cross, "annual_change_5d_bp", "跨期 · 5日年化变动最大", "bp", 0, 1),
        (totals, "oi_change_1d", "四合约 · 当日总持仓变动最大", "万手", 2, .0001)):
        valid = frame[frame[field].notna() & np.isfinite(frame[field])]
        if valid.empty:
            cards.append({"title": title, "value": "—", "detail": "数据不足", "direction": 0})
            continue
        row = valid.loc[valid[field].abs().idxmax()]
        identity = f"{int(row.slot)-1:02d}" if "slot" in frame else " " + row.pair if "pair" in frame else ""
        value = row[field]*scale
        lag = 5 if "5d" in field else 1
        roll = " · 含换月" if row.get(f"roll_{lag}d", False) else ""
        if "days_to_expiry" in frame and pd.notna(row.days_to_expiry) and row.days_to_expiry < 5:
            roll += f" · T={int(row.days_to_expiry)}"
        cards.append({"title": title, "value": f"{value:+.{decimals}f} {units}",
                      "detail": row.root + identity + roll, "direction": int(np.sign(value))})
    return cards
