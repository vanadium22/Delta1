"""Three combined Matplotlib figures, with no market requests or display fills."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from ..analytics import NAMES
from .data import ORDER, PAIRS, WINDOWS, change

COLORS = ("#3371ba", "#d7952c", "#149b8c", "#915db4")
QCOLORS = ("#86a7c4", "#4b9b93", "#c6a057")
INK, MUTED, RED = "#1c344a", "#68798a", "#cd4d57"


def setup():
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False, "font.size": 9, "axes.titlesize": 11,
        "axes.titleweight": "bold", "axes.titlecolor": INK, "text.color": INK,
        "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": "#dce3e9", "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "axes.spines.top": False, "axes.spines.right": False,
    })


def number(value, decimals=1, signed=False):
    if not np.isfinite(value):
        return "—"
    return f"{value:+.{decimals}f}" if signed else f"{value:.{decimals}f}"


def header(fig, title, subtitle, note):
    fig.text(.052, .968, title, fontsize=21, weight="bold", color=INK, va="top")
    fig.text(.053, .934, subtitle, fontsize=10, color=MUTED, va="top")
    fig.text(.053, .024, note, fontsize=8.3, color=MUTED, va="bottom", linespacing=1.65)


def date_axis(ax, days):
    ticks = np.unique(np.linspace(0, max(len(days) - 1, 0), min(6, len(days))).astype(int))
    ax.set_xticks(ticks, [pd.Timestamp(days[i]).strftime("%m-%d") for i in ticks], fontsize=8)
    ax.tick_params(axis="both", labelsize=8, length=2)
    ax.grid(axis="y", color="#e8edf1", linewidth=.7)
    ax.set_axisbelow(True)
    if len(days):
        ax.set_xlim(-.6, len(days) - .3)
    ax.margins(y=.2)


def save(fig, output):
    fig.savefig(output, dpi=155)
    plt.close(fig)


def trends(panel, spreads, end, output, note, sessions=60):
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[-sessions:]
    recent = panel[panel.trade_date.isin(days)]
    cross = spreads[spreads.trade_date.isin(days)]
    fig, axes = plt.subplots(4, 2, figsize=(17.5, 13.2), gridspec_kw={"width_ratios": [1.28, 1]})
    fig.subplots_adjust(left=.055, right=.976, top=.834, bottom=.095, hspace=.78, wspace=.19)
    header(fig, "股指期货  /  近期基差与跨期", f"行情截至 {end:%Y-%m-%d}  ·  最近 {len(days)} 个本地交易日  ·  分红调整后，单位：点", note)
    fig.text(.055, .895, "单合约  00 / 01 / 02 / 03", fontsize=12, weight="bold")
    fig.text(.576, .895, "跨期  01−02 / 02−03（前者减后者）", fontsize=12, weight="bold")
    for row, root in enumerate(ORDER):
        for col, frame, key, ids in [(0, recent, "slot", range(1, 5)), (1, cross, "pair", PAIRS)]:
            ax = axes[row, col]
            ax.axhline(0, color="#b9c5cf", lw=.8, ls="--")
            ax.axvspan(max(-.5, len(days) - 10.5), len(days) - .5, color="#f1f5f8", zorder=0)
            labels = []
            for i, identity in enumerate(ids):
                g = frame[frame.root.eq(root) & frame[key].eq(identity)].set_index("trade_date").reindex(days)
                vals = g.basis_points.to_numpy()
                color = COLORS[i] if col == 0 else COLORS[i + 1]
                current = vals[-1] if len(vals) else np.nan
                name = f"{identity-1:02d}" if col == 0 else identity
                ax.plot(range(len(days)), vals, color=color, lw=1.65,
                        label=f"{name}  {number(current)}")
                if np.isfinite(current):
                    ax.scatter([len(days) - 1], [current], s=17, color=color, zorder=4)
                # Mark roll observations; their moves are not silently called price shocks.
                rolls = np.flatnonzero(g.roll_day.fillna(False).to_numpy(dtype=bool))
                ax.scatter(rolls, np.full(len(rolls), .025), transform=ax.get_xaxis_transform(),
                           marker="|", color=color, s=24, alpha=.7)
                labels.append(name)
            ax.set_title(f"{root}  {NAMES[root]}", loc="left", pad=30, fontsize=11)
            ax.legend(loc="lower left", bbox_to_anchor=(-.012, 1.015), ncol=4 if col == 0 else 2,
                      frameon=False, fontsize=8.3, handlelength=1.5, columnspacing=1.6)
            date_axis(ax, days)
            ax.set_ylabel("点", rotation=0, labelpad=9, fontsize=8)
    save(fig, output)


def distribution_axis(ax, rows, label):
    ax.set_title(label, loc="left", fontsize=10, pad=11)
    current = rows.current.iloc[0] if len(rows) else np.nan
    extents = [current] if np.isfinite(current) else []
    ticklabels = []
    for x, months, color in zip(range(3), WINDOWS, QCOLORS):
        q = rows[rows.months.eq(months)] if len(rows) else rows
        if q.empty or not bool(q.iloc[0].complete):
            ticklabels.append(f"{months}月\n不足")
            continue
        q = q.iloc[0]
        extents.extend([q.p05, q.p95])
        ax.plot([x, x], [q.p05, q.p95], color=color, lw=1.25)
        ax.plot([x-.13, x+.13], [q.p05, q.p05], color=color, lw=1.1)
        ax.plot([x-.13, x+.13], [q.p95, q.p95], color=color, lw=1.1)
        ax.add_patch(Rectangle((x-.23, q.p25), .46, q.p75-q.p25,
                              facecolor=color, edgecolor=color, alpha=.52))
        ax.plot([x-.23, x+.23], [q.p50, q.p50], color=INK, lw=1.2)
        ticklabels.append(f"{months}月\nP{q.percentile:.0f}%" if np.isfinite(q.percentile) else f"{months}月\nP—")
    if np.isfinite(current):
        ax.plot([-.25, 2.5], [current, current], color=RED, lw=.8, ls=(0, (2, 3)), alpha=.7)
        ax.scatter([2.85], [current], marker="D", color=RED, s=24, zorder=5)
        ax.annotate(number(current), (2.85, current), xytext=(5, 0), textcoords="offset points",
                    color=RED, fontsize=8.5, va="center", weight="bold")
    else:
        ax.text(.5, .5, "当前值缺失", transform=ax.transAxes, ha="center", color=MUTED)
    if extents:
        low, high = min(extents), max(extents)
        pad = max((high-low)*.18, 2)
        ax.set_ylim(low-pad, high+pad)
    ax.set_xlim(-.55, 4.55)
    ax.set_xticks(range(3), ticklabels, fontsize=7.6)
    ax.tick_params(axis="y", labelsize=7.3, length=2, pad=2)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#edf0f3", linewidth=.6)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)


def distributions(panel, single_q, cross_q, end, output, note):
    fig, axes = plt.subplots(4, 6, figsize=(18.6, 13.2))
    fig.subplots_adjust(left=.042, right=.987, top=.862, bottom=.105, hspace=.64, wspace=.36)
    header(fig, "股指期货  /  基差历史分位", f"行情截至 {end:%Y-%m-%d}  ·  各格独立纵轴，单位：点  ·  3 / 6 / 12 自然月，不含当日", note)
    fig.text(.042, .894, "单合约  00 / 01 / 02 / 03", fontsize=12, weight="bold")
    fig.text(.685, .894, "跨期  01−02 / 02−03", fontsize=12, weight="bold")
    fig.add_artist(Line2D([.669, .669], [.10, .873], transform=fig.transFigure, color="#d6e0e7", lw=1))
    for row, root in enumerate(ORDER):
        for col in range(6):
            if col < 4:
                q = single_q[single_q.root.eq(root) & single_q.slot.eq(col+1)]
                current = panel[panel.root.eq(root) & panel.slot.eq(col+1) & panel.trade_date.eq(end)]
                code = current.instrument_id.iloc[0] if len(current) else ""
                suffix = code[2:6] if code else "—"
                label = f"{root}{col:02d} · {suffix}"
            else:
                pair = list(PAIRS)[col-4]
                q = cross_q[cross_q.root.eq(root) & cross_q.pair.eq(pair)]
                label = f"{root}  {pair}"
            distribution_axis(axes[row, col], q, label)
    save(fig, output)


def activity(panel, end, output, note, sessions=60):
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[-sessions:]
    fig, axes = plt.subplots(4, 2, figsize=(17.5, 13.2))
    fig.subplots_adjust(left=.055, right=.976, top=.852, bottom=.095, hspace=.67, wspace=.19)
    header(fig, "股指期货  /  持仓与成交量", f"行情截至 {end:%Y-%m-%d}  ·  最近 {len(days)} 个本地交易日  ·  四档分别展示，跨期复用对应两腿", note)
    fig.legend(handles=[Line2D([0], [0], color=c, lw=3, label=f"{i:02d}") for i, c in enumerate(COLORS)],
               loc="upper left", bbox_to_anchor=(.05, .912), ncol=4, frameon=False, fontsize=10)
    for row, root in enumerate(ORDER):
        g = panel[panel.root.eq(root)].copy()
        for col, field, title in [(0, "open_interest", "持仓量"), (1, "volume", "成交量")]:
            ax = axes[row, col]
            wide = g.pivot(index="trade_date", columns="slot", values=field).reindex(index=days, columns=range(1, 5)) / 10000
            latest = wide.iloc[-1]
            total = latest.sum(min_count=4)
            suffix = f"四档合计 {number(total, 2)} 万手"
            ax.set_title(f"{root}  {NAMES[root]}  /  {title}    {suffix}", loc="left", fontsize=10.5, pad=12)
            for i, slot in enumerate(range(1, 5)):
                vals = wide[slot].to_numpy()
                if col == 0:
                    ax.plot(range(len(days)), vals, color=COLORS[i], lw=1.6)
                    if np.isfinite(vals[-1]):
                        ax.scatter([len(days)-1], [vals[-1]], color=COLORS[i], s=14)
                else:
                    # Grouped bars keep a missing leg blank instead of implying a full stacked sum.
                    ax.bar(np.arange(len(days)) + (i-1.5)*.2, vals, width=.19, color=COLORS[i], alpha=.8)
            if not wide.notna().any().any():
                ax.text(.5, .5, "本地未保存该字段", transform=ax.transAxes, ha="center", color=MUTED)
            date_axis(ax, days)
            ax.set_ylim(bottom=0)
            ax.set_ylabel("万手", rotation=0, labelpad=15, fontsize=8)
    save(fig, output)
