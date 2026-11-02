import json
import unittest
from unittest.mock import patch

import pandas as pd

from dashboard.backtest.__main__ import load_job
from dashboard.backtest import BacktestError
from dashboard.backtest.io import frame_fingerprint
from dashboard.backtest.strategy import load_cta, load_factors
from dashboard.backtest.structure_report import render_saved_structure_report
from dashboard.backtest.structure_study import run_structure_study
from dashboard.backtest.synthetic import write_inputs
from dashboard.backtest.test.test_data import local_temp
from dashboard.backtest.workflow import cta_stage


class StructureStudyTests(unittest.TestCase):
    def test_saved_conditional_factor_reuse_annualized_study_and_offline_report(self):
        with local_temp() as root:
            inputs=write_inputs(root/"inputs")
            job=load_job(inputs/"structure.local.json")
            study=root/"study"
            result=run_structure_study(job,study,synthetic=True,render=False)
            self.assertEqual(len(result["summary"]),8)
            self.assertTrue(result["protocol"]["all_factor_cells_unchanged"])
            self.assertTrue(all(a["pair_pnl_margin_fee_reconciled"] for a in result["protocol"]["audits"]))
            saved=load_factors(study/"factors")
            before={k:frame_fingerprint(v) for k,v in saved.continuous_factors.items()}
            with patch("dashboard.backtest.workflow.compute_factors",side_effect=AssertionError("Must not refit")):
                for threshold in (.9,.8):
                    changed={**job,"backtest":{**job["backtest"],"start":result["protocol"]["evaluation_start"],
                        "end":result["protocol"]["evaluation_end"]},
                        "cta":{**job["cta"],"parameters":{**job["cta"]["parameters"],"threshold":threshold}}}
                    signal=cta_stage(saved,changed)
                    expected=load_cta(study/f"quantile_pairs_{str(threshold).replace('.','_')}"/"cta")
                    pd.testing.assert_frame_equal(signal.targets,expected.targets,check_freq=False)
            self.assertEqual(before,{k:frame_fingerprint(v) for k,v in saved.continuous_factors.items()})
            with patch("dashboard.backtest.structure_study.factor_stage",side_effect=AssertionError("Must reuse artifact")):
                reused=run_structure_study(job,root/"reused",synthetic=True,thresholds=(.8,),factor_artifact=study/"factors",render=False)
            original=result["summary"].loc[result["summary"].threshold.eq(.8)].reset_index(drop=True)
            pd.testing.assert_frame_equal(original,reused["summary"])
            # Rendering uses only saved account/pair/factor artifacts, without original prices.
            with patch("dashboard.backtest.strategy.pipeline._load_market",side_effect=AssertionError("No raw reread")):
                rendered=render_saved_structure_report(study)
            self.assertTrue((study/"report.html").is_file())
            self.assertTrue(all((study/p).stat().st_size>1000 for p in rendered["images"]))
            content=(study/"report.html").read_text(encoding="utf-8")
            self.assertNotIn("cdn.",content)
            self.assertIn("T03−T01",content)
            self.assertIn("compound 365",json.dumps(result["summary"].annualization.iloc[0]))
            main=result["summary"].iloc[0]
            expected=(main.final_equity/main.initial_capital)**(365/main.elapsed_calendar_days)-1
            self.assertAlmostEqual(main.annualized_return,expected)
            changed=pd.read_parquet(inputs/"daily_close.parquet")
            changed.iloc[0,0]+=1
            changed.to_parquet(inputs/"daily_close.parquet")
            with self.assertRaisesRegex(BacktestError,"Saved factor input differs"):
                run_structure_study(job,root/"changed",synthetic=True,factor_artifact=study/"factors",render=False)


if __name__=="__main__":
    unittest.main()
