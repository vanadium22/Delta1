"""Annualized 01-minus-03 carry using the difference of true expiry dates."""
from dataclasses import replace

import numpy as np
import pandas as pd

from ..models import BacktestError
from .factors import basis_percentile


def annual_calendar_spread(panel, *, min_gap_days=1, price_base="near"):
    if type(min_gap_days) is not int or min_gap_days < 1 or price_base not in {"near", "spot"}:
        raise BacktestError("Invalid annual calendar min_gap_days/price_base")
    values = pd.DataFrame(np.nan, index=panel.close.index, columns=panel.close.columns)
    gaps = values.copy()
    for root in sorted({s[:2] for s in panel.close}):
        near, far = root + "01.CFE", root + "03.CFE"
        if near not in panel.close or far not in panel.close:
            raise BacktestError("Annual calendar spread requires slots 01 and 03")
        gap = panel.days_to_expiry[far] - panel.days_to_expiry[near]
        if (gap.notna() & gap.le(0)).any():
            raise BacktestError("Annual calendar spread requires a positive far-minus-near expiry difference")
        denominator = panel.close[near] if price_base == "near" else panel.spot[near]
        numerator = panel.close[near] - panel.close[far] + panel.dividend_points[near] - panel.dividend_points[far]
        valid = (panel.close[near].gt(0) & panel.close[far].gt(0) & denominator.gt(0)
                 & panel.dividend_points[near].ge(0) & panel.dividend_points[far].ge(0)
                 & panel.days_to_expiry[near].ge(0) & gap.ge(min_gap_days))
        values[near] = (36500 * numerator / denominator / gap.where(gap.gt(0))).where(valid)
        gaps[near] = gap
    return values, gaps


def annual_calendar_percentile(panel, config, parameters, *, cancel_event=None):
    values, gaps = annual_calendar_spread(panel, **{k: parameters[k] for k in ("min_gap_days", "price_base")})
    numerical = replace(panel, days_to_expiry=gaps)
    runtime = replace(config, min_annual_days=parameters["min_gap_days"])
    return values, basis_percentile(numerical, values, runtime, cancel_event=cancel_event)
