"""Public inputs and results for the independent big-table backtester."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd


SPOT_SYMBOLS = {
    "000300.SH": "IF_spot", "000016.SH": "IH_spot",
    "000905.SH": "IC_spot", "000852.SH": "IM_spot",
}
INDEX_SYMBOLS = {v: k for k, v in SPOT_SYMBOLS.items()}
DEFAULT_MULTIPLIERS = {"IF": 300.0, "IH": 300.0, "IC": 200.0, "IM": 200.0}


class BacktestError(ValueError):
    """Invalid instructions, parameters, or unavailable required market data."""


class BacktestCancelled(BacktestError):
    """A read/computation was cooperatively cancelled before publication."""


def check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise BacktestCancelled("Backtest cancelled")


def normalize_symbol(value: str) -> str:
    symbol = str(value).strip().upper()
    if symbol in SPOT_SYMBOLS:
        return SPOT_SYMBOLS[symbol]
    if re.fullmatch(r"(?:IF|IH|IC|IM)_SPOT", symbol):
        return symbol[:2] + "_spot"
    if re.fullmatch(r"(?:IF|IH|IC|IM)\d{4}\.CFE", symbol) and 1 <= int(symbol[4:6]) <= 12:
        return symbol
    raise BacktestError(f"Unsupported symbol {value!r}; use a concrete CFE contract or IF/IH/IC/IM_spot")


def timestamp(value, *, timezone="Asia/Shanghai", date_at="15:00", unit=None) -> pd.Timestamp:
    """Midnight/date labels denote that day's close; epoch units must be explicit."""
    if isinstance(value, (int, float, np.integer, np.floating)):
        if unit is None:
            raise BacktestError("Numeric timestamps require an explicit timestamp_unit (s/ms/us/ns)")
        stamp = pd.to_datetime(value, unit=unit, utc=True)
    else:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise BacktestError("Timestamp cannot be NaT")
        if stamp.tzinfo is None:
            if stamp == stamp.normalize() and date_at is not None:
                hours, minutes = map(int, date_at.split(":"))
                stamp += pd.Timedelta(hours=hours, minutes=minutes)
            stamp = stamp.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    if pd.isna(stamp):
        raise BacktestError("Timestamp cannot be NaT")
    return stamp.tz_convert(timezone)


def time_bound(value, *, end=False, timezone="Asia/Shanghai"):
    if value is None:
        return None
    stamp = timestamp(value, timezone=timezone, date_at=None)
    date_label = (isinstance(value, date) and not isinstance(value, datetime)) or (
        isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()))
    )
    if date_label and end:
        stamp = stamp.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return stamp


def normalize_frame(frame: pd.DataFrame, *, label="table", timezone="Asia/Shanghai",
                    date_at="15:00", unit=None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise BacktestError(f"{label} must be a non-empty DataFrame")
    result = frame.copy()
    result.columns = [normalize_symbol(c) for c in result.columns]
    if result.columns.duplicated().any():
        raise BacktestError(f"{label} has duplicate symbols after spot mapping")
    result.index = pd.DatetimeIndex([
        timestamp(t, timezone=timezone, date_at=date_at, unit=unit) for t in result.index
    ], name="timestamp")
    if result.index.duplicated().any():
        raise BacktestError(f"{label} has duplicate timestamps after normalization")
    try:
        result = result.apply(pd.to_numeric, errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise BacktestError(f"{label} contains non-numeric values: {exc}") from exc
    if np.isinf(result.to_numpy()).any():
        raise BacktestError(f"{label} contains infinite values")
    return result.sort_index()


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    max_capital_usage: float = 0.99
    minimum_margin_ratio: float = 0.0001
    margin_call_basis: str = "equity"
    mode: str = "portfolio"  # symbol / product / portfolio
    start: Any = None
    end: Any = None
    timezone: str = "Asia/Shanghai"
    date_at: str = "15:00"
    timestamp_unit: str | None = None
    nan_policy: str = "error"  # error / zero (explicit opt-in)
    liquidate_at_end: bool = False

    def __post_init__(self):
        for key in ("initial_capital", "commission_rate", "max_capital_usage", "minimum_margin_ratio"):
            value = getattr(self, key)
            if isinstance(value, bool) or not np.isfinite(value):
                raise BacktestError(f"{key} must be finite")
        if self.initial_capital <= 0 or not 0 < self.max_capital_usage <= 1:
            raise BacktestError("initial_capital must be positive; max_capital_usage must be in (0, 1]")
        if self.commission_rate < 0 or self.minimum_margin_ratio < 0:
            raise BacktestError("Commission and minimum margin ratios cannot be negative")
        if self.mode not in {"symbol", "product", "portfolio"}:
            raise BacktestError("mode must be symbol, product, or portfolio")
        if self.margin_call_basis not in {"available_equity", "equity"}:
            raise BacktestError("margin_call_basis must be available_equity or equity")
        if self.nan_policy not in {"error", "zero"}:
            raise BacktestError("nan_policy must be error or zero")
        time.fromisoformat(self.date_at)
        left = time_bound(self.start, timezone=self.timezone)
        right = time_bound(self.end, end=True, timezone=self.timezone)
        if left is not None and right is not None and left > right:
            raise BacktestError("start must not be after end")


@dataclass(frozen=True)
class DataConfig:
    """All paths are read-only inputs; no acquisition or VPN side effects."""
    data_root: str | Path | None = None
    dashboard_config_path: str | Path | None = None
    history_roots: tuple[str | Path, ...] = ()
    reference_path: str | Path | None = None
    frequency: str = "1d"
    close_path: str | Path | None = None
    multiplier_path: str | Path | None = None
    margin_rate_path: str | Path | None = None
    adjusted_close_path: str | Path | None = None
    dividend_points_path: str | Path | None = None
    dividend_root: str | Path | None = None
    dividend_policy: str = "none"  # none / asof_snapshot / fixed_scenario
    multipliers: Mapping[str, float] = field(default_factory=dict)
    margin_rates: Mapping[str, float] = field(default_factory=dict)
    allow_unverified_availability: bool = False
    trusted_pickle: bool = False

    def __post_init__(self):
        if self.frequency not in {"1d", "1m", "1s"}:
            raise BacktestError("frequency must be 1d, 1m, or 1s")
        if self.dividend_policy not in {"none", "asof_snapshot", "fixed_scenario"}:
            raise BacktestError("Unknown dividend_policy")
        if self.adjusted_close_path and self.dividend_points_path:
            raise BacktestError("Choose adjusted_close_path or dividend_points_path, not both")


@dataclass
class MarketData:
    close: pd.DataFrame
    multiplier: Mapping[str, float] | pd.DataFrame = field(default_factory=lambda: dict(DEFAULT_MULTIPLIERS))
    margin_rate: Mapping[str, float] | pd.DataFrame = field(default_factory=dict)
    adjusted_close: pd.DataFrame | None = None
    contracts: dict[str, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class AccountResult:
    equity: pd.DataFrame
    positions: pd.DataFrame
    actual_orders: pd.DataFrame
    target_weights: pd.DataFrame
    schedule: pd.DataFrame
    summary: dict


@dataclass
class BacktestResult:
    accounts: dict[str, AccountResult]
    metadata: dict
    output_paths: dict = field(default_factory=dict)
    input_instructions: pd.DataFrame | None = None

    @property
    def actual_orders(self) -> pd.DataFrame:
        return pd.concat([r.actual_orders.assign(account=name) for name, r in self.accounts.items()], ignore_index=True)

    @property
    def summary(self) -> pd.DataFrame:
        return pd.DataFrame({k: r.summary for k, r in self.accounts.items()}).T.rename_axis("account")

    def save(self, output_dir: str | Path) -> dict:
        from .io import save_result
        self.output_paths = save_result(self, output_dir)
        return self.output_paths
