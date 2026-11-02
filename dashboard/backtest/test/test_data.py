from contextlib import contextmanager
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, DataConfig, audit_data, load_market_data, run_backtest
from dashboard.backtest.__main__ import load_job, main
from dashboard.backtest.io import write_json
from dashboard.marketdata.bars import BarDataset


@contextmanager
def local_temp():
    base = Path(__file__).resolve().parents[3] / "local_artifacts/validation" / date.today().isoformat() / "backtest_tests"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base, prefix="data_") as temp:
        root = Path(temp).resolve()
        if not root.is_relative_to(base.resolve()):
            raise RuntimeError("Test directory escaped the workspace output directory")
        yield root


class DataTests(unittest.TestCase):
    def fixture_store(self, root, *, available=True):
        symbols = {"IC2612.CFE": {"asset_type": "cn_index_future", "market_region": "CN"},
                   "000905.SH": {"asset_type": "cn_index", "market_region": "CN"}}
        store = BarDataset.create(root, dict(dataset_id="isolated_backtest_fixture", source_id="unit_test",
                                            series_kind="concrete", price_adjustment="none", volume_unit="not_used",
                                            availability_policy="verified" if available else "unknown", instruments=symbols))
        rows = []
        for day, price in (("2026-09-21", 100), ("2026-09-22", 101), ("2026-09-23", 102)):
            stamp = pd.Timestamp(day + " 15:00", tz="Asia/Shanghai").tz_convert("UTC")
            for symbol in symbols:
                rows.append(dict(instrument_id=symbol, frequency="1d", event_time=stamp,
                                 trade_date=day, close=price, is_final=True, revision=0,
                                 available_at=stamp if available else None, recorded_at=stamp, quality_flags=0))
        store.commit(rows)
        return store

    def test_registered_adapter_mapping_version_and_orphan_exclusion(self):
        with local_temp() as root:
            store = self.fixture_store(root / "history")
            pd.DataFrame({"bad": [99999]}).to_parquet(root / "history/orphan.parquet")
            config = DataConfig(history_roots=(store.root,), margin_rates={"IC": 0.12})
            market = load_market_data(config, symbols=["IC2612.CFE"])
            self.assertEqual(set(market.close.columns), {"IC2612.CFE", "IC_spot"})
            self.assertEqual(market.close["IC2612.CFE"].tolist(), [100, 101, 102])
            self.assertEqual(market.metadata["datasets"][0]["version"], store.snapshot()["version"])
            report = audit_data(config)
            self.assertEqual(len(report["coverage"]), 2)

    def test_unknown_availability_requires_explicit_research_opt_in(self):
        with local_temp() as root:
            store = self.fixture_store(root / "history", available=False)
            with self.assertRaisesRegex(BacktestError, "allow_unverified_availability"):
                load_market_data(DataConfig(history_roots=(store.root,)))
            market = load_market_data(DataConfig(history_roots=(store.root,), allow_unverified_availability=True))
            self.assertEqual(len(market.close), 3)
            self.assertTrue(any("PIT" in w for w in market.metadata["warnings"]))

    def test_conflicting_sources_are_not_silently_merged(self):
        with local_temp() as root:
            first = self.fixture_store(root / "first")
            second = self.fixture_store(root / "second")
            with self.assertRaisesRegex(BacktestError, "duplicate bars"):
                load_market_data(DataConfig(history_roots=(first.root, second.root)))

    def test_wide_csv_inputs_and_custom_instruction_reader(self):
        with local_temp() as root:
            prices = pd.DataFrame({"date": ["2026-09-21", "2026-09-22", "2026-09-23"],
                                   "IC2612.CFE": [100, 110, 120], "000905.SH": [100, 110, 120]})
            prices.to_csv(root / "close.csv", index=False)
            instructions = pd.DataFrame({"date": ["2026-09-21"], "IC2612.CFE": [0.2], "IC_spot": [0.2]})
            instructions.to_csv(root / "signals.csv", index=False)
            result = run_backtest(instructions_path=root / "signals.csv",
                                  instruction_loader=lambda path: pd.read_csv(path).set_index("date"),
                                  data_config=DataConfig(close_path=root / "close.csv", multipliers={"IC": 10}, margin_rates={"IC": 0.1}),
                                  config=BacktestConfig(initial_capital=10_000), output_dir=root / "run")
            self.assertEqual(len(result.actual_orders), 2)
            self.assertTrue(Path(result.output_paths["actual_orders"]).is_file())

    def test_daily_dividend_points_map_to_same_day_minutes_only(self):
        with local_temp() as root:
            times = pd.to_datetime(["2026-09-21 09:31", "2026-09-21 09:32", "2026-09-22 09:31"])
            pd.DataFrame({"IC2612.CFE": [100, 101, 102]}, index=times).to_parquet(root / "close.parquet")
            pd.DataFrame({"IC2612.CFE": [5]}, index=["2026-09-21"]).to_parquet(root / "dividend.parquet")
            market = load_market_data(DataConfig(close_path=root / "close.parquet", dividend_points_path=root / "dividend.parquet"))
            self.assertEqual(market.adjusted_close.iloc[:2, 0].tolist(), [105, 106])
            self.assertTrue(np.isnan(market.adjusted_close.iloc[2, 0]))

    def test_job_paths_are_relative_to_config_and_cli_runs(self):
        with local_temp() as root:
            prices = pd.DataFrame({"IC2612.CFE": [100, 110, 120]}, index=pd.date_range("2026-09-21", periods=3))
            signals = pd.DataFrame({"IC2612.CFE": [0.2]}, index=["2026-09-21"])
            prices.to_parquet(root / "close.parquet")
            signals.to_parquet(root / "signals.parquet")
            write_json(root / "job.json", dict(instructions_path="signals.parquet", output_dir="cli_run",
                                               data=dict(close_path="close.parquet", margin_rates={"IC": 0.1}),
                                               backtest=dict(initial_capital=100_000)))
            job = load_job(root / "job.json")
            self.assertEqual(job["instructions_path"], str(root / "signals.parquet"))
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["run", "--config", str(root / "job.json")]), 0)
            self.assertTrue((root / "cli_run/actual_orders.csv").is_file())
            self.assertEqual(len(pd.read_parquet(root / "cli_run/actual_orders.parquet")), 1)


if __name__ == "__main__":
    unittest.main()
