"""Local-only price/volume plots, rendered without changing the report backend."""
from io import BytesIO
from pathlib import Path

import numpy as np

from .security_model import AMOUNT_UNITS, VOLUME_UNITS, field_label


def plot_result(result):
    if result.query.frequency == "snapshot":
        return b""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = FontProperties(fname=str(font_path)) if font_path.exists() else FontProperties()
    query, frame = result.query, result.frame
    price_fields = [f for f in query.fields if f not in {"volume", "amt"}]
    if query.twap and "close" not in price_fields:
        price_fields.append("close")
    groups = ([price_fields] if price_fields else []) + [[f] for f in query.fields if f in {"volume", "amt"}]
    if query.vwap and not price_fields:
        groups.insert(0, [])
    figure = Figure(figsize=(11, max(3.5, len(groups) * 2.5)), dpi=130, layout="constrained", facecolor="white")
    FigureCanvasAgg(figure)
    axes = figure.subplots(len(groups), 1, sharex=True, squeeze=False).ravel()
    x = np.arange(len(frame))
    for axis, fields in zip(axes, groups):
        for field in fields:
            label = field_label(field, query.frequency)
            if field in {"volume", "amt"}:
                axis.bar(x, frame[field], color="#70A6BB", width=.85, label=label)
                unit = VOLUME_UNITS[query.volume_unit][0] if field == "volume" else AMOUNT_UNITS[query.amount_unit][0]
                axis.set_ylabel(label + "（" + ("Wind原始单位" if unit == "未确认" else unit) + "）", fontproperties=font)
            else:
                axis.plot(x, frame[field], linewidth=1.4, label=label)
                axis.set_ylabel("不复权价格", fontproperties=font)
        if not fields or all(f not in {"volume", "amt"} for f in fields):
            for metric, value in result.summary["metrics"].items():
                axis.axhline(value, linestyle="--", linewidth=1.2,
                             color="#C57D36" if metric == "twap" else "#29927F", label=f"{metric.upper()} {value:.4f}")
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, prop=font, loc="best", frameon=False)
        axis.grid(axis="y", alpha=.2)
        axis.spines[["top", "right"]].set_visible(False)
    ticks = np.unique(np.linspace(0, max(0, len(frame) - 1), min(6, len(frame))).astype(int))
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels([str(frame.time.iloc[i])[:16].replace("T", "\n") for i in ticks], fontsize=9)
    axes[-1].set_xlabel("交易周期顺序（午休及非交易时段不占横轴）", fontproperties=font)
    cutoff = f" · 实际截至 {result.metadata['grid_end'][11:16]}" if result.metadata.get("pending_rows") else ""
    figure.suptitle(f"{query.code} · {result.metadata['name']} · {query.frequency}\n"
                   f"{query.start[:16]} — {query.end[:16]}{cutoff} · {result.metadata['source']}", fontproperties=font, fontsize=13)
    note = "；".join(result.summary["notes"])
    if result.metadata.get("missing_cells"):
        note = "存在缺失值，缺口不填充；" + note
    if note:
        # Keep chart annotations short; the full explanation accompanies the exported manifest.
        figure.text(.01, .002, note[:90], fontproperties=font, fontsize=8, color="#9B503B")
    stream = BytesIO()
    figure.savefig(stream, format="png", dpi=150)
    figure.clear()
    return stream.getvalue()
