from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, DataConfig, MarketData, load_market_data, run_backtest
from dashboard.backtest.__main__ import load_job
from dashboard.backtest.configuration import CTASpec, FactorSpec, cta_spec, describe_functions
from dashboard.backtest.data import _wide, parameter_frame, resolve_paths
from dashboard.backtest.strategy import CTAResult, load_cta, load_factors
from dashboard.backtest.synthetic import write_inputs
from dashboard.backtest.test.test_data import local_temp
from dashboard.backtest.test.test_hedging import pair_market
from dashboard.backtest.workflow import backtest_stage, cta_stage, factor_stage


class WorkflowTests(unittest.TestCase):
    def test_data_relocation_requires_only_config_root_change(self):
        with local_temp() as root:
            left, right = write_inputs(root / "a"), write_inputs(root / "b")
            job = load_job(left / "index_09.local.json")
            # The API also accepts the original relative declarations unchanged.
            import json
            raw = json.loads((left / "index_09.local.json").read_text(encoding="utf-8"))
            raw["data"]["data_root"] = str(left)
            first = factor_stage(raw)
            first_run = backtest_stage(cta_stage(first, raw), raw)
            raw["data"]["data_root"] = str(right)
            second = factor_stage(raw)
            second_run = backtest_stage(cta_stage(second, raw), raw)
            for name in first.factors:
                pd.testing.assert_frame_equal(first.factors[name], second.factors[name])
            pd.testing.assert_frame_equal(first_run.actual_orders, second_run.actual_orders)
            self.assertNotEqual(first.metadata["market"]["files"], second.metadata["market"]["files"])
            self.assertTrue(job["data"]["reference_path"].startswith(str(left)))
            self.assertTrue(first.metadata["market"]["coverage"])
            self.assertTrue(all(v["path"].startswith(str(left)) for v in first.metadata["market"]["files"].values()))

    def test_saved_factor_reuse_two_thresholds_and_z_without_any_recomputation(self):
        with local_temp() as root:
            data = write_inputs(root / "inputs")
            job = load_job(data / "index_09.local.json")
            factor = factor_stage(job, output_dir=root / "factor")
            before = {k: v.copy(deep=True) for k, v in factor.continuous_factors.items()}
            self.assertNotIn("cta", factor.metadata)
            with patch("dashboard.backtest.workflow.compute_factors", side_effect=AssertionError("recomputed")), \
                 patch("dashboard.backtest.strategy.pipeline._load_market", side_effect=AssertionError("read market")):
                a = cta_stage(factor, job, output_dir=root / "cta09")
                b = cta_stage(root / "factor", load_job(data / "index_08.local.json"))
                reload = cta_stage(load_factors(root / "factor"), job)
                zjob = {**job, "cta": dict(name="zscore", input_factor="basis_percentile", parameters=dict(lookback_window=3))}
                z = cta_stage(factor, zjob)
            pd.testing.assert_frame_equal(a.targets, reload.targets, check_freq=False)
            pd.testing.assert_frame_equal(a.targets, load_cta(root / "cta09").targets, check_freq=False)
            self.assertEqual(a.metadata["factor_fingerprint"], b.metadata["factor_fingerprint"])
            self.assertEqual(a.metadata["factor_fingerprint"], z.metadata["factor_fingerprint"])
            for name, frame in before.items():
                pd.testing.assert_frame_equal(frame, factor.continuous_factors[name], check_exact=True)
            self.assertTrue(np.allclose(a.targets.sum(axis=1), 0))

    def test_stage_artifacts_are_portable_and_tampering_is_rejected(self):
        with local_temp() as root:
            data = write_inputs(root / "inputs")
            factor = factor_stage(load_job(data / "index_09.local.json"), output_dir=root / "factor")
            path = root / "factor/continuous/basis_percentile.parquet"
            frame = pd.read_parquet(path)
            frame.iloc[-1, 0] = .123
            frame.to_parquet(path)
            with self.assertRaisesRegex(BacktestError, "hash mismatch"):
                load_factors(root / "factor")
            with self.assertRaises(FileExistsError):
                factor.save(root / "factor")

    def test_each_function_rejects_parameters_from_another_stage(self):
        for name in ("annual_basis", "basis_percentile"):
            with self.assertRaisesRegex(BacktestError, "unexpected parameters"):
                FactorSpec(name=name, parameters=dict(direction=-1))
        with self.assertRaisesRegex(BacktestError, "unexpected parameters"):
            CTASpec(parameters=dict(window_days=60))
        with self.assertRaisesRegex(BacktestError, "unexpected parameters"):
            CTASpec(name="fixed", parameters=dict(z_open=2))
        with self.assertRaises(BacktestError):
            FactorSpec(parameters=dict(window_days=3.5))
        self.assertEqual(describe_functions()["factor"]["basis_percentile"]["parameters"]["window_days"]["default"], 60)
        self.assertEqual(cta_spec(dict(factor=dict(name="basis_percentile"))).parameters["transform"], "identity")

    def test_conflicting_data_paths_and_missing_explicit_source_fail(self):
        with self.assertRaisesRegex(BacktestError, "Ambiguous"):
            DataConfig(close_path="close.parquet", daily_close_path="daily.parquet")
        with self.assertRaisesRegex(BacktestError, "Conflicting price sources"):
            DataConfig(history_roots=("dataset",), close_path="close.parquet")
        with self.assertRaisesRegex(BacktestError, "distinct paths"):
            DataConfig(minute_close_path="same.parquet", daily_close_path="same.parquet")
        with self.assertRaisesRegex(BacktestError, "margin"):
            DataConfig(margin_rates={"IC": 1}, margin_rate_path="margin.parquet")
        with self.assertRaisesRegex(BacktestError, "implicit native discovery is disabled"):
            resolve_paths(DataConfig())
        with self.assertRaisesRegex(BacktestError, "Z-derived"):
            DataConfig(source_id="local_ddb_plus_readonly_z_v1")
        with self.assertRaisesRegex(BacktestError, "dated dividend book"):
            DataConfig(dividend_points_path="d.parquet", dividend_records_path="d.json")

    def test_aware_daily_dates_and_minute_midnight_have_explicit_different_labels(self):
        with local_temp() as root:
            path = root / "close.parquet"
            pd.DataFrame({"000905.SH": [100]}, index=pd.DatetimeIndex(["2026-01-05"], tz="Asia/Shanghai")).to_parquet(path)
            config = DataConfig(daily_close_path=path)
            daily = _wide(path, config, label="daily close", timezone="Asia/Shanghai")
            minute = _wide(path, config, label="minute close", timezone="Asia/Shanghai", date_at=None)
            self.assertEqual(daily.index[0].hour, 15)
            self.assertEqual(minute.index[0].hour, 0)
            self.assertEqual(daily.columns.tolist(), ["IC_spot"])

    def test_parameters_only_apply_after_effective_time_and_explicit_missing_persists(self):
        close = pd.DataFrame({"IC2612.CFE": 100.}, index=pd.date_range("2026-01-05", periods=4, tz="Asia/Shanghai"))
        source = pd.DataFrame({"IC2612.CFE": [.1, np.nan]}, index=close.index[[1, 2]])
        result = parameter_frame(source, close, kind="margin")
        self.assertTrue(np.isnan(result.iloc[0, 0]))
        self.assertEqual(result.iloc[1, 0], .1)
        self.assertTrue(result.iloc[2:, 0].isna().all())

    def test_explicit_dividend_ignore_and_required_missing(self):
        with local_temp() as root:
            data = write_inputs(root / "input")
            job = load_job(data / "index_09.local.json")
            factor = factor_stage(job)
            self.assertEqual(factor.metadata["dividend_mode"], "ignore")
            self.assertTrue(factor.panel.dividend_points.eq(0).all().all())
            job["data"]["dividend_mode"] = "required"
            with self.assertRaisesRegex(BacktestError, "requires dated dividends"):
                factor_stage(job)
            with self.assertRaisesRegex(BacktestError, "conflicts"):
                DataConfig(dividend_mode="ignore", dividend_points_path="d.parquet")

    def test_registered_versions_are_pinned_without_scanning_orphans(self):
        from dashboard.backtest.test.test_data import DataTests
        from dashboard.backtest.test.fixtures import write_reference
        from dashboard.backtest.io import write_json
        with local_temp() as root:
            store = DataTests().fixture_store(root / "history")
            version = store.snapshot()["version"]
            config = DataConfig(history_roots=(store.root,), history_versions={str(store.root): version})
            result = load_market_data(config)
            self.assertEqual(result.metadata["datasets"][0]["version"], version)
            self.assertEqual(result.metadata["paths"]["history_versions"][str(store.root)], version)
            ref = write_reference(root)
            write_json(root / "native.json", dict(history_roots=[str(store.root)], reference_file=str(ref)))
            legacy = load_market_data(DataConfig(dashboard_config_path=root / "native.json"))
            self.assertEqual(legacy.metadata["files"]["reference_path"]["path"], str(ref))
            self.assertEqual(len(legacy.metadata["files"]["reference_path"]["sha256"]), 64)

    def test_neutral_index_weights_exact_integer_exposure_and_100_percent_margin(self):
        market = replace(pair_market(), margin_rate={"IC": 1})
        weights = pd.DataFrame({"IC2612.CFE": [.495], "IC_spot": [-.495]}, index=["2026-09-21"])
        original = weights.copy(deep=True)
        result = run_backtest(weights, market_data=market, config=BacktestConfig(initial_capital=100_000, weight_mode="neutral_units"))
        account = result.accounts["portfolio"]
        self.assertEqual(account.positions.iloc[1].tolist(), [2, -400])
        self.assertAlmostEqual(account.equity.required_margin.iloc[1], 80_000)
        self.assertAlmostEqual(account.equity.equity.iloc[-1], 100_351.4)
        self.assertTrue((account.positions["IC2612.CFE"] * 200 + account.positions.IC_spot).eq(0).all())
        self.assertTrue(np.allclose(account.target_weights.sum(axis=1), 0))
        pd.testing.assert_frame_equal(weights, original)
        short = run_backtest(-weights, market_data=market,
                             config=BacktestConfig(initial_capital=100_000, weight_mode="neutral_units")).accounts["portfolio"]
        self.assertEqual(short.positions.iloc[1].tolist(), [-2, 400])
        self.assertAlmostEqual(short.equity.equity.iloc[-1], 99_551.4)
        with self.assertRaisesRegex(BacktestError, "zero summed"):
            run_backtest(weights.assign(IC_spot=-.4), market_data=market,
                         config=BacktestConfig(weight_mode="neutral_units"))

    def test_neutral_calendar_spread_closes_both_on_first_expiry(self):
        close = pd.DataFrame({"IC2601.CFE": [100, 100, 103], "IC2603.CFE": [101, 101, 102]},
                             index=pd.date_range("2026-01-05", periods=3))
        market = MarketData(close, margin_rate={"IC": 1}, contracts={
            "IC2601.CFE": dict(expiry_date="2026-01-07"), "IC2603.CFE": dict(expiry_date="2026-03-20")})
        targets = pd.DataFrame({"IC2601.CFE": [.495], "IC2603.CFE": [-.495]}, index=["2026-01-05"])
        result = run_backtest(targets, market_data=market, config=BacktestConfig(initial_capital=100_000, weight_mode="neutral_units"))
        account = result.accounts["portfolio"]
        self.assertEqual(account.positions.iloc[1].tolist(), [2, -2])
        self.assertEqual(account.positions.iloc[-1].tolist(), [0, 0])
        self.assertEqual(account.actual_orders.reason.tolist(), ["target_rebalance"] * 2 + ["expiry_d0"] * 2)
        self.assertTrue(account.positions.sum(axis=1).eq(0).all())
        reverse = run_backtest(-targets, market_data=market,
                               config=BacktestConfig(initial_capital=100_000, weight_mode="neutral_units")).accounts["portfolio"]
        self.assertEqual(reverse.positions.iloc[-1].tolist(), [0, 0])
        self.assertEqual(set(reverse.actual_orders.query("reason == 'expiry_d0'").symbol), set(targets.columns))

    def test_price_basis_and_spread_examples_execute_from_saved_stages(self):
        with local_temp() as root:
            data = write_inputs(root / "inputs")
            for filename in ("close.local.json", "price_basis.local.json", "spread.local.json"):
                job = load_job(data / filename)
                factor = factor_stage(job, output_dir=root / filename / "factor")
                signals = cta_stage(factor, job, output_dir=root / filename / "cta")
                result = backtest_stage(root / filename / "cta", job)
                self.assertGreater(len(result.actual_orders), 0)
                self.assertTrue(np.allclose(signals.targets.sum(axis=1), 0))
                for account in result.accounts.values():
                    position = account.positions
                    equivalents = sum(position[s] * (1 if s.endswith("_spot") else 200 if s[:2] in {"IC", "IM"} else 300) for s in position)
                    self.assertTrue(equivalents.eq(0).all())
            self.assertNotIn("direction", factor.metadata["factor_config"])

    def test_neutral_expiry_serial_and_process_accounts_match(self):
        with local_temp() as root:
            data = write_inputs(root / "inputs")
            job = load_job(data / "index_09.local.json")
            signals = cta_stage(factor_stage(job), job)
            serial = backtest_stage(signals, job)
            parallel_job = {**job, "backtest": {**job["backtest"], "workers": 2}}
            parallel = backtest_stage(signals, parallel_job)
            for name, account in serial.accounts.items():
                pd.testing.assert_frame_equal(account.equity, parallel.accounts[name].equity)
                pd.testing.assert_frame_equal(account.positions, parallel.accounts[name].positions)
            pd.testing.assert_frame_equal(serial.actual_orders, parallel.actual_orders)

    def test_changed_wide_file_is_rejected_before_results_are_saved(self):
        with local_temp() as root:
            data = write_inputs(root / "input")
            job = load_job(data / "index_09.local.json")
            signals = cta_stage(factor_stage(job), job)
            path = data / "daily_close.parquet"
            prices = pd.read_parquet(path)
            prices.iloc[0, 0] += .001
            prices.to_parquet(path)
            with self.assertRaisesRegex(BacktestError, "changed since factor"):
                backtest_stage(signals, job, output_dir=root / "rejected")
            self.assertFalse((root / "rejected").exists())

    def test_execution_reuses_frozen_registered_version_after_current_advances(self):
        from dashboard.backtest.test.test_data import DataTests
        from dashboard.backtest.test.fixtures import write_reference
        with local_temp() as root:
            store = DataTests().fixture_store(root / "history")
            version = store.snapshot()["version"]
            stamp = pd.Timestamp("2026-09-22 15:00", tz="Asia/Shanghai").tz_convert("UTC")
            store.commit([dict(instrument_id="IC2612.CFE", frequency="1d", event_time=stamp, trade_date="2026-09-22",
                               close=200., is_final=True, revision=1, available_at=stamp, recorded_at=stamp, quality_flags=0)])
            self.assertNotEqual(version, store.snapshot()["version"])
            weights = pd.DataFrame({"IC2612.CFE": [.2]}, index=["2026-09-21"])
            signals = CTAResult(weights, weights, dict(data_context=dict(datasets=[dict(root=str(store.root), version=version)])))
            job = dict(data=dict(history_roots=[str(store.root)], reference_path=str(write_reference(root)), margin_rates={"IC": .1}),
                       backtest=dict(initial_capital=10_000))
            result = backtest_stage(signals, job)
            self.assertEqual(result.metadata["market_data"]["datasets"][0]["version"], version)
            self.assertTrue(result.actual_orders.price.eq(101).all())

    def test_neutral_independent_contract_accounts_derive_hedges_and_preserve_lots(self):
        with local_temp() as root:
            data = write_inputs(root / "input")
            job = load_job(data / "index_09.local.json")
            job["cta"]["parameters"]["selection"] = "contract_independent"
            job["backtest"]["mode"] = "contract_pair"
            signals = cta_stage(factor_stage(job), job)
            result = backtest_stage(signals, job)
            self.assertEqual(set(result.accounts), {s for s in signals.targets if s.endswith(".CFE")})
            for name, account in result.accounts.items():
                multiple = 200 if name[:2] in {"IC", "IM"} else 300
                self.assertTrue((account.positions[name] * multiple + account.positions[name[:2] + "_spot"]).eq(0).all())
                opened = account.actual_orders.loc[account.actual_orders.symbol.eq(name) & account.actual_orders.action.str.startswith("open")]
                self.assertLessEqual(len(opened), 1)
            self.assertGreater(len(result.actual_orders), 0)

    def test_factor_does_not_read_execution_only_margin_or_multiplier_files(self):
        with local_temp() as root:
            data = write_inputs(root / "input")
            job = load_job(data / "index_09.local.json")
            job["data"].update(margin_rate_path=str(root / "not_yet_supplied_margin.parquet"), margin_rates={},
                               multiplier_path=str(root / "not_yet_supplied_multipliers.parquet"))
            factors = factor_stage(job)
            self.assertGreater(factors.metadata["quality"]["basis_percentile"]["valid_cells"], 0)
            self.assertNotIn("margin_rate_path", factors.metadata["market"]["files"])
            self.assertNotIn("multiplier_path", factors.metadata["market"]["files"])
            with self.assertRaisesRegex(BacktestError, "Input does not exist"):
                backtest_stage(cta_stage(factors, job), job)

    def test_spread_holds_original_actual_pair_across_slot_changes(self):
        with local_temp() as root:
            data = write_inputs(root / "input")
            job = load_job(data / "spread.local.json")
            factor = factor_stage(job)
            signals = cta_stage(factor, job)
            result = backtest_stage(signals, job)
            openings = signals.decisions.loc[signals.decisions.action.eq("signal_open") & signals.decisions.root.eq("IC")]
            first = openings.iloc[0]
            self.assertLess(str(first.timestamp.date()), "2026-01-16")
            self.assertEqual((first.primary, first.hedge), ("IC2602.CFE", "IC2606.CFE"))
            day = pd.Timestamp("2026-01-20 15:00", tz="Asia/Shanghai")
            self.assertNotEqual(factor.panel.mapping.at[day, "IC01.CFE"], first.primary)
            self.assertNotEqual(factor.panel.mapping.at[day, "IC03.CFE"], first.hedge)
            held = result.accounts["IC"].positions.loc[day]
            self.assertNotEqual(held[first.primary], 0)
            self.assertEqual(held[first.primary], -held[first.hedge])
            closes = result.accounts["IC"].actual_orders.query("reason == 'expiry_d0'")
            self.assertEqual(set(closes.symbol), {first.primary, first.hedge})

    def test_multiple_daily_observations_are_rejected_in_both_adapters(self):
        with local_temp() as root:
            data = write_inputs(root / "input")
            job = load_job(data / "index_09.local.json")
            frame = pd.read_parquet(data / "daily_close.parquet")
            extra = frame.iloc[:1].copy()
            extra.index += pd.Timedelta(minutes=1)
            pd.concat([frame, extra]).to_parquet(data / "daily_close.parquet")
            with self.assertRaisesRegex(BacktestError, "at most one"):
                factor_stage(job)
            with self.assertRaisesRegex(BacktestError, "at most one"):
                load_market_data(DataConfig(**job["data"]))

    def test_mixed_timezones_convert_to_shanghai_and_duplicate_instants_are_rejected(self):
        from dashboard.backtest.models import normalize_frame
        frame = pd.DataFrame({"IC_spot": [100., 101., 102.]}, index=[
            "2026-01-05 15:00:00", "2026-01-06T07:00:00Z", "2026-01-07T15:00:00+08:00"])
        normalized = normalize_frame(frame)
        self.assertEqual(str(normalized.index.tz), "Asia/Shanghai")
        self.assertTrue((normalized.index.hour == 15).all())
        duplicate = frame.iloc[:2].copy()
        duplicate.index = ["2026-01-05T07:00:00Z", "2026-01-05T15:00:00+08:00"]
        with self.assertRaisesRegex(BacktestError, "duplicate timestamps"):
            normalize_frame(duplicate)


if __name__ == "__main__":
    unittest.main()
