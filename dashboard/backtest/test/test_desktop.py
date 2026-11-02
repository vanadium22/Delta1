# ruff: noqa: E402 -- Configure an offscreen test platform before importing Qt.
import os
import time
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("DELTA1_THEME", "public")

from dashboard.backtest.desktop import BacktestWindow, configure_style
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from dashboard.backtest.test.test_data import local_temp
from dashboard.backtest.test.test_desktop_service import make_job


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_style(cls.app)

    def setUp(self):
        self.window = BacktestWindow()
        self.window.show()
        self.app.processEvents()

    def wait_idle(self):
        deadline = time.monotonic() + 10
        while self.window.task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertIsNone(self.window.task, self.window.status.text())

    def tearDown(self):
        self.window.close()
        self.wait_idle()
        self.window.close()
        self.app.processEvents()

    def test_default_units_and_total_equity_threshold(self):
        job = self.window.job()
        self.assertEqual(job["backtest"]["commission_rate"], 0.0003)
        self.assertEqual(job["backtest"]["minimum_margin_ratio"], 0.0001)
        self.assertEqual(job["backtest"]["max_capital_usage"], 0.99)
        self.assertEqual(job["backtest"]["margin_call_basis"], "equity")
        self.assertEqual(job["backtest"]["precision"], "1d")
        self.assertEqual(job["backtest"]["workers"], 0)
        self.assertEqual(job["backtest"]["d0"], 0)

    def test_background_run_tables_search_and_result_reopen(self):
        from dashboard.backtest.io import write_json
        with local_temp() as root:
            job = make_job(root)
            job["ui"] = {"output_root": str(root / "runs")}
            path = root / "job.local.json"
            write_json(path, job)
            self.window.load_config(path)
            self.window.inspect()
            self.wait_idle()
            self.assertIsNotNone(self.window.inspection, self.window.status.text())
            self.assertFalse(self.window.inspection["report"]["required_missing"])
            self.window.run_backtest()
            self.wait_idle()
            self.assertIsNotNone(self.window.result, self.window.status.text())
            self.assertEqual(self.window.models["actual_orders"].rowCount(), 2)
            self.window.search.setText("开多")
            self.window.filter_table()
            self.assertEqual(self.window.models["actual_orders"].rowCount(), 1)
            self.window.search.clear()
            self.window.tables.setCurrentIndex(4)
            self.assertEqual(self.window.models["instructions"].rowCount(), 2)
            output = self.window.result.output_paths["output_dir"]
            self.window.open_result(output)
            self.wait_idle()
            self.assertEqual(len(self.window.result.actual_orders), 2)
            self.assertTrue(self.window.run_button.isEnabled())
            self.assertFalse(self.window.cancel_button.isEnabled())

    def test_configuration_round_trip(self):
        with local_temp() as root:
            self.window.capital.setValue(23_000_000)
            self.window.fee.setValue(2.5)
            self.window.precision.setCurrentIndex(self.window.precision.findData("auto"))
            self.window.workers.setValue(2)
            self.window.d0.setValue(3)
            self.window.strategy_controls["min_samples"].setValue(3)
            self.window.strategy_controls["missing"].setCurrentIndex(1)
            self.window.strategy_controls["transform"].setCurrentIndex(0)
            self.window.show_location("save_config")
            destination = root / "job.local.json"
            self.window.location_path.setText(str(destination))
            self.window.apply_location()
            self.assertTrue(destination.is_file())
            self.window.capital.setValue(1)
            self.window.load_config(destination)
            self.assertEqual(self.window.capital.value(), 23_000_000)
            self.assertEqual(self.window.job()["backtest"]["commission_rate"], 0.00025)
            self.assertEqual(self.window.job()["backtest"]["precision"], "auto")
            self.assertEqual(self.window.job()["backtest"]["workers"], 2)
            self.assertEqual(self.window.job()["backtest"]["d0"], 3)
            self.assertEqual(self.window.job()["factor"]["parameters"]["min_samples"], 3)
            self.assertEqual(self.window.job()["cta"]["parameters"]["missing"], "hold")
            self.assertEqual(self.window.job()["cta"]["parameters"]["transform"], "identity")

    def test_generate_factor_targets_then_backtest_inside_desktop(self):
        from dashboard.backtest.desktop_strategy import generate_targets
        from dashboard.backtest.io import write_json
        from dashboard.backtest.test.test_strategy import strategy_job
        with local_temp() as root:
            job = strategy_job(root)
            job["ui"] = {"output_root": str(root / "runs")}
            path = root / "strategy.local.json"
            write_json(path, job)
            self.window.load_config(path)
            generate_targets(self.window)
            self.wait_idle()
            self.assertTrue(hasattr(self.window, "strategy_result"), self.window.status.text())
            self.assertTrue(self.window.fields["instructions_path"].text().endswith("targets.parquet"))
            self.window.run_backtest()
            self.wait_idle()
            self.assertIsNotNone(self.window.result, self.window.status.text())
            self.assertGreater(len(self.window.result.actual_orders), 0)

    def test_four_pages_saved_factor_only_cta_and_independent_parameter_round_trip(self):
        from dashboard.backtest.desktop_strategy import compute_only, apply_cta_only, read_factor
        from dashboard.backtest.io import write_json
        from dashboard.backtest.synthetic import write_inputs
        from dashboard.backtest.__main__ import load_job
        import pandas as pd
        with local_temp() as root:
            inputs = write_inputs(root / "inputs")
            job = load_job(inputs / "index_09.local.json")
            job["ui"] = dict(output_root=str(root / "runs"))
            path = root / "job.local.json"
            write_json(path, job)
            self.window.load_config(path)
            self.assertEqual([self.window.forms.tabText(i) for i in range(self.window.forms.count())],
                             ["数据配置", "因子参数", "CTA 参数", "回测执行参数"])
            self.window.strategy_controls["factor_workers"].setValue(1)
            self.window.workers.setValue(2)
            compute_only(self.window)
            self.wait_idle()
            self.assertIsNotNone(self.window.factor_result, self.window.status.text())
            before = self.window.factor_result.continuous_factors["basis_percentile"].copy(deep=True)
            self.window.strategy_controls["threshold"].setValue(.8)
            self.window.show_location("save_config")
            self.window.location_path.setText(str(path))
            self.window.apply_location()
            self.window.load_config(path)
            settings = self.window.job()
            self.assertEqual(settings["factor"]["workers"], 1)
            self.assertEqual(settings["backtest"]["workers"], 2)
            self.assertEqual(settings["cta"]["parameters"]["threshold"], .8)
            self.assertEqual(settings["data"]["margin_rates"], {s: 1 for s in ("IF", "IH", "IC", "IM")})
            self.assertIsNone(self.window.factor_result)
            read_factor(self.window)
            self.wait_idle()
            pd.testing.assert_frame_equal(before, self.window.factor_result.continuous_factors["basis_percentile"], check_freq=False)
            with patch("dashboard.backtest.desktop_strategy.factor_stage", side_effect=AssertionError("CTA must not compute factors")):
                apply_cta_only(self.window)
                self.wait_idle()
            self.assertTrue(hasattr(self.window, "strategy_result"), self.window.status.text())
            self.assertEqual(self.window.weight_mode.currentData(), "neutral_units")
            self.assertTrue(self.window.on_change.isChecked())
            self.assertIn("daily_close.parquet", self.window.data_manifest_view.toPlainText())
            self.window.run_backtest()
            self.wait_idle()
            self.assertIsNotNone(self.window.result, self.window.status.text())

    def test_active_parameters_restore_for_every_cta_function(self):
        from dataclasses import asdict
        import json
        from dashboard.backtest.configuration import CTASpec, FactorSpec
        from dashboard.backtest.io import write_json
        cases = [
            CTASpec(name="fixed", parameters=dict(open_threshold=.8, close_threshold=.15, position_weight=.23,
                    direction=-1, transform="center_percentile", missing="hold", hedge="index")),
            CTASpec(name="zscore", parameters=dict(lookback_window=7, z_open=1.8, z_close=.3, position_weight=.24,
                    direction=-1, transform="identity", missing="error")),
            CTASpec(name="expiry_index", parameters=dict(threshold=.8, position_weight=.4, slots=(1, 3), selection="contract_independent")),
            CTASpec(name="expiry_spread", input_factor="calendar_spread_percentile", parameters=dict(threshold=.8, position_weight=.4)),
        ]
        with local_temp() as root:
            for case in cases:
                factor = FactorSpec(name=case.input_factor, parameters=dict(window_days=7, min_samples=3))
                path = root / "job.local.json"
                write_json(path, dict(factor=asdict(factor), cta=asdict(case)))
                self.window.load_config(path)
                restored = self.window.job()
                def normalize(obj):
                    return json.loads(json.dumps(obj))
                self.assertEqual(normalize(restored["factor"]), normalize(asdict(factor)))
                self.assertEqual(normalize(restored["cta"]), normalize(asdict(case)))

    def test_saving_relative_files_keeps_root_only_relocation_available(self):
        from dashboard.backtest.synthetic import write_inputs
        from dashboard.backtest import DataConfig
        with local_temp() as root:
            first, second = write_inputs(root / "a"), write_inputs(root / "b")
            self.window.load_config(first / "index_09.local.json")
            self.assertEqual(self.window.fields["daily_close_path"].text(), "daily_close.parquet")
            self.window.fields["data_root"].setText(str(second))
            data = self.window.job()["data"]
            self.assertEqual(data["daily_close_path"], "daily_close.parquet")
            self.assertEqual(DataConfig(**data).daily_close_path, str(second / "daily_close.parquet"))

    def test_cancel_is_responsive_and_closing_waits_for_worker(self):
        started = []
        def read(cancel, progress):
            started.append(True)
            while not cancel.wait(0.005):
                continue
            from dashboard.backtest import BacktestCancelled
            raise BacktestCancelled("cancelled")
        self.window.submit(read, lambda _: self.fail("Cancelled read must not report success"))
        QTimer.singleShot(20, self.window.close)
        self.wait_idle()
        self.assertTrue(started)
        self.assertFalse(self.window.isVisible())

    def test_file_picker_stays_inside_window_and_4k_layout_fits(self):
        self.window.resize(3840, 2160)
        self.app.processEvents()
        self.window.picker.open_for(self.window.fields["instructions_path"])
        self.app.processEvents()
        self.assertFalse(self.window.picker.isWindow())
        self.assertTrue(self.window.picker.isVisible())
        self.assertGreater(self.window.left.width(), 500)
        self.assertLessEqual(self.window.split.width(), self.window.centralWidget().width())
        self.window.picker.hide()
        self.window.forms.setCurrentIndex(1)
        for width, height in ((3840, 2160), (1920, 1080)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.app.processEvents()
            self.assertEqual(self.window.forms.currentWidget().horizontalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
