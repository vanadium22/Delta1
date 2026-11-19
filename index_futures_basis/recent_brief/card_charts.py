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
from .data import ORDER, PAIRS, activity_totals
from .metrics import series_metrics, total_metrics, price_audit_lines

STYLES = ("-", (0, (5, 2)), (0, (4, 2, 1, 2)), (0, (1, 1.5)))
DPI = 200


def _header(fig, title, subtitle, note):
    fig.text(.055, .985, title, fontsize=25, weight="bold", va="top", color=INK)
    fig.text(.055, .985-40/(72*fig.get_figheight()), subtitle.split(" · ", 1)[0], fontsize=11, va="top", color=MUTED)


def _card(fig, x, y, width, height, title, value, detail, secondary, color, audit=()):
    fig.add_artist(FancyBboxPatch((x, y), width, height, transform=fig.transFigure,
                   boxstyle="round,pad=0.003,rounding_size=0.004", facecolor="#f5f8fb",
                   edgecolor="#e0e7ef", linewidth=.8, zorder=2))
    fig.add_artist(Rectangle((x, y+.006), .0023, height-.012, transform=fig.transFigure,
                             facecolor=color, edgecolor="none", zorder=3))
    pad = min(.009, width*.06)
    lines = (
        (title, y+height*.86, 10.5, MUTED, "normal"),
        (value, y+height*.58, 22, color, "bold"),
        (detail, y+height*.28, 10, INK, "normal"),
        (secondary, y+height*.08, 9.8, MUTED, "normal"))
    if audit:
        lines = ((title, y+height*.90, 10.5, MUTED, "normal"),
                 (value, y+height*.73, 22, color, "bold"),
                 (detail, y+height*.55, 9.4, INK, "normal"),
                 (secondary, y+height*.41, 9.4, MUTED, "normal"))
        lines += tuple((line, y+height*pos, 9.0, INK, "normal")
                       for line, pos in zip(audit, (.27, .16, .05)))
    for text, ypos, size, tone, weight in lines:
        fig.text(x+pad, ypos, text, fontsize=size, va="center", color=tone, weight=weight, zorder=4)


def _date_axis(ax, days):
    ticks = np.unique(np.linspace(0, len(days)-1, min(6, len(days))).astype(int))
    ax.set_xticks(ticks, [pd.Timestamp(days[i]).strftime("%m-%d") for i in ticks], fontsize=10)
    ax.tick_params(axis="y", labelsize=10, length=3)
    ax.yaxis.set_major_locator(MaxNLocator(7))
    ax.set_xlim(-.5, len(days)-.15)
    ax.grid(axis="y", color="#e4ebf2", linewidth=.75)
    ax.set_axisbelow(True)
    ax.margins(y=.12)


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


def _quantile_table(ax, qs, key, ids, current):
    ax.axis("off")
    body = []
    for identity in ids:
        rows = current[current[key].eq(identity)]
        row = rows.iloc[0] if len(rows) else None
        label = f"{identity-1:02d}" if key == "slot" else identity
        if row is not None and key == "slot":
            label += f" · T{int(row.days_to_expiry)}" if pd.notna(row.days_to_expiry) else ""
            label += "\n"+row.contract.replace(".CFE", "")
        value = f"{row.annual_current:.2f}%" if row is not None and np.isfinite(row.annual_current) else "—"
        cells = [label, value]
        for window in (30, 60, 120):
            matches = qs[qs[key].eq(identity) & qs.window_sessions.eq(window)]
            q = matches.iloc[0] if len(matches) else None
            cells.append((f"P{q.percentile:.1f}%\nn={int(q.n)}" if q is not None and np.isfinite(q.percentile)
                          else f"—\nn={int(q.n) if q is not None else 0}/{window}"))
        body.append(cells)
    table = ax.table(cellText=body, colLabels=["合约", "当前年化", "30日分位", "60日分位", "120日分位"],
                     colWidths=[.24,.19,.19,.19,.19], cellLoc="center", bbox=[0,0,1,1])
    table.set_gid("rank-table")
    table.auto_set_font_size(False)
    table.set_fontsize(10.5)
    for (r,c), cell in table.get_celld().items():
        cell.set_edgecolor("#e0e7ef")
        cell.set_linewidth(.7)
        cell.set_facecolor("#e8eef6" if r == 0 else "white" if r%2 else "#f5f8fb")
        cell.get_text().set_color(INK)
        if r == 0:
            cell.get_text().set_weight("bold")
        if r > 0 and c >= 2 and cell.get_text().get_text().startswith("P"):
            percentile = float(cell.get_text().get_text().split("%",1)[0][1:])
            if percentile <= 5 or percentile >= 95:
                cell.set_facecolor("#fbe9e8" if percentile >= 95 else "#e8f1fc")
                cell.get_text().set_color(RED if percentile >= 95 else COLORS[0])
    return table


def annualized(series, quantiles, end, output, note, sessions=60, key="slot", metrics=None):
    days = sorted(series.loc[series.trade_date.le(end), "trade_date"].unique())[-sessions:]
    metrics = series_metrics(series, end, key, quantiles) if metrics is None else metrics
    ids = [2, 3, 4] if key == "slot" else list(PAIRS)
    table_ids = [1, 2, 3, 4] if key == "slot" else list(PAIRS)
    kind = "单合约" if key == "slot" else "跨期"
    fig = plt.figure(figsize=(19, 30))
    _header(fig, f"股指期货 / {kind}年化与历史分位表",
            f"行情截至 {end:%Y-%m-%d} · T≥1均计算 · 卡片：当前值、1日/5日变化、分位日变 · " +
            ("年化走势仅01—03，00保留在表格" if key == "slot" else "跨期仅01−02、02−03；前30/60/120交易日分位"), note)
    for row, root in enumerate(ORDER):
        top = .934-row*.222
        fig.text(.06, top, f"{root}  {NAMES[root]}", fontsize=16, weight="bold", va="top")
        current = metrics[metrics.root.eq(root)]
        width = (.894-(len(ids)-1)*.010)/len(ids)
        for i, identity in enumerate(ids):
            matches = current[current[key].eq(identity)]
            r = matches.iloc[0] if len(matches) else None
            label = f"{root}{identity-1:02d}" if key == "slot" else f"{root} {identity}"
            color = COLORS[identity-1] if key == "slot" else COLORS[i+1]
            if r is None:
                value, detail, secondary = "—", "日变 — · 5日 —", "60日分位 —"
            else:
                value = f"{r.annual_current:.2f}%" if np.isfinite(r.annual_current) else "—"
                if key == "slot":
                    label += " · " + r.contract.replace(".CFE", "")
                    if pd.notna(r.days_to_expiry):
                        label += f" · T={int(r.days_to_expiry)}"
                detail = f"日变 {number(r.annual_change_1d_pct_points, 2, True)} / 5日 {number(r.annual_change_5d_pct_points, 2, True)} 个百分点"
                secondary = f"60日 P{number(r.percentile, 1)}%  ·  分位日变 {number(r.percentile_change_1d, 1, True)}个百分点"
                if r.roll_5d:
                    secondary += " · 含换月"
            audit = price_audit_lines(r) if r is not None else ("指数 —", "期货 —", "分红 —")
            _card(fig, .06+i*(width+.010), top-.088, width, .068, label, value, detail, secondary, color, audit)
        trend = fig.add_axes([.06, top-.208, .47, .112])
        rank_axis = fig.add_axes([.592, top-.208, .362, .112])
        _trend(trend, series, root, key, ids, days, "annualized_basis_pct", annual=True)
        _quantile_table(rank_axis, quantiles[quantiles.root.eq(root)], key, table_ids, current)
    _save(fig, output)


def trends(panel, spreads, end, output, note, sessions=60, single_metrics=None, cross_metrics=None):
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[-sessions:]
    single_metrics = series_metrics(panel, end, "slot") if single_metrics is None else single_metrics
    cross_metrics = series_metrics(spreads, end, "pair") if cross_metrics is None else cross_metrics
    fig = plt.figure(figsize=(19, 30))
    _header(fig, "股指期货 / 去分红绝对基差与跨期",
            f"行情截至 {end:%Y-%m-%d} · 当前点数与1日/5日变化自动计算 · 阴影及加粗线为最近5个交易日", note)
    for row, root in enumerate(ORDER):
        top = .934-row*.222
        fig.text(.06, top, f"{root}  {NAMES[root]}", fontsize=16, weight="bold", va="top")
        for frame, metrics, key, ids, x, width in (
            (panel, single_metrics, "slot", list(range(1, 5)), .06, .51),
            (spreads, cross_metrics, "pair", list(PAIRS), .624, .33)):
            current = metrics[metrics.root.eq(root)]
            card_width = (width-(len(ids)-1)*.008)/len(ids)
            for i, identity in enumerate(ids):
                rows = current[current[key].eq(identity)]
                r = rows.iloc[0] if len(rows) else None
                label = f"{root}{identity-1:02d}" if key == "slot" else f"{root} {identity}"
                if r is not None and key == "slot":
                    label += " · " + r.contract.replace(".CFE", "")
                color = COLORS[i] if key == "slot" else COLORS[i+1]
                value = number(r.basis_current, 1) + "点" if r is not None else "—"
                detail = "日变 " + number(r.basis_change_1d, 1, True) + "点" if r is not None else "日变 —"
                secondary = "5日 " + number(r.basis_change_5d, 1, True) + "点" if r is not None else "5日 —"
                if r is not None and r.roll_5d:
                    secondary += " · 换月"
                audit = price_audit_lines(r) if r is not None else ("指数 —", "期货 —", "分红 —")
                _card(fig, x+i*(card_width+.008), top-.088, card_width, .068, label, value, detail, secondary, color, audit)
            ax = fig.add_axes([x, top-.208, width, .112])
            _trend(ax, frame, root, key, ids, days, "basis_points")
    _save(fig, output)


def activity(panel, end, output, note, sessions=60, metrics=None):
    days = sorted(panel.loc[panel.trade_date.le(end), "trade_date"].unique())[-sessions:]
    metrics = total_metrics(panel, end) if metrics is None else metrics
    totals = activity_totals(panel)
    fig = plt.figure(figsize=(19, 17))
    _header(fig, "股指期货 / 四合约总量与变化",
            f"行情截至 {end:%Y-%m-%d} · 四合约累和 · 总成交柱形读左轴，总持仓曲线读右轴 · 最近5日着色", note)
    for i, root in enumerate(ORDER):
        x, top = (.06 if i % 2 == 0 else .56), .904-(i//2)*.411
        width = .384
        fig.text(x, top, f"{root}  {NAMES[root]}", fontsize=16, weight="bold", va="top")
        rows = metrics[metrics.root.eq(root)]
        r = rows.iloc[0] if len(rows) else None
        for col, prefix, title, color in ((0, "oi", "四合约总持仓", COLORS[0]), (1, "volume", "四合约总成交", "#248f82")):
            value = number(r[f"{prefix}_current"]/10000, 2) + "万手" if r is not None else "—"
            detail = (f"日变 {number(r[f'{prefix}_change_1d']/10000, 2, True)}万手 / {number(r[f'{prefix}_change_1d_pct'], 1, True)}%"
                      if r is not None else "日变 —")
            secondary = f"5日 {number(r[f'{prefix}_change_5d']/10000, 2, True)}万手" if r is not None else "5日 —"
            if r is not None:
                secondary += (f" · 20日中位数 {number(r.volume_multiple, 2)}倍" if prefix == "volume"
                              else f" / {number(r.oi_change_5d_pct, 1, True)}%")
            _card(fig, x+col*(width/2+.005), top-.104, width/2-.005, .080,
                  title, value, detail, secondary, color)
        ax = fig.add_axes([x, top-.350, width, .230])
        right = ax.twinx()
        g = totals[totals.root.eq(root)].set_index("trade_date").reindex(days)
        volume, oi = g.volume/10000, g.open_interest/10000
        colors = ["#b9ddd8"]*max(0, len(days)-5) + ["#389f91"]*min(5, len(days))
        ax.bar(range(len(days)), volume, width=.72, color=colors)
        ax.axvspan(max(-.5, len(days)-6), len(days)-1, color="#edf3f8", zorder=0)
        right.plot(range(len(days)), oi, color=COLORS[0], lw=2)
        right.plot(range(max(0, len(days)-6), len(days)), oi.iloc[-6:], color=COLORS[0], lw=3)
        if np.isfinite(oi.iloc[-1]):
            right.scatter([len(days)-1], [oi.iloc[-1]], color=COLORS[0], s=45, edgecolor="white", zorder=6)
        if r is not None and np.isfinite(r.volume_20d_median):
            ax.axhline(r.volume_20d_median/10000, color="#489e92", ls="--", lw=1.1)
        _date_axis(ax, days)
        ax.set_ylim(bottom=0)
        right.margins(y=.15)
        right.yaxis.set_major_locator(MaxNLocator(7))
        ax.set_ylabel("成交/万手", fontsize=10, color="#248f82")
        right.set_ylabel("持仓/万手", fontsize=10, color=COLORS[0])
        right.tick_params(axis="y", labelsize=10, colors=COLORS[0])
        right.spines["right"].set_visible(True)
        right.spines["right"].set_color("#dce3e9")
        if not volume.notna().any() or not oi.notna().any():
            ax.text(.5, .45, "部分字段缺失，总量留空", transform=ax.transAxes, ha="center", color=MUTED)
    _save(fig, output)
