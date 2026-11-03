from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from dashboard.backtest import BacktestError
from dashboard.backtest.__main__ import load_job
from dashboard.backtest.io import load_result
from dashboard.backtest.strategy import load_factors
from dashboard.backtest.synthetic import write_inputs
from dashboard.backtest.test.test_data import local_temp
from dashboard.backtest.tuning import expand_tuning, run_tuning
from dashboard.backtest.workflow import factor_stage


class TuningTests(unittest.TestCase):
    def test_window_threshold_fee_grid_uses_canonical_stages_and_reuses_both_caches(self):
        with local_temp() as root:
            job=load_job(write_inputs(root/"inputs")/"index_09.local.json")
            job["tuning"]=dict(grid={"factor.parameters.window_days":[3,4],"cta.parameters.threshold":[.8,.9],
                                      "backtest.commission_rate":[.0003,.0005]})
            original=deepcopy(job)
            with patch("dashboard.backtest.tuning.factor_stage",wraps=factor_stage) as compute:
                tuned=run_tuning(job,root/"tuned")
            self.assertEqual(job,original)
            self.assertEqual(compute.call_count,2)
            manifest=tuned["manifest"]
            self.assertEqual(manifest["factor_computations"],2)
            self.assertEqual(manifest["unique_ctas"],4)
            self.assertEqual(manifest["completed_runs"],8)
            self.assertTrue(manifest["raw_factor_cells_unchanged"])
            first=root/"tuned/variants/v0001"
            effective=json.loads((first/"job.local.json").read_text())
            from dashboard.backtest.workflow import backtest_stage
            replay=backtest_stage(Path(effective["instructions_path"]).parent,effective)
            saved=load_result(first/"backtest")
            for account in replay.accounts:
                pd.testing.assert_frame_equal(replay.accounts[account].equity,saved.accounts[account].equity)
            self.assertEqual(len(tuned["summary"]),32)

    def test_external_saved_factor_has_zero_computations_and_checks_its_parameters(self):
        with local_temp() as root:
            job=load_job(write_inputs(root/"inputs")/"index_09.local.json")
            factor_stage(job,output_dir=root/"saved")
            job["factor_input"]=str(root/"saved")
            job["tuning"]=dict(grid={"cta.parameters.threshold":[.9,.8]})
            before=load_factors(root/"saved").continuous_factors["basis_percentile"].copy()
            with patch("dashboard.backtest.tuning.factor_stage",side_effect=AssertionError("No factor recalculation")):
                tuned=run_tuning(job,root/"reuse")
            self.assertEqual(tuned["manifest"]["factor_computations"],0)
            self.assertEqual(tuned["manifest"]["unique_factors"],1)
            pd.testing.assert_frame_equal(before,load_factors(root/"saved").continuous_factors["basis_percentile"])
            job["factor"]["parameters"]["window_days"]=4
            with self.assertRaisesRegex(BacktestError,"Saved factor declaration differs"):
                run_tuning(job,root/"different")

    def test_cases_reset_another_functions_internal_parameters_and_validate_every_variant(self):
        with local_temp() as root:
            job=load_job(write_inputs(root/"inputs")/"structure.local.json")
            job["tuning"]=dict(cases=[dict(name="regression"),dict(name="history",factor=dict(name="basis_percentile",
                parameters=dict(window_days=4,min_samples=2)),cta=dict(input_factor="basis_percentile"))],
                grid={"cta.parameters.threshold":[.9,.8]})
            variants=expand_tuning(job)
            self.assertEqual(len(variants),4)
            for variant in variants[2:]:
                self.assertNotIn("quantiles",variant["job"]["factor"]["parameters"])
                self.assertEqual(variant["job"]["cta"]["input_factor"],"basis_percentile")
            job["tuning"]["grid"]={"cta.parameters.window_days":[20]}
            with self.assertRaises(BacktestError):
                expand_tuning(job)
            job["tuning"]=dict(grid={"cta.parameters.threshold":[.8,.9]},max_runs=1)
            with self.assertRaisesRegex(BacktestError,"max_runs"):
                expand_tuning(job)

    def test_changing_only_data_root_in_grid_preserves_relative_standard_files(self):
        with local_temp() as root:
            left,right=write_inputs(root/"a"),write_inputs(root/"b")
            job=load_job(left/"index_09.local.json")
            job["tuning"]=dict(grid={"data.data_root":[str(left),str(right)]})
            variants=expand_tuning(job)
            self.assertEqual(variants[1]["job"]["data"]["daily_close_path"],str(right/"daily_close.parquet"))
            self.assertEqual(variants[1]["job"]["data"]["reference_path"],str(right/"contracts.parquet"))

    def test_mutating_only_actual_factor_cells_is_detected_before_execution(self):
        from dashboard.backtest.workflow import cta_stage
        with local_temp() as root:
            job=load_job(write_inputs(root/"inputs")/"index_09.local.json")
            def mutate(factors,*args,**kwargs):
                result=cta_stage(factors,*args,**kwargs)
                factors.factors["basis_percentile"].iloc[0,0]=.5
                return result
            with patch("dashboard.backtest.tuning.cta_stage",side_effect=mutate), \
                 patch("dashboard.backtest.tuning.backtest_stage",side_effect=AssertionError("Must reject before execution")):
                with self.assertRaisesRegex(BacktestError,"mutated"):
                    run_tuning(job,root/"rejected")


if __name__=="__main__":
    unittest.main()
