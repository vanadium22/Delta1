from dataclasses import asdict
from pathlib import Path
import shutil
import threading
import unittest

import pandas as pd

from dashboard.backtest import BacktestCancelled, BacktestConfig, MarketData, load_result, run_backtest
from dashboard.backtest.desktop_service import execute_job, inspect_job
from dashboard.backtest.io import write_json
from dashboard.backtest.test.test_data import local_temp


def make_job(root, *, spot=False):
    symbol = "IC_spot" if spot else "IC2612.CFE"
    dates = pd.date_range("2026-09-21", periods=4)
    pd.DataFrame({symbol: [100, 110, 120, 130]}, index=dates).to_parquet(root / "close.parquet")
    pd.DataFrame({symbol: [0.3, 0]}, index=dates[[0, 2]]).to_parquet(root / "targets.parquet")
    return dict(instructions_path=str(root / "targets.parquet"), output_dir=str(root / "run"),
                data=dict(close_path=str(root / "close.parquet"), multipliers={"IC": 10},
                          margin_rates={} if spot else {"IC": 0.1}),
                backtest=asdict(BacktestConfig(initial_capital=100_000)))


class DesktopServiceTests(unittest.TestCase):
    make_job = staticmethod(make_job)

    def test_optional_dividend_gap_does_not_block_raw_close_run(self):
        with local_temp() as root:
            check = inspect_job(self.make_job(root))
            self.assertFalse(check["report"]["required_missing"])
            self.assertTrue(check["report"]["optional_missing"])

    def test_futures_missing_margin_and_spot_full_funding_are_distinguished(self):
        with local_temp() as root:
            job = self.make_job(root)
            job["data"]["margin_rates"] = {}
            self.assertTrue(inspect_job(job)["report"]["required_missing"])
            spot_job = self.make_job(root, spot=True)
            self.assertFalse(inspect_job(spot_job)["report"]["required_missing"])

    def test_cancel_before_read_does_not_create_output(self):
        with local_temp() as root:
            event = threading.Event()
            event.set()
            with self.assertRaises(BacktestCancelled):
                execute_job(self.make_job(root), cancel_event=event)
            self.assertFalse((root / "run").exists())

    def test_cancel_during_simulation_does_not_publish_results(self):
        with local_temp() as root:
            event = threading.Event()
            def progress(info):
                if info["stage"] == "simulating":
                    event.set()
            with self.assertRaises(BacktestCancelled):
                execute_job(self.make_job(root), cancel_event=event, progress=progress)
            self.assertFalse((root / "run").exists())

    def test_save_finishes_safely_and_results_reopen_after_directory_move(self):
        with local_temp() as root:
            event = threading.Event()
            def progress(info):
                if info["stage"] == "saving":
                    event.set()
            result = execute_job(self.make_job(root), cancel_event=event, progress=progress)
            self.assertTrue((root / "run/job.local.json").is_file())
            destination = root / "moved"
            self.assertTrue((root / "run").resolve().is_relative_to(root.resolve()))
            self.assertTrue(destination.resolve().is_relative_to(root.resolve()))
            shutil.move(str(root / "run"), str(destination))
            reopened = load_result(destination)
            pd.testing.assert_frame_equal(result.actual_orders, reopened.actual_orders)
            pd.testing.assert_frame_equal(result.input_instructions, reopened.input_instructions)
            self.assertEqual(result.summary.final_equity.tolist(), reopened.summary.final_equity.tolist())
            self.assertTrue(Path(reopened.output_paths["actual_orders"]).is_file())

    def test_old_result_metadata_without_account_summaries_still_opens(self):
        with local_temp() as root:
            dates = pd.date_range("2026-09-21", periods=3)
            market = MarketData(pd.DataFrame({"IC_spot": [100, 101, 102]}, index=dates))
            result = run_backtest(pd.DataFrame({"IC_spot": [0.2]}, index=dates[:1]), market_data=market,
                                  output_dir=root / "legacy")
            metadata = {**result.metadata, "output_paths": result.output_paths}
            write_json(root / "legacy/metadata.json", metadata)
            reopened = load_result(root / "legacy")
            self.assertEqual(reopened.accounts["portfolio"].summary["status"], "completed")


if __name__ == "__main__":
    unittest.main()
