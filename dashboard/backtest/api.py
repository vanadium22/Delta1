"""Public entry point: direct DataFrames, file paths, or custom instruction loaders."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from time import perf_counter
from typing import Callable

import pandas as pd

from .data import _reference, read_frame, resolve_paths
from .data_events import load_event_market_data
from .engine import run_engine
from .io import frame_fingerprint
from .models import (BacktestConfig, BacktestError, DataConfig, MarketData,
                     check_cancelled, check_source_paths, normalize_frame)


def run_backtest(instructions: pd.DataFrame | None = None, *,
                 instructions_path: str | Path | None = None,
                 instruction_loader: Callable[[Path], pd.DataFrame] | None = None,
                 market_data: MarketData | None = None,
                 data_config: DataConfig | None = None,
                 config: BacktestConfig | None = None,
                 output_dir: str | Path | None = None, cancel_event=None, progress=None):
    """Each row is a complete target; zero closes. No rows means no rebalancing."""
    config, data_config = config or BacktestConfig(), data_config or DataConfig()
    started = perf_counter()
    check_cancelled(cancel_event)
    if progress:
        progress(dict(stage="instructions", message="正在读取目标指令表"))
    if instructions is not None and instructions_path is not None:
        raise BacktestError("Supply instructions or instructions_path, not both")
    if instructions is None:
        if instructions_path is None:
            raise BacktestError("instructions or instructions_path is required")
        check_source_paths(instructions_path)
        path = Path(instructions_path).expanduser().resolve()
        instructions = (instruction_loader(path) if instruction_loader else
                        read_frame(path, trusted_pickle=data_config.trusted_pickle))
    normalized = normalize_frame(instructions, label="instructions", timezone=config.timezone,
                                 date_at=config.date_at, unit=config.timestamp_unit, allow_continuous=True)
    if normalized.isna().any().any() and config.nan_policy == "error":
        raise BacktestError("Instructions contain NaN; enter explicit zero targets or opt into nan_policy='zero'")
    parameters = replace(config, timestamp_unit=None)
    continuous = any(re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE", s) for s in normalized)
    targets = normalized
    if continuous:
        from .strategy.mapping import expand_slot_targets
        contracts = market_data.contracts if market_data is not None else _reference(resolve_paths(data_config)["reference_path"])
        targets, _ = expand_slot_targets(normalized.fillna(0) if config.nan_policy == "zero" else normalized,
                                         contracts, timezone=config.timezone, date_at=config.date_at)
    if config.weight_mode == "neutral_units" and not config.hedges and any(s.endswith("_spot") for s in targets):
        from .data import load_multipliers
        from .hedging import index_hedges
        references = market_data.contracts if market_data is not None else _reference(resolve_paths(data_config)["reference_path"])
        multiples = market_data.multiplier if market_data is not None else load_multipliers(data_config, references)
        if isinstance(multiples, pd.DataFrame):
            chosen = {}
            for symbol in targets:
                if not symbol.endswith(".CFE"):
                    continue
                values = multiples[symbol].dropna().unique() if symbol in multiples else []
                if len(values) != 1:
                    raise BacktestError("Neutral index hedge requires one explicit constant multiplier per contract")
                chosen[symbol] = float(values[0])
            multiples = chosen
        parameters = replace(parameters, hedges=index_hedges(targets.columns, multiples))
    if market_data is None:
        market_data = load_event_market_data(data_config, targets.fillna(0) if config.nan_policy == "zero" else targets,
                                            parameters, cancel_event=cancel_event, progress=progress)
    loaded_at = perf_counter()
    # Epoch conversion applies only to the original input, which is normalized above.
    result = run_engine(targets, market_data, parameters,
                        cancel_event=cancel_event, progress=progress)
    result.metadata["config"]["timestamp_unit"] = config.timestamp_unit
    result.metadata["instructions"] = dict(path=str(Path(instructions_path).resolve()) if instructions_path else None,
                                          rows=len(normalized), columns=list(normalized.columns),
                                          fingerprint=frame_fingerprint(normalized))
    result.input_instructions = normalized
    if continuous:
        result.execution_instructions = targets
        result.metadata["instructions"]["continuous_expanded"] = True
        result.metadata["instructions"]["execution_fingerprint"] = frame_fingerprint(targets)
    result.metadata["performance"].update(load_seconds=loaded_at - started, engine_seconds=perf_counter() - loaded_at)
    if output_dir is not None:
        check_cancelled(cancel_event)
        if progress:
            progress(dict(stage="saving", message="正在完整保存结果，请等待写出结束"))
        result.save(output_dir)
    return result
