"""Current product tables and conditional within-product annualized summaries."""
from __future__ import annotations

import math
import pandas as pd

from ..analytics import NAMES
from .data import ORDER, PAIRS

ANNUAL_CLOSE_PP = 1.0


def _number(value):
    try:
        return float(value) if math.isfinite(float(value)) else None
    except (ValueError, TypeError):
        return None


def _date(value):
    return str(pd.Timestamp(value).date()) if pd.notna(value) else None


def _contract(value):
    return str(value) if pd.notna(value) and str(value).strip() else None


def current_tables(panel, spreads, end):
    """Keep full precision and actual identities; format only when rendering."""
    tables = []
    now = panel[panel.trade_date.eq(pd.Timestamp(end))]
    cross = spreads[spreads.trade_date.eq(pd.Timestamp(end))]
    for root in ORDER:
        contracts, calendar = now[now.root.eq(root)], cross[cross.root.eq(root)]
        spots = contracts.spot_close.dropna().unique()
        table = {"root": root, "name": NAMES[root],
                 "spot_close": _number(spots[0]) if len(spots) == 1 else None, "rows": []}
        for slot in range(1, 5):
            matches = contracts[contracts.slot.eq(slot)]
            row = matches.iloc[0] if len(matches) == 1 else pd.Series(dtype=object)
            table["rows"].append({"kind": "single", "label": f"{root}{slot-1:02d}",
                "contracts": [_contract(row.get("instrument_id"))],
                "raw_price": _number(row.get("futures_close")),
                "dividend": _number(row.get("dividend_points")),
                "basis_points": _number(row.get("basis_points")),
                "annualized_basis_pct": _number(row.get("annualized_basis_pct")),
                "expiries": [_date(row.get("expiry_date"))],
                "days": _number(row.get("days_to_expiry"))})
        for pair in PAIRS:
            matches = calendar[calendar.pair.eq(pair)]
            row = matches.iloc[0] if len(matches) == 1 else pd.Series(dtype=object)
            raw = [_number(row.get(f"{side}_futures_close")) for side in ("left", "right")]
            dividends = [_number(row.get(f"{side}_dividend_points")) for side in ("left", "right")]
            table["rows"].append({"kind": "calendar", "label": pair,
                "contracts": [_contract(row.get(f"{side}_contract")) for side in ("left", "right")],
                "raw_price": raw[0]-raw[1] if all(v is not None for v in raw) else None,
                "dividend": dividends[0]-dividends[1] if all(v is not None for v in dividends) else None,
                "basis_points": _number(row.get("basis_points")),
                "annualized_basis_pct": _number(row.get("annualized_basis_pct")),
                "expiries": [_date(row.get(f"{side}_expiry")) for side in ("left", "right")],
                "days": _number(row.get("expiry_gap_days"))})
        tables.append(table)
    return tables


def annualized_current(panel, end, tolerance_pp=ANNUAL_CLOSE_PP):
    """One product at a time; average complete, close, same-sign groups only."""
    if not math.isfinite(tolerance_pp) or tolerance_pp < 0:
        raise ValueError("年化接近阈值须为非负有限百分点")
    current, evidence, sentences = panel[panel.trade_date.eq(pd.Timestamp(end))], [], []

    def group(rows, slots):
        values = [rows.get(slot) for slot in slots]
        complete = all(v is not None for v in values)
        spread = max(values)-min(values) if complete else None
        close = complete and spread <= tolerance_pp and (min(values) >= 0 or max(values) <= 0)
        return {"slots": [f"{i-1:02d}" for i in slots], "values_pct": values,
                "complete": complete, "range_pp": spread, "close": close,
                "mean_pct": sum(values)/len(values) if close else None}

    for root in ORDER:
        rows, near_days = {}, None
        for slot in range(1, 5):
            matches = current[current.root.eq(root) & current.slot.eq(slot)]
            if len(matches) == 1:
                r = matches.iloc[0]
                days = _number(r.get("days_to_expiry"))
                rows[slot] = (_number(r.annualized_basis_pct)
                              if r.get("calendar_known", False) == True and days is not None and days >= 1 else None)
                if slot == 1:
                    near_days = days
        all_four, near, far = group(rows, (1,2,3,4)), group(rows, (1,2)), group(rows, (3,4))
        item = {"root": root, "all": all_four, "near": near, "far": far}
        if all_four["close"]:
            text = f"{root}四档年化接近，00—03简单平均{all_four['mean_pct']:.2f}%"
        else:
            parts = []
            for name, data, slots in (("近月00/01", near, (1,2)), ("远月02/03", far, (3,4))):
                if data["close"]:
                    parts.append(f"{name}年化接近，简单平均{data['mean_pct']:.2f}%")
                else:
                    parts.append("、".join(f"{slot-1:02d}为{rows[slot]:.2f}%" if rows.get(slot) is not None
                                          else f"{slot-1:02d}缺失" for slot in slots))
            text = root+"年化分档看："+"；".join(parts)
        if near_days is not None and 1 <= near_days <= 3:
            text += f"（00距到期{near_days:.0f}天，年化受短期限放大）"
        item["text"] = text+"。"
        evidence.append(item)
        sentences.append(item["text"])
    return "\n".join(sentences), {"tolerance_pp": tolerance_pp, "products": evidence,
        "policy": "same product only; all four first, otherwise 00/01 and 02/03; complete same-sign groups; max-min <= tolerance; simple mean"}


TABLE_HEADERS = ("连续档位", "实际合约", "期货价 /\n原始价差", "分红G /\n分红差", "去分红基差 /\n调整后价差", "年化基差", "到期日\n远腿 / 近腿", "剩余 /\n间隔天数")
TABLE_WIDTHS = (1.2, 3.0, 2.0, 1.8, 2.0, 1.6, 2.4, 1.54)


def table_cells(row):
    def fmt(value, digits):
        return f"{value:,.{digits}f}" if value is not None else "—"
    return [row["label"], "\n− ".join(str(v) if v else "—" for v in row["contracts"]),
            fmt(row["raw_price"], 4), fmt(row["dividend"], 4), fmt(row["basis_points"], 2),
            fmt(row["annualized_basis_pct"], 2)+("%" if row["annualized_basis_pct"] is not None else ""),
            "\n".join(v or "—" for v in row["expiries"]),
            fmt(row["days"], 0)]
