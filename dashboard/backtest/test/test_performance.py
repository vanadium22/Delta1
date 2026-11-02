from dataclasses import replace
import os
import threading
import time
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestCancelled, BacktestConfig, BacktestError, DataConfig, MarketData, run_backtest
from dashboard.backtest.data_events import load_event_market_data
from dashboard.backtest.parallel import process_map, worker_cancel_event
from dashboard.backtest.test import test_data as data_fixtures
from dashboard.backtest.test.test_data import local_temp


def slow_task(value):
    for _ in range(30):
        event = worker_cancel_event()
        if event is not None and event.is_set():
            raise BacktestCancelled("cancelled")
        time.sleep(0.01)
    return value


def example_market(*, missing_first=False, crash=False):
    times = pd.to_datetime(["2026-09-21 09:31", "2026-09-21 15:00", "2026-09-22 09:31",
                            "2026-09-22 09:32", "2026-09-22 10:00", "2026-09-22 15:00",
                            "2026-09-23 09:31", "2026-09-23 15:00"])
    prices = [100, 100, 100, 100, 80.0305 if crash else 105, 100 if crash else 120, 125, 130]
    if missing_first:
        prices[2] = np.nan
    close = pd.DataFrame({"IC2612.CFE": prices}, index=times)
    daily = pd.DataFrame({"IC2612.CFE": [100, 100 if crash else 120, 130]},
                         index=pd.to_datetime(["2026-09-21 15:00", "2026-09-22 15:00", "2026-09-23 15:00"]))
    return MarketData(close, {"IC": 10}, {"IC": 0.1}, daily_close=daily)


class PerformanceTests(unittest.TestCase):
    def test_daily_equity_and_last_close_signal_next_first_quote(self):
        targets = pd.DataFrame({"IC2612.CFE": [0.3]}, index=["2026-09-21"])
        market = example_market()
        r = run_backtest(targets, market_data=market, config=BacktestConfig(initial_capital=10_000)).accounts["portfolio"]
        self.assertEqual(len(r.equity), 3)
        self.assertEqual(r.actual_orders.execution_time.iloc[0], pd.Timestamp("2026-09-22 09:31", tz="Asia/Shanghai"))
        self.assertEqual(r.actual_orders.quantity.iloc[0], 30)
        expected = 10_000 + 30 * (130 - 100) * 10 - 30 * 100 * 10 * 0.0003
        self.assertAlmostEqual(r.equity.equity.iloc[-1], expected)
        self.assertTrue((r.equity.index.hour == 15).all())
        self.assertEqual(r.summary["risk_checks"], 3)
        self.assertLess(r.summary["evaluated_events"], r.summary["quote_rows"])

    def test_daily_precision_uses_final_target_and_does_not_enter_early(self):
        targets = pd.DataFrame({"IC2612.CFE": [0.1, 0.3]},
                               index=pd.to_datetime(["2026-09-21 09:31", "2026-09-21 14:59"]))
        result = run_backtest(targets, market_data=example_market(), config=BacktestConfig(initial_capital=10_000))
        account = result.accounts["portfolio"]
        self.assertEqual(len(account.schedule), 1)
        self.assertEqual(account.actual_orders.signal_time.iloc[0], pd.Timestamp("2026-09-21 15:00", tz="Asia/Shanghai"))
        self.assertEqual(account.actual_orders.execution_time.iloc[0].date(), pd.Timestamp("2026-09-22").date())
        self.assertEqual(account.actual_orders.quantity.iloc[0], 30)
        self.assertEqual(len(result.input_instructions), 2)

    def test_auto_preserves_intraday_fills_but_aggregates_daily_fees_and_pnl(self):
        targets = pd.DataFrame({"IC2612.CFE": [0.3, 0]},
                               index=pd.to_datetime(["2026-09-22 09:31", "2026-09-22 09:32"]))
        result = run_backtest(targets, market_data=example_market(), config=BacktestConfig(initial_capital=10_000, precision="auto"))
        r = result.accounts["portfolio"]
        self.assertEqual(result.metadata["precision"]["resolved"], "1m")
        self.assertEqual(r.actual_orders.execution_time.dt.strftime("%H:%M").tolist(), ["09:32", "10:00"])
        self.assertEqual(len(r.equity), 2)
        self.assertAlmostEqual(r.equity.fees.iloc[0], r.actual_orders.fee.sum())
        self.assertAlmostEqual(r.equity.pnl.sum(), r.equity.equity.iloc[-1] - 10_000)

    def test_daily_uses_official_close_for_equity(self):
        market = example_market()
        market.daily_close.iloc[1, 0] = 121
        targets = pd.DataFrame({"IC2612.CFE": [0.3]}, index=["2026-09-21"])
        r = run_backtest(targets, market_data=market, config=BacktestConfig(initial_capital=10_000)).accounts["portfolio"]
        self.assertAlmostEqual(r.equity.equity.iloc[1], 10_000 + 30 * 21 * 10 - 9)

    def test_daily_close_does_not_emit_multiple_rows_for_one_day(self):
        market = example_market()
        extra = market.daily_close.iloc[[0]].copy()
        extra.index += pd.Timedelta(minutes=1)
        market.daily_close = pd.concat([market.daily_close, extra]).sort_index()
        with self.assertRaisesRegex(BacktestError, "one close timestamp"):
            run_backtest(pd.DataFrame({"IC2612.CFE": [.3]}, index=["2026-09-21"]), market_data=market)

    def test_next_day_first_missing_quote_uses_first_valid_quote(self):
        r = run_backtest(pd.DataFrame({"IC2612.CFE": [0.3]}, index=["2026-09-21"]),
                         market_data=example_market(missing_first=True), config=BacktestConfig(initial_capital=10_000))
        self.assertEqual(r.actual_orders.execution_time.iloc[0], pd.Timestamp("2026-09-22 09:32", tz="Asia/Shanghai"))

    def test_daily_close_label_after_1500_still_waits_for_next_day(self):
        close = pd.DataFrame({"IC_spot": [100, 110, 120]},
                             index=pd.to_datetime(["2026-09-18 15:01", "2026-09-21 09:31", "2026-09-21 15:00"]))
        result = run_backtest(pd.DataFrame({"IC_spot": [.3]}, index=["2026-09-18"]), market_data=MarketData(close))
        self.assertEqual(result.actual_orders.execution_time.iloc[0], pd.Timestamp("2026-09-21 09:31", tz="Asia/Shanghai"))

    def test_missing_symbol_daily_close_can_use_actual_same_time_minute_close(self):
        with local_temp() as root:
            market = example_market()
            market.close["IF2703.CFE"] = market.close["IC2612.CFE"] + 1
            market.close.to_parquet(root / "minute.parquet")
            market.daily_close.to_parquet(root / "daily.parquet")
            data = DataConfig(minute_close_path=root / "minute.parquet", daily_close_path=root / "daily.parquet",
                              multipliers={"IC": 10, "IF": 10}, margin_rates={"IC": .1, "IF": .1})
            targets = pd.DataFrame({"IC2612.CFE": [.1], "IF2703.CFE": [.1]}, index=["2026-09-21"])
            result = run_backtest(targets, data_config=data)
            self.assertEqual(result.accounts["portfolio"].summary["status"], "completed")
            self.assertEqual(len(result.actual_orders), 2)

    def test_auto_checks_intraday_crash_and_daily_only_checks_close(self):
        targets = pd.DataFrame({"IC2612.CFE": [0.5]}, index=["2026-09-21"])
        daily = run_backtest(targets, market_data=example_market(crash=True), config=BacktestConfig(initial_capital=10_000))
        auto = run_backtest(targets, market_data=example_market(crash=True), config=BacktestConfig(initial_capital=10_000, precision="auto"))
        self.assertEqual(daily.accounts["portfolio"].summary["status"], "completed")
        account = auto.accounts["portfolio"]
        self.assertEqual(account.summary["status"], "blown_up")
        self.assertEqual(account.actual_orders.execution_time.iloc[-1], pd.Timestamp("2026-09-22 10:00", tz="Asia/Shanghai"))
        self.assertEqual(account.equity.index[-1], pd.Timestamp("2026-09-22 15:00", tz="Asia/Shanghai"))
        self.assertEqual(account.equity.trigger_time.iloc[-1], pd.Timestamp("2026-09-22 10:00", tz="Asia/Shanghai"))
        self.assertEqual(account.positions.iloc[-1, 0], 0)

    def test_minute_absence_falls_back_at_real_daily_close(self):
        with local_temp() as root:
            minute = example_market().close.iloc[:2]
            daily = example_market().daily_close
            minute.to_parquet(root / "minute.parquet")
            daily.to_parquet(root / "daily.parquet")
            data = DataConfig(minute_close_path=root / "minute.parquet", daily_close_path=root / "daily.parquet",
                              multipliers={"IC": 10}, margin_rates={"IC": 0.1})
            result = run_backtest(pd.DataFrame({"IC2612.CFE": [0.3]}, index=["2026-09-21"]), data_config=data,
                                  config=BacktestConfig(initial_capital=10_000))
            self.assertEqual(result.actual_orders.execution_time.iloc[0], pd.Timestamp("2026-09-22 15:00", tz="Asia/Shanghai"))
            self.assertEqual(result.actual_orders.price_source.iloc[0], "daily_fallback")
            self.assertEqual(result.actual_orders.execution_precision.iloc[0], "1d")

    def test_missing_contract_day_keeps_first_minute_on_later_valid_day(self):
        with local_temp() as root:
            market = example_market()
            for frame in (market.close, market.daily_close):
                frame["IC_spot"] = 100
                frame.loc[frame.index.date == pd.Timestamp("2026-09-22").date(), "IC2612.CFE"] = np.nan
            market.close.to_parquet(root / "minute.parquet")
            market.daily_close.to_parquet(root / "daily.parquet")
            data = DataConfig(minute_close_path=root / "minute.parquet", daily_close_path=root / "daily.parquet",
                              multipliers={"IC": 10}, margin_rates={"IC": .1})
            result = run_backtest(pd.DataFrame({"IC2612.CFE": [.3]}, index=["2026-09-21"]), data_config=data)
            self.assertEqual(result.actual_orders.execution_time.iloc[0], pd.Timestamp("2026-09-23 09:31", tz="Asia/Shanghai"))
            self.assertEqual(result.actual_orders.price.iloc[0], 125)

    def test_registered_daily_mode_retains_only_opening_quote_and_daily_closes(self):
        with local_temp() as root:
            store = data_fixtures.DataTests().fixture_store(root / "history")
            rows = []
            for day in ("2026-09-21", "2026-09-22", "2026-09-23"):
                for minute in ("09:31", "09:32", "10:00", "15:00"):
                    stamp = pd.Timestamp(day + " " + minute, tz="Asia/Shanghai").tz_convert("UTC")
                    for symbol in ("IC2612.CFE", "000905.SH"):
                        rows.append(dict(instrument_id=symbol, frequency="1m", event_time=stamp, trade_date=day,
                                         close=100, is_final=True, revision=0, available_at=stamp, recorded_at=stamp, quality_flags=0))
            store.commit(rows)
            data = DataConfig(history_roots=(store.root,), margin_rates={"IC": .1})
            targets = pd.DataFrame({"IC2612.CFE": [.3]}, index=pd.DatetimeIndex(["2026-09-21 15:00"], tz="Asia/Shanghai"))
            market = load_event_market_data(data, targets, BacktestConfig())
            self.assertEqual(market.metadata["load_statistics"]["minute_rows_retained"], 1)
            self.assertEqual(len(market.daily_close), 3)
            self.assertEqual(len(market.close), 4)
            parallel_market = load_event_market_data(data, targets, BacktestConfig(workers=2))
            pd.testing.assert_frame_equal(market.close, parallel_market.close)
            pd.testing.assert_frame_equal(market.daily_close, parallel_market.daily_close)
            self.assertEqual(parallel_market.metadata["load_statistics"]["workers"], 2)
            self.assertTrue(all(pid != os.getpid() for pid in parallel_market.metadata["load_statistics"]["worker_pids"]))
            result = run_backtest(targets, market_data=market)
            self.assertEqual(result.actual_orders.execution_time.iloc[0].strftime("%Y-%m-%d %H:%M"), "2026-09-22 09:31")

    def test_unused_flat_contract_needs_no_price_or_margin(self):
        targets = pd.DataFrame({"IC2612.CFE": [0], "IF2703.CFE": [0]}, index=["2026-09-21"])
        quotes = pd.DataFrame({"IC_spot": [100, 101]}, index=pd.date_range("2026-09-21", periods=2))
        result = run_backtest(targets, market_data=MarketData(quotes), config=BacktestConfig(mode="symbol", workers=1))
        self.assertEqual(len(result.accounts), 2)
        self.assertEqual(len(result.actual_orders), 0)
        self.assertTrue((result.summary.final_equity == 1_000_000).all())

    def test_unused_bad_minute_does_not_block_daily_close_accounting(self):
        market = example_market()
        market.close.iloc[4, 0] = 0
        targets = pd.DataFrame({"IC2612.CFE": [.3]}, index=["2026-09-21"])
        daily = run_backtest(targets, market_data=market, config=BacktestConfig(initial_capital=10_000))
        auto = run_backtest(targets, market_data=market, config=BacktestConfig(initial_capital=10_000, precision="auto"))
        self.assertEqual(daily.accounts["portfolio"].summary["status"], "completed")
        self.assertGreater(auto.accounts["portfolio"].summary["risk_quote_gaps"], 0)
        self.assertTrue(auto.metadata["market_data"]["warnings"])

    def test_process_accounts_match_serial_without_splitting_portfolio_cash(self):
        market = example_market()
        market.close["IF2703.CFE"] = market.close["IC2612.CFE"] + 1
        market.daily_close["IF2703.CFE"] = market.daily_close["IC2612.CFE"] + 1
        market.multiplier = {"IC": 10, "IF": 10}
        market.margin_rate = {"IC": .1, "IF": .1}
        targets = pd.DataFrame({"IC2612.CFE": [.3], "IF2703.CFE": [-.2]}, index=["2026-09-21"])
        for mode in ("symbol", "product"):
            config = BacktestConfig(initial_capital=100_000, mode=mode, workers=1, precision="auto")
            serial = run_backtest(targets, market_data=market, config=config)
            parallel = run_backtest(targets, market_data=market, config=replace(config, workers=2))
            pd.testing.assert_frame_equal(serial.actual_orders, parallel.actual_orders)
            self.assertEqual(parallel.metadata["performance"]["account_processes"]["workers"], 2)
            self.assertTrue(all(pid != os.getpid() for pid in parallel.metadata["performance"]["account_processes"]["worker_pids"]))
            for name in serial.accounts:
                pd.testing.assert_frame_equal(serial.accounts[name].equity, parallel.accounts[name].equity)
                pd.testing.assert_frame_equal(serial.accounts[name].positions, parallel.accounts[name].positions)
        portfolio = run_backtest(targets, market_data=market, config=BacktestConfig(workers=2))
        self.assertEqual(len(portfolio.accounts), 1)
        self.assertEqual(portfolio.metadata["performance"]["account_processes"]["workers"], 1)

    def test_process_cancellation_waits_for_owned_workers(self):
        event = threading.Event()
        timer = threading.Timer(0.1, event.set)
        timer.start()
        try:
            with self.assertRaises(BacktestCancelled):
                process_map(slow_task, [1, 2, 3, 4], workers=2, cancel_event=event)
        finally:
            timer.cancel()


if __name__ == "__main__":
    unittest.main()
