"""Explainable two-leg observations; fixed contracts, aligned prices, prior-only fits.

No orders, backtest, fitted trading thresholds, or claims of executable profits.
All arithmetic is in price-return / notional units, never margin-return units.
"""
from __future__ import annotations

from itertools import combinations
import json
import math

import numpy as np
import pandas as pd

from .analytics import KEYS, _continuous, _regression

WINDOW = 20
BETA_WINDOW = 60
MULTIPLIERS = {"IF":300, "IH":300, "IC":200, "IM":200}


def finite(value):
    return value is not None and not isinstance(value, (bool, np.bool_)) and np.isfinite(value)


def align(frames):
    """Reject ambiguous keys, invalid prices, and unequal latest observations."""
    merged = None
    ends = []
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame) or frame.empty or not set(KEYS + ["close"]).issubset(frame):
            return pd.DataFrame(), False
        part = frame[KEYS + ["close"]].copy()
        part["event_time"] = pd.to_datetime(part["event_time"], utc=True)
        part["trade_date"] = pd.to_datetime(part["trade_date"]).dt.date
        part = part.sort_values("event_time")
        ends.append(part.iloc[-1].event_time)
        part["close"] = pd.to_numeric(part["close"], errors="coerce")
        part = part.drop_duplicates(KEYS, keep=False)
        part = part[np.isfinite(part.close) & (part.close > 0)].rename(columns={"close":name})
        merged = part if merged is None else merged.merge(part, on=KEYS, how="inner", validate="one_to_one")
    if merged is None or merged.empty:
        return pd.DataFrame(), False
    merged = merged.sort_values("event_time").reset_index(drop=True)
    return merged, bool(all(t == merged.iloc[-1].event_time for t in ends))


def history_stats(frame, column, frequency, window=WINDOW):
    result = dict(z=None, percentile=None, mean=None, samples=max(0, min(window, len(frame)-1)), reason="")
    sample = frame.tail(window + 1)
    if len(sample) < window + 1:
        result["reason"] = f"需要当前值及此前 {window} 根同期数据"
    elif not _continuous(sample, frequency) or not np.isfinite(sample[column]).all():
        result["reason"] = "窗口缺口、跨会话或期限不可年化"
    else:
        prior = sample[column].iloc[:-1]
        current = float(sample[column].iloc[-1])
        result.update(mean=float(prior.mean()), percentile=float(((prior < current).sum() + .5*(prior == current).sum())/window*100))
        sigma = float(prior.std(ddof=1))
        if sigma > 1e-12:
            result["z"] = (current-result["mean"])/sigma
        else:
            result["reason"] = "历史窗口无有效波动"
    return result


def series(frame, column):
    result = frame[KEYS + [column]].rename(columns={column:"value"}).tail(180)
    return json.loads(result.to_json(orient="records", date_format="iso"))


def change(frame, column, frequency, periods=5):
    sample = frame.tail(periods + 1)
    if len(sample) != periods + 1 or not _continuous(sample, frequency) or not np.isfinite(sample[column]).all():
        return None
    return float(sample[column].iloc[-1]-sample[column].iloc[0])


def days(frame, metadata):
    expiry = metadata.get("expiry_date")
    if not expiry:
        return pd.Series(np.nan, index=frame.index)
    end = pd.Timestamp(expiry).date()
    return frame["trade_date"].map(lambda d:(end-d).days).astype(float)


def direction(z, left, right):
    if not finite(z):
        return "样本不足或无有效波动；暂不形成方向假设"
    if abs(z) < 2:
        return "偏离未达到观察阈值 |Z|=2"
    return (f"若偏离回归：多 {right} / 空 {left}" if z > 0 else f"若偏离回归：多 {left} / 空 {right}")


def common_row(frame, column, frequency, identity, title, left, right):
    stats = history_stats(frame, column, frequency)
    return dict(id=identity, title=title, left=left, right=right, value=float(frame.iloc[-1][column]),
                time=frame.iloc[-1].event_time.isoformat(), z=stats["z"], percentile=stats["percentile"],
                mean=stats["mean"], samples=stats["samples"], reason=stats["reason"],
                change5=change(frame, column, frequency), series=series(frame, column),
                direction=direction(stats["z"], left, right))


def contract_basis(state):
    rows = []
    frequency = state["frequency"]
    for symbol, prices in state.get("contract_frames", {}).items():
        frame, current = align({"future":prices, "spot":state.get("spot")})
        if not current:
            continue
        frame["basis"] = (frame.future/frame.spot-1)*10000
        frame["log_basis"] = np.log(frame.future/frame.spot)*10000
        frame["dte"] = days(frame, state.get("contract_metadata", {}).get(symbol, {}))
        frame["annual"] = frame.log_basis*365/frame.dte.where(frame.dte >= 5)/100
        row = common_row(frame, "basis", frequency, symbol, symbol, symbol, state["roles"]["$spot"])
        annual = history_stats(frame, "annual", frequency)
        last = frame.iloc[-1]
        dte = float(last.dte) if finite(last.dte) else None
        row.update(product=state["product"], dte=dte,
                   annual_pct=float(last.annual) if finite(last.annual) else None, annual_z=annual["z"],
                   notional=float(last.future)*MULTIPLIERS[state["product"]],
                   future=float(last.future), spot=float(last.spot),
                   roll_down_bp_day=-float(last.log_basis)/dte if dte is not None and dte >= 5 else None,
                   expiry=state.get("contract_metadata", {}).get(symbol, {}).get("expiry_date"))
        row["logic"] = ("正值是期货升水，负值是贴水。原始 Z 衡量相对此前 20 根的偏离；临近到期的自然收敛也会改变 Z。"
                        "年化采用 log(F/S)×365/剩余自然日，剩余不足 5 天不显示。每日收敛仅是假设指数不变、基差线性归零的量级。"
                        "指数不能直接交易；期现两腿需要对应 ETF 或现货篮子，分红、融资、借券与跟踪误差尚未扣除。")
        rows.append(row)
    return rows


def calendar_pairs(state):
    rows = []
    frequency = state["frequency"]
    contracts = state.get("contract_frames", {})
    for left, right in combinations(sorted(contracts), 2):
        frame, current = align({"near":contracts[left], "far":contracts[right], "spot":state.get("spot")})
        if not current:
            continue
        frame["gap"] = (frame.near-frame.far)/frame.spot*10000
        left_dte = days(frame, state.get("contract_metadata", {}).get(left, {}))
        right_dte = days(frame, state.get("contract_metadata", {}).get(right, {}))
        interval = (right_dte-left_dte).where((right_dte>left_dte) & (left_dte>=0))
        frame["carry"] = np.log(frame.far/frame.near)*365/interval*100
        row = common_row(frame, "gap", frequency, left+"/"+right, left+" / "+right, left, right)
        last = frame.iloc[-1]
        row.update(product=state["product"], points=float(last.near-last.far),
                   carry_pct=float(last.carry) if finite(last.carry) else None,
                   carry_z=history_stats(frame, "carry", frequency)["z"],
                   hedge_contracts=1., delta_days=float(interval.iloc[-1]) if finite(interval.iloc[-1]) else None,
                   equal_notional_contracts=float(last.near/last.far))
        row["logic"] = ("价差 = (近端−远端)/现货。正向组合是多近空远；价差上升时固定一手对一手的点差组合受益。"
                        "同品种合约乘数相同，一手对一手对冲共同指数点位变动；等名义手数另为近价/远价。"
                        "区间隐含持有率 = log(远价/近价)×365/到期间隔，反映区间分红、资金和供需的合成定价。"
                        "Z 高时回归假设为空近多远，Z 低时相反；季节分红和移仓需求可能使历史均值失效。")
        rows.append(row)
    return rows


def cross_pairs(states):
    rows = []
    for left_product, right_product in combinations(MULTIPLIERS, 2):
        a, b = states.get(left_product, {}), states.get(right_product, {})
        frequency = a.get("frequency", "1d")
        a_contracts, b_contracts = a.get("contract_frames", {}), b.get("contract_frames", {})
        spot_frame, spot_current = align({"close_left":a.get("spot"), "close_right":b.get("spot")})
        regression, _, reg_reasons = _regression(spot_frame, frequency, BETA_WINDOW)
        if not spot_current:
            regression = dict(beta=None, r_squared=None)
        beta = regression.get("beta")
        beta_valid = finite(beta) and beta > 0
        for left in sorted(a_contracts):
            right = right_product + left[2:]
            if right not in b_contracts:
                continue
            frame, current = align({"fa":a_contracts[left], "fb":b_contracts[right], "sa":a.get("spot"), "sb":b.get("spot")})
            if not current:
                continue
            meta_a, meta_b = a.get("contract_metadata", {}).get(left, {}), b.get("contract_metadata", {}).get(right, {})
            if meta_a.get("expiry_date") and meta_b.get("expiry_date") and meta_a["expiry_date"] != meta_b["expiry_date"]:
                continue
            frame["ba"] = np.log(frame.fa/frame.sa)*10000
            frame["bb"] = np.log(frame.fb/frame.sb)*10000
            frame["gap"] = frame.ba-frame.bb
            frame["simple_gap"] = (frame.fa/frame.sa-frame.fb/frame.sb)*10000
            # Log differences decompose EXACTLY for unit notional log returns.
            frame["spot_ratio"] = np.log(frame.sa/frame.sb)*10000
            frame["futures_ratio"] = np.log(frame.fa/frame.fb)*10000
            row = common_row(frame, "gap", frequency, left+"/"+right, left+" / "+right, left, right)
            last = frame.iloc[-1]
            equal_h = float(last.fa*MULTIPLIERS[left_product]/(last.fb*MULTIPLIERS[right_product]))
            base = dict(beta=beta if beta_valid else None, r_squared=regression.get("r_squared"),
                        beta_reason=reg_reasons.get("beta", "") if not beta_valid else "",
                        hedge_contracts=equal_h*beta if beta_valid else None,
                        equal_notional_contracts=equal_h, simple_gap_bp=float(last.simple_gap),
                        spot_change5=change(frame, "spot_ratio", frequency),
                        futures_change5=change(frame, "futures_ratio", frequency),
                        basis_change5=change(frame, "gap", frequency))
            # A beta hedge leaves beta-weighted spot exposure plus basis effects;
            # do not call the unweighted basis gap its full profit or residual.
            if beta_valid:
                frame["weighted_basis"] = frame.ba-beta*frame.bb
                frame["weighted_spot"] = (np.log(frame.sa)-beta*np.log(frame.sb))*10000
                frame["weighted_futures"] = (np.log(frame.fa)-beta*np.log(frame.fb))*10000
                base.update(weighted_basis_change5=change(frame,"weighted_basis",frequency),
                            weighted_spot_change5=change(frame,"weighted_spot",frequency),
                            weighted_futures_change5=change(frame,"weighted_futures",frequency))
            row.update(**base)
            row["logic"] = ("A 与 B 使用相同到期月份。主值为 10,000×[log(FA/SA)−log(FB/SB)]，用于精确拆分等名义对数收益差。"
                            "期货收益差 = 指数收益差 + 基差差变化；基差更便宜不代表指数本身更强。"
                            "β 用此前 60 根指数收益回归，当前收益不参与；B 手数/A 手数 = β×FA×乘数A/(FB×乘数B)。"
                            "β 版本按当前 β 固定拆分最近 5 根，仅是诊断，不是逐期调仓收益。手数是理论小数，整数取整会留下敞口。"
                            "Z 为原始基差差的历史尺度，不是收益预测；分红差、风格趋势和 β 漂移会使回归假设失败。")
            rows.append(row)
    return rows


def build_research(states):
    valid = {p:s for p,s in states.items() if s.get("frequency")}
    frequency = next(iter(valid.values()), {}).get("frequency", "1d")
    basis = [row for state in valid.values() for row in contract_basis(state)]
    calendar = [row for state in valid.values() for row in calendar_pairs(state)]
    cross = cross_pairs(valid)
    times = [row["time"] for row in basis]
    return dict(version="basis_pairs_v1", frequency=frequency, window=WINDOW, beta_window=BETA_WINDOW,
                time=max(times) if times else None, basis=basis, calendar=calendar, cross=cross,
                note="历史研究观测 · Z 用此前20根，β用此前60个收益；分钟须同日同会话连续。未扣分红、资金及交易成本。")


# The publisher only exports display results, never raw frames, filesystem paths,
# credentials, or arbitrary model/config properties.
ROW_FIELDS = {"id", "title", "left", "right", "product", "value", "time", "z", "percentile", "mean", "samples", "reason",
              "change5", "direction", "series", "dte", "annual_pct", "annual_z", "notional", "future", "spot",
              "roll_down_bp_day", "expiry", "logic", "points", "carry_pct", "carry_z", "hedge_contracts",
              "delta_days", "equal_notional_contracts", "beta", "r_squared", "beta_reason", "simple_gap_bp",
              "spot_change5", "futures_change5", "basis_change5", "weighted_basis_change5",
              "weighted_spot_change5", "weighted_futures_change5"}


def export_research(value):
    result = {k:value[k] for k in ("version", "frequency", "window", "beta_window", "time", "note") if k in value}
    for category in ("basis", "calendar", "cross"):
        result[category] = [{k:v for k,v in row.items() if k in ROW_FIELDS} for row in value.get(category, [])[:64]]
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
