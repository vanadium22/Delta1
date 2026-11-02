from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, DataConfig, MarketData, load_result, run_backtest
from dashboard.backtest.io import write_json
from dashboard.backtest.test.test_data import local_temp


def expiry_market():
    index = pd.DatetimeIndex([day + " " + hour for day in ("2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24")
                              for hour in ("09:31", "15:00")], tz="Asia/Shanghai")
    close = pd.DataFrame({"IC2612.CFE": [100, 100, 100, 101, 102, 103, np.nan, np.nan], "IC_spot": 100}, index=index)
    return MarketData(close, {"IC": 10}, {"IC": .1},
                      contracts={"IC2612.CFE": dict(listing_date="2026-01-01", expiry_date="2026-09-23")})


class ExpiryTests(unittest.TestCase):
    def test_default_zero_forces_official_close_and_blocks_reentry(self):
        market = expiry_market()
        targets = pd.DataFrame({"IC2612.CFE": [.3, .4, .5]}, index=["2026-09-21", "2026-09-22", "2026-09-23"])
        result = run_backtest(targets, market_data=market, config=BacktestConfig(initial_capital=10_000))
        orders = result.actual_orders
        self.assertEqual(orders.reason.tolist(), ["target_rebalance", "expiry_d0"])
        self.assertEqual(orders.quantity.tolist(), [30, 30])
        self.assertEqual(orders.execution_time.iloc[-1], pd.Timestamp("2026-09-23 15:00", tz="Asia/Shanghai"))
        self.assertEqual(orders.days_to_expiry.iloc[-1], 0)
        self.assertAlmostEqual(result.accounts["portfolio"].equity.equity.iloc[-1], 10_000 + 30 * 3 * 10 - 30 * (100 + 103) * 10 * .0003)
        self.assertEqual(result.accounts["portfolio"].positions.iloc[-1, 0], 0)

    def test_positive_d0_and_other_contract_spot_survive(self):
        market = expiry_market()
        market.contracts["IC2612.CFE"]["expiry_date"] = "2026-09-24"
        market.close["IF2703.CFE"] = 100
        market.multiplier = {"IC": 10, "IF": 10}
        market.margin_rate = {"IC": .1, "IF": .1}
        market.contracts["IF2703.CFE"] = dict(expiry_date="2027-03-19")
        targets = pd.DataFrame({"IC2612.CFE": [.1], "IF2703.CFE": [.1], "IC_spot": [.1]}, index=["2026-09-21 09:31"])
        result = run_backtest(targets, market_data=market, config=BacktestConfig(precision="auto", d0=2, initial_capital=100_000))
        forced = result.actual_orders.query("reason == 'expiry_d0'")
        self.assertEqual(forced.symbol.tolist(), ["IC2612.CFE"])
        self.assertEqual(str(forced.execution_time.iloc[0]), "2026-09-22 15:00:00+08:00")
        self.assertGreater(result.accounts["portfolio"].positions["IF2703.CFE"].iloc[-1], 0)
        self.assertGreater(result.accounts["portfolio"].positions["IC_spot"].iloc[-1], 0)

    def test_direct_remaining_days_without_reference_and_round_trip(self):
        market = expiry_market()
        market.contracts = {}
        market.days_to_expiry = pd.DataFrame({"IC2612.CFE": [2, 1, 0, -1]}, index=pd.date_range("2026-09-21", periods=4))
        with local_temp() as root:
            result = run_backtest(pd.DataFrame({"IC2612.CFE": [.3]}, index=["2026-09-21"]), market_data=market, output_dir=root / "run")
            loaded = load_result(root / "run")
            pd.testing.assert_frame_equal(result.days_to_expiry, loaded.days_to_expiry)
            self.assertEqual(loaded.actual_orders.reason.iloc[-1], "expiry_d0")

    def test_missing_or_conflicting_maturity_is_explicit(self):
        targets = pd.DataFrame({"IC2612.CFE": [.3]}, index=["2026-09-21"])
        market = expiry_market()
        market.contracts = {}
        with self.assertRaisesRegex(BacktestError, "Missing expiry_date"):
            run_backtest(targets, market_data=market)
        market = expiry_market()
        market.days_to_expiry = pd.DataFrame({"IC2612.CFE": [3]}, index=["2026-09-21"])
        with self.assertRaisesRegex(BacktestError, "conflicts"):
            run_backtest(targets, market_data=market)

    def test_expiry_liquidation_serial_and_process_accounts_match(self):
        market = expiry_market()
        market.close["IF2703.CFE"] = 100
        market.contracts["IF2703.CFE"] = dict(expiry_date="2027-03-19")
        market.multiplier = {"IC": 10, "IF": 10}
        market.margin_rate = {"IC": .1, "IF": .1}
        targets = pd.DataFrame({"IC2612.CFE": [.2], "IF2703.CFE": [-.2]}, index=["2026-09-21"])
        config = BacktestConfig(mode="product", workers=1)
        serial = run_backtest(targets, market_data=market, config=config)
        parallel = run_backtest(targets, market_data=market, config=replace(config, workers=2))
        pd.testing.assert_frame_equal(serial.actual_orders, parallel.actual_orders)
        for name in serial.accounts:
            pd.testing.assert_frame_equal(serial.accounts[name].equity, parallel.accounts[name].equity)

    def test_due_position_waits_for_close_and_reserves_margin_for_other_orders(self):
        market = expiry_market()
        market.contracts["IC2612.CFE"]["expiry_date"] = "2026-09-24"
        market.close["IF2703.CFE"] = 100
        market.contracts["IF2703.CFE"] = dict(expiry_date="2027-03-19")
        market.multiplier = {"IC": 10, "IF": 10}
        market.margin_rate = {"IC": .1, "IF": .1}
        weights = pd.DataFrame({"IC2612.CFE": [.4, .9], "IF2703.CFE": [0, .9]},
                               index=["2026-09-21 09:31", "2026-09-21 15:00"])
        result = run_backtest(weights, market_data=market, config=BacktestConfig(initial_capital=10_000, precision="auto", d0=2))
        ic = result.actual_orders.query("symbol == 'IC2612.CFE'")
        self.assertEqual(ic.quantity.tolist(), [40, 40])
        self.assertEqual(ic.reason.tolist(), ["target_rebalance", "expiry_d0"])
        other = result.actual_orders.query("symbol == 'IF2703.CFE'").iloc[0]
        equity_after_fees = 10_000 - 40 * 1000 * .0003 - other.fee
        self.assertLessEqual(40 * 100 + other.quantity * 100, .99 * equity_after_fees)

    def test_expired_stale_target_does_not_remove_other_contract_first_minute(self):
        market = expiry_market()
        market.contracts["IC2612.CFE"]["expiry_date"] = "2026-09-22"
        market.contracts["IF2703.CFE"] = dict(expiry_date="2027-03-19")
        market.close["IF2703.CFE"] = 100
        market.close.loc[market.close.index.date >= pd.Timestamp("2026-09-23").date(), "IC2612.CFE"] = np.nan
        with local_temp() as root:
            market.close.to_parquet(root / "minute.parquet")
            market.close.groupby(market.close.index.normalize()).tail(1).to_parquet(root / "daily.parquet")
            write_json(root / "reference.json", dict(contracts=[dict(instrument_id=s, **r) for s, r in market.contracts.items()]))
            config = DataConfig(minute_close_path=root / "minute.parquet", daily_close_path=root / "daily.parquet",
                                reference_path=root / "reference.json", multipliers={"IC": 10, "IF": 10}, margin_rates={"IC": .1, "IF": .1})
            targets = pd.DataFrame({"IC2612.CFE": [.2, .2], "IF2703.CFE": [0, .2]}, index=["2026-09-18", "2026-09-22"])
            result = run_backtest(targets, data_config=config)
            order = result.actual_orders.query("symbol == 'IF2703.CFE'").iloc[0]
            self.assertEqual(order.execution_time, pd.Timestamp("2026-09-23 09:31", tz="Asia/Shanghai"))


if __name__ == "__main__":
    unittest.main()
