"""Reproducible isolated benchmark; generated prices are never production data."""
from dataclasses import replace
import argparse
import importlib.util
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, MarketData, run_backtest
from dashboard.backtest.io import write_json


def fixture(days, *, dense=False):
    calendar = pd.bdate_range("2025-01-06", periods=days)
    offsets = np.r_[np.arange(571, 691), np.arange(781, 901)]
    index = pd.DatetimeIndex(np.concatenate([(day.to_datetime64() + offsets.astype("timedelta64[m]")) for day in calendar]))
    index = index.tz_localize("Asia/Shanghai")
    symbols = [root + expiry + ".CFE" for root in ("IF", "IH", "IC", "IM") for expiry in ("2609", "2610", "2611", "2612")]
    clock = np.arange(len(index), dtype=float)
    prices = np.column_stack([100 + i * 2 + 0.9 * np.sin(clock / (120 + i)) + 0.3 * np.cos(clock / (53 + i)) for i in range(len(symbols))])
    close = pd.DataFrame(prices, index=index, columns=symbols)
    rows = np.arange(0, len(index) - 1, 1 if dense else 1200)
    base = np.array([(-1 if i % 2 else 1) * .035 for i in range(len(symbols))])
    weights = np.tile(base, (len(rows), 1))
    weights[(rows // 240) % 3 == 1] *= -1
    targets = pd.DataFrame(weights, index=index[rows], columns=symbols)
    return targets, MarketData(close, multiplier={r: 10 for r in ("IF", "IH", "IC", "IM")},
                               margin_rate={r: .15 for r in ("IF", "IH", "IC", "IM")})


def timed(function):
    start = perf_counter()
    result = function()
    return result, perf_counter() - start


def compare_accounts(left, right):
    pd.testing.assert_frame_equal(left.actual_orders, right.actual_orders, check_exact=False, rtol=1e-11, atol=1e-6)
    for key in left.accounts:
        pd.testing.assert_frame_equal(left.accounts[key].equity, right.accounts[key].equity, check_exact=False, rtol=1e-11, atol=1e-6)
        pd.testing.assert_frame_equal(left.accounts[key].positions, right.accounts[key].positions)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=252)
    parser.add_argument("--dense-days", type=int, default=24)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("dashboard.backtest._reference_engine", args.baseline)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    config = BacktestConfig(initial_capital=10_000_000, precision="auto", workers=1, d0=None)
    targets, market = fixture(args.days)
    print("Comparing old per-quote loop with daily-output event engine...", flush=True)
    baseline, old_seconds = timed(lambda: old.run_engine(targets, market, config))
    optimized, new_seconds = timed(lambda: run_backtest(targets, market_data=market, config=config))
    common = list(baseline.actual_orders.columns)
    pd.testing.assert_frame_equal(baseline.actual_orders, optimized.actual_orders[common], check_exact=False, rtol=1e-11, atol=1e-6)
    old_curve = baseline.accounts["portfolio"].equity
    day_end = old_curve.groupby(old_curve.index.normalize()).tail(1)
    new_curve = optimized.accounts["portfolio"].equity
    for column in ("equity", "cash", "required_margin", "available_equity"):
        np.testing.assert_allclose(day_end[column], new_curve[column], rtol=1e-11, atol=1e-6)
    np.testing.assert_allclose(old_curve.fees.groupby(old_curve.index.normalize()).sum(), new_curve.fees, rtol=1e-11, atol=1e-6)
    print(f"Sparse: {old_seconds:.3f}s -> {new_seconds:.3f}s; {old_seconds/new_seconds:.2f}x", flush=True)
    targets, market = fixture(args.dense_days, dense=True)
    independent = replace(config, mode="product")
    print("Comparing serial and four owned account processes...", flush=True)
    serial, serial_seconds = timed(lambda: run_backtest(targets, market_data=market, config=independent))
    parallel, parallel_seconds = timed(lambda: run_backtest(targets, market_data=market, config=replace(independent, workers=4)))
    compare_accounts(serial, parallel)
    report = dict(test_data="isolated deterministic synthetic prices, not strategy evidence",
                  sparse=dict(quote_rows=len(old_curve), daily_rows=len(new_curve), signals=optimized.metadata["precision"]["input_rows"],
                              evaluated_events=optimized.accounts["portfolio"].summary["evaluated_events"],
                              old_seconds=old_seconds, new_seconds=new_seconds, speedup=old_seconds / new_seconds,
                              trades_and_daily_equity_match=True),
                  processes=dict(quote_rows=len(market.close), signal_rows=len(targets), accounts=4,
                                 serial_seconds=serial_seconds, parallel_seconds=parallel_seconds,
                                 speedup=serial_seconds / parallel_seconds,
                                 workers=parallel.metadata["performance"]["account_processes"], results_match=True))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, report)
    print(f"Processes: {serial_seconds:.3f}s -> {parallel_seconds:.3f}s; {serial_seconds/parallel_seconds:.2f}x", flush=True)
    print(str(args.output.resolve()), flush=True)


if __name__ == "__main__":
    main()
