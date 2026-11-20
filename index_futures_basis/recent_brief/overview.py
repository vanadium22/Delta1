"""Single-line current tables and per-product group means with historical ranks."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from ..analytics import NAMES
from .data import ORDER, PAIRS

ANNUAL_RANK_SESSIONS = 60


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


def annualized_current(panel, end, sessions=ANNUAL_RANK_SESSIONS):
    """Current equal-weight group means ranked against their own daily means."""
    end = pd.Timestamp(end)
    days = sorted(panel.loc[panel.trade_date.lt(end), 'trade_date'].unique())[-max(sessions,7):]
    calendar = pd.DatetimeIndex(days+[end])
    history_days = calendar[:-1][-sessions:]
    evidence, sentences, recent = [], [], []
    for root in ORDER:
        item = {'root':root}
        for key, label, slots in (('near','近月00/01',(1,2)), ('far','远月02/03',(3,4)), ('all','四档整体',(1,2,3,4))):
            part = panel[panel.root.eq(root) & panel.slot.isin(slots) & panel.trade_date.isin(calendar)]
            grouped = part.groupby('trade_date').agg(
                count=('slot','size'), unique=('slot','nunique'),
                known=('calendar_known',lambda v: v.eq(True).all()),
                days_count=('days_to_expiry',lambda v: np.isfinite(v).sum()),
                min_days=('days_to_expiry','min'),
                value_count=('annualized_basis_pct',lambda v: np.isfinite(v).sum()),
                mean=('annualized_basis_pct','mean'), roll=('roll_day','any')).reindex(calendar)
            present = grouped['count'].eq(len(slots)) & grouped.unique.eq(len(slots))
            known = present & grouped.known.eq(True) & grouped.days_count.eq(len(slots))
            expired = known & grouped.min_days.lt(1)
            valid = known & ~expired & grouped.value_count.eq(len(slots))
            values = grouped['mean'].where(valid)
            now = _number(values.loc[end])
            history = values.reindex(history_days)
            eligible = ~expired.reindex(history_days)
            sample = history[eligible].dropna()
            complete = bool(len(history_days) == sessions and len(sample) == int(eligible.sum()) and len(sample))
            rank = (float(100*((sample < now).sum()+.5*(sample == now).sum())/len(sample))
                    if complete and now is not None else None)
            last = values.tail(8)
            comparable = bool(len(last) == 8 and last.notna().all()
                              and not grouped.roll.tail(7).eq(True).any())
            change = float(last.iloc[-1]-last.iloc[0]) if comparable else None
            row = {'slots':[f'{s-1:02d}' for s in slots], 'mean_pct':now, 'percentile':rank,
                   'current_status':'expired' if bool(expired.loc[end]) else 'missing' if now is None else 'valid',
                   'window_sessions':sessions, 'complete':complete, 'n':len(sample),
                   'expiry_excluded_n':int((~eligible).sum()),
                   'window_start':_date(history_days.min()) if len(history_days) else None,
                   'window_end_exclusive':str(end.date()),
                   'history_mean_pct':float(sample.mean()) if complete else None,
                   'change_7d_pp':change}
            item[key] = row
            if change is not None:
                recent.append({'root':root,'group':key,'label':label,'change_pp':change,'current':now,
                               'noteworthy':abs(change)>=1.0})
        near, far = item['near'], item['far']
        near_text = '近月00/01均值—'
        if near['mean_pct'] is not None:
            near_text = f"近月00/01均值{near['mean_pct']:.2f}%"
        elif near['current_status'] == 'expired':
            legs = panel[panel.root.eq(root) & panel.trade_date.eq(end) & panel.slot.isin((1, 2))]
            front, next_month = legs[legs.slot.eq(1)], legs[legs.slot.eq(2)]
            if (len(front) == len(next_month) == 1 and front.iloc[0].days_to_expiry == 0
                    and next_month.iloc[0].days_to_expiry >= 1):
                value = _number(next_month.iloc[0].annualized_basis_pct)
                if value is not None:
                    near_text = f'当月到期，次月年化{value:.2f}%'
                    item['expiry_day_next_month_pct'] = value
            if 'expiry_day_next_month_pct' not in item:
                near_text += '（含到期合约）'
        far_text = '远月02/03均值—'
        if far['mean_pct'] is not None:
            rank = far['percentile']
            rank_text = f'{sessions}日P{rank:.1f}%' if rank is not None else f'{sessions}日分位待补'
            far_text = f"远月02/03均值{far['mean_pct']:.2f}%（{rank_text}）"
        item['text'] = f'{root} {near_text}，{far_text}。'
        evidence.append(item); sentences.append(item['text'])
    material = sorted((r for r in recent if r['noteworthy']), key=lambda r:-abs(r['change_pp']))
    selected, used = [], set()
    for row in material:
        if row['root'] not in used:
            selected.append(row); used.add(row['root'])
        if len(selected) == 2:
            break
    current = panel[panel.trade_date.eq(end) & panel.slot.eq(1)]
    if current.days_to_expiry.between(1,3).any():
        sentences.append('00临近到期，短期限会放大近月年化。')
    return '\n'.join(sentences), {'products':evidence, 'recent_changes':recent,'selected_changes':selected,
        'rank_sessions':sessions, 'change_threshold_pp':1.0,
        'policy':'current same-product equal-weight means; ranks of historical daily group means, not averages of leg ranks; exclude current; known expired groups excluded, missing inputs invalidate window'}


TABLE_HEADERS = ("连续档位", "实际合约", "期货价 /\n原始价差", "分红G /\n分红差", "去分红基差 /\n调整后价差", "年化基差", "到期日", "剩余 /\n间隔天数")
TABLE_WIDTHS = (1.35, 2.1, 2.25, 2.0, 2.3, 1.7, 2.1, 1.74)


def table_cells(row):
    def fmt(value, digits):
        return f"{value:,.{digits}f}" if value is not None else "—"
    calendar = row['kind'] == 'calendar'
    return [row["label"], '' if calendar else str(row['contracts'][0] or '—'),
            fmt(row["raw_price"], 2), fmt(row["dividend"], 2), fmt(row["basis_points"], 2),
            fmt(row["annualized_basis_pct"], 2)+("%" if row["annualized_basis_pct"] is not None else ""),
            '' if calendar else row['expiries'][0] or '—',
            fmt(row["days"], 0)]
