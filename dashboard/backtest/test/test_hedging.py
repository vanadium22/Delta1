from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, DataConfig, HedgeRule, MarketData, index_hedges, run_backtest
from dashboard.backtest.io import write_json
from dashboard.backtest.test.test_data import local_temp


def pair_market():
    close = pd.DataFrame({"IC2612.CFE": [100, 100, 103], "IC_spot": [100, 100, 102]},
                         index=pd.date_range("2026-09-21", periods=3))
    return MarketData(close, {"IC": 200}, {"IC": .1},
                      contracts={"IC2612.CFE": dict(expiry_date="2026-09-23", listing_date="2026-01-01")})


class HedgingTests(unittest.TestCase):
    def config(self, **kwargs):
        return BacktestConfig(initial_capital=100_000, hedges=index_hedges(["IC2612.CFE"]), **kwargs)

    def test_long_future_short_index_exact_units_budget_and_paired_expiry(self):
        result = run_backtest(pd.DataFrame({"IC2612.CFE": [.99]}, index=["2026-09-21"]), market_data=pair_market(), config=self.config())
        r = result.accounts["portfolio"]
        self.assertEqual(r.positions.iloc[1].tolist(), [4, -800])
        self.assertEqual(r.positions.iloc[-1].tolist(), [0, 0])
        self.assertAlmostEqual(r.equity.required_margin.iloc[1], 88_000)
        self.assertAlmostEqual(r.equity.equity.iloc[-1], 100_000 + 800 - 97.2)
        self.assertEqual(r.actual_orders.quantity.tolist(), [4, 800, 4, 800])
        self.assertEqual(r.actual_orders.reason.tolist(), ["target_rebalance", "target_rebalance", "expiry_d0", "expiry_d0"])
        self.assertTrue(r.actual_orders.hedge_primary.eq("IC2612.CFE").all())

    def test_short_future_long_index_is_symmetric_except_fees(self):
        result = run_backtest(pd.DataFrame({"IC2612.CFE": [-.99]}, index=["2026-09-21"]), market_data=pair_market(), config=self.config())
        r = result.accounts["portfolio"]
        self.assertEqual(r.positions.iloc[1].tolist(), [-4, 800])
        self.assertAlmostEqual(r.equity.equity.iloc[-1], 100_000 - 800 - 97.2)

    def test_fee_budget_rounds_primary_then_rebuilds_exact_hedge_quantity(self):
        config = replace(self.config(), initial_capital=111_125)
        result = run_backtest(pd.DataFrame({"IC2612.CFE": [.99]}, index=["2026-09-21"]), market_data=pair_market(), config=config)
        r = result.accounts["portfolio"]
        self.assertEqual(r.positions.iloc[1].tolist(), [4, -800])
        self.assertLessEqual(r.equity.required_margin.iloc[1], .99 * r.equity.equity.iloc[1])

    def test_unchanged_weights_do_not_resize_held_lots(self):
        market = pair_market()
        market.contracts["IC2612.CFE"]["expiry_date"] = "2027-01-15"
        weights = pd.DataFrame({"IC2612.CFE": [.99, .99, .99]}, index=market.close.index)
        result = run_backtest(weights, market_data=market, config=self.config(rebalance_on_change_only=True))
        r = result.accounts["portfolio"]
        self.assertEqual(len(r.actual_orders), 2)
        self.assertEqual(r.positions.iloc[-1].tolist(), [4, -800])
        self.assertEqual(r.summary["processed_instructions"], 1)

    def test_expiring_one_future_releases_only_its_linked_index_units(self):
        market = pair_market()
        market.close["IC2703.CFE"] = 100
        market.contracts["IC2703.CFE"] = dict(expiry_date="2027-03-19")
        config = replace(self.config(), hedges=index_hedges(["IC2612.CFE", "IC2703.CFE"]))
        result = run_backtest(pd.DataFrame({"IC2612.CFE": [.3], "IC2703.CFE": [.3]}, index=["2026-09-21"]), market_data=market, config=config)
        positions = result.accounts["portfolio"].positions
        self.assertTrue(positions.IC_spot.eq(-200 * (positions["IC2612.CFE"] + positions["IC2703.CFE"])).all())
        self.assertEqual(positions["IC2612.CFE"].iloc[-1], 0)
        self.assertGreater(positions["IC2703.CFE"].iloc[-1], 0)

    def test_contract_pairs_have_independent_capital_and_process_results_match(self):
        market = pair_market()
        market.close["IC2703.CFE"] = 100
        market.contracts["IC2703.CFE"] = dict(expiry_date="2027-03-19")
        config = replace(self.config(), mode="contract_pair", workers=1, hedges=index_hedges(["IC2612.CFE", "IC2703.CFE"]))
        targets = pd.DataFrame({"IC2612.CFE": [.99], "IC2703.CFE": [.99]}, index=["2026-09-21"])
        serial = run_backtest(targets, market_data=market, config=config)
        parallel = run_backtest(targets, market_data=market, config=replace(config, workers=2))
        self.assertEqual(set(serial.accounts), {"IC2612.CFE", "IC2703.CFE"})
        for key, account in serial.accounts.items():
            self.assertEqual(abs(account.positions.iloc[1][key]), 4)
            pd.testing.assert_frame_equal(account.equity, parallel.accounts[key].equity)
        pd.testing.assert_frame_equal(serial.actual_orders, parallel.actual_orders)

    def test_pair_waits_for_first_jointly_valid_minute_and_does_not_read_nan_hedge(self):
        with local_temp() as root:
            market = pair_market()
            market.close.index = pd.DatetimeIndex(["2026-09-21 15:00", "2026-09-22 09:31", "2026-09-22 09:32"])
            market.close.iloc[1, 1] = np.nan
            market.close.to_parquet(root / "minute.parquet")
            write_json(root / "reference.json", dict(contracts=[dict(instrument_id=s, **r) for s, r in market.contracts.items()]))
            result = run_backtest(pd.DataFrame({"IC2612.CFE": [.5]}, index=["2026-09-21"]),
                data_config=DataConfig(minute_close_path=root / "minute.parquet", reference_path=root / "reference.json", margin_rates={"IC": .1}), config=self.config())
            self.assertTrue(result.actual_orders.execution_time.eq(pd.Timestamp("2026-09-22 09:32", tz="Asia/Shanghai")).all())
            orders = result.actual_orders
            self.assertEqual(orders.loc[orders.symbol.eq("IC_spot"), "signed_quantity"].iloc[0],
                             -200 * orders.loc[orders.symbol.eq("IC2612.CFE"), "signed_quantity"].iloc[0])

    def test_hedge_weight_and_split_symbol_modes_are_rejected(self):
        with self.assertRaisesRegex(BacktestError, "zero hedge weights"):
            run_backtest(pd.DataFrame({"IC2612.CFE": [.5], "IC_spot": [-.5]}, index=["2026-09-21"]), market_data=pair_market(), config=self.config())
        with self.assertRaisesRegex(BacktestError, "contract_pair"):
            self.config(mode="symbol")
        self.assertEqual(index_hedges(["IF2703.CFE"])[0], HedgeRule("IF2703.CFE", "IF_spot", -300))


if __name__ == "__main__":
    unittest.main()
