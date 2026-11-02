"""Read declared inputs, build slot factors, then publish concrete CTA targets."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from ..data import _reference, load_market_data, resolve_paths
from ..data_events import load_event_market_data
from ..expiry import remaining_days
from ..io import frame_fingerprint, write_json
from ..models import (BacktestConfig, BacktestError, DataConfig, check_cancelled, check_market_source,
                      normalize_frame, time_bound, timestamp)
from .cta import cta_targets
from .factors import annual_basis, basis_percentile
from .mapping import slot_mapping, to_actual
from .models import ContinuousPanel, CTAConfig, CTAResult, FactorConfig, FactorResult, StrategyDataConfig, StrategyResult


def _load_market(data, factors, cancel_event, progress):
    chosen = ((data.daily_close_path or data.close_path or data.minute_close_path) if factors.precision == "1d"
              else (data.minute_close_path or data.close_path or data.daily_close_path))
    if chosen is None:
        contracts = _reference(resolve_paths(data)["reference_path"])
        selected_symbols = [s for s in contracts if s[:2] in factors.roots]
        listings = [contracts[s].get("listing_date") for s in selected_symbols]
        if not selected_symbols or any(not day for day in listings):
            raise BacktestError("Registered factor inputs require dated contract listing/expiry references")
        # This selector declares columns only. It never enters an account or
        # becomes a strategy signal; daily factors do not read execution minutes.
        first = timestamp(min(listings), date_at=None)
        selector = pd.DataFrame(1.0, index=pd.DatetimeIndex([first]), columns=selected_symbols)
        return load_event_market_data(data, selector, BacktestConfig(precision=factors.precision, workers=factors.workers, d0=None),
                                      cancel_event=cancel_event, progress=progress, daily_marks_only=factors.precision == "1d")
    # Keep data positions explicit; the execution engine later reads the original
    # minute/daily configuration independently when consuming these targets.
    selected = replace(data, close_path=chosen, minute_close_path=None, daily_close_path=None,
                       frequency="1d" if factors.precision == "1d" else data.frequency)
    market = load_market_data(selected, cancel_event=cancel_event, progress=progress)
    if chosen == data.daily_close_path and market.close.index.normalize().duplicated().any():
        raise BacktestError("daily_close_path must contain at most one close timestamp per day")
    return market


def _calendar(path, timezone):
    if path is None:
        return None
    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        values = raw.get("trading_days", []) if isinstance(raw, dict) else raw
    else:
        frame = pd.read_csv(path)
        col = next((c for c in ("trade_date", "date", "timestamp") if c in frame), None)
        if col is None:
            raise BacktestError("Trading calendar CSV needs a trade_date/date/timestamp column")
        values = frame[col]
    index = pd.DatetimeIndex([timestamp(v, timezone=timezone, date_at=None) for v in values]).normalize()
    if index.empty or index.duplicated().any():
        raise BacktestError("Trading calendar must contain nonempty unique dates")
    return index.sort_values()


def prepare_panel(market, config, sources, *, dividend_book=None, dividend_points=None,
                  extra_data=None, calendar=None, timezone="Asia/Shanghai", cancel_event=None, require_dividends=True):
    check_market_source(market.metadata)
    raw = market.daily_close if config.precision == "1d" and market.daily_close is not None else market.close
    close = normalize_frame(raw, label="factor close", timezone=timezone)
    if config.precision == "1d":
        close = close.groupby(close.index.normalize(), sort=True).tail(1)
    calendar = _calendar(sources.calendar_path, timezone) if calendar is None else calendar
    if calendar is not None:
        calendar = pd.DatetimeIndex([timestamp(d, timezone=timezone, date_at=None) for d in calendar]).normalize()
        missing = calendar.difference(close.index.normalize())
        close = close.reindex(index=close.index.union(missing + pd.Timedelta(hours=15))).sort_index()
    mapping, gaps = slot_mapping(close.index, market.contracts, config.roots, config.slots)
    future = pd.DataFrame(np.nan, index=close.index, columns=mapping.columns)
    spot, dividends, days = future.copy(), future.copy(), future.copy()
    revisions = pd.DataFrame(None, index=close.index, columns=mapping.columns, dtype=object)
    concrete_days = remaining_days(close.index, list(close.columns), market.contracts,
                                   market.days_to_expiry, timezone=timezone)
    if dividend_book is None and (sources.dividend_store_root or sources.dividend_records_path):
        from dashboard.marketdata.overview_dividends import DatedDividendBook, DividendStore
        records = DividendStore(sources.dividend_store_root).read() if sources.dividend_store_root else []
        if sources.dividend_records_path:
            raw = json.loads(Path(sources.dividend_records_path).read_text(encoding="utf-8-sig"))
            records.extend(raw.get("records", []) if isinstance(raw, dict) else raw)
        dividend_book = DatedDividendBook(records, market.contracts)
    adjusted = (normalize_frame(market.adjusted_close, label="adjusted factor close", timezone=timezone)
                if market.adjusted_close is not None else None)
    point_table = None
    if dividend_points is not None:
        point_table = normalize_frame(dividend_points, label="factor dividends", timezone=timezone, date_at="00:00")
        if (point_table.index == point_table.index.normalize()).all():
            point_table = point_table.reindex(close.index.normalize())
            point_table.index = close.index
        else:
            point_table = point_table.reindex(close.index)
    if require_dividends and dividend_book is None and adjusted is None and point_table is None:
        raise BacktestError("Annual basis requires dated dividends, explicit dividend points, or adjusted_close; missing D is not zero")
    for alias in mapping:
        root = alias[:2]
        if root + "_spot" in close:
            spot[alias] = close[root + "_spot"]
        for symbol in mapping[alias].dropna().unique():
            check_cancelled(cancel_event)
            mask = mapping[alias].eq(symbol)
            if symbol in close:
                future.loc[mask, alias] = close.loc[mask, symbol]
                days.loc[mask, alias] = concrete_days.loc[mask, symbol]
            if dividend_book is not None:
                for stamp in close.index[mask]:
                    record = dividend_book.resolve(symbol, stamp) if hasattr(dividend_book, "resolve") else None
                    value = record.get("points") if record else dividend_book.points(symbol, stamp)
                    if value is not None:
                        dividends.at[stamp, alias] = value
                    revisions.at[stamp, alias] = (record or {}).get("revision", getattr(dividend_book, "version", None))
            elif point_table is not None and symbol in point_table:
                dividends.loc[mask, alias] = point_table.loc[mask, symbol]
            elif adjusted is not None and symbol in adjusted and symbol in close:
                dividends.loc[mask, alias] = adjusted[symbol].reindex(close.index)[mask] - close.loc[mask, symbol]
    if (dividends < 0).any().any() or np.isinf(dividends.to_numpy()).any():
        raise BacktestError("Remaining dividend points must be finite non-negative values or explicit missing cells")
    extras = {}
    for name, values in (extra_data or {}).items():
        source = normalize_frame(values, label=name, timezone=timezone).reindex(close.index)
        table = future.copy()
        for alias in mapping:
            for symbol in mapping[alias].dropna().unique():
                if symbol in source:
                    mask = mapping[alias].eq(symbol)
                    table.loc[mask, alias] = source.loc[mask, symbol]
        extras[name] = table
    metadata = dict(mapping_policy="dated listing/expiry ordering; expiry date retains old slots; not PIT-certified metadata",
                    mapping_gaps=gaps, calendar="explicit" if calendar is not None else "observed_market_dates",
                    dividend_source="dated_book" if dividend_book is not None else "points" if point_table is not None else
                    "adjusted_close_minus_raw" if adjusted is not None else "unavailable",
                    dividend_version=getattr(dividend_book, "version", None), dividend_info=getattr(dividend_book, "info", {}),
                    prices_forward_filled=False)
    return ContinuousPanel(future, spot, dividends, days, mapping, extras, metadata, revisions)


def compute_factors(*, market_data=None, data_config=None, source_config=None, factor_config=None,
                      factor_name="basis_percentile", data_loader=None,
                      dividend_book=None, dividend_points=None, extra_data=None, factor_definitions=(),
                      factor_parameters=None, include_examples=True, requested_only=False, load_execution_parameters=False,
                      calendar=None, output_dir=None,
                      cancel_event=None, progress=None):
    """Custom data_loader(DataConfig)->MarketData; custom factors declare their inputs."""
    data = data_config or DataConfig()
    source = source_config or StrategyDataConfig(dividend_store_root=data.dividend_store_root,
        dividend_records_path=data.dividend_records_path, calendar_path=data.calendar_path)
    factors = factor_config or FactorConfig()
    check_cancelled(cancel_event)
    reading = data if load_execution_parameters else replace(data, margin_rate_path=None, margin_rates={}, multiplier_path=None, multipliers={})
    market = market_data if market_data is not None else (
        data_loader(reading) if data_loader is not None else _load_market(reading, factors, cancel_event, progress))
    if data.dividend_mode == "ignore":
        if dividend_book is not None or dividend_points is not None or source.dividend_store_root or source.dividend_records_path:
            raise BacktestError("Explicit ignore-dividend assumption conflicts with supplied research dividends")
        dividend_points = pd.DataFrame(0.0, index=market.close.index, columns=market.close.columns)
    panel = prepare_panel(market, factors, source, dividend_book=dividend_book, dividend_points=dividend_points,
                          extra_data=extra_data, calendar=calendar, cancel_event=cancel_event,
                          require_dividends=include_examples and factor_name in {"annual_basis", "basis_percentile"})
    values = {}
    if include_examples:
        if factor_name not in {"close_percentile", "price_basis_percentile", "calendar_spread_percentile"}:
            annual = annual_basis(panel, factors)
            values["annual_basis"] = annual
            if not requested_only or factor_name != "annual_basis":
                values["basis_percentile"] = basis_percentile(panel, annual, factors, cancel_event=cancel_event)
        else:
            from .research_factors import research_factor
            values[factor_name] = research_factor(factor_name, panel, factors, cancel_event=cancel_event)
    definitions = []
    for definition in factor_definitions:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", definition.name) or definition.name in values:
            raise BacktestError("Factor names must be unique identifiers")
        params = (factor_parameters or {}).get(definition.name, {})
        absent = [k for k in definition.required_data if not hasattr(panel, k) and k not in panel.extras]
        absent += [k for k in definition.required_parameters if k not in params]
        if absent:
            raise BacktestError(f"{definition.name}: missing declared data/parameters {absent}")
        calculated = definition.compute(panel, params)
        if not isinstance(calculated, pd.DataFrame) or not calculated.index.equals(panel.close.index) or not calculated.columns.equals(panel.close.columns):
            raise BacktestError("Custom factors must return the exact timestamp x slot shape")
        if np.isinf(calculated.to_numpy()).any():
            raise BacktestError("Custom factors cannot return infinity")
        values[definition.name] = calculated
        definitions.append(dict(name=definition.name, data=definition.required_data, parameters=definition.required_parameters))
    if factor_name not in values:
        raise BacktestError(f"Unknown factor {factor_name!r}")
    actual = {name: to_actual(frame, panel.mapping) for name, frame in values.items()}
    quality = {name: dict(valid_cells=int(frame.notna().sum().sum()), total_cells=int(frame.size))
               for name, frame in actual.items()}
    warnings = []
    if "basis_percentile" in quality and quality["basis_percentile"]["valid_cells"] == 0:
        warnings.append("无完整历史分位窗口；检查历史价格、逐日分红、T、映射和窗口长度，不缩短窗口或填零")
    if "annual_basis" in quality and quality["annual_basis"]["valid_cells"] == 0:
        warnings.append("无有效年化基差；检查 F/S/D/T 及最小剩余天数")
    if quality[factor_name]["valid_cells"] == 0 and factor_name not in {"annual_basis", "basis_percentile"}:
        warnings.append("所选因子无有效单元格；检查完整历史窗口、价格和连续映射，不填零或缩短窗口")
    if panel.metadata["mapping_gaps"]:
        warnings.append("部分日期缺完整四档映射；详见 panel.mapping_gaps")
    metadata = dict(factor_config=asdict(factors), factor_name=factor_name,
                    factor_units={"annual_basis": "percentage_points", "basis_percentile": "0_to_1"},
                    percentile="previous window_days daily slots; current date excluded; ties half weight; known T<min_annual_days excluded; other missing days invalidate window",
                    output_columns="concrete_contracts_only", custom_factors=definitions, panel=panel.metadata,
                    market=market.metadata, quality=quality, warnings=warnings, dividend_mode=data.dividend_mode,
                    factor_fingerprints={k: frame_fingerprint(v) for k, v in values.items()})
    result = FactorResult(actual, values, panel, market.contracts, metadata, market_data=market)
    if output_dir is not None:
        check_cancelled(cancel_event)
        result.save(output_dir)
    return result


def generate_cta(factors, *, factor_name=None, cta_config=None, start=None, end=None,
                 output_dir=None, cancel_event=None):
    """Only numerical factor results + dated mapping; no market loader or recomputation."""
    name = factor_name or factors.metadata["factor_name"]
    if name not in factors.continuous_factors:
        raise BacktestError(f"Input factor artifact does not contain {name}")
    config = cta_config or CTAConfig()
    weights, scores = cta_targets(factors.continuous_factors[name], config, cancel_event=cancel_event)
    targets = to_actual(weights, factors.panel.mapping, fill=0.0)
    scores = to_actual(scores, factors.panel.mapping)
    selected = _interval(targets.index, start, end)
    targets, scores = targets.loc[selected], scores.loc[selected]
    if targets.empty:
        raise BacktestError("No mapped target rows remain in the selected strategy interval")
    result = CTAResult(targets, scores, dict(cta_config=asdict(config), input_factor=name,
                       factor_fingerprint=frame_fingerprint(factors.continuous_factors[name]),
                       target_fingerprint=frame_fingerprint(targets)))
    if output_dir is not None:
        check_cancelled(cancel_event)
        result.save(output_dir)
    return result


def _interval(index, start, end):
    left, right = time_bound(start), time_bound(end, end=True)
    return ((index >= left) if left is not None else np.ones(len(index), dtype=bool)) & (
        (index <= right) if right is not None else True)


def generate_strategy(*, cta_config=None, start=None, end=None, output_dir=None, **kwargs):
    """Compatibility composition of the two independently callable stages."""
    kwargs.setdefault("load_execution_parameters", True)
    factors = compute_factors(**kwargs)
    if cta_config is None:
        cta_config = CTAConfig(transform="center_percentile" if factors.metadata["factor_name"] == "basis_percentile" else "identity")
    signals = generate_cta(factors, factor_name=kwargs.get("factor_name"), cta_config=cta_config,
                           start=start, end=end, cancel_event=kwargs.get("cancel_event"))
    selected = _interval(factors.panel.mapping.index, start, end)
    metadata = dict(factors.metadata, cta_config=signals.metadata["cta_config"],
                    target_fingerprint=signals.metadata["target_fingerprint"])
    result = StrategyResult({k: v.loc[selected] for k, v in factors.factors.items()}, factors.continuous_factors,
                            signals.targets, signals.scores, factors.panel, metadata, market_data=factors.market_data)
    if output_dir is not None:
        check_cancelled(kwargs.get("cancel_event"))
        result.save(output_dir)
    return result


def save_strategy(result, directory):
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    paths = {"output_dir": str(root), "factors": {}, "continuous_factors": {}}
    for group, frames in (("factors", result.factors), ("continuous_factors", result.continuous_factors)):
        folder = root / group
        folder.mkdir()
        for name, frame in frames.items():
            target = folder / (name + ".parquet")
            frame.to_parquet(target)
            paths[group][name] = str(target)
    frames = dict(targets=result.targets, scores=result.scores, slot_mapping=result.panel.mapping,
                  continuous_close=result.panel.close, continuous_spot=result.panel.spot,
                  continuous_dividends=result.panel.dividend_points, continuous_days=result.panel.days_to_expiry,
                  dividend_revisions=result.panel.dividend_revisions)
    for name, frame in frames.items():
        if frame is not None:
            target = root / (name + ".parquet")
            frame.to_parquet(target)
            paths[name] = str(target)
    result.targets.to_csv(root / "targets.csv", encoding="utf-8-sig")
    paths["targets_csv"] = str(root / "targets.csv")
    write_json(root / "metadata.json", {**result.metadata, "output_paths": paths})
    return paths
