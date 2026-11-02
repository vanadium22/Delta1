from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, DataConfig, load_result, run_backtest
from dashboard.backtest.io import write_json
from dashboard.backtest.strategy import CTAConfig, FactorConfig, FactorDefinition, StrategyDataConfig, cta_targets, generate_strategy
from dashboard.backtest.strategy.__main__ import main
from dashboard.backtest.strategy.examples import demo_market
from dashboard.backtest.strategy.mapping import is_slot, slot_mapping
from dashboard.backtest.test.test_data import local_temp


def strategy_job(root):
    market, points = demo_market()
    market.close.to_parquet(root / "prices.parquet")
    points.to_parquet(root / "points.parquet")
    write_json(root / "reference.json", dict(contracts=list(market.contracts.values())))
    return dict(data=dict(close_path=str(root / "prices.parquet"), dividend_points_path=str(root / "points.parquet"),
                          reference_path=str(root / "reference.json"), margin_rates={"IC": .15}),
                factors=dict(window_days=3), factor_name="basis_percentile",
                cta=dict(transform="center_percentile"), output_dir=str(root / "strategy"))


class StrategyTests(unittest.TestCase):
    def test_annual_basis_exact_formula_and_concrete_output(self):
        market, points = demo_market()
        result = generate_strategy(market_data=market, dividend_points=points, factor_config=FactorConfig(window_days=3))
        stamp = result.targets.index[3]
        symbol = "IC2603.CFE"
        days = (pd.Timestamp("2026-03-20") - stamp.tz_localize(None).normalize()).days
        expected = 36500 * (market.close.at[stamp, symbol] - 100 + 2) / 100 / days
        self.assertAlmostEqual(result.factors["annual_basis"].at[stamp, symbol], expected)
        self.assertTrue(any(is_slot(c) for c in result.panel.close))
        self.assertFalse(any(is_slot(c) for c in result.targets))
        self.assertFalse(any(is_slot(c) for c in result.factors["basis_percentile"]))

    def test_percentile_follows_current_slot_history_across_contract_roll(self):
        market, points = demo_market()
        config = FactorConfig(window_days=3)
        mapping, _ = slot_mapping(market.close.index, market.contracts, config.roots)
        # IC2603 starts as 02; after January expiry it is 01. Set prior 01
        # observations on different contracts, unlike IC2603's own past.
        day = pd.Timestamp("2026-01-20 15:00", tz="Asia/Shanghai")
        row = market.close.index.get_loc(day)
        for loc, annual in zip(range(row - 3, row + 1), (.2, .3, .4, .35)):
            stamp = market.close.index[loc]
            symbol = mapping.at[stamp, "IC01.CFE"]
            days = (pd.Timestamp(market.contracts[symbol]["expiry_date"]) - stamp.tz_localize(None).normalize()).days
            market.close.at[stamp, symbol] = 100 + annual * 100 * days / 36500 - 2
        result = generate_strategy(market_data=market, dividend_points=points, factor_config=config)
        self.assertEqual(mapping.at[day, "IC01.CFE"], "IC2603.CFE")
        self.assertAlmostEqual(result.factors["basis_percentile"].at[day, "IC2603.CFE"], 2 / 3)
        self.assertTrue(result.factors["basis_percentile"].iloc[:3].isna().all().all())

    def test_prefix_replay_ignores_future_prices_and_current_day_in_statistics(self):
        market, points = demo_market()
        config = FactorConfig(window_days=3)
        full = generate_strategy(market_data=market, dividend_points=points, factor_config=config)
        cutoff = 18
        prefix = replace(market, close=market.close.iloc[:cutoff])
        replay = generate_strategy(market_data=prefix, dividend_points=points, factor_config=config)
        for name in full.factors:
            pd.testing.assert_frame_equal(full.factors[name].iloc[:cutoff].reindex(columns=replay.factors[name].columns), replay.factors[name])
        pd.testing.assert_frame_equal(full.targets.iloc[:cutoff].reindex(columns=replay.targets.columns), replay.targets)

    def test_missing_history_is_not_dropped_to_shorten_window(self):
        market, points = demo_market()
        market.close.iloc[3, market.close.columns.get_loc("IC_spot")] = np.nan
        result = generate_strategy(market_data=market, dividend_points=points, factor_config=FactorConfig(window_days=3))
        self.assertTrue(result.factors["basis_percentile"].iloc[5].isna().all())

    def test_fixed_hysteresis_strict_bounds_reversal_and_direction(self):
        frame = pd.DataFrame({"IC00.CFE": [.8, .5, .2, .199, -.8, -.5, -.2, -.199, .8, -.8]},
                             index=pd.date_range("2026-01-01", periods=10, tz="Asia/Shanghai"))
        targets, _ = cta_targets(frame)
        np.testing.assert_allclose(targets.iloc[:, 0], [.2, .2, .2, 0, -.2, -.2, -.2, 0, .2, -.2])
        reverse, _ = cta_targets(frame, CTAConfig(direction=-1))
        pd.testing.assert_frame_equal(reverse, -targets)

    def test_zscore_uses_previous_days_only_and_constant_window_is_missing(self):
        index = pd.date_range("2026-01-01", periods=6, tz="Asia/Shanghai")
        factor = pd.DataFrame({"IC00.CFE": [0, 1, 2, 3, 4, 5]}, index=index)
        targets, scores = cta_targets(factor, CTAConfig(mode="zscore", lookback_window=3))
        self.assertTrue(scores.iloc[:3].isna().all().all())
        self.assertAlmostEqual(scores.iloc[3, 0], 2 / np.sqrt(2 / 3))
        self.assertEqual(targets.iloc[3, 0], .2)
        _, constant = cta_targets(factor * 0, CTAConfig(mode="zscore", lookback_window=3))
        self.assertTrue(constant.isna().all().all())

    def test_dated_dividend_revisions_do_not_rewrite_history(self):
        from dashboard.marketdata.overview_dividends import DatedDividendBook
        market, _ = demo_market()
        records = [dict(contract_id=s, points=2, effective_from="2026-01-01T00:00:00+08:00", revision=s,
                        source_business_date="2026-01-01") for s in market.contracts]
        records.append(dict(contract_id="IC2603.CFE", points=5, effective_from="2026-01-20T15:00:00+08:00",
                            revision="new", source_business_date="2026-01-20"))
        book = DatedDividendBook(records, market.contracts)
        result = generate_strategy(market_data=market, dividend_book=book, factor_config=FactorConfig(window_days=3))
        for day, expected in (("2026-01-19", 2), ("2026-01-20", 5)):
            stamp = pd.Timestamp(day + " 15:00", tz="Asia/Shanghai")
            alias = result.panel.mapping.loc[stamp].eq("IC2603.CFE").idxmax()
            self.assertEqual(result.panel.dividend_points.at[stamp, alias], expected)
        self.assertEqual(result.panel.dividend_revisions.loc[pd.Timestamp("2026-01-20 15:00", tz="Asia/Shanghai"), "IC01.CFE"], "new")

    def test_custom_factor_requires_declared_data_and_parameters(self):
        market, points = demo_market()
        custom = FactorDefinition("example_spread", ("close", "spot"), ("scale",), lambda p, k: (p.close - p.spot) * k["scale"])
        with self.assertRaisesRegex(BacktestError, "missing declared"):
            generate_strategy(market_data=market, dividend_points=points, factor_definitions=[custom])
        result = generate_strategy(market_data=market, dividend_points=points, factor_name=custom.name,
                                   factor_definitions=[custom], factor_parameters={custom.name: dict(scale=2)})
        self.assertIn(custom.name, result.factors)
        provided = generate_strategy(data_loader=lambda _: market, factor_name=custom.name, include_examples=False,
                                      factor_definitions=[custom], factor_parameters={custom.name: dict(scale=2)})
        self.assertEqual(list(provided.factors), [custom.name])

    def test_intraday_zscore_ignores_later_close_on_current_day(self):
        index = pd.DatetimeIndex(["2026-01-05 15:00", "2026-01-06 15:00", "2026-01-07 15:00",
                                  "2026-01-08 09:31", "2026-01-08 15:00"], tz="Asia/Shanghai")
        factor = pd.DataFrame({"IC00.CFE": [0, 1, 2, 3, 999]}, index=index)
        _, scores = cta_targets(factor, CTAConfig(mode="zscore", lookback_window=3))
        _, replay = cta_targets(factor.iloc[:4], CTAConfig(mode="zscore", lookback_window=3))
        pd.testing.assert_frame_equal(scores.iloc[:4], replay)
        self.assertAlmostEqual(scores.iloc[3, 0], 2 / np.sqrt(2 / 3))

    def test_continuous_backtest_input_becomes_actual_orders_and_snapshot(self):
        market, _ = demo_market()
        inputs = pd.DataFrame({"IC01.CFE": .2}, index=market.close.index)
        with local_temp() as root:
            result = run_backtest(inputs, market_data=market, config=BacktestConfig(initial_capital=1_000_000), output_dir=root / "run")
            loaded = load_result(root / "run")
            self.assertFalse(any(is_slot(s) for s in result.actual_orders.symbol))
            self.assertTrue({"IC2602.CFE", "IC2603.CFE"} <= set(result.actual_orders.symbol))
            self.assertEqual(result.input_instructions.columns.tolist(), ["IC01.CFE"])
            pd.testing.assert_frame_equal(result.execution_instructions, loaded.execution_instructions, check_freq=False)

    def test_config_cli_and_exported_targets_can_be_backtested(self):
        with local_temp() as root:
            job = strategy_job(root)
            job["data"] = {k: str(v).removeprefix(str(root) + "\\") if isinstance(v, str) else v for k, v in job["data"].items()}
            job["output_dir"] = "strategy"
            write_json(root / "strategy.local.json", job)
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["--config", str(root / "strategy.local.json")]), 0)
            targets = pd.read_parquet(root / "strategy/targets.parquet")
            market, _ = demo_market()
            result = run_backtest(targets, market_data=market)
            self.assertGreater(len(result.actual_orders), 0)

    def test_registered_factor_reader_processes_match_memory_inputs(self):
        from dashboard.marketdata.bars import BarDataset
        market, points = demo_market()
        with local_temp() as root:
            instruments = {s: dict(asset_type="cn_index_future", market_region="CN") for s in market.contracts}
            instruments["000905.SH"] = dict(asset_type="cn_index", market_region="CN")
            store = BarDataset.create(root / "history", dict(dataset_id="strategy_fixture", source_id="unit_test",
                series_kind="concrete", price_adjustment="none", volume_unit="unused", availability_policy="verified", instruments=instruments))
            rows = []
            for stamp, row in market.close.iterrows():
                for symbol, value in row.dropna().items():
                    utc = stamp.tz_convert("UTC")
                    rows.append(dict(instrument_id="000905.SH" if symbol == "IC_spot" else symbol, frequency="1d",
                                     event_time=utc, trade_date=str(stamp.date()), close=value, is_final=True,
                                     revision=0, available_at=utc, recorded_at=utc, quality_flags=0))
            store.commit(rows)
            write_json(root / "reference.json", dict(contracts=list(market.contracts.values())))
            points.to_parquet(root / "points.parquet")
            config = FactorConfig(window_days=3, workers=2)
            memory = generate_strategy(market_data=market, dividend_points=points, factor_config=config)
            loaded = generate_strategy(data_config=DataConfig(history_roots=(store.root,), reference_path=root / "reference.json",
                                       dividend_points_path=root / "points.parquet"), factor_config=config)
            pd.testing.assert_frame_equal(memory.targets, loaded.targets, check_freq=False)
            for name in memory.factors:
                pd.testing.assert_frame_equal(memory.factors[name], loaded.factors[name], check_freq=False)
            self.assertEqual(loaded.market_data.metadata["load_statistics"]["workers"], 2)
            self.assertEqual(loaded.market_data.metadata["load_statistics"]["minute_rows_read"], 0)

    def test_no_missing_dividend_zero_assumption_and_no_z_dependency(self):
        market, _ = demo_market()
        with self.assertRaisesRegex(BacktestError, "requires dated dividends"):
            generate_strategy(market_data=market)
        with self.assertRaisesRegex(BacktestError, "Z-drive"):
            DataConfig(close_path="Z:/internal/prices.parquet")
        with self.assertRaisesRegex(BacktestError, "Z-drive"):
            StrategyDataConfig(dividend_store_root="z:/internal/dividends")
        short, points = demo_market(periods=3)
        result = generate_strategy(market_data=short, dividend_points=points)
        self.assertEqual(result.metadata["quality"]["basis_percentile"]["valid_cells"], 0)
        self.assertTrue(result.metadata["warnings"])


if __name__ == "__main__":
    unittest.main()
