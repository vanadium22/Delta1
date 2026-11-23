"""Bounded descriptive rules: product overview first, then material exceptions."""
from __future__ import annotations

from collections import Counter
import math

import numpy as np
import pandas as pd

from .data import CALENDAR_RANK_SESSIONS, ORDER, PAIRS, activity_totals
from .overview import annualized_current

RULE_VERSION = "descriptive-tree-v8"
WINDOWS = (30, 60)


def classify_path(values, sessions=40, minimum_move=3.):
    """Describe signed basis magnitude without bridging missing observations."""
    values = np.asarray(values, dtype=float)
    if len(values) != sessions or not np.isfinite(values).all():
        return {"shape": "insufficient", "text": f"{sessions}日历史覆盖不足"}
    if np.max(np.abs(values)) <= 1e-8:
        return {"shape": "flat", "text": "维持平水", "current": 0.0}
    if (values <= 0).all():
        size, state = -values, "贴水"
    elif (values >= 0).all():
        size, state = values, "升水"
    else:
        return {"shape": "sign_change", "text": "期间出现升贴水切换", "current": float(values[-1])}
    smooth = pd.Series(size).rolling(5, center=True, min_periods=5).median()
    start, end = float(np.median(size[:5])), float(np.median(size[-5:]))
    margin = max(5, round(sessions*.175))
    interior = smooth.iloc[margin:-margin]
    high, low = float(interior.max()), float(interior.min())
    noise = float(np.mean(np.abs(np.diff(size))))
    threshold = max(minimum_move, .15*float(np.ptp(size)), 2*noise)
    peak, trough = int(interior.idxmax()), int(interior.idxmin())
    if peak < trough and high-start >= threshold and high-low >= threshold and end-low >= threshold:
        shape, text = "widen_narrow_widen", f"{state}幅度先扩大、后收敛，近期再扩大"
    elif trough < peak and start-low >= threshold and high-low >= threshold and high-end >= threshold:
        shape, text = "narrow_widen_narrow", f"{state}幅度先收敛、后扩大，近期再收敛"
    elif high-max(start,end) >= threshold:
        shape, text = "widen_then_narrow", f"{state}幅度先扩大后收敛"
    elif min(start,end)-low >= threshold:
        shape, text = "narrow_then_widen", f"{state}幅度先收敛后扩大"
    elif end-start >= threshold:
        shape, text = "widen", f"{state}幅度总体扩大"
    elif start-end >= threshold:
        shape, text = "narrow", f"{state}幅度总体收敛"
    else:
        shape, text = "range", f"{state}幅度无明显方向变化"
    return {"shape": shape, "text": text, "state": state, "start_median": start,
            "end_median": end, "interior_high": high, "interior_low": low,
            "threshold": threshold, "noise": noise, "current": float(values[-1])}


def _aligned(series, days, root, key, identity):
    return series[series.root.eq(root) & series[key].eq(identity)].set_index("trade_date").reindex(days)


def _complete(group, field):
    return bool(len(group) and group.calendar_known.eq(True).all()
                and np.isfinite(group[field].to_numpy(dtype=float)).all())


def _stable_identity(group):
    """Never interpret a continuous-contract roll jump as a market trend."""
    if 'roll_day' in group and group.roll_day.iloc[1:].eq(True).any():
        return False
    for field in ('instrument_id', 'left_contract', 'right_contract'):
        if field in group and (group[field].isna().any() or group[field].nunique() != 1):
            return False
    return True


def _dividend_changed(group):
    fields = [name for name in ("dividend_points", "left_dividend_points", "right_dividend_points") if name in group]
    return bool(fields and group[fields].diff().abs().gt(1e-8).any().any())


def _overview(series, end, key, ids, field):
    """Require a two-thirds majority of tenors, not a hidden representative."""
    days = sorted(series.loc[series.trade_date.le(end), "trade_date"].unique())
    result, clauses, grouped, divided = {}, [], {}, {}
    for root in ORDER:
        selected = None
        for window in (60, 30):
            if len(days) < window:
                continue
            features = []
            for identity in ids:
                group = _aligned(series, days[-window:], root, key, identity)
                if not _complete(group, field) or not _stable_identity(group):
                    break
                features.append(classify_path(group[field], window, .4 if field == "annualized_basis_pct" else 3.))
            if len(features) == len(ids):
                selected = {"window": window, "tenors": features}
                break
        if selected is None:
            result[root] = {"complete": False}
            clauses.append(f"{root}的30/60日历史不足或含换月，未据换档跳变判断走势")
            continue
        counts = Counter(f["text"] for f in selected["tenors"])
        text, count = counts.most_common(1)[0]
        majority = count >= math.ceil(len(ids)*2/3)
        selected.update(complete=True, majority_count=count, majority=majority)
        result[root] = selected
        if majority:
            scope = "全部" if count == len(ids) else "多数"
            grouped.setdefault((selected['window'], scope, text), []).append(root)
        else:
            divided.setdefault(selected['window'], []).append(root)
    clauses = [f"{'、'.join(roots)}近{window}日{scope}合约{text}"
               for (window,scope,text),roots in grouped.items()]+[
                   f"{'、'.join(roots)}近{window}日各期限走势分化" for window,roots in divided.items()]+clauses
    # Independent short-window observation; a quiet week can follow a large
    # multi-month move, so do not infer it from the overall direction.
    quiet = []
    for root in ORDER:
        matches = 0
        for identity in ids:
            group = _aligned(series, days[-30:], root, key, identity)
            if len(group) != 30 or not _complete(group, field) or not _stable_identity(group):
                continue
            moves = np.abs(np.diff(group[field].to_numpy(dtype=float)))
            floor = .4 if field == 'annualized_basis_pct' else 3.
            if moves[-7:].max() <= max(floor, 1.5*float(moves[:-7].mean())):
                matches += 1
        if matches >= math.ceil(len(ids)*2/3):
            quiet.append(root)
    text = "；".join(clauses)+"。"
    if quiet:
        text += "、".join(quiet)+"多数期限近一周未见明显大幅波动。"
    return text, result


def _annual_state(features):
    groups = {}
    for root in ORDER:
        rows = [r for r in features if r['root'] == root and r['window'] == 60]
        if len(rows) != 3:
            continue
        low = [r for r in rows if r['percentile'] <= 20]
        high = [r for r in rows if r['percentile'] >= 80]
        if len(low) >= 2:
            label = '多数合约处于60日20%以下历史分位'
            label += '，年化贴水较深' if all(r['current'] < 0 for r in low) else '，年化水平偏低'
        elif len(high) >= 2:
            label = '多数合约处于60日80%以上历史分位，年化水平偏高'
        else:
            continue
        groups.setdefault(label, []).append(root)
    return "；".join('、'.join(roots)+label for label,roots in groups.items())+("。" if groups else "")


def _next_month(panel, end):
    days = sorted(panel.loc[panel.trade_date.le(end),'trade_date'].unique())[-8:]
    evidence, grouped, dividend_effects = [], {}, []
    if len(days) == 8:
        for root in ORDER:
            group = _aligned(panel, days, root, 'slot', 2)
            if not _complete(group, 'annualized_basis_pct') or not _stable_identity(group):
                continue
            previous, current = map(float, group.annualized_basis_pct.iloc[[0, -1]])
            delta = current - previous
            dividend_change = 0.0
            if _dividend_changed(group):
                first, last = group.iloc[0], group.iloc[-1]
                dividend_change = float((last.dividend_points-first.dividend_points) / last.spot_close
                                        * 36500 / last.days_to_expiry)
            comparable_change = delta - dividend_change
            direction = None
            if abs(delta) >= 1 and abs(dividend_change) >= .4:
                dividend_effects.append(root)
            if abs(delta) >= 1 and abs(comparable_change) >= 1 and delta * comparable_change > 0:
                if previous <= 0 and current <= 0:
                    direction = '年化贴水扩大' if delta < 0 else '年化贴水收敛'
                elif previous >= 0 and current >= 0:
                    direction = '年化升水扩大' if delta > 0 else '年化升水收敛'
                else:
                    direction = '由贴水转为升水' if delta > 0 else '由升水转为贴水'
                grouped.setdefault(direction, []).append(root)
            evidence.append({'root': root, 'previous_pct': previous, 'current_pct': current,
                             'change_pp': delta, 'dividend_change_pp': dividend_change,
                             'change_at_start_dividend_pp': comparable_change, 'direction': direction})
    clauses = [f"{'四品种' if len(roots) == len(ORDER) else '、'.join(roots)}次月合约{direction}"
               for direction, roots in grouped.items()]
    if clauses:
        text = '近7个交易日，' + '。'.join(clauses) + '。'
    elif not dividend_effects:
        text = '次月合约近7个交易日可比数据不足。' if not evidence else '次月合约近7个交易日可比数据未见明显变化。'
    else:
        text = ""
    if dividend_effects:
        names = "四品种" if len(dividend_effects) == len(ORDER) else "、".join(dividend_effects)
        text += f"{names}次月合约近7个交易日年化变化含分红调整影响。"
    return text, evidence


def _features(series, end, key, ids, field, windows=WINDOWS, ranks=None):
    days = sorted(series.loc[series.trade_date.lt(end), "trade_date"].unique())
    rows = []
    shared_ranks = (ranks.set_index(["root", key, "window_sessions"]).to_dict("index")
                    if ranks is not None else None)
    for root in ORDER:
        for identity in ids:
            current = _aligned(series, [end], root, key, identity)
            if not _complete(current, field):
                continue
            now = float(current[field].iloc[0])
            for window in windows:
                if len(days) < window:
                    continue
                group = _aligned(series, days[-window:], root, key, identity)
                combined = pd.concat([group, current])
                stable = _stable_identity(combined)
                if field == 'basis_points' and not stable and (key != 'pair' or window <= max(WINDOWS)):
                    continue
                if field == "annualized_basis_pct" and key == "slot":
                    if not group.calendar_known.eq(True).all():
                        continue
                    group = group[group.days_to_expiry.ne(0)]
                if not _complete(group, field):
                    continue
                values = group[field].to_numpy(dtype=float)
                if shared_ranks is not None:
                    rank = shared_ranks.get((root, identity, window))
                    if rank is None or not rank["complete"] or not np.isfinite(rank["percentile"]):
                        continue
                    now, mean, std, percentile = map(float, (rank["current"], rank["mean"],
                                                              rank["std"], rank["percentile"]))
                else:
                    mean, std = float(values.mean()), float(values.std())
                    percentile = 100*((values < now).sum()+.5*(values == now).sum())/len(values)
                deviation = now-mean
                floor = .4 if field == "annualized_basis_pct" else 3.
                score = abs(deviation)/max(std, floor)
                recent_move = base_move = move_multiple = None
                volatile = False
                if (key != 'pair' or stable) and not _dividend_changed(combined):
                    moves = np.abs(np.diff(np.r_[values, now]))
                    recent_move, base_move = float(moves[-7:].mean()), float(moves[:-7].mean())
                    move_multiple = recent_move/base_move if base_move > 1e-8 else None
                    volatile = bool(recent_move >= floor and
                                    (move_multiple >= 2.5 if move_multiple is not None else recent_move >= 2.5*floor))
                level_extreme = bool(abs(deviation) >= floor and
                                     (score >= 1.5 or percentile <= 10 or percentile >= 90))
                rows.append({"root": root, key: identity, "window": window, "n": len(values),
                    "current": now, "mean": mean, "deviation": deviation, "std": std,
                    "score": max(score, (move_multiple or recent_move/floor) if volatile else 0),
                    "percentile": float(percentile), "change": float(now-values[0]) if stable or key != 'pair' else None,
                    "recent_mean_abs_move": recent_move, "reference_mean_abs_move": base_move,
                    "move_multiple": move_multiple, "volatility_expansion": volatile,
                    "roll": not stable if key == 'pair' else bool(combined.roll_day.eq(True).any()),
                    "noteworthy": bool(level_extreme or volatile),
                    "contains_dividend_estimate": bool(combined["dividend_is_estimated"].eq(True).any())
                    if "dividend_is_estimated" in combined else False})
    return rows


def _picks(features, key, count=2, *, preferred_window=None, exclude=()):
    candidates = sorted((f for f in features if f["noteworthy"]),
                        key=lambda f: (preferred_window is not None and f["window"] != preferred_window,
                                       -f["score"], -abs(f["percentile"]-50), -f["window"], f["root"], str(f[key])))
    picked, used = [], set(exclude)
    for row in candidates:
        identity = (row["root"], row[key])
        if identity not in used:
            picked.append(row)
            used.add(identity)
        if len(picked) >= count:
            break
    return picked


def _exception_text(picks, key, annual=False):
    clauses = []
    for row in picks:
        identity = f"{int(row[key])-1:02d}" if key == "slot" else " "+row[key]
        unit, value_unit = ("个百分点", "%") if annual else ("点", "点")
        delta = row['deviation']
        relation = f"{'低' if delta < 0 else '高'}{abs(delta):.2f}{unit}" if delta else "持平"
        text = (f"{row['root']}{identity}当前{row['current']:.2f}{value_unit}，"
                f"较前{row['window']}个交易日均值{relation}，处于P{row['percentile']:.1f}%")
        if row.get("volatility_expansion"):
            text += f"，近7日日均变幅{row['recent_mean_abs_move']:.2f}{unit}"
            text += (f"，为此前{row['n']-7}日日均的{row['move_multiple']:.1f}倍"
                     if row['move_multiple'] is not None else f"，此前{row['n']-7}日基本无波动")
        notes = []
        if row["roll"]:
            notes.append("样本含换月")
        if row["contains_dividend_estimate"]:
            notes.append("含分红估算")
        if notes:
            text += "（"+"、".join(notes)+"）"
        clauses.append(text)
    return "。".join(clauses)+"。" if clauses else ""


def _activity(panel, end):
    totals = activity_totals(panel)
    known = panel.groupby(["trade_date", "root"], as_index=False).calendar_known.all()
    totals = totals.merge(known, on=["trade_date", "root"])
    days = sorted(totals.loc[totals.trade_date.le(end), "trade_date"].unique())
    features, overview, positions = [], {}, []
    for root in ORDER:
        group = totals[totals.root.eq(root)].set_index("trade_date").reindex(days)
        history = group.iloc[:-1].tail(60)
        if len(history) == 60 and _complete(history, 'open_interest') and _complete(group.tail(1), 'open_interest'):
            current = float(group.open_interest.iloc[-1])
            rank = 100*((history.open_interest < current).sum()+.5*(history.open_interest == current).sum())/60
            if rank >= 80:
                positions.append({'root': root, 'percentile': float(rank), 'current': current})
        root_rows = []
        for window in (7, 30, 60):
            oi = group.tail(window+1)
            if len(oi) == window+1 and _complete(oi, "open_interest") and oi.open_interest.iloc[0] > 0:
                change = (oi.open_interest.iloc[-1]/oi.open_interest.iloc[0]-1)*100
                threshold = 10 if window == 7 else 20
                row = {"root": root, "metric": "oi", "window": window, "change_pct": float(change),
                       "current": float(oi.open_interest.iloc[-1]), "base": float(oi.open_interest.iloc[0]),
                       "noteworthy": bool(abs(change) >= threshold), "score": abs(change)/threshold}
                features.append(row)
                root_rows.append(row)
            # Latest seven-session mean vs disjoint preceding 7/30/60 sessions.
            # At most 67 observations are needed, within the existing 80-day sync.
            volume = group.tail(window+7)
            if len(volume) == window+7 and _complete(volume, "volume"):
                current = float(volume.volume.tail(7).mean())
                base = float(volume.volume.iloc[:-7].mean())
                if base > 0:
                    change = (current/base-1)*100
                    row = {"root": root, "metric": "volume", "window": window, "change_pct": float(change),
                           "current": current, "base": base, "noteworthy": bool(abs(change) >= 25),
                           "score": abs(change)/25}
                    features.append(row)
                    root_rows.append(row)
        oi7 = next((r for r in root_rows if r["metric"] == "oi" and r["window"] == 7), None)
        vol7 = next((r for r in root_rows if r["metric"] == "volume" and r["window"] == 7), None)
        if oi7:
            oi_direction = "增仓" if oi7["change_pct"] >= 5 else "减仓" if oi7["change_pct"] <= -5 else "持仓平稳"
        else:
            oi_direction = "持仓可比数据不足"
        if vol7:
            vol_direction = "成交扩张" if vol7["change_pct"] >= 10 else "成交收缩" if vol7["change_pct"] <= -10 else "成交平稳"
        else:
            vol_direction = "成交可比数据不足"
        overview.setdefault(oi_direction+"、"+vol_direction, []).append(root)
    if list(overview) == ["持仓可比数据不足、成交可比数据不足"]:
        text = "近期持仓和成交可比数据不足。"
    else:
        text = "，".join(("四品种均" if len(roots) == len(ORDER) else "、".join(roots))+description
                        for description, roots in overview.items())+"。"
    picked = []
    for metric in ("oi", "volume"):
        rows = [r for r in features if r["metric"] == metric and r["noteworthy"]]
        if not rows:
            continue
        row = max(rows, key=lambda r: (r["score"], r["window"], r["root"]))
        picked.append(row)
    high = sorted(positions, key=lambda r: (-r['percentile'],r['root']))[:2]
    if high:
        text += '、'.join(r['root'] for r in high)+'四合约总持仓处于近60个交易日高位。'
    return text, {"features": features, "selected": picked, "high_positions": high}


def compose(panel, spreads, single_ranks, cross_ranks, totals, end, *, unadjusted=False):
    """Three concise, data-filled front-page templates; retain calculation evidence."""
    end = pd.Timestamp(end)
    absolute, absolute_overview = _overview(panel, end, "slot", range(1,5), "basis_points")
    annual, annual_overview = _overview(panel, end, "slot", range(2,5), "annualized_basis_pct")
    absolute_features = _features(panel, end, "slot", range(1,5), "basis_points")
    annual_features = _features(panel, end, "slot", range(2,5), "annualized_basis_pct", ranks=single_ranks)
    annual_current, annual_groups = annualized_current(panel, end)
    next_month_text, next_month_changes = _next_month(panel, end)
    annual = annual_current + '\n' + next_month_text
    days = sorted(panel.loc[panel.trade_date.le(end), 'trade_date'].unique())[-2:]
    updates = []
    if not unadjusted and len(days) == 2 and "dividend_source_date" in panel:
        for contract, group in panel[panel.trade_date.isin(days)].groupby('instrument_id'):
            if not contract or len(group) != 2:
                continue
            previous, current = group.sort_values('trade_date').itertuples(index=False)
            valid = pd.notna(current.dividend_source_date) and not getattr(current, "dividend_is_estimated", False)
            prior_source = (getattr(previous, "dividend_effective_at", previous.dividend_source_date),
                            getattr(previous, "dividend_source_sha256", None))
            current_source = (getattr(current, "dividend_effective_at", current.dividend_source_date),
                              getattr(current, "dividend_source_sha256", None))
            change = current.dividend_points-previous.dividend_points
            source_changed = any(pd.notna(value) and (pd.isna(old) or value != old)
                                 for old, value in zip(prior_source, current_source))
            if valid and source_changed and np.isfinite(change) and abs(change) > 1e-8:
                updates.append({'contract': contract, 'change_points': float(change)})
    if updates:
        annual += f'\n当日{len(updates)}个实际合约的分红点数更新，去分红日变含此影响。'
    absolute_picks, annual_picks = _picks(absolute_features, "slot", 1), _picks(annual_features, "slot", 1)
    absolute += _exception_text(absolute_picks, "slot") or ("当前未见明显绝对基差异常。" if absolute_features else "当前异常判断所需历史不足。")
    activity, activity_evidence = _activity(panel, end)
    positive, negative, mixed, unavailable = [], [], [], []
    for root in ORDER:
        current = spreads[spreads.root.eq(root) & spreads.trade_date.eq(end)]
        if len(current) != len(PAIRS) or not _complete(current, "basis_points"):
            unavailable.append(root)
        elif current.basis_points.gt(0).all():
            positive.append(root)
        elif current.basis_points.lt(0).all():
            negative.append(root)
        else:
            mixed.append(root)
    structure = []
    if positive:
        structure.append("、".join(positive)+"两组调整后价差均为正，远腿高于近腿")
    if negative:
        structure.append("、".join(negative)+"两组调整后价差均为负，远腿低于近腿")
    if mixed:
        structure.append("、".join(mixed)+"两组价差方向不一致或接近平水")
    cross = "目前"+"。".join(structure)+"。" if structure else "当前跨期数据不足。"
    point_features = _features(spreads, end, "pair", PAIRS, "basis_points", CALENDAR_RANK_SESSIONS)
    cross_features = _features(spreads, end, "pair", PAIRS, "annualized_basis_pct", CALENDAR_RANK_SESSIONS,
                               ranks=cross_ranks)
    longest = CALENDAR_RANK_SESSIONS[-1]
    cross_picks = _picks(cross_features, "pair", 2, preferred_window=longest)
    point_picks = _picks(point_features, "pair", 1, preferred_window=longest,
                         exclude={(row["root"], row["pair"]) for row in cross_picks})
    if cross_picks:
        cross += "跨期年化方面，"+_exception_text(cross_picks, "pair", True)
    if point_picks:
        cross += "绝对价差方面，"+_exception_text(point_picks, "pair")
    noteworthy_roots = {row["root"] for row in (*cross_features, *point_features) if row["noteworthy"]}
    screened = {(row["root"], row["pair"]) for row in cross_features}
    quiet = [root for root in ORDER if root not in noteworthy_roots
             and all((root, pair) in screened for pair in PAIRS)]
    if quiet:
        cross += "、".join(quiet)+"跨期年化未见明显异动。"
    if unavailable and structure:
        cross += "、".join(unavailable)+"当前跨期数据不足。"
    lacking_history = [root for root in ORDER if root not in unavailable
                       and not all((root, pair) in screened for pair in PAIRS)]
    if lacking_history:
        cross += "、".join(lacking_history)+"部分跨期历史不足。"
    if unadjusted:
        cross = cross.replace('调整后价差', '价差')
    sections = [{"key": key, "title": title, "text": text} for key, title, text in (
        ("annualized", "不去分红年化基差" if unadjusted else "去分红年化基差", annual),
        ("calendar", "跨期结构", cross), ("activity", "持仓成交", activity))]
    return {"engine": RULE_VERSION, "as_of": str(end.date()), "sections": sections,
        "text": "\n".join(s["title"]+"："+s["text"] for s in sections),
        "windows": {"basis": list(WINDOWS), "calendar": list(CALENDAR_RANK_SESSIONS), "activity": [7,30,60]},
        "absolute": {"overview": absolute_overview, "features": absolute_features, "selected": absolute_picks},
        "annualized": {"current_groups": annual_groups, "next_month_changes": next_month_changes,
                       "dividend_updates_on_as_of": updates,
                       "overview": annual_overview, "features": annual_features, "selected": annual_picks},
        "activity": activity_evidence,
        "calendar": {"absolute_features": point_features, "annualized_features": cross_features,
                     "absolute_selected": point_picks, "annualized_selected": cross_picks},
        "policy": "descriptive rules and templates; exact sessions; missing coverage explicit; no forced anomalies; no fitted predictive model"}
