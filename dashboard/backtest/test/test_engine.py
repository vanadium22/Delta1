from datetime import date
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, MarketData, run_backtest


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.date_range("2026-09-21", periods=5, freq="B")

    def market(self, prices=None, **kwargs):
        close = pd.DataFrame({"IC2612.CFE": [100, 110, 120, 130, 140] if prices is None else prices}, index=self.dates)
        return MarketData(close, multiplier={"IC": 10}, margin_rate={"IC": 0.1}, **kwargs)

    def run_case(self, weights, *, market=None, **config):
        return run_backtest(weights, market_data=market or self.market(),
                            config=BacktestConfig(initial_capital=10_000, **config))

    def test_next_close_integer_sizing_and_manual_pnl(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.3, 0]}, index=[self.dates[0], self.dates[2]])
        r = self.run_case(weights).accounts["portfolio"]
        self.assertEqual(r.positions.iloc[:, 0].tolist(), [0, 27, 27, 0, 0])
        self.assertAlmostEqual(r.equity.equity.iloc[-1], 10_000 + 27 * (130 - 110) * 10 - 27 * (110 + 130) * 10 * 0.0003)
        self.assertEqual(r.actual_orders.action.tolist(), ["open_long", "close_long"])
        self.assertTrue((r.actual_orders.execution_time > r.actual_orders.signal_time).all())
        self.assertAlmostEqual(r.equity.equity.iloc[1], 10_000 - 27 * 110 * 10 * 0.0003)

    def test_short_pnl_and_truncation_toward_zero(self):
        weights = pd.DataFrame({"IC2612.CFE": [-0.3]}, index=[self.dates[0]])
        r = self.run_case(weights, margin_call_basis="equity").accounts["portfolio"]
        self.assertEqual(r.positions.iloc[1, 0], -27)
        self.assertAlmostEqual(r.equity.equity.iloc[-1], 10_000 - 27 * (140 - 110) * 10 - 27 * 1100 * 0.0003)

    def test_spot_mapping_cash_and_equity(self):
        market = MarketData(pd.DataFrame({"000905.SH": [100, 110, 120, 130, 140]}, index=self.dates))
        weights = pd.DataFrame({"IC_spot": [0.3, 0]}, index=[date(2026, 9, 21), date(2026, 9, 23)])
        r = self.run_case(weights, market=market).accounts["portfolio"]
        self.assertEqual(r.positions.columns.tolist(), ["IC_spot"])
        self.assertEqual(r.positions.iloc[1, 0], 27)
        self.assertAlmostEqual(r.equity.cash.iloc[1], 10_000 - 27 * 110 * 1.0003)
        self.assertAlmostEqual(r.equity.equity.iloc[-1], 10_000 + 27 * 20 - 27 * 240 * 0.0003)

    def test_literal_weights_not_renormalized_to_full_capital(self):
        r = self.run_case(pd.DataFrame({"IC2612.CFE": [0.3]}, index=[self.dates[0]]), market=self.market([100] * 5))
        account = r.accounts["portfolio"]
        self.assertEqual(account.positions.iloc[1, 0], 30)
        self.assertAlmostEqual(account.equity.required_margin.iloc[1], 3000)

    def test_gross_budget_does_not_net_long_and_short(self):
        close = pd.DataFrame({"IC2612.CFE": [100] * 5, "IC2703.CFE": [100] * 5}, index=self.dates)
        market = MarketData(close, multiplier={"IC": 10}, margin_rate={"IC": 0.1})
        weights = pd.DataFrame({"IC2612.CFE": [0.6], "IC2703.CFE": [-0.6]}, index=[self.dates[0]])
        r = self.run_case(weights, market=market).accounts["portfolio"]
        self.assertEqual(r.positions.iloc[1].tolist(), [49, -49])
        self.assertLessEqual(r.equity.required_margin.iloc[1], r.equity.equity.iloc[1] * 0.99)
        self.assertAlmostEqual(r.target_weights.iloc[0].abs().sum(), 0.99)

    def test_commission_reserve_limits_leveraged_targets(self):
        market = self.market([100] * 5)
        market.margin_rate = {"IC": 0.001}
        r = self.run_case(pd.DataFrame({"IC2612.CFE": [1]}, index=[self.dates[0]]), market=market).accounts["portfolio"]
        self.assertGreater(r.equity.fees.sum(), 0)
        self.assertLessEqual(r.equity.required_margin.iloc[1], r.equity.equity.iloc[1] * 0.99 + 1e-6)
        self.assertEqual(r.summary["status"], "completed")

    def test_reversal_closes_then_opens_and_charges_both(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.2, -0.2]}, index=self.dates[:2])
        r = self.run_case(weights, market=self.market([100] * 5)).accounts["portfolio"]
        self.assertEqual(r.actual_orders.action.tolist(), ["open_long", "close_long", "open_short"])
        self.assertEqual(r.actual_orders.quantity.tolist(), [20, 20, 19])
        self.assertAlmostEqual(r.equity.fees.sum(), 59 * 1000 * 0.0003)

    def test_closes_precede_all_opens_on_reallocation(self):
        market = self.market([100] * 5)
        market.close["IC2703.CFE"] = 100
        weights = pd.DataFrame({"IC2612.CFE": [0, 0.5], "IC2703.CFE": [0.5, 0]}, index=self.dates[:2])
        r = self.run_case(weights, market=market).accounts["portfolio"]
        self.assertEqual(r.actual_orders.iloc[1:].action.tolist(), ["close_long", "open_long"])

    def test_optional_available_equity_margin_call_stops(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.5, 0]}, index=self.dates[:2])
        r = self.run_case(weights, market=self.market([100, 100, 88, 100, 100]),
                          margin_call_basis="available_equity").accounts["portfolio"]
        self.assertEqual(r.summary["status"], "blown_up")
        self.assertEqual(len(r.equity), 3)
        self.assertEqual(r.actual_orders.iloc[-1].reason, "margin_call")
        self.assertEqual(r.positions.iloc[-1, 0], 0)
        self.assertLess(r.equity.trigger_available_equity.iloc[-1], 0)
        self.assertEqual(r.schedule.iloc[-1].status, "stopped_by_margin_call")

    def test_default_uses_total_equity_when_margin_balance_is_negative(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.5]}, index=[self.dates[0]])
        result = self.run_case(weights, market=self.market([100, 100, 88, 100, 100]))
        r = result.accounts["portfolio"]
        self.assertEqual(result.metadata["config"]["margin_call_basis"], "equity")
        self.assertEqual(result.metadata["margin_call"], "equity < required_margin * minimum_margin_ratio")
        self.assertEqual(r.summary["status"], "completed")
        self.assertLess(r.equity.available_equity.iloc[2], 0)
        self.assertGreater(r.equity.equity.iloc[2], r.equity.required_margin.iloc[2] * 0.0001)
        self.assertGreater(r.positions.iloc[-1, 0], 0)

    def test_default_total_equity_threshold_with_small_positive_equity(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.5]}, index=[self.dates[0]])
        # 50 lots at 100, multiplier 10; entry fee 15. At these two closes,
        # total equity is 0.45 / 0.25 while margin * 0.0001 is about 0.40.
        for price, status in ((80.0309, "completed"), (80.0305, "blown_up")):
            with self.subTest(price=price):
                r = self.run_case(weights, market=self.market([100, 100, price, 100, 100])).accounts["portfolio"]
                self.assertEqual(r.summary["status"], status)
                if status == "blown_up":
                    trigger = r.equity.iloc[-1]
                    total_equity = trigger.trigger_margin + trigger.trigger_available_equity
                    self.assertGreater(total_equity, 0)
                    self.assertLess(total_equity, trigger.trigger_margin * 0.0001)
                    self.assertEqual(r.actual_orders.iloc[-1].reason, "margin_call")
                    self.assertEqual(r.positions.iloc[-1, 0], 0)
                    self.assertEqual(len(r.equity), 3)

    def test_optional_balance_threshold_can_trigger_with_positive_balance(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.9]}, index=[self.dates[0]])
        r = self.run_case(weights, market=self.market([100] * 5), minimum_margin_ratio=0.2,
                          margin_call_basis="available_equity").accounts["portfolio"]
        self.assertEqual(r.summary["status"], "blown_up")
        trigger = r.equity.iloc[-1]
        self.assertGreater(trigger.trigger_available_equity, 0)
        self.assertLess(trigger.trigger_available_equity, trigger.trigger_margin * 0.2)

    def test_next_valid_entry_is_delayed_and_missing_held_close_errors(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.2]}, index=[self.dates[0]])
        delayed = self.run_case(weights, market=self.market([100, np.nan, 100, 100, 100])).accounts["portfolio"]
        self.assertEqual(delayed.actual_orders.execution_time.iloc[0].date(), self.dates[2].date())
        self.assertEqual(delayed.positions.iloc[1, 0], 0)
        with self.assertRaisesRegex(BacktestError, "close"):
            self.run_case(weights, market=self.market([100, 100, np.nan, 100, 100]))

    def test_missing_margin_is_explicit(self):
        market = self.market()
        market.margin_rate = {}
        with self.assertRaisesRegex(BacktestError, "margin_rate"):
            self.run_case(pd.DataFrame({"IC2612.CFE": [0.2]}, index=[self.dates[0]]), market=market)

    def test_zero_unused_columns_need_no_margin_or_price(self):
        market = self.market([100] * 5)
        market.close["IF2703.CFE"] = np.nan
        market.multiplier = {"IC": 10}
        weights = pd.DataFrame({"IC2612.CFE": [0.2], "IF2703.CFE": [0]}, index=[self.dates[0]])
        self.assertEqual(self.run_case(weights, market=market).accounts["portfolio"].summary["status"], "completed")

    def test_three_account_modes_and_independent_capital(self):
        market = self.market([100] * 5)
        market.close["IC2703.CFE"] = 100
        market.close["IF2703.CFE"] = 100
        market.multiplier = {"IC": 10, "IF": 10}
        market.margin_rate = {"IC": 0.1, "IF": 0.1}
        weights = pd.DataFrame({"IC2612.CFE": [0.2], "IC2703.CFE": [0.2], "IF2703.CFE": [0.2]}, index=[self.dates[0]])
        for mode, keys in (("symbol", ["IC2612.CFE", "IC2703.CFE", "IF2703.CFE"]),
                           ("product", ["IC", "IF"]), ("portfolio", ["portfolio"])):
            r = self.run_case(weights, market=market, mode=mode)
            self.assertEqual(list(r.accounts), keys)
            self.assertTrue((r.summary.initial_capital == 10_000).all())

    def test_date_only_minute_signal_waits_until_after_day_close(self):
        times = pd.to_datetime(["2026-09-21 09:31", "2026-09-21 15:00", "2026-09-22 09:31", "2026-09-22 09:32"])
        market = MarketData(pd.DataFrame({"IC2612.CFE": [100] * 4}, index=times), {"IC": 10}, {"IC": 0.1})
        weights = pd.DataFrame({"IC2612.CFE": [0.2]}, index=[date(2026, 9, 21)])
        r = self.run_case(weights, market=market).accounts["portfolio"]
        self.assertEqual(r.actual_orders.execution_time.iloc[0], pd.Timestamp("2026-09-22 09:31", tz="Asia/Shanghai"))

    def test_intrabar_signals_latest_before_next_bar_wins(self):
        times = pd.to_datetime(["2026-09-21 09:31", "2026-09-21 09:32", "2026-09-21 09:33"])
        market = MarketData(pd.DataFrame({"IC2612.CFE": [100] * 3}, index=times), {"IC": 10}, {"IC": 0.1})
        weights = pd.DataFrame({"IC2612.CFE": [0.1, 0.2]}, index=pd.to_datetime(["2026-09-21 09:31:10", "2026-09-21 09:31:20"]))
        r = self.run_case(weights, market=market, precision="auto").accounts["portfolio"]
        self.assertEqual(r.schedule.status.tolist(), ["superseded", "executed"])
        self.assertEqual(r.positions.iloc[0, 0], 20)

    def test_terminal_signal_is_reported_and_end_liquidation_is_optional(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.2, 0.3]}, index=[self.dates[0], self.dates[-1]])
        r = self.run_case(weights, market=self.market([100] * 5), liquidate_at_end=True).accounts["portfolio"]
        self.assertEqual(r.schedule.status.tolist(), ["executed", "no_next_bar"])
        self.assertEqual(r.positions.iloc[-1, 0], 0)
        self.assertEqual(r.actual_orders.iloc[-1].reason, "end_of_backtest")

    def test_nan_instructions_need_explicit_policy(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.2, np.nan]}, index=self.dates[:2])
        with self.assertRaisesRegex(BacktestError, "NaN"):
            self.run_case(weights)
        r = self.run_case(weights, nan_policy="zero").accounts["portfolio"]
        self.assertEqual(r.positions.iloc[2, 0], 0)

    def test_effective_margin_change_can_trigger_call(self):
        market = self.market([100] * 5)
        market.margin_rate = pd.DataFrame({"IC2612.CFE": [0.1, 0.9]}, index=[self.dates[0], self.dates[2]])
        weights = pd.DataFrame({"IC2612.CFE": [0.3]}, index=[self.dates[0]])
        r = self.run_case(weights, market=market, minimum_margin_ratio=0.4).accounts["portfolio"]
        self.assertEqual(r.summary["status"], "blown_up")
        self.assertEqual(r.equity.index[-1].date(), self.dates[2].date())

    def test_margin_parameters_never_backfill_from_future(self):
        market = self.market()
        market.margin_rate = pd.DataFrame({"IC2612.CFE": [0.1]}, index=[self.dates[2]])
        with self.assertRaisesRegex(BacktestError, "margin_rate"):
            self.run_case(pd.DataFrame({"IC2612.CFE": [0.2]}, index=[self.dates[0]]), market=market)

    def test_explicit_missing_margin_does_not_restore_an_old_rate(self):
        market = self.market([100] * 5)
        market.margin_rate = pd.DataFrame({"IC2612.CFE": [0.1, np.nan]}, index=[self.dates[0], self.dates[2]])
        with self.assertRaisesRegex(BacktestError, "margin_rate"):
            self.run_case(pd.DataFrame({"IC2612.CFE": [0.2]}, index=[self.dates[0]]), market=market)

    def test_missing_contract_margin_is_not_copied_from_another_column(self):
        market = self.market([100] * 5)
        market.close["IC2703.CFE"] = 100
        market.margin_rate = pd.DataFrame({"IC2612.CFE": [0.1]}, index=[self.dates[0]])
        weights = pd.DataFrame({"IC2612.CFE": [0.1], "IC2703.CFE": [0.1]}, index=[self.dates[0]])
        with self.assertRaisesRegex(BacktestError, "IC2703.CFE"):
            self.run_case(weights, market=market)

    def test_no_guessed_expiry_settlement(self):
        market = self.market([100] * 5)
        market.contracts = {"IC2612.CFE": {"expiry_date": "2026-09-23"}}
        with self.assertRaisesRegex(BacktestError, "after expiry"):
            self.run_case(pd.DataFrame({"IC2612.CFE": [0.2]}, index=[self.dates[0]]), market=market)

    def test_adjusted_price_does_not_become_execution_price(self):
        market = self.market([100] * 5)
        market.adjusted_close = market.close + 1000
        r = self.run_case(pd.DataFrame({"IC2612.CFE": [0.2]}, index=[self.dates[0]]), market=market).accounts["portfolio"]
        self.assertEqual(r.actual_orders.price.iloc[0], 100)
        self.assertAlmostEqual(r.equity.equity.iloc[-1], 10_000 - 20 * 1000 * 0.0003)

    def test_epoch_instructions_are_explicit(self):
        epoch = pd.Timestamp("2026-09-21 15:00", tz="Asia/Shanghai").timestamp()
        weights = pd.DataFrame({"IC2612.CFE": [0.2]}, index=[epoch])
        with self.assertRaisesRegex(BacktestError, "timestamp_unit"):
            self.run_case(weights)
        self.assertEqual(len(self.run_case(weights, timestamp_unit="s").actual_orders), 1)

    def test_date_bounds_exclude_earlier_signals_and_include_last_day(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.3, 0.2]}, index=[self.dates[0], self.dates[2]])
        r = self.run_case(weights, start="2026-09-23", end="2026-09-25").accounts["portfolio"]
        self.assertEqual(len(r.equity), 3)
        self.assertEqual(r.positions.iloc[0, 0], 0)
        self.assertEqual(r.actual_orders.execution_time.iloc[0].date(), date(2026, 9, 24))

    def test_readable_output_paths_and_no_overwrite(self):
        weights = pd.DataFrame({"IC2612.CFE": [0.2]}, index=[self.dates[0]])
        base = Path(__file__).resolve().parents[3] / "local_artifacts/validation" / date.today().isoformat() / "backtest_tests"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base, prefix="engine_") as temp:
            self.assertTrue(Path(temp).resolve().is_relative_to(base.resolve()))
            directory = Path(temp) / "run"
            result = self.run_case(weights)
            paths = result.save(directory)
            actual = pd.read_parquet(paths["actual_orders"])
            self.assertEqual(actual.quantity.tolist(), result.actual_orders.quantity.tolist())
            self.assertTrue(Path(paths["actual_orders_csv"]).is_file())
            with self.assertRaises(FileExistsError):
                result.save(directory)


if __name__ == "__main__":
    unittest.main()
