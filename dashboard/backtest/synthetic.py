"""Create a small, runnable, fully synthetic standard dataset (never market evidence)."""
import argparse
from pathlib import Path

import pandas as pd

from .io import write_json
from .models import DEFAULT_MULTIPLIERS
from .strategy.examples import demo_market


def write_inputs(directory):
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    market, _ = demo_market()
    prices, contracts = [], []
    for product, multiple in DEFAULT_MULTIPLIERS.items():
        rename = {s: product + s[2:] for s in market.close}
        prices.append(market.close.rename(columns=rename))
        for symbol, row in market.contracts.items():
            contracts.append(dict(row, instrument_id=product + symbol[2:], root=product, multiplier=multiple))
    close = pd.concat(prices, axis=1)
    close.to_parquet(root / "daily_close.parquet")
    minute = close.copy()
    minute.index = close.index.normalize() + pd.Timedelta(hours=9, minutes=31)
    pd.concat([minute, close]).sort_index().to_parquet(root / "minute_close.parquet")
    pd.DataFrame(contracts).to_parquet(root / "contracts.parquet", index=False)
    base = dict(data=dict(data_root=".", dataset_id="synthetic_four_products", data_version="v1", source_id="synthetic_fixture",
                         daily_close_path="daily_close.parquet", minute_close_path="minute_close.parquet",
                         reference_path="contracts.parquet", margin_rates={r: 1. for r in DEFAULT_MULTIPLIERS},
                         dividend_mode="ignore"),
                factor=dict(name="basis_percentile", parameters=dict(window_days=3, min_samples=2, min_annual_days=5),
                            roots=list(DEFAULT_MULTIPLIERS), slots=[0, 1, 2, 3], precision="1d", workers=1),
                cta=dict(name="expiry_index", input_factor="basis_percentile", parameters=dict(threshold=.9,
                         position_weight=.495, direction=-1, transform="center_percentile", selection="product_best", slots=[0, 1, 2, 3])),
                backtest=dict(initial_capital=1_000_000, commission_rate=.0003, max_capital_usage=.99, precision="1d",
                              mode="product", weight_mode="neutral_units", d0=0, rebalance_on_change_only=True, workers=1))
    write_json(root / "index_09.local.json", base)
    write_json(root / "index_08.local.json", {**base, "cta": {**base["cta"], "parameters": {**base["cta"]["parameters"], "threshold": .8}}})
    price_job = {**base, "factor": {**base["factor"], "name": "price_basis_percentile", "parameters": dict(window_days=3, min_samples=2)},
                 "cta": {**base["cta"], "input_factor": "price_basis_percentile"}}
    write_json(root / "price_basis.local.json", price_job)
    write_json(root / "close.local.json", {**price_job, "factor": {**price_job["factor"], "name": "close_percentile"},
                                          "cta": {**price_job["cta"], "input_factor": "close_percentile"}})
    spread = {**base, "factor": {**base["factor"], "name": "calendar_spread_percentile", "parameters": dict(window_days=3, min_samples=2)},
              "cta": dict(name="expiry_spread", input_factor="calendar_spread_percentile", parameters=dict(threshold=.9,
                          position_weight=.495, direction=-1, transform="center_percentile"))}
    write_json(root / "spread.local.json", spread)
    write_json(root / "README.local.json", dict(source="All prices, calendars and references are synthetic fixtures, not observed markets",
        coverage=dict(start=str(close.index[0]), end=str(close.index[-1])), roots=list(DEFAULT_MULTIPLIERS),
        margin_assumption="100% per futures leg and synthetic index; commissions charged per leg"))
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(write_inputs(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
