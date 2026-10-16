"""Fixed-maturity and calendar-spread evidence from actual dividend-adjusted contracts."""
import numpy as np
import pandas as pd

from .analytics import fixed_tenor, unique
from .distributions import distribution_rows
from .windows import normalize_windows

PAIRS = {"02-00": (3, 1), "03-02": (4, 3)}


def annualized_calendar_spreads(panel):
    unique(panel, ["trade_date", "root", "slot"], "跨期合约")
    rows = []
    for (day, root), group in panel.groupby(["trade_date", "root"]):
        group = group.set_index("slot")
        for pair, (far_slot, near_slot) in PAIRS.items():
            if not {far_slot, near_slot}.issubset(group.index):
                raise ValueError(f"{day} {root} {pair}缺少同日配对合约")
            far, near = group.loc[far_slot], group.loc[near_slot]
            gap = (far.expiry_date - near.expiry_date).days
            if gap <= 0 or near.expiry_date < day:
                raise ValueError(f"{day} {root} {pair}实际到期日顺序无效")
            if not np.isfinite(near.spot_close) or near.spot_close <= 0 or not np.isclose(
                    near.spot_close, far.spot_close, rtol=0, atol=1e-8):
                raise ValueError(f"{day} {root} {pair}现货收盘值无效或不一致")
            points = far.adjusted_futures_close - near.adjusted_futures_close
            rows.append({"trade_date": day, "root": root, "pair": pair,
                "near_contract": near.instrument_id, "far_contract": far.instrument_id,
                "near_expiry": near.expiry_date, "far_expiry": far.expiry_date,
                "expiry_gap_days": gap, "spot_close": near.spot_close,
                "near_adjusted_close": near.adjusted_futures_close, "far_adjusted_close": far.adjusted_futures_close,
                "raw_spread_points": far.futures_close - near.futures_close,
                "dividend_difference": far.dividend_points - near.dividend_points,
                "spread_points": points, "annualized_basis_pct": points / near.spot_close * 36500 / gap,
                "roll_day": bool(far.roll_day or near.roll_day)})
    return pd.DataFrame(rows)


def term_distributions(series, end, keys, eligible=None, windows=(6, 12)):
    rows = []
    for key, group in series.groupby(keys, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        labels = dict(zip(keys, key))
        rows.extend({**labels, **row} for row in distribution_rows(
            group, end, "annualized_basis_pct", eligible, windows=windows))
    return pd.DataFrame(rows)


def term_analysis(panel, end, windows=None):
    windows = normalize_windows(windows)
    fixed90 = fixed_tenor(panel, 90)
    calendar = annualized_calendar_spreads(panel)
    return (fixed90, term_distributions(fixed90, end, ["root"], "interpolable",
                                      windows=windows["fixed_90_quantile_months"]), calendar,
            term_distributions(calendar, end, ["root", "pair"], windows=windows["calendar_quantile_months"]))


def term_chart_catalog(windows=None):
    windows = normalize_windows(windows)
    return ([f"{days}天固定期限_近{months}个月" for days in (60, 90) for months in windows[f"fixed_{days}_months"]]
            + [f"{days}天固定期限_分位蜡烛图" for days in (60, 90)]
            + [f"跨期{pair}_{kind}" for pair in PAIRS for kind in ("年化基差", "年化分位蜡烛图")])
