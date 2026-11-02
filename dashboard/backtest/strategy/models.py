"""Small, explicit data and parameter interfaces for factor-to-position research."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

import pandas as pd

from ..models import BacktestError, MarketData


@dataclass(frozen=True)
class FactorConfig:
    roots: tuple[str, ...] = ("IC",)
    slots: tuple[int, ...] = (0, 1, 2, 3)
    window_days: int = 20
    min_annual_days: int = 5
    min_samples: int = 2
    precision: str = "1d"
    workers: int = 0

    def __post_init__(self):
        if not self.roots or len(set(self.roots)) != len(self.roots) or not set(self.roots) <= {"IF", "IH", "IC", "IM"}:
            raise BacktestError("roots must contain unique IF/IH/IC/IM products")
        if not self.slots or len(set(self.slots)) != len(self.slots) or not set(self.slots) <= {0, 1, 2, 3}:
            raise BacktestError("slots must contain unique 0/1/2/3 values")
        for key in ("window_days", "min_annual_days", "min_samples"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise BacktestError(f"{key} must be a positive integer")
        if self.min_samples > self.window_days:
            raise BacktestError("min_samples cannot exceed window_days")
        if self.precision not in {"1d", "auto"}:
            raise BacktestError("Factor precision must be 1d or auto")
        if isinstance(self.workers, bool) or not isinstance(self.workers, int) or self.workers < 0:
            raise BacktestError("Factor workers must be a non-negative integer")


@dataclass(frozen=True)
class CTAConfig:
    mode: str = "fixed"  # fixed / zscore
    open_threshold: float = 0.7
    close_threshold: float = 0.2
    lookback_window: int = 20
    z_open: float = 2.0
    z_close: float = 0.4
    position_weight: float = 0.2
    direction: int = 1
    transform: str = "identity"  # identity / center_percentile
    missing: str = "flat"  # flat / hold / error

    def __post_init__(self):
        import math
        for high, low in ((self.open_threshold, self.close_threshold), (self.z_open, self.z_close)):
            if not math.isfinite(high) or not math.isfinite(low) or not 0 <= low < high:
                raise BacktestError("CTA thresholds must satisfy 0 <= close < open")
        if not math.isfinite(self.position_weight) or not 0 < self.position_weight <= 1:
            raise BacktestError("position_weight must be in (0, 1]")
        if isinstance(self.lookback_window, bool) or not isinstance(self.lookback_window, int) or self.lookback_window < 2:
            raise BacktestError("lookback_window must be an integer >= 2")
        if self.direction not in (-1, 1) or self.mode not in {"fixed", "zscore"}:
            raise BacktestError("direction must be -1/1; mode must be fixed/zscore")
        if self.transform not in {"identity", "center_percentile"} or self.missing not in {"flat", "hold", "error"}:
            raise BacktestError("Invalid CTA transform or missing policy")


@dataclass(frozen=True)
class StrategyDataConfig:
    dividend_store_root: str | Path | None = None
    dividend_records_path: str | Path | None = None
    calendar_path: str | Path | None = None

    def __post_init__(self):
        from ..models import check_source_paths
        check_source_paths(vars(self))


@dataclass
class ContinuousPanel:
    close: pd.DataFrame
    spot: pd.DataFrame
    dividend_points: pd.DataFrame
    days_to_expiry: pd.DataFrame
    mapping: pd.DataFrame
    extras: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    dividend_revisions: pd.DataFrame | None = None


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    required_data: tuple[str, ...]
    required_parameters: tuple[str, ...]
    compute: Callable  # (ContinuousPanel, parameters) -> timestamp x continuous-slot DataFrame


@dataclass
class StrategyResult:
    factors: dict[str, pd.DataFrame]
    continuous_factors: dict[str, pd.DataFrame]
    targets: pd.DataFrame
    scores: pd.DataFrame
    panel: ContinuousPanel
    metadata: dict
    output_paths: dict = field(default_factory=dict)
    market_data: MarketData | None = None

    def save(self, directory):
        from .pipeline import save_strategy
        self.output_paths = save_strategy(self, directory)
        return self.output_paths


@dataclass
class FactorResult:
    """Numerical research output plus dated mapping context; contains no CTA settings."""
    factors: dict[str, pd.DataFrame]
    continuous_factors: dict[str, pd.DataFrame]
    panel: ContinuousPanel
    contracts: dict
    metadata: dict
    output_paths: dict = field(default_factory=dict)
    market_data: MarketData | None = None
    diagnostics: dict[str, pd.DataFrame] = field(default_factory=dict)

    def save(self, directory):
        from .artifacts import save_factors
        self.output_paths = save_factors(self, directory)
        return self.output_paths


@dataclass
class CTAResult:
    targets: pd.DataFrame
    scores: pd.DataFrame
    metadata: dict
    decisions: pd.DataFrame | None = None
    output_paths: dict = field(default_factory=dict)

    def save(self, directory):
        from .artifacts import save_cta
        self.output_paths = save_cta(self, directory)
        return self.output_paths
