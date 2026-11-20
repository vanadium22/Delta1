"""Tall, high-resolution panels with computed cards and in-axis current markers."""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import MaxNLocator
import json
import numpy as np
import pandas as pd

from ..analytics import NAMES
from .charts import COLORS, INK, MUTED, RED, number, setup
from .data import (CALENDAR_CHART_MONTHS, CALENDAR_RANK_SESSIONS, ORDER, PAIRS,
                   SINGLE_RANK_SESSIONS, activity_totals)
from .metrics import series_metrics, total_metrics

STYLES = ("-", (0, (5, 2)), (0, (4, 2, 1, 2)), (0, (1, 1.5)))
DPI = 200
CARD_FACE, CARD_EDGE = "#F4F7FB", "#DCE5EF"
VOLUME, VOLUME_BAR, VOLUME_LIGHT = "#248F82", "#389F91", "#B9DDD8"
LOW_RANK, HIGH_RANK = "#E7F1FC", "#FAECE8"


def _header(fig, title, subtitle, note):
    fig.text(.055, .985, title, fontsize=25, weight="bold", va="top", color=INK)
    fig.text(.055, .985-40/(72*fig.get_figheight()), subtitle.split(" · ", 1)[0], fontsize=11, va="top", color=MUTED)




def _date_axis(ax, days):
    ticks = np.unique(np.linspace(0, len(days)-1, min(6, len(days))).astype(int))
    ax.set_xticks(ticks, [pd.Timestamp(days[i]).strftime("%m-%d") for i in ticks], fontsize=10)
    ax.tick_params(axis="y", labelsize=10, length=3)
    ax.yaxis.set_major_locator(MaxNLocator(7))
    ax.set_xlim(-.5, len(days)-.15)
    ax.grid(axis="y", color="#e4ebf2", linewidth=.75)
    ax.set_axisbelow(True)
    ax.margins(y=.12)


def _calendar_chart_days(series, end):
    start = end - pd.DateOffset(months=CALENDAR_CHART_MONTHS)
    return sorted(series.loc[series.trade_date.between(start, end), "trade_date"].unique())


def _save(fig, output):
    # Vector companion and 3800px-wide PNG are produced from the same figure.
    fig.set_dpi(DPI)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    labels = [t for ax in fig.axes for t in ax.texts if t.get_gid() == "current-value-label"]
    for label in labels:
        bounds = label.get_bbox_patch().get_window_extent(renderer)
        area = label.axes.bbox
        dx = max(area.x0+6-bounds.x0, 0)-max(bounds.x1-area.x1+6, 0)
        dy = max(area.y0+6-bounds.y0, 0)-max(bounds.y1-area.y1+6, 0)
        x, y = label.get_position()
        label.set_position((x+dx*72/DPI, y+dy*72/DPI))
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    contained = []
    for label in labels:
        bounds, area = label.get_bbox_patch().get_window_extent(renderer), label.axes.bbox
        contained.append({"text": label.get_text(), "inside_axes": bool(
            bounds.x0 >= area.x0 and bounds.x1 <= area.x1 and bounds.y0 >= area.y0 and bounds.y1 <= area.y1)})
    fig.savefig(output, dpi=DPI)
    fig.savefig(output.with_suffix(".svg"))
    output.with_suffix(".layout.json").write_text(json.dumps({"pixels": [int(fig.bbox.width), int(fig.bbox.height)],
        "dpi": DPI, "current_value_labels": contained,
        "quantile_tables": [[cell.get_text().get_text() for cell in table.get_celld().values()]
                            for ax in fig.axes for table in ax.tables if table.get_gid() == "rank-table"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    plt.close(fig)


def _trend(ax, series, root, key, ids, days, field, annual=False):
    ax.axvspan(max(-.5, len(days)-6), len(days)-1, color="#edf3f8", zorder=0)
    handles = []
    near_axis = ax.twinx() if annual and key == "slot" and 1 in ids else None
    for i, identity in enumerate(ids):
        style_index = identity-1 if key == "slot" else i+1
        color = COLORS[style_index]
        name = f"{identity-1:02d}" if key == "slot" else identity
        g = series[series.root.eq(root) & series[key].eq(identity)].set_index("trade_date").reindex(days)
        values = g[field].to_numpy()
        target = near_axis if near_axis is not None and identity == 1 else ax
        target.plot(range(len(days)), values, color=color, lw=1.6, ls=STYLES[style_index], alpha=.88)
        first = max(0, len(days)-6)
        target.plot(range(first, len(days)), values[first:], color=color, lw=2.6, ls=STYLES[style_index])
        if np.isfinite(values[-1]):
            target.scatter([len(days)-1], [values[-1]], s=42, color=color, edgecolor="white", lw=.7, zorder=6)
        if np.isfinite(values[first]):
            target.scatter([first], [values[first]], s=24, facecolor="white", edgecolor=color, lw=1.2, zorder=5)
        if annual and key == "slot":
            fill = g.annualized_plot_filled.eq(True).to_numpy()
            joins = fill | np.r_[fill[1:], False]
            target.plot(range(len(days)), g.annualized_plot_pct.where(joins), color=color, ls="--", lw=1.1, alpha=.65)
        handles.append(Line2D([0], [0], color=color, lw=2, ls=STYLES[style_index], label=name))
    _date_axis(ax, days)
    if ax.get_ylim()[0] <= 0 <= ax.get_ylim()[1]:
        ax.axhline(0, color="#aab9c6", lw=.8, ls="--")
    ax.legend(handles=handles, loc="upper left", ncol=len(ids), fontsize=10, frameon=True,
              facecolor="white", edgecolor="none", framealpha=.85, handlelength=2.3)
    ax.set_ylabel("01—03 / %" if near_axis is not None else "%" if annual else "点", fontsize=10)
    if near_axis is not None:
        near_axis.set_ylabel("00 / %", color=COLORS[0], fontsize=10)
        near_axis.tick_params(axis="y", labelsize=10, colors=COLORS[0])
        near_axis.yaxis.set_major_locator(MaxNLocator(6))
        near_axis.margins(y=.12)
        near_axis.spines["right"].set_visible(True)
        near_axis.spines["right"].set_color(COLORS[0])


def _candle_panel(ax, qs, key, ids, current):
    """Current diamonds are centered on their own candle, with labels kept inside axes."""
    extents, labels, annotations = {"main": [], "near": []}, [], []
    near_axis = ax.twinx() if key == "slot" else None
    if near_axis is not None:
        ax.axvspan(-.5, .5, color="#f0f5fc", zorder=0)
    for i, identity in enumerate(ids):
        color = COLORS[i] if key == "slot" else COLORS[i+1]
        name = f"{identity-1:02d}" if key == "slot" else identity
        rows = qs[qs[key].eq(identity)]
        q = rows.iloc[0] if len(rows) else None
        metric = current[current[key].eq(identity)]
        actual = metric.annual_current.iloc[0] if len(metric) else np.nan
        target = near_axis if near_axis is not None and identity == 1 else ax
        extent_key = "near" if target is near_axis else "main"
        rank = number(q.percentile, 1) if q is not None else "—"
        sample = f"有效n={int(q.n)}" if q is not None and q.complete else "覆盖不足"
        labels.append(f"{name}\n{sample}")
        if q is not None and q.complete:
            extents[extent_key].extend([q.p05, q.p95])
            target.plot([i, i], [q.p05, q.p95], color=color, lw=1.8)
            for value in (q.p05, q.p95):
                target.plot([i-.16, i+.16], [value, value], color=color, lw=1.7)
            target.add_patch(Rectangle((i-.25, q.p25), .5, q.p75-q.p25,
                                  facecolor=color, edgecolor=color, alpha=.32))
            target.plot([i-.25, i+.25], [q.p50, q.p50], color=INK, lw=1.8)
        if np.isfinite(actual):
            extents[extent_key].append(actual)
            marker = target.scatter([i], [actual], marker="D", color=RED, edgecolor="white", lw=.7, s=58, zorder=7)
            marker.set_gid("current-value")
            annotations.append((target, extent_key, i, actual, f"P{rank}%"))
        else:
            reason = "当前到期/缺失" if key == "slot" else "当前缺失"
            target.text(i, .95, reason, transform=target.get_xaxis_transform(), color=MUTED, fontsize=9, ha="center", va="top")
    limits = {}
    for target, extent_key in ((ax, "main"), (near_axis, "near")):
        if target is None:
            continue
        values = extents[extent_key]
        low, high = (min(values), max(values)) if values else (-1, 1)
        pad = max((high-low)*.16, .25)
        target.set_ylim(low-pad, high+pad)
        limits[extent_key] = (low, high)
    ax.set_xlim(-.55, len(ids)-.45)
    for target, extent_key, x, y, rank_label in annotations:
        low, high = limits[extent_key]
        upper = (y-low)/(high-low) > .72 if high != low else False
        label = target.annotate(rank_label, (x, y), xytext=(0, -16 if upper else 16),
                    textcoords="offset points", ha="center", va="top" if upper else "bottom",
                    color=RED, fontsize=10, weight="bold", clip_on=True, annotation_clip=True,
                    bbox={"boxstyle": "round,pad=.23", "fc": "white", "ec": "#edc4c9", "lw": .6}, zorder=8)
        label.set_gid("current-value-label")
    ax.set_xticks(range(len(ids)), labels, fontsize=10)
    ax.tick_params(axis="x", length=0, pad=8)
    ax.tick_params(axis="y", labelsize=10, length=3)
    ax.yaxis.set_major_locator(MaxNLocator(7))
    ax.grid(axis="y", color="#e4ebf2", linewidth=.75)
    ax.set_axisbelow(True)
    ax.set_ylabel("01—03 / %" if near_axis is not None else "%", fontsize=10)
    if near_axis is not None:
        near_axis.set_ylabel("00 / %", color=COLORS[0], fontsize=10)
        near_axis.tick_params(axis="y", colors=COLORS[0], labelsize=10)
        near_axis.yaxis.set_major_locator(MaxNLocator(6))
        near_axis.spines["right"].set_visible(True)
        near_axis.spines["right"].set_color(COLORS[0])



def _value(value, suffix="", signed=False):
    try:
        return (
            (f"{value:+.2f}" if signed else f"{value:,.2f}") + suffix
            if np.isfinite(value)
            else "—"
        )
    except (TypeError, ValueError):
        return "—"


def _get(row, field):
    return row.get(field, np.nan) if row is not None else np.nan


def _metric(current, key, identity):
    matches = current[current[key].eq(identity)]
    return matches.iloc[0] if len(matches) else None


def _card(fig, x, y, width, height, title, value, change, color):
    fig.add_artist(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            transform=fig.transFigure,
            boxstyle="round,pad=0.003,rounding_size=0.004",
            facecolor=CARD_FACE,
            edgecolor=CARD_EDGE,
            lw=0.7,
        )
    )
    fig.add_artist(
        Rectangle(
            (x, y + 0.005),
            0.003,
            height - 0.01,
            transform=fig.transFigure,
            facecolor=color,
            edgecolor="none",
        )
    )
    fig.text(x + 0.012, y + height * 0.79, title, fontsize=13, color="#40566B", va="center")
    fig.text(
        x + 0.012,
        y + height * 0.46,
        value,
        fontsize=22,
        weight="bold",
        color=color,
        va="center",
    )
    fig.text(
        x + 0.012, y + height * 0.14, change, fontsize=11.5, color="#40566B", va="center"
    )


def _quantile_table(ax, qs, key, ids, current):
    """Each full window shows rank, annualized mean and annualized median."""
    ax.axis("off")
    windows = SINGLE_RANK_SESSIONS if key == "slot" else CALENDAR_RANK_SESSIONS
    body = []
    for identity in ids:
        row = _metric(current, key, identity)
        cells = [
            f"{identity-1:02d}" if key == "slot" else identity,
            _value(_get(row, "annual_current"), "%"),
        ]
        for window in windows:
            matches = qs[qs[key].eq(identity) & qs.window_sessions.eq(window)]
            q = matches.iloc[0] if len(matches) else None
            if q is not None and q.complete == True:
                rank = (
                    f"P{q.percentile:.2f}%" if np.isfinite(q.percentile) else "分位 —"
                )
                text = (
                    rank
                    + "\n均值 "
                    + _value(q["mean"], "%")
                    + "\n中位数 "
                    + _value(q.p50, "%")
                )
            else:
                text = "分位 —\n均值 —\n中位数 —"
            cells.append(text)
        body.append(cells)
    table = ax.table(
        cellText=body,
        colLabels=["合约" if key == "slot" else "跨期", "当前年化", *(f"{n}日" for n in windows)],
        colWidths=[0.12, 0.18, *([0.70 / len(windows)] * len(windows))],
        cellLoc="center",
        bbox=[0, 0, 1, 1],
    )
    table.set_gid("rank-table")
    table.auto_set_font_size(False)
    for (i, j), cell in table.get_celld().items():
        cell.set_edgecolor("#D9E1E9")
        cell.set_linewidth(0.7)
        cell.set_facecolor("#264B6C" if i == 0 else "white" if i % 2 else "#F0F5FA")
        cell.get_text().set_color("white" if i == 0 else "#233F59")
        cell.get_text().set_fontsize(12.5 if i == 0 else 12)
        if i == 0 or j in (0, 1):
            cell.get_text().set_weight("bold")
        if i > 0 and j >= 2 and cell.get_text().get_text().startswith("P"):
            rank = float(cell.get_text().get_text().split("%", 1)[0][1:])
            if rank <= 5:
                cell.set_facecolor(LOW_RANK)
            elif rank >= 95:
                cell.set_facecolor(HIGH_RANK)
    return table


def annualized(
    series, quantiles, end, output, note, sessions=60, key="slot", metrics=None
):
    days = sorted(series.loc[series.trade_date.le(end), "trade_date"].unique())[
        -sessions:
    ] if key == "slot" else _calendar_chart_days(series, end)
    metrics = series_metrics(series, end, key) if metrics is None else metrics
    ids = [2, 3, 4] if key == "slot" else list(PAIRS)
    table_ids = [1, 2, 3, 4] if key == "slot" else ids
    fig = plt.figure(figsize=(19, 26))
    title = "单合约年化与分位统计" if key == "slot" else "跨期年化与分位统计"
    subtitle = f"行情截至 {end:%Y-%m-%d}"
    if key == "pair":
        subtitle += "  跨期走势近半年"
    _header(fig, title, subtitle, note)
    for index, root in enumerate(ORDER):
        top = 0.94 - index * 0.225
        fig.text(
            0.055, top, f"{root}  {NAMES[root]}", fontsize=18, weight="bold", va="top"
        )
        current = metrics[metrics.root.eq(root)]
        width = (0.90 - (len(ids) - 1) * 0.012) / len(ids)
        for i, identity in enumerate(ids):
            row = _metric(current, key, identity)
            label = (
                f"{identity-1:02d}  " + {2: "次月", 3: "季月一", 4: "季月二"}[identity]
                if key == "slot"
                else identity
            )
            color = COLORS[identity - 1] if key == "slot" else COLORS[i + 1]
            _card(
                fig,
                0.055 + i * (width + 0.012),
                top - 0.060,
                width,
                0.041,
                label,
                _value(_get(row, "annual_current"), "%"),
                "日变 "
                + _value(_get(row, "annual_change_1d_pct_points"), "个百分点", True),
                color,
            )
        trend_width, table_left = (0.46, 0.56) if key == "slot" else (0.41, 0.505)
        ax = fig.add_axes([0.055, top - 0.205, trend_width, 0.135])
        _trend(ax, series, root, key, ids, days, "annualized_basis_pct", annual=True)
        ax.tick_params(axis="both", labelsize=11)
        _quantile_table(
            fig.add_axes([table_left, top - 0.205, 0.955 - table_left, 0.135]),
            quantiles[quantiles.root.eq(root)],
            key,
            table_ids,
            current,
        )
    _save(fig, output)


def trends(
    panel,
    spreads,
    end,
    output,
    note,
    sessions=60,
    single_metrics=None,
    cross_metrics=None,
):
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[
        -sessions:
    ]
    cross_days = _calendar_chart_days(panel, end)
    single_metrics = (
        series_metrics(panel, end, "slot") if single_metrics is None else single_metrics
    )
    cross_metrics = (
        series_metrics(spreads, end, "pair") if cross_metrics is None else cross_metrics
    )
    fig = plt.figure(figsize=(19, 26))
    _header(fig, "去分红绝对基差与跨期",
            f"行情截至 {end:%Y-%m-%d}  单合约近{sessions}个交易日  跨期走势近半年", note)
    for index, root in enumerate(ORDER):
        top = 0.94 - index * 0.225
        fig.text(
            0.055, top, f"{root}  {NAMES[root]}", fontsize=18, weight="bold", va="top"
        )
        for frame, metrics, key, ids, x, width in (
            (panel, single_metrics, "slot", [1, 2, 3, 4], 0.055, 0.51),
            (spreads, cross_metrics, "pair", list(PAIRS), 0.625, 0.33),
        ):
            current = metrics[metrics.root.eq(root)]
            card_width = (width - (len(ids) - 1) * 0.008) / len(ids)
            for i, identity in enumerate(ids):
                row = _metric(current, key, identity)
                label = f"{identity-1:02d}" if key == "slot" else identity
                _card(
                    fig,
                    x + i * (card_width + 0.008),
                    top - 0.060,
                    card_width,
                    0.041,
                    label,
                    _value(_get(row, "basis_current"), "点"),
                    "日变 " + _value(_get(row, "basis_change_1d"), "点", True),
                    COLORS[i] if key == "slot" else COLORS[i + 1],
                )
            ax = fig.add_axes([x, top - 0.205, width, 0.135])
            _trend(ax, frame, root, key, ids, days if key == "slot" else cross_days, "basis_points")
            ax.tick_params(axis="both", labelsize=11)
    _save(fig, output)


def activity(panel, end, output, note, sessions=60, metrics=None):
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[
        -sessions:
    ]
    metrics = total_metrics(panel, end) if metrics is None else metrics
    totals = activity_totals(panel)
    fig = plt.figure(figsize=(19, 22))
    _header(fig, "四合约总成交与总持仓", f"行情截至 {end:%Y-%m-%d}", note)
    for i, root in enumerate(ORDER):
        x, top = (0.065 if i % 2 == 0 else 0.555), 0.925 - (i // 2) * 0.435
        width = 0.38
        fig.text(x, top, f"{root}  {NAMES[root]}", fontsize=18, weight="bold", va="top")
        matches = metrics[metrics.root.eq(root)]
        row = matches.iloc[0] if len(matches) else None
        for j, prefix, label, color in (
            (0, "oi", "总持仓", COLORS[0]),
            (1, "volume", "总成交", VOLUME),
        ):
            _card(
                fig,
                x + j * (width / 2 + 0.006),
                top - 0.087,
                width / 2 - 0.006,
                0.065,
                label,
                _value(_get(row, prefix + "_current") / 10000, "万手"),
                "日变 " + _value(_get(row, prefix + "_change_1d_pct"), "%", True),
                color,
            )
        ax = fig.add_axes([x, top - 0.370, width, 0.265])
        right = ax.twinx()
        g = totals[totals.root.eq(root)].set_index("trade_date").reindex(days)
        ax.bar(
            range(len(days)),
            g.volume / 10000,
            color=[VOLUME_LIGHT] * max(0, len(days) - 5) + [VOLUME_BAR] * min(5, len(days)),
            width=0.72,
        )
        ax.axvspan(max(-0.5, len(days) - 6), len(days) - 1, color="#EDF3F8", zorder=0)
        right.plot(range(len(days)), g.open_interest / 10000, color=COLORS[0], lw=2)
        first = max(0, len(days) - 6)
        right.plot(
            range(first, len(days)),
            g.open_interest.iloc[first:] / 10000,
            color=COLORS[0],
            lw=3,
        )
        if np.isfinite(g.open_interest.iloc[-1]):
            right.scatter(
                [len(days) - 1],
                [g.open_interest.iloc[-1] / 10000],
                s=44,
                color=COLORS[0],
                edgecolor="white",
                zorder=5,
            )
        _date_axis(ax, days)
        if g.volume.notna().any():
            ax.set_ylim(bottom=0)
        else:
            ax.set_yticks([])
        if not g.volume.notna().any() or not g.open_interest.notna().any():
            ax.text(
                0.5,
                0.45,
                "部分字段缺失，总量留空",
                transform=ax.transAxes,
                ha="center",
                fontsize=12,
                color=MUTED,
            )
        ax.set_ylabel("成交量 / 万手", fontsize=12, color=VOLUME)
        right.set_ylabel("持仓量 / 万手", fontsize=12, color=COLORS[0])
        right.tick_params(axis="y", labelsize=11, colors=COLORS[0])
        right.yaxis.set_major_locator(MaxNLocator(7))
        right.spines["right"].set_visible(True)
        right.spines["right"].set_color("#DCE3E9")
        right.margins(y=0.15)
        ax.tick_params(axis="both", labelsize=11)
    _save(fig, output)
