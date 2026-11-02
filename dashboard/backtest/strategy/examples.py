"""Runnable synthetic examples. Every input and expiry below is a test fixture."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..models import MarketData
from .models import CTAConfig, FactorConfig
from .pipeline import generate_strategy


def demo_market(periods=35):
    dates = pd.bdate_range("2026-01-05", periods=periods, tz="Asia/Shanghai") + pd.Timedelta(hours=15)
    dates_spec = (("IC2601.CFE", "2025-09-01", "2026-01-16"),
                  ("IC2602.CFE", "2025-12-01", "2026-02-20"),
                  ("IC2603.CFE", "2025-06-01", "2026-03-20"),
                  ("IC2606.CFE", "2025-09-01", "2026-06-19"),
                  ("IC2609.CFE", "2026-01-19", "2026-09-18"),
                  ("IC2604.CFE", "2026-02-23", "2026-04-17"))
    contracts = {s: dict(instrument_id=s, listing_date=left, expiry_date=right, known_at="2025-01-01T00:00:00+08:00")
                 for s, left, right in dates_spec}
    close = pd.DataFrame({"IC_spot": 100.0}, index=dates)
    points = pd.DataFrame(2.0, index=dates.normalize(), columns=contracts)
    for j, (symbol, ref) in enumerate(contracts.items()):
        days = (pd.Timestamp(ref["expiry_date"]) - dates.tz_localize(None).normalize()).days.to_numpy()
        annual = 1.2 * np.sin(np.arange(periods) / 3 + j / 2)
        prices = 100 + annual * 100 * days / 36500 - 2
        active = (dates.strftime("%Y-%m-%d") >= ref["listing_date"]) & (dates.strftime("%Y-%m-%d") <= ref["expiry_date"])
        close[symbol] = np.where(active, prices, np.nan)
    return MarketData(close, {"IC": 200}, {"IC": .15}, contracts=contracts), points


def main(argv=None):
    parser = argparse.ArgumentParser(description="两个因子、固定与 Z 阈值的隔离合成示例；不是实际行情")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    market, dividends = demo_market()
    cases = (("annual_fixed", "annual_basis", CTAConfig()),
             ("percentile_fixed", "basis_percentile", CTAConfig(transform="center_percentile")),
             ("annual_zscore", "annual_basis", CTAConfig(mode="zscore")))
    for folder, factor, cta in cases:
        result = generate_strategy(market_data=market, dividend_points=dividends, factor_config=FactorConfig(),
                                   cta_config=cta, factor_name=factor, output_dir=args.output / folder)
        print(f"{folder}: {len(result.targets)} rows; {result.output_paths['targets']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
