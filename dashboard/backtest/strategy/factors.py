"""Dividend-adjusted annual basis and prior-window continuous-slot percentile."""
import numpy as np
import pandas as pd

from .models import FactorConfig


def annual_basis(panel, config=None):
    config = config or FactorConfig()
    valid = (panel.close.gt(0) & panel.spot.gt(0) & panel.dividend_points.ge(0)
             & panel.days_to_expiry.ge(config.min_annual_days))
    # Same percentage-point convention as the existing Excel/Overview formulas.
    return ((panel.close - panel.spot + panel.dividend_points) / panel.spot
            * 36500 / panel.days_to_expiry.where(panel.days_to_expiry.gt(0))).where(valid)


def previous_windows(frame, window):
    """Last actual daily observations; each current date uses previous dates only."""
    daily = frame.groupby(frame.index.normalize(), sort=True).tail(1).copy()
    daily.index = daily.index.normalize()
    padded = np.vstack([np.full((window, len(frame.columns)), np.nan), daily.to_numpy()])
    windows = np.lib.stride_tricks.sliding_window_view(padded, window, axis=0)[:len(daily)]
    locations = daily.index.get_indexer(frame.index.normalize())
    return windows, locations, np.arange(len(daily)) >= window


def basis_percentile(panel, annual, config=None, *, cancel_event=None):
    from ..models import check_cancelled
    config = config or FactorConfig()
    history, locations, warmed = previous_windows(annual, config.window_days)
    excluded_frame = panel.days_to_expiry.lt(config.min_annual_days) & panel.days_to_expiry.notna()
    excluded, _, _ = previous_windows(excluded_frame.astype(float), config.window_days)
    output = np.full(annual.shape, np.nan)
    for left in range(0, len(annual), 1024):
        check_cancelled(cancel_event)
        right = min(left + 1024, len(annual))
        old = history[locations[left:right]]
        skip = excluded[locations[left:right]] == 1
        valid = np.isfinite(old)
        counts = valid.sum(axis=2)
        current = annual.iloc[left:right].to_numpy()[:, :, None]
        complete = (valid | skip).all(axis=2) & warmed[locations[left:right], None] & (counts >= config.min_samples)
        rank = ((old < current).sum(axis=2) + .5 * (old == current).sum(axis=2)) / np.maximum(counts, 1)
        output[left:right] = np.where(complete & np.isfinite(current[:, :, 0]), rank, np.nan)
    return pd.DataFrame(output, index=annual.index, columns=annual.columns)
