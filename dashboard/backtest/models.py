"""Public inputs and results for the independent big-table backtester."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
import re
import warnings
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


def check_source_paths(value):
    """The user excludes Z-drive dependencies from this project."""
    if isinstance(value, Mapping):
        for item in value.values():
            check_source_paths(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            check_source_paths(item)
    elif isinstance(value, (str, Path)):
        path = str(value).strip().replace("\\", "/")
        if re.match(r"(?i)^(?://[?.]/)?z:", path):
            raise BacktestError("Z-drive sources are excluded; use an explicit Delta1/data source or a future DDB provider")
        if any(part.lower() in {"backfilled_cn_index", "backfilled_cn_index_future", "excluded_mixed_source_run"} for part in path.split("/")):
            raise BacktestError("Known Z-derived/mixed cache path is excluded; choose a traceable pure dataset")


def check_market_source(value):
    check_source_paths(value)
    if isinstance(value, Mapping):
        for item in value.values():
            check_market_source(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            check_market_source(item)
    elif isinstance(value, str) and any(token in value.lower() for token in ("readonly_z", "z_derived", "z-derived", "z_drive_source")):
        raise BacktestError("Z-derived/mixed market sources are excluded even when cached on another drive; select a pure DDB dataset")


def normalize_symbol(value: str, *, allow_continuous=False) -> str:
    symbol = str(value).strip().upper()
    if symbol in SPOT_SYMBOLS:
        return SPOT_SYMBOLS[symbol]
    if re.fullmatch(r"(?:IF|IH|IC|IM)_SPOT", symbol):
        return symbol[:2] + "_spot"
    if allow_continuous and re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE", symbol):
        return symbol
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
                clock = time.fromisoformat(date_at)
                stamp += pd.Timedelta(hours=clock.hour, minutes=clock.minute, seconds=clock.second, microseconds=clock.microsecond)
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
                    date_at="15:00", unit=None, allow_continuous=False) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise BacktestError(f"{label} must be a non-empty DataFrame")
    result = frame.copy(deep=False)
    result.columns = [normalize_symbol(c, allow_continuous=allow_continuous) for c in result.columns]
    if result.columns.duplicated().any():
        raise BacktestError(f"{label} has duplicate symbols after spot mapping")
    index = result.index
    if pd.api.types.is_numeric_dtype(index.dtype):
        if unit is None:
            raise BacktestError("Numeric timestamps require an explicit timestamp_unit (s/ms/us/ns)")
        index = pd.to_datetime(index, unit=unit, utc=True)
    elif not isinstance(index, pd.DatetimeIndex):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", FutureWarning)
                index = pd.DatetimeIndex(pd.to_datetime(index, format="mixed"))
        except (ValueError, TypeError, FutureWarning):
            index = pd.DatetimeIndex([timestamp(t, timezone=timezone, date_at=date_at, unit=unit) for t in index])
    if index.hasnans:
        raise BacktestError(f"{label} timestamp cannot be NaT")
    if index.tz is None:
        if date_at is not None:
            clock = time.fromisoformat(date_at)
            offset = pd.Timedelta(hours=clock.hour, minutes=clock.minute, seconds=clock.second, microseconds=clock.microsecond)
            index = index.where(index != index.normalize(), index + offset)
        index = index.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    result.index = index.tz_convert(timezone).rename("timestamp")
    if result.index.duplicated().any():
        raise BacktestError(f"{label} has duplicate timestamps after normalization")
    try:
        if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in result.dtypes):
            result = result.apply(pd.to_numeric, errors="raise")
        result = result.astype(float, copy=False)
    except (TypeError, ValueError) as exc:
        raise BacktestError(f"{label} contains non-numeric values: {exc}") from exc
    if np.isinf(result.to_numpy()).any():
        raise BacktestError(f"{label} contains infinite values")
    return result.sort_index()


@dataclass(frozen=True)
class HedgeRule:
    primary: str
    hedge: str
    quantity_ratio: int

    def __post_init__(self):
        object.__setattr__(self, "primary", normalize_symbol(self.primary))
        object.__setattr__(self, "hedge", normalize_symbol(self.hedge))
        if not self.primary.endswith(".CFE") or self.hedge != self.primary[:2] + "_spot":
            raise BacktestError("An index hedge must pair a concrete future with its own product_spot")
        if isinstance(self.quantity_ratio, bool) or not isinstance(self.quantity_ratio, (int, np.integer)) or self.quantity_ratio >= 0:
            raise BacktestError("quantity_ratio must be a negative integer number of index units per futures lot")


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    max_capital_usage: float = 0.99
    minimum_margin_ratio: float = 0.0001
    margin_call_basis: str = "equity"
    mode: str = "portfolio"  # symbol / product / portfolio
    precision: str = "1d"  # 1d: day-end signals/risk; auto: input precision and quote-by-quote risk
    workers: int = 0  # 0: bounded automatic process count; 1: serial
    d0: int | None = 0  # calendar days; None explicitly disables maturity liquidation
    hedges: tuple[HedgeRule, ...] = ()
    rebalance_on_change_only: bool = False
    preserve_pair_lots: bool = False  # unchanged primary targets keep their executed lots
    weight_mode: str = "capital"  # capital / neutral_units (equal contract-equivalent weights)
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
        if self.mode not in {"symbol", "product", "portfolio", "contract_pair"}:
            raise BacktestError("mode must be symbol, product, portfolio, or contract_pair")
        rules = tuple(HedgeRule(**r) if isinstance(r, Mapping) else r for r in self.hedges)
        if any(not isinstance(r, HedgeRule) for r in rules) or len({r.primary for r in rules}) != len(rules):
            raise BacktestError("hedges must contain unique HedgeRule primary symbols")
        if rules and self.mode == "symbol":
            raise BacktestError("Use contract_pair for independent hedged contracts; symbol mode splits the hedge")
        if self.mode == "contract_pair" and not rules and self.weight_mode != "neutral_units":
            raise BacktestError("contract_pair mode requires explicit hedge rules")
        object.__setattr__(self, "hedges", rules)
        if self.weight_mode not in {"capital", "neutral_units"}:
            raise BacktestError("weight_mode must be capital or neutral_units")
        if self.weight_mode == "neutral_units" and self.mode == "symbol":
            raise BacktestError("neutral_units requires paired/product/portfolio accounts")
        if {r.primary for r in rules} & {r.hedge for r in rules}:
            raise BacktestError("Hedge chains/cycles are not supported; use independent pairs")
        if not isinstance(self.rebalance_on_change_only, bool):
            raise BacktestError("rebalance_on_change_only must be boolean")
        if not isinstance(self.preserve_pair_lots, bool) or (self.preserve_pair_lots and self.weight_mode != "neutral_units"):
            raise BacktestError("preserve_pair_lots requires boolean and neutral_units weights")
        if self.precision not in {"1d", "auto"}:
            raise BacktestError("precision must be 1d or auto")
        if isinstance(self.workers, bool) or not isinstance(self.workers, (int, np.integer)) or self.workers < 0:
            raise BacktestError("workers must be a non-negative integer; 0 selects a bounded automatic count")
        if self.d0 is not None and (isinstance(self.d0, bool) or not isinstance(self.d0, (int, np.integer)) or self.d0 < 0):
            raise BacktestError("d0 must be a non-negative integer or None")
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
    minute_close_path: str | Path | None = None
    daily_close_path: str | Path | None = None
    days_to_expiry_path: str | Path | None = None
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
    dataset_id: str = "unversioned_local"
    data_version: str = "unversioned"
    source_id: str = "explicit_local"
    history_versions: Mapping[str, str] = field(default_factory=dict)
    daily_label_time: str = "15:00"
    dividend_mode: str = "required"  # factor research: required / ignore (explicit D=0 assumption)
    dividend_records_path: str | Path | None = None
    dividend_store_root: str | Path | None = None
    calendar_path: str | Path | None = None

    def __post_init__(self):
        check_market_source(vars(self))
        base = Path(self.data_root).expanduser().resolve() if self.data_root else Path.cwd()
        if self.data_root:
            object.__setattr__(self, "data_root", str(base))
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value and (name.endswith("_path") or name in {"dividend_root", "dividend_store_root"}):
                object.__setattr__(self, name, str((base / Path(value).expanduser()).resolve()))
        roots = tuple(str((base / Path(p).expanduser()).resolve()) for p in self.history_roots)
        object.__setattr__(self, "history_roots", roots)
        if not isinstance(self.history_versions, Mapping):
            raise BacktestError("history_versions must be a directory-to-version object")
        versions = {str((base / Path(p).expanduser()).resolve()): v for p, v in self.history_versions.items()}
        object.__setattr__(self, "history_versions", versions)
        if any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{32}", v) for v in versions.values()):
            raise BacktestError("history_versions must contain exact 32-character registered version IDs")
        if set(versions) - set(roots):
            raise BacktestError("history_versions keys must name configured history_roots")
        if self.dividend_mode not in {"required", "ignore"}:
            raise BacktestError("dividend_mode must be required or explicitly ignore")
        if any(not isinstance(getattr(self, k), str) or not getattr(self, k).strip() for k in ("dataset_id", "data_version", "source_id")):
            raise BacktestError("dataset_id, data_version and source_id must be nonempty strings")
        for name, values in (("margin_rates", self.margin_rates), ("multipliers", self.multipliers)):
            for symbol, value in values.items():
                if symbol not in DEFAULT_MULTIPLIERS:
                    normalize_symbol(symbol)
                if isinstance(value, bool) or not np.isfinite(value) or value <= 0 or (name == "margin_rates" and value > 1):
                    raise BacktestError(f"Invalid fixed {name} for {symbol}")
        time.fromisoformat(self.daily_label_time)
        if self.close_path and (self.minute_close_path or self.daily_close_path):
            raise BacktestError("Ambiguous price paths: use close_path OR daily_close_path/minute_close_path")
        if roots and (self.close_path or self.minute_close_path or self.daily_close_path):
            raise BacktestError("Conflicting price sources: choose history_roots OR wide price files")
        if self.minute_close_path and self.daily_close_path and Path(self.minute_close_path) == Path(self.daily_close_path):
            raise BacktestError("Daily and minute close must use distinct paths")
        if self.dashboard_config_path and (roots or self.close_path or self.minute_close_path or self.daily_close_path):
            raise BacktestError("dashboard_config_path is an explicit legacy adapter; do not mix it with other price sources")
        if self.margin_rate_path and self.margin_rates:
            raise BacktestError("Choose historical margin_rate_path OR explicit fixed margin_rates")
        if self.multiplier_path and self.multipliers:
            raise BacktestError("Choose multiplier_path OR fixed multiplier overrides")
        if self.dividend_mode == "ignore" and (self.dividend_points_path or self.adjusted_close_path or self.dividend_records_path or self.dividend_store_root or self.dividend_policy != "none"):
            raise BacktestError("dividend_mode=ignore conflicts with configured dividend inputs")
        if self.frequency not in {"1d", "1m", "1s"}:
            raise BacktestError("frequency must be 1d, 1m, or 1s")
        if self.dividend_policy not in {"none", "asof_snapshot", "fixed_scenario"}:
            raise BacktestError("Unknown dividend_policy")
        if self.adjusted_close_path and self.dividend_points_path:
            raise BacktestError("Choose adjusted_close_path or dividend_points_path, not both")
        if (self.adjusted_close_path or self.dividend_points_path) and (self.dividend_records_path or self.dividend_store_root):
            raise BacktestError("Choose dividend wide tables OR the dated dividend book, not both")
        check_market_source(vars(self))


@dataclass
class MarketData:
    close: pd.DataFrame
    multiplier: Mapping[str, float] | pd.DataFrame = field(default_factory=lambda: dict(DEFAULT_MULTIPLIERS))
    margin_rate: Mapping[str, float] | pd.DataFrame = field(default_factory=dict)
    adjusted_close: pd.DataFrame | None = None
    contracts: dict[str, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    daily_close: pd.DataFrame | None = None
    daily_fallback: pd.DataFrame | None = None
    days_to_expiry: pd.DataFrame | None = None


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
    days_to_expiry: pd.DataFrame | None = None
    execution_instructions: pd.DataFrame | None = None

    @property
    def actual_orders(self) -> pd.DataFrame:
        frames = [r.actual_orders.assign(account=name) for name, r in self.accounts.items() if len(r.actual_orders)]
        if frames:
            return pd.concat(frames, ignore_index=True)
        if self.accounts:
            return next(iter(self.accounts.values())).actual_orders.iloc[:0].assign(account=pd.Series(dtype=object))
        return pd.DataFrame()

    @property
    def summary(self) -> pd.DataFrame:
        return pd.DataFrame({k: r.summary for k, r in self.accounts.items()}).T.rename_axis("account")

    def save(self, output_dir: str | Path) -> dict:
        from .io import save_result
        self.output_paths = save_result(self, output_dir)
        return self.output_paths
