"""Symmetric hysteresis, using fixed values or previous-day rolling Z scores."""
import numpy as np
import pandas as pd

from ..models import BacktestError, check_cancelled
from .factors import previous_windows
from .models import CTAConfig


def cta_targets(factor, config=None, *, cancel_event=None):
    config = config or CTAConfig()
    values = factor.astype(float)
    if config.transform == "center_percentile":
        if ((values < 0) | (values > 1)).any().any():
            raise BacktestError("center_percentile expects factor values in [0, 1]")
        values = 2 * values - 1
    if config.mode == "zscore":
        windows, locations, warm = previous_windows(values, config.lookback_window)
        complete = np.isfinite(windows).all(axis=2) & warm[:, None]
        # Missing/constant history remains unavailable, never infinite or zero-filled.
        means = np.where(complete, np.where(np.isfinite(windows), windows, 0).mean(axis=2), np.nan)
        centered = np.where(np.isfinite(windows), windows, 0) - means[:, :, None]
        std = np.sqrt(np.mean(centered * centered, axis=2))
        std[std <= 1e-12] = np.nan
        scores = (values.to_numpy() - means[locations]) / std[locations]
        high, low = config.z_open, config.z_close
    else:
        scores = values.to_numpy(copy=True)
        high, low = config.open_threshold, config.close_threshold
    scores *= config.direction
    state = np.zeros(len(values.columns), dtype=np.int8)
    targets = np.zeros(values.shape)
    for i, row in enumerate(scores):
        if i % 1024 == 0:
            check_cancelled(cancel_event)
        missing = ~np.isfinite(row)
        if missing.any() and config.missing == "error":
            raise BacktestError(f"Missing CTA factor/history at {values.index[i]}")
        if config.missing == "flat":
            state[missing] = 0
        state[np.abs(row) < low] = 0
        state[row > high] = 1
        state[row < -high] = -1
        targets[i] = state * config.position_weight
    return (pd.DataFrame(targets, index=values.index, columns=values.columns),
            pd.DataFrame(scores, index=values.index, columns=values.columns))
