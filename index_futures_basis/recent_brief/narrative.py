"""Auditable descriptive decision rules and templates, with no trained-model claims."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import ORDER

RULE_VERSION = "descriptive-tree-v1"


def classify_path(values):
    """Describe signed basis as discount/premium magnitude; never bridge a gap."""
    values = np.asarray(values, dtype=float)
    if len(values) != 40 or not np.isfinite(values).all():
        return {"shape": "insufficient", "text": "40日历史覆盖不足"}
    if np.max(np.abs(values)) <= 1e-8:
        return {"shape": "flat", "text": "维持平水", "current": 0.0}
    if (values <= 0).all():
        size, state = -values, "贴水"
    elif (values >= 0).all():
        size, state = values, "升水"
    else:
        return {"shape": "sign_change", "text": "期间出现升贴水切换", "current": float(values[-1])}
    # Five-session medians damp one-day noise. Require material moves on both
    # sides of an interior turning point, rather than force a two-stage pattern.
    smooth = pd.Series(size).rolling(5, center=True, min_periods=5).median()
    start, end = float(np.median(size[:5])), float(np.median(size[-5:]))
    interior = smooth.iloc[7:-7]
    high, low = float(interior.max()), float(interior.min())
    noise = float(np.mean(np.abs(np.diff(size))))
    threshold = max(3., .15*float(np.ptp(size)), 2*noise)
    if high-max(start,end) >= threshold and high-start >= threshold and high-end >= threshold:
        shape, text = "widen_then_narrow", f"{state}幅度先扩大后收敛"
    elif min(start,end)-low >= threshold and start-low >= threshold and end-low >= threshold:
        shape, text = "narrow_then_widen", f"{state}幅度先收敛后扩大"
    elif end-start >= threshold:
        shape, text = "widen", f"{state}幅度总体扩大"
    elif start-end >= threshold:
        shape, text = "narrow", f"{state}幅度总体收敛"
    else:
        shape, text = "range", f"{state}幅度以区间波动为主"
    return {"shape": shape, "text": text, "state": state, "start_median": start,
            "end_median": end, "interior_high": high, "interior_low": low,
            "threshold": threshold, "noise": noise, "current": float(values[-1])}


def compose(panel, spreads, single_ranks, cross_ranks, totals, end):
    """Generate one connected paragraph and retain all evidence for review."""
    end = pd.Timestamp(end)
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[-40:]
    paths, clauses, missing = {}, [], []
    for root in ORDER:
        # 03 is an explicitly named representative, not a claim about all tenors.
        group = panel[panel.root.eq(root) & panel.slot.eq(4)].set_index("trade_date").reindex(days)
        valid = len(days) == 40 and group.calendar_known.eq(True).all()
        feature = classify_path(group.basis_points.to_numpy()) if valid else {"shape": "insufficient", "text": "40日历史覆盖不足"}
        paths[root] = feature
        if feature["shape"] == "insufficient":
            missing.append(root)
        else:
            clauses.append(f"{root}03{feature['text']}")
    pieces = []
    if clauses:
        pieces.append("近40个交易日的去分红绝对基差中，"+"，".join(clauses)+"。")
    if missing:
        pieces.append("、".join(missing)+"的40日历史不足，暂不判断走势。")
    q = single_ranks[single_ranks.window_sessions.eq(60) & single_ranks.slot.gt(1)
                     & single_ranks.complete & single_ranks.percentile.notna()].copy()
    low = q[q.percentile.le(20)].sort_values(["percentile", "current", "root", "slot"]).head(3)
    rank_evidence = []
    if len(low):
        labels = []
        for row in low.itertuples():
            labels.append(f"{row.root}{row.slot-1:02d}（{row.current:.2f}%，P{row.percentile:.1f}%）")
            rank_evidence.append({"root": row.root, "slot": row.slot, "current": row.current, "percentile": row.percentile})
        negative = low.current.lt(0).all()
        pieces.append("年化基差方面，"+"、".join(labels)+"位于各自60日历史低分位，"+
                      ("年化贴水相对自身历史较深。" if negative else "当前年化水平相对自身历史较低。"))
    elif len(q):
        pieces.append("01—03档年化基差目前均未进入各自60日历史最低20%区间。")
    else:
        pieces.append("单合约年化历史覆盖不足，暂不判断低分位状态。")
    cq = cross_ranks[cross_ranks.window_sessions.eq(60) & cross_ranks.complete & cross_ranks.percentile.notna()].copy()
    if len(cq):
        cq["distance"] = (cq.percentile-50).abs()
        row = cq.sort_values(["distance", "root", "pair"], ascending=[False,True,True]).iloc[0]
        location = "偏高" if row.percentile >= 80 else "偏低" if row.percentile <= 20 else "处于中部区间"
        pieces.append(f"跨期中，{row.root} {row.pair}当前年化{row.current:.2f}%，60日分位P{row.percentile:.1f}%，相对历史{location}。")
    finite = totals[totals[["oi_current","volume_current","oi_change_5d","volume_change_5d"]].notna().all(axis=1)]
    if len(finite):
        together = finite[finite.oi_change_5d.gt(0) & finite.volume_change_5d.gt(0)]
        falling = finite[finite.oi_change_5d.lt(0) & finite.volume_change_5d.lt(0)]
        if len(together):
            pieces.append("量仓方面，"+"、".join(together.root)+"近5日均为增仓伴随成交扩张。")
        if len(falling):
            pieces.append("、".join(falling.root)+"近5日减仓与成交收缩同向。")
        row = finite.loc[finite.oi_change_5d.abs().idxmax()]
        pieces.append(f"其中{row.root}四合约总持仓为{row.oi_current/10000:.2f}万手，近5日{row.oi_change_5d/10000:+.2f}万手；总成交为{row.volume_current/10000:.2f}万手，近5日{row.volume_change_5d/10000:+.2f}万手。")
        active = finite[np.isfinite(finite.volume_multiple)]
        if len(active):
            row = active.loc[active.volume_multiple.idxmax()]
            pieces.append(f"当前成交相对前20日中位数的倍数以{row.root}最高，为{row.volume_multiple:.2f}倍。")
    else:
        pieces.append("量仓可比数据不足，暂不判断近期方向。")
    recent = panel[panel.trade_date.isin(days) & panel.slot.eq(4)]
    if recent.roll_day.eq(True).any():
        pieces.append("上述绝对基差走势的部分变化伴随合约换月。")
    return {"engine": RULE_VERSION, "text": "".join(pieces), "as_of": str(end.date()),
            "window_sessions": 40, "basis_representative_slot": "03", "basis_paths": paths,
            "low_annualized_ranks": rank_evidence,
            "policy": "deterministic descriptive decision tree and templates; no fitted predictive model; no future returns"}
