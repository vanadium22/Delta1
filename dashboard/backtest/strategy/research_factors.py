"""Simple price-basis and 01-minus-03 percentile examples; no position rules."""
import numpy as np
import pandas as pd

from ..models import BacktestError
from .factors import basis_percentile


def research_factor(name, panel, config, *, cancel_event=None):
    if name == "close_percentile":
        values = panel.close.where(panel.close.gt(0))
    elif name == "price_basis_percentile":
        values = (panel.close - panel.spot).where(panel.close.gt(0) & panel.spot.gt(0))
    elif name == "calendar_spread_percentile":
        values = pd.DataFrame(np.nan, index=panel.close.index, columns=panel.close.columns)
        for root in config.roots:
            near, far = root + "01.CFE", root + "03.CFE"
            if near not in panel.close or far not in panel.close:
                raise BacktestError("calendar_spread_percentile requires calculation slots 01 and 03")
            values[near] = (panel.close[near] - panel.close[far]).where(panel.close[near].gt(0) & panel.close[far].gt(0))
    else:
        raise BacktestError(f"Unknown factor {name!r}")
    # For these non-annual factors no near-expiry values are excluded from history.
    from dataclasses import replace
    numerical_panel = replace(panel, days_to_expiry=panel.days_to_expiry * np.nan)
    return basis_percentile(numerical_panel, values, config, cancel_event=cancel_event)
