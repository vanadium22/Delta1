"""Public entry point: direct DataFrames, file paths, or custom instruction loaders."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

import pandas as pd

from .data import load_market_data, read_frame
from .engine import run_engine
from .io import frame_fingerprint
from .models import (BacktestConfig, BacktestError, DataConfig, MarketData,
                     normalize_frame)


def run_backtest(instructions: pd.DataFrame | None = None, *,
                 instructions_path: str | Path | None = None,
                 instruction_loader: Callable[[Path], pd.DataFrame] | None = None,
                 market_data: MarketData | None = None,
                 data_config: DataConfig | None = None,
                 config: BacktestConfig | None = None,
                 output_dir: str | Path | None = None):
    """Each row is a complete target; zero closes. No rows means no rebalancing."""
    config, data_config = config or BacktestConfig(), data_config or DataConfig()
    if instructions is not None and instructions_path is not None:
        raise BacktestError("Supply instructions or instructions_path, not both")
    if instructions is None:
        if instructions_path is None:
            raise BacktestError("instructions or instructions_path is required")
        path = Path(instructions_path).expanduser().resolve()
        instructions = (instruction_loader(path) if instruction_loader else
                        read_frame(path, trusted_pickle=data_config.trusted_pickle))
    normalized = normalize_frame(instructions, label="instructions", timezone=config.timezone,
                                 date_at=config.date_at, unit=config.timestamp_unit)
    if market_data is None:
        market_data = load_market_data(data_config, symbols=list(normalized.columns),
                                       start=config.start or normalized.index.min(), end=config.end,
                                       timezone=config.timezone)
    # Epoch conversion applies only to the original input, which is normalized above.
    result = run_engine(normalized, market_data, replace(config, timestamp_unit=None))
    result.metadata["config"]["timestamp_unit"] = config.timestamp_unit
    result.metadata["instructions"] = dict(path=str(Path(instructions_path).resolve()) if instructions_path else None,
                                          rows=len(normalized), columns=list(normalized.columns),
                                          fingerprint=frame_fingerprint(normalized))
    if output_dir is not None:
        result.save(output_dir)
    return result
