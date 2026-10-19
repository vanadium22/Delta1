"""Prior-only observational analytics for the shared market dashboard.

These functions calculate monitoring values, never orders or guaranteed returns.
Prices are aligned on event time, trade date and session; intraday estimation
windows must be continuous within one trading session.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


WINDOW = 30
KEYS = ["event_time", "trade_date", "session_id"]
REGRESSION_KEYS = ("beta", "r_squared", "residual_bp", "residual_z")
FRESHNESS = {"1d":129600, "1m":120, "1s":5}
STEP = {"1m":60, "1s":1}


def _finite(value):
    return not isinstance(value, (bool, np.bool_)) and isinstance(value, (int, float, np.number)) and math.isfinite(float(value))


def _frame(frame, columns, as_of=None):
    """Make a local copy; never repair missing history by backfilling prices."""
    if not isinstance(frame, pd.DataFrame) or not set(KEYS + list(columns)).issubset(frame):
        return pd.DataFrame(columns=KEYS + list(columns))
    result = frame.copy()
    result["event_time"] = pd.to_datetime(result["event_time"], utc=True, errors="coerce")
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.date
    result = result.dropna(subset=KEYS)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None:
            return pd.DataFrame(columns=KEYS + list(columns))
        result = result[result["event_time"] <= cutoff]
        if "available_at" in result:
            available = pd.to_datetime(result["available_at"], utc=True, errors="coerce")
            # Missing availability remains an observation; known future releases
            # are excluded. The model carries the quality limitation separately.
            result = result[available.isna() | (available <= cutoff)]
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        result = result[np.isfinite(result[column])]
    if "close" in columns:
        result = result[result["close"] > 0]
    # Ambiguous duplicate bars cannot be silently selected as a current price.
    return result.drop_duplicates(KEYS, keep=False).sort_values("event_time")[KEYS + list(columns)].reset_index(drop=True)


def _align(left, right, as_of=None):
    left = _frame(left, ["close"], as_of)
    right = _frame(right, ["close"], as_of)
    pair = left.merge(right, on=KEYS, suffixes=("_left", "_right")).sort_values("event_time").reset_index(drop=True)
    current = bool(len(pair) and len(left) and len(right) and pair.iloc[-1].event_time == left.iloc[-1].event_time == right.iloc[-1].event_time)
    return pair, current


def _continuous(frame, frequency):
    if len(frame) < 2:
        return bool(len(frame))
    if frequency == "1d":
        # Trading-calendar gaps include weekends and exchange holidays. Daily
        # samples are distinct trading dates, not 86,400-second intervals.
        return frame["trade_date"].is_unique and frame["event_time"].is_monotonic_increasing
    duration = STEP.get(frequency)
    return bool(duration and frame["trade_date"].nunique() == 1 and frame["session_id"].nunique() == 1 and
                (frame["event_time"].diff().iloc[1:].dt.total_seconds() == duration).all())


def _z_series(frame, frequency, window=WINDOW):
    result = frame[KEYS + ["value"]].copy()
    result["z"] = np.nan
    for i in range(window, len(result)):
        sample = result.iloc[i-window:i+1]
        if not _continuous(sample, frequency):
            continue
        prior = sample["value"].iloc[:-1]
        sigma = float(prior.std(ddof=1))
        if sigma > 1e-12:
            result.loc[i, "z"] = (float(sample.iloc[-1]["value"]) - float(prior.mean())) / sigma
    return result


def _regression(pair, frequency, window=WINDOW):
    result = dict.fromkeys(REGRESSION_KEYS)
    result.update(samples=0, window=window)
    reasons = {}
    output = []
    if len(pair) < window + 2:
        result["samples"] = min(window, max(0, len(pair)-2))
        reasons["beta"] = f"收益回归需要 {window+2} 条同刻价格，当前 {len(pair)} 条"
    for i in range(window+1, len(pair)):
        sample = pair.iloc[i-window-1:i+1]
        if not _continuous(sample, frequency):
            if i == len(pair)-1:
                reasons["beta"] = "回归窗口有缺口或跨交易会话"
            continue
        x = np.diff(np.log(sample["close_right"].to_numpy(dtype=float)))
        y = np.diff(np.log(sample["close_left"].to_numpy(dtype=float)))
        train_x, train_y = x[:-1], y[:-1]
        dx, dy = train_x-train_x.mean(), train_y-train_y.mean()
        denominator = float(np.dot(dx, dx))
        if denominator <= 1e-20:
            if i == len(pair)-1:
                result["samples"] = window
                reasons["beta"] = "解释变量历史收益无有效波动"
            continue
        beta = float(np.dot(dx, dy) / denominator)
        alpha = float(train_y.mean() - beta*train_x.mean())
        prior_residual = train_y - alpha - beta*train_x
        residual = float(y[-1] - alpha - beta*x[-1])
        sigma = float(prior_residual.std(ddof=1))
        variance = float(np.dot(dy, dy))
        r_squared = float(np.clip(1-float(np.dot(prior_residual, prior_residual))/variance, 0, 1)) if variance > 1e-20 else None
        residual_z = residual / sigma if sigma > 1e-12 else None
        output.append({**{key:sample.iloc[-1][key] for key in KEYS}, "value":residual*10000, "z":residual_z})
        if i == len(pair)-1:
            result.update(beta=beta, r_squared=r_squared, residual_bp=residual*10000,
                          residual_z=residual_z, samples=window)
            if residual_z is None:
                reasons["residual_z"] = "历史回归残差无有效波动"
            if r_squared is None:
                reasons["r_squared"] = "被解释变量历史收益无有效波动"
    reason = reasons.get("beta")
    if reason:
        for key in REGRESSION_KEYS:
            reasons.setdefault(key, reason)
    return result, pd.DataFrame(output, columns=KEYS + ["value", "z"]), reasons


def _utc_now():
    return pd.Timestamp.now(tz="UTC")


def _quality(state, event_time):
    if state.get("analytics_observation_reason"):
        return "observed", state["analytics_observation_reason"]
    if state.get("demo"):
        return "observed", "合成演示"
    if state.get("replay"):
        return "observed", "历史回放"
    if state.get("history_limited") or state.get("publication_stale"):
        return "observed", "数据质量或更新时效待核验"
    cutoff = pd.Timestamp(state.get("as_of"))
    if cutoff.tzinfo is None:
        return "observed", "截止时刻缺少时区"
    stamp = pd.Timestamp(event_time)
    age = (cutoff-stamp).total_seconds()
    wall_age = (_utc_now()-stamp).total_seconds()
    limit = FRESHNESS.get(state.get("frequency"), 0)
    if not 0 <= age <= limit or not 0 <= wall_age <= limit:
        return "observed", "仅历史观测"
    return "verified", "连续且时间有效的指标观测"


def _events(frame, state, kind, title, threshold=2., duration=3):
    """Collapse a threshold episode into one ongoing or recovered event."""
    events, active = [], None
    run, sign = 0, 0
    previous = None
    for _, row in frame.iterrows():
        if previous is not None and not _continuous(pd.DataFrame([previous, row]), state.get("frequency", "1m")):
            if active is not None:
                active["observation_reason"] = "后续有数据缺口或跨会话，仅保留历史观测"
                events.append(active)
            active, run, sign = None, 0, 0
        previous = row
        z = row.get("z")
        if not _finite(z):
            if active is not None:
                active["observation_reason"] = "后续估计窗口无效，仅保留历史观测"
                events.append(active)
            active, run, sign = None, 0, 0
            continue
        direction = 1 if z > 0 else -1
        hit = abs(float(z)) >= threshold
        if active is not None and (not hit or direction != sign):
            active.update(last_time=row.event_time.isoformat(), value=float(z), lifecycle="recovered")
            events.append(active)
            active, run = None, 0
        if not hit:
            run, sign = 0, 0
            continue
        run = run+1 if direction == sign else 1
        sign = direction
        if run >= duration:
            if active is None:
                active = {"product":state.get("product"), "type":kind, "title":title,
                          "event_time":row.event_time.isoformat(), "last_time":row.event_time.isoformat(),
                          "value":float(z), "unit":"Z", "threshold":threshold,
                          "lifecycle":"active", "duration":run, "peak":abs(float(z))}
            else:
                active.update(last_time=row.event_time.isoformat(), value=float(z), duration=run)
                if abs(z) > active["peak"]:
                    active["peak"] = abs(float(z))
    if active is not None:
        events.append(active)
    for event in events:
        quality, reason = _quality(state, event["last_time"])
        if event.get("observation_reason"):
            quality, reason = "observed", event.pop("observation_reason")
        event["status"] = "observed" if quality == "observed" else event["lifecycle"]
        event["quality"], event["reason"] = quality, reason
    return events


def enrich_state(state):
    """Add the numeric summary, residual history and at most 12 events in place."""
    frequency, cutoff = state.get("frequency", "1m"), state.get("as_of")
    pair, current = _align(state.get("near"), state.get("spot"), cutoff)
    regression, residuals, reasons = _regression(pair, frequency)
    if not current:
        for key in REGRESSION_KEYS:
            regression[key] = None
            reasons[key] = "期货与指数最新价格不同刻或缺失"
    basis = pair[KEYS].copy()
    basis["value"] = (pair["close_left"]/pair["close_right"]-1)*10000
    basis_z = _z_series(basis, frequency)
    basis_value = float(basis_z.iloc[-1].z) if current and len(basis_z) and _finite(basis_z.iloc[-1].z) else None
    if basis_value is None:
        reasons["basis_z"] = "需要此前 30 条连续同刻基差且历史波动有效"
    spread = _frame(state.get("spread"), ["value"], cutoff)
    spot = _frame(state.get("spot"), ["close"], cutoff)
    calendar = spread.merge(spot, on=KEYS).sort_values("event_time").reset_index(drop=True)
    calendar_current = bool(len(calendar) and len(spread) and len(spot) and calendar.iloc[-1].event_time == spread.iloc[-1].event_time == spot.iloc[-1].event_time)
    if len(calendar):
        calendar["value"] = 10000*calendar["value"]/calendar["close"]
    calendar = calendar[KEYS + ["value"]]
    calendar_z = _z_series(calendar, frequency)
    calendar_value = float(calendar.iloc[-1].value) if calendar_current else None
    if calendar_value is None:
        reasons["calendar_bp"] = "近远月价差与现货指数缺少最新同刻数据"
    calendar_score = float(calendar_z.iloc[-1].z) if calendar_current and len(calendar_z) and _finite(calendar_z.iloc[-1].z) else None
    state["analytics"] = {"calendar_bp":calendar_value, "calendar_z":calendar_score,
                          "basis_z":basis_value, **regression, "reasons":reasons}
    state["regression"] = residuals[KEYS + ["value"]].copy()
    event_inputs = ((basis_z, "basis", "期现基差持续偏离", basis_value),
                    (calendar_z, "calendar", "跨期价差持续偏离", calendar_score),
                    (residuals, "regression", "收益回归残差持续偏离", regression["residual_z"]))
    events = []
    for frame, kind, title, latest in event_inputs:
        context = state if latest is not None else {**state, "analytics_observation_reason":"最新同刻连续估计不足，仅保留历史观测"}
        events.extend(_events(frame, context, kind, title))
    state["events"] = sorted(events, key=lambda event:event["last_time"], reverse=True)[:12]
    return state


def cross_product_metrics(states):
    """Comparable basis gaps and return regressions for configured index pairs."""
    output = []
    for left, right in (("IF", "IH"), ("IC", "IM"), ("IF", "IC"), ("IH", "IM")):
        a, b = states.get(left, {}), states.get(right, {})
        row = {"left":left, "right":right, "basis_gap_bp":None,
               **dict.fromkeys(REGRESSION_KEYS), "samples":0, "window":WINDOW, "reasons":{}}
        frequency = a.get("frequency", "1m")
        if not a or not b or frequency != b.get("frequency"):
            row["reasons"]["beta"] = "两品种缺失或频率不同"
            output.append(row)
            continue
        cutoffs = [pd.Timestamp(state["as_of"]) for state in (a, b) if state.get("as_of")]
        cutoff = min(cutoffs) if cutoffs else None
        pair, current = _align(a.get("near"), b.get("near"), cutoff)
        regression, _, reasons = _regression(pair, frequency)
        row.update(regression, reasons=reasons)
        # Distinct concrete expiry months are a different comparison, not the
        # same-tenor observation displayed by this table.
        near_a, near_b = a.get("roles", {}).get("$near"), b.get("roles", {}).get("$near")
        same_tenor = not (near_a and near_b) or str(near_a)[2:] == str(near_b)[2:]
        if not current or not same_tenor:
            for key in REGRESSION_KEYS:
                row[key] = None
            row["reasons"]["beta"] = "两品种最新价格不同刻或合约期限不同"
        basis_a = _frame(a.get("basis"), ["value"], cutoff)
        basis_b = _frame(b.get("basis"), ["value"], cutoff)
        aligned_basis = basis_a.merge(basis_b, on=KEYS, suffixes=("_left", "_right"))
        if same_tenor and len(aligned_basis) and len(basis_a) and len(basis_b):
            last = aligned_basis.iloc[-1]
            if last.event_time == basis_a.iloc[-1].event_time == basis_b.iloc[-1].event_time:
                row["basis_gap_bp"] = float(last.value_left-last.value_right)
        if row["basis_gap_bp"] is None:
            row["reasons"]["basis_gap_bp"] = "两品种基差缺少最新同刻同期限数据"
        output.append(row)
    return output


def _expiry(value):
    if value is None or value == "":
        return None
    try:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("Asia/Shanghai")
            if timestamp.hour == timestamp.minute == timestamp.second == 0:
                timestamp += pd.Timedelta(hours=15)
        return timestamp.tz_convert("UTC")
    except (TypeError, ValueError):
        return None


def carry_values(spot, future, near, far, as_of, near_expiry, far_expiry,
                 financing_rate=None, dividend_yield=None, cost_bp=None):
    """Transparent simple-yield carry model; explicit expiry metadata is required.

    Rates are decimals (0.02 means 2%); output annual rates are percentages.
    net_space_bp is absolute model deviation minus an input cost estimate. It
    describes an observation outside a model band, not executable profit.
    """
    values = dict.fromkeys(("fair_value", "fair_deviation_bp", "net_space_bp",
                           "annualized_basis_pct", "implied_carry_pct", "near_days", "far_days"))
    reasons = {}
    try:
        cutoff = pd.Timestamp(as_of)
    except (TypeError, ValueError):
        cutoff = pd.NaT
    n, f = _expiry(near_expiry), _expiry(far_expiry)
    if pd.isna(cutoff) or cutoff.tzinfo is None:
        reasons["expiry"] = "计算截止时刻缺失或没有时区"
        return {**values, "reasons":reasons}
    if n is None or n <= cutoff:
        reasons["expiry"] = "近月真实到期资料缺失或合约已到期"
        return {**values, "reasons":reasons}
    days = (n-cutoff).total_seconds()/86400
    values["near_days"] = days
    if _finite(spot) and _finite(future) and spot > 0 and future > 0:
        values["annualized_basis_pct"] = (future/spot-1)*365/days*100
        if _finite(financing_rate) and _finite(dividend_yield):
            fair = spot*(1+(financing_rate-dividend_yield)*days/365)
            values["fair_value"] = float(fair)
            values["fair_deviation_bp"] = float((future-fair)/spot*10000)
            if _finite(cost_bp) and cost_bp >= 0:
                values["net_space_bp"] = abs(values["fair_deviation_bp"])-float(cost_bp)
            else:
                reasons["net_space_bp"] = "费用、冲击及方向相关成本估计待接入"
        else:
            reasons["fair_value"] = "融资利率与预计股息率待接入"
    else:
        reasons["fair_value"] = "缺少有效同期现货和期货价格"
    if f is not None and f > n:
        values["far_days"] = (f-cutoff).total_seconds()/86400
        if _finite(near) and _finite(far) and near > 0 and far > 0:
            values["implied_carry_pct"] = math.log(far/near)*365/((f-n).total_seconds()/86400)*100
        else:
            reasons["implied_carry_pct"] = "缺少有效同期近远月价格"
    else:
        reasons["implied_carry_pct"] = "远月真实到期资料缺失或期限次序无效"
    if days < 5:
        values["annualized_basis_pct"] = None
        reasons["annualized_basis_pct"] = "距到期不足 5 天，隐藏对时点敏感的年化基差"
    reasons["model"] = "简单股息率近似，ACT/365；净偏离不等于可交易收益"
    return {**values, "reasons":reasons}
