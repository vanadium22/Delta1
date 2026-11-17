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


def baseline_metrics(group, end, field, prefix):
    """60 prior levels and 60 prior one-session moves; current day excluded."""
    group = group.sort_values("trade_date").set_index("trade_date")
    history = group.loc[group.index < end].tail(61)
    reference = history.tail(60)
    eligible = (reference.days_to_expiry.ge(1) | reference.days_to_expiry.isna()
                if field == "annualized_basis_pct" and "days_to_expiry" in reference else pd.Series(True, index=reference.index))
    values = reference.loc[eligible, field].replace([np.inf, -np.inf], np.nan)
    complete = (len(reference) == 60 and reference.calendar_known.eq(True).all()
                and values.notna().all() and len(values) > 0)
    mean, std = (values.mean(), values.std(ddof=0)) if complete else (np.nan, np.nan)
    now = group.loc[end, field]
    if group.loc[end, "calendar_known"] != True:
        now = np.nan
    deviation = now-mean if np.isfinite(now) and np.isfinite(mean) else np.nan
    score = abs(deviation)/(std if std > 0 else 1) if np.isfinite(deviation) else np.nan
    old = history[field].replace([np.inf, -np.inf], np.nan)
    moves = old.diff().abs().iloc[1:]
    move_eligible = pd.Series(True, index=moves.index)
    if field == "annualized_basis_pct" and "days_to_expiry" in history:
        valid_t = history.days_to_expiry.ge(1) | history.days_to_expiry.isna()
        move_eligible = (valid_t & valid_t.shift(1, fill_value=False)).iloc[1:]
    moves = moves[move_eligible]
    moves_complete = (len(history) == 61 and history.calendar_known.eq(True).all()
                      and moves.notna().all() and len(moves) > 0)
    mean_move = moves.mean() if moves_complete else np.nan
    previous = history[field].iloc[-1] if len(history) else np.nan
    delta = now-previous if len(history) and history.calendar_known.iloc[-1] == True else np.nan
    multiple = abs(delta)/mean_move if np.isfinite(mean_move) and mean_move > 0 and np.isfinite(delta) else np.nan
    return {f"{prefix}_mean_60": mean, f"{prefix}_std_60": std,
            f"{prefix}_deviation_60": deviation, f"{prefix}_deviation_score_60": score,
            f"{prefix}_mean_abs_change_60": mean_move, f"{prefix}_change_multiple_60": multiple,
            f"{prefix}_reference_n": int(values.notna().sum()),
            f"{prefix}_change_reference_n": int(moves.notna().sum())}


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
            # Percentage-point difference is the display unit; bp remains an audit column.
            delta = _difference(group, end, day, "annualized_basis_pct")
            row[f"annual_change_{lag}d_pct_points"] = delta
            row[f"annual_change_{lag}d_bp"] = 100*delta
            previous_rank = lookup.get(lag, pd.Series(dtype=float)).get((root, identity), np.nan)
            interval = group[group.trade_date.between(day, end)] if day is not None else group.iloc[:0]
            row[f"percentile_change_{lag}d"] = (percentile-previous_rank
                if day is not None and interval.calendar_known.eq(True).all() else np.nan)
            row[f"roll_{lag}d"] = bool(interval.loc[interval.trade_date.gt(day), "roll_day"].any()) if day is not None else False
        row.update(baseline_metrics(group, end, "basis_points", "basis"))
        row.update(baseline_metrics(group, end, "annualized_basis_pct", "annual"))
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
        row.update(baseline_metrics(group, end, "volume", "volume"))
        row.update(baseline_metrics(group, end, "open_interest", "oi"))
        rows.append(row)
    return pd.DataFrame(rows)


def highlights(single, cross, totals):
    """Rank current deviations against the prior 60-session distribution."""
    cards = []
    for frame, prefix, title, units, digits in (
        (single, "basis", "绝对基差 · 偏离60日均值", "点", 1),
        (single[single.slot.gt(1)], "annual", "01—03年化 · 偏离60日均值", "个百分点", 2),
        (cross, "annual", "跨期年化 · 偏离60日均值", "个百分点", 2)):
        score = prefix+"_deviation_score_60"
        valid = frame[frame[score].notna() & np.isfinite(frame[score])]
        if valid.empty:
            cards.append({"title": title, "value": "—", "detail": "前60交易日覆盖不足", "direction": 0})
            continue
        row = valid.loc[valid[score].idxmax()]
        identity = f"{int(row.slot)-1:02d}" if "slot" in frame else " "+row.pair
        current = row.basis_current if prefix == "basis" else row.annual_current
        suffix = "点" if prefix == "basis" else "%"
        delta = row[prefix+"_deviation_60"]
        multiple = row[prefix+"_change_multiple_60"]
        detail = f"{row.root}{identity} 当前{current:.2f}{suffix} / 60均{row[prefix+'_mean_60']:.2f}{suffix}"
        if np.isfinite(multiple):
            detail += f"；日变幅为60日均幅{multiple:.2f}倍"
        if row.get("roll_5d", False):
            detail += "；近期含换月"
        cards.append({"title": title, "value": f"{delta:+.{digits}f} {units}", "detail": detail,
                      "direction": int(np.sign(delta)), "baseline_sessions": 60, "selection_score": float(row[score])})
    candidates = []
    for _, row in totals.iterrows():
        for prefix in ("volume", "oi"):
            score, mean = row[prefix+"_deviation_score_60"], row[prefix+"_mean_60"]
            if np.isfinite(score) and np.isfinite(mean) and mean > 0:
                candidates.append((score, row.root, prefix, row))
    title = "量仓 · 偏离60日均值"
    if not candidates:
        cards.append({"title": title, "value": "—", "detail": "前60交易日覆盖不足", "direction": 0})
    else:
        score, root, prefix, row = max(candidates, key=lambda item: item[0])
        value = 100*row[prefix+"_deviation_60"]/row[prefix+"_mean_60"]
        label = "总成交" if prefix == "volume" else "总持仓"
        detail = f"{root}{label} 当前{row[prefix+'_current']/10000:.2f}万手 / 60均{row[prefix+'_mean_60']/10000:.2f}万手"
        multiple = row[prefix+"_change_multiple_60"]
        if np.isfinite(multiple):
            detail += f"；日变幅为60日均幅{multiple:.2f}倍"
        cards.append({"title": title, "value": f"{value:+.1f}%", "detail": detail,
                      "direction": int(np.sign(value)), "baseline_sessions": 60, "selection_score": float(score)})
    return cards


def activity_commentary(panel, end):
    """Describe independent volume/OI trends; dual-axis line crossings have no invariant meaning."""
    totals = activity_totals(panel)
    known = panel.groupby(["trade_date", "root"], as_index=False).calendar_known.all()
    totals = totals.merge(known, on=["trade_date", "root"])
    result = {}
    for root, group in totals.groupby("root"):
        recent = group[group.trade_date.le(end)].tail(11).sort_values("trade_date")
        phrases = []
        for field, label in (("open_interest", "总持仓"), ("volume", "总成交")):
            if len(recent) < 6 or not recent.calendar_known.eq(True).all() or recent[field].isna().any():
                phrases.append(label+"数据不足，暂不判断持续方向")
                continue
            values = recent[field].to_numpy()
            differences = np.diff(values)
            last_sign = np.sign(differences[-1])
            count = 0
            for delta in differences[::-1]:
                if last_sign == 0 or np.sign(delta) != last_sign:
                    break
                count += 1
            if count >= 3:
                change = values[-1]-values[-count-1]
                text = f"{label}连续{count}日{'增加' if last_sign > 0 else '减少'}，累计{change/10000:+.2f}万手"
            else:
                previous = differences[-6:-1] if len(differences) >= 6 else differences[:-1]
                up, down = (previous > 0).sum(), (previous < 0).sum()
                if len(previous) >= 4 and max(up, down) >= 4 and last_sign == (-1 if up > down else 1):
                    text = f"{label}此前{len(previous)}日中{max(up,down)}日{'增加' if up > down else '减少'}，最新转为{'增加' if last_sign > 0 else '减少'}"
                else:
                    change = values[-1]-values[-6]
                    smooth = pd.Series(values).rolling(5).mean().dropna().diff().dropna().to_numpy()
                    direction = np.sign(smooth[-1]) if len(smooth) else 0
                    run = 0
                    for delta in smooth[::-1]:
                        if direction == 0 or np.sign(delta) != direction:
                            break
                        run += 1
                    if run >= 3:
                        text = f"{label}5日均值连续{run}日{'上行' if direction > 0 else '下行'}，近5日累计{change/10000:+.2f}万手"
                    else:
                        text = f"{label}近{len(differences)}日有{int((differences>0).sum())}日增加，近5日累计{change/10000:+.2f}万手"
            phrases.append(text)
        if len(recent) >= 6 and recent.calendar_known.eq(True).all() and recent[["volume","open_interest"]].notna().all().all():
            oi_delta, vol_delta = recent.open_interest.iloc[-1]-recent.open_interest.iloc[-6], recent.volume.iloc[-1]-recent.volume.iloc[-6]
            if oi_delta > 0 and vol_delta > 0:
                phrases.append("近5日增仓与成交扩张同向")
            elif oi_delta < 0 and vol_delta < 0:
                phrases.append("近5日减仓与成交收缩同向")
            elif oi_delta*vol_delta < 0:
                phrases.append("近5日持仓与成交方向分化")
        result[root] = "；".join(phrases)+"。"
    return result
