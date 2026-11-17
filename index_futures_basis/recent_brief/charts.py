"""Combined Matplotlib figures with large per-index panels and explicit units."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from ..analytics import NAMES
from .data import ORDER, PAIRS, activity_totals

COLORS = ("#3371ba", "#d7952c", "#149b8c", "#915db4")
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


def annualized(series, quantiles, end, output, note, sessions=60, key="slot"):
    """One wide trend plus one shared-axis candle panel per index, no per-contract axes."""
    days = sorted(series.loc[series.trade_date.le(end), "trade_date"].unique())[-sessions:]
    single = key == "slot"
    ids = list(range(1, 5)) if single else list(PAIRS)
    fig, axes = plt.subplots(4, 2, figsize=(17.5, 13.2), sharey="row",
                             gridspec_kw={"width_ratios": [2.25, 1]})
    fig.subplots_adjust(left=.06, right=.976, top=.843, bottom=.113, hspace=.83, wspace=.075)
    kind = "单合约年化基差" if single else "跨期年化基差"
    header(fig, f"股指期货  /  {kind}与60日分位",
           f"行情截至 {end:%Y-%m-%d}  ·  每品种合并展示  ·  单位：%  ·  分位使用此前60个交易日，不含当日", note)
    fig.text(.06, .894, "近期年化基差走势", fontsize=12, weight="bold")
    fig.text(.714, .894, "60交易日分布 / 当前值", fontsize=12, weight="bold")
    for row, root in enumerate(ORDER):
        trend, candles = axes[row]
        trend.set_title(f"{root}  {NAMES[root]}", loc="left", pad=30, fontsize=12)
        ticklabels = []
        for x, identity in enumerate(ids):
            color = COLORS[x] if single else COLORS[x+1]
            label = f"{identity-1:02d}" if single else identity
            g = series[series.root.eq(root) & series[key].eq(identity)].set_index("trade_date").reindex(days)
            vals = g.annualized_basis_pct.to_numpy()
            current = vals[-1]
            trend.plot(range(len(days)), vals, color=color, lw=1.8,
                       label=f"{label}  {number(current, 2)}%" if np.isfinite(current) else f"{label}  当前—")
            if np.isfinite(current):
                trend.scatter([len(days)-1], [current], color=color, s=20, zorder=5)
            if single:
                filled = g.annualized_plot_filled.eq(True).to_numpy()
                joins = filled | np.r_[filled[1:], False]
                trend.plot(range(len(days)), g.annualized_plot_pct.where(joins), color=color, lw=1.4, ls="--")
            qs = quantiles[quantiles.root.eq(root) & quantiles[key].eq(identity)]
            q = qs.iloc[0] if len(qs) else None
            percentile = number(q.percentile, 0) if q is not None else "—"
            sample = f"n={int(q.n)}" if q is not None and q.complete else "覆盖不足"
            ticklabels.append(f"{label}\nP{percentile}% · {sample}")
            if q is not None and q.complete:
                candles.plot([x, x], [q.p05, q.p95], color=color, lw=1.5)
                for y in (q.p05, q.p95):
                    candles.plot([x-.13, x+.13], [y, y], color=color, lw=1.4)
                candles.add_patch(Rectangle((x-.24, q.p25), .48, q.p75-q.p25,
                                            facecolor=color, edgecolor=color, alpha=.35))
                candles.plot([x-.24, x+.24], [q.p50, q.p50], color=INK, lw=1.6)
            if np.isfinite(current):
                candles.scatter([x+.28], [current], marker="D", color=RED, s=28, zorder=5)
                candles.annotate(f"{current:.2f}%", (x+.28, current), xytext=(4, 0),
                                 textcoords="offset points", va="center", color=RED, fontsize=8.2, weight="bold")
            elif single:
                candles.text(x, .96, "当前临期/缺失", transform=candles.get_xaxis_transform(),
                             ha="center", va="top", color=MUTED, fontsize=7.4)
        date_axis(trend, days)
        trend.set_ylabel("%", rotation=0, labelpad=12)
        if trend.get_ylim()[0] <= 0 <= trend.get_ylim()[1]:
            trend.axhline(0, color="#b9c5cf", lw=.8, ls="--")
        trend.legend(loc="lower left", bbox_to_anchor=(-.008, 1.015), ncol=len(ids),
                     frameon=False, fontsize=8.7, handlelength=1.5, columnspacing=1.6)
        candles.set_xticks(range(len(ids)), ticklabels, fontsize=8)
        candles.set_xlim(-.55, len(ids)-.03 if single else len(ids)+.15)
        candles.tick_params(axis="x", length=0)
        candles.tick_params(axis="y", left=False, labelleft=False)
        candles.grid(axis="y", color="#e8edf1", lw=.7)
        candles.set_axisbelow(True)
        candles.spines["left"].set_visible(False)
        candles.spines["bottom"].set_visible(False)
        trend.margins(y=.18)
    save(fig, output)


def activity(panel, end, output, note, sessions=60):
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[-sessions:]
    totals = activity_totals(panel)
    fig, axes = plt.subplots(2, 2, figsize=(17.5, 10))
    fig.subplots_adjust(left=.06, right=.943, top=.795, bottom=.15, hspace=.52, wspace=.26)
    header(fig, "股指期货  /  四合约总成交与总持仓",
           f"行情截至 {end:%Y-%m-%d}  ·  最近 {len(days)} 个本地交易日  ·  每品种00—03四合约相加，单位：万手", note)
    fig.legend(handles=[Rectangle((0, 0), 1, 1, color="#8bc9c0", label="总成交量 · 左轴"),
                        Line2D([0], [0], color=COLORS[0], lw=2.5, label="总持仓量 · 右轴")],
               loc="upper left", bbox_to_anchor=(.055, .91), ncol=2, frameon=False, fontsize=11)
    for ax, root in zip(axes.flat, ORDER):
        g = totals[totals.root.eq(root)].set_index("trade_date").reindex(days)
        volume, oi = g.volume/10000, g.open_interest/10000
        right = ax.twinx()
        ax.bar(range(len(days)), volume, width=.75, color="#8bc9c0", alpha=.85)
        right.plot(range(len(days)), oi, color=COLORS[0], lw=2.3)
        if np.isfinite(oi.iloc[-1]):
            right.scatter([len(days)-1], [oi.iloc[-1]], color=COLORS[0], s=26)
        ax.set_title(f"{root}  {NAMES[root]}", loc="left", fontsize=13, pad=30)
        ax.text(0, 1.025, f"总成交 {number(volume.iloc[-1], 2)} 万手     总持仓 {number(oi.iloc[-1], 2)} 万手",
                transform=ax.transAxes, fontsize=10, color=MUTED, va="bottom")
        date_axis(ax, days)
        ax.set_ylim(bottom=0)
        right.set_ylim(bottom=0)
        ax.set_ylabel("成交", rotation=0, labelpad=15, fontsize=9, color="#489c90")
        right.set_ylabel("持仓", rotation=0, labelpad=16, fontsize=9, color=COLORS[0])
        right.tick_params(axis="y", labelsize=8, colors=COLORS[0])
        right.spines["right"].set_visible(True)
        right.spines["right"].set_color("#dce3e9")
        if not volume.notna().any() or not oi.notna().any():
            ax.text(.5, .45, "部分字段缺失，四合约总量留空", transform=ax.transAxes,
                    color=MUTED, ha="center", fontsize=10)
    save(fig, output)
