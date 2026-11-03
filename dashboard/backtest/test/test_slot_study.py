import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig,BacktestError,DataConfig,run_backtest
from dashboard.backtest.__main__ import load_job
from dashboard.backtest.io import load_result,write_json
from dashboard.backtest.models import check_market_source
from dashboard.backtest.readonly_import import SOURCE_ID,read_source
from dashboard.backtest.slot_report import render_slot_report
from dashboard.backtest.slot_study import run_slot_study
from dashboard.backtest.strategy import load_cta,load_factors
from dashboard.backtest.strategy.pipeline import _load_market
from dashboard.backtest.configuration import factor_spec
from dashboard.backtest.synthetic import write_inputs
from dashboard.backtest.test.test_data import local_temp
from dashboard.backtest.workflow import factor_stage


class SlotStudyTests(unittest.TestCase):
    def test_source_authorization_is_explicit_and_does_not_allow_runtime_z_or_old_cache(self):
        with self.assertRaises(BacktestError):
            DataConfig(source_id=SOURCE_ID)
        with self.assertRaises(BacktestError):
            DataConfig(source_id=SOURCE_ID,allow_readonly_z_import=True)
        with self.assertRaises(BacktestError):
            DataConfig(close_path="Z:/data/close.parquet",source_id=SOURCE_ID,allow_readonly_z_import=True,source_manifest_path="manifest.json")
        with self.assertRaises(BacktestError):
            DataConfig(close_path="P:/data/backfilled_cn_index/close.parquet",allow_readonly_z_import=True,source_manifest_path="manifest.json")
        DataConfig(source_id=SOURCE_ID,allow_readonly_z_import=True,source_manifest_path="manifest.json")
        check_market_source(dict(market=dict(source_id=SOURCE_ID,allow_readonly_z_import=True)))

    def test_import_manifest_hashes_and_source_side_read_only_helper(self):
        with local_temp() as root:
            directory=write_inputs(root/"inputs")
            job=load_job(directory/"structure.local.json")
            source=root/"source.pkl"
            original=pd.DataFrame({r+".CFE":[1.,2.] for r in ("IF","IH","IC","IM")},index=pd.date_range("2024-01-02",periods=2))
            original.to_pickle(source)
            before=source.stat()
            evidence=[]
            pd.testing.assert_frame_equal(read_source(source,evidence),original)
            self.assertEqual(source.stat().st_mtime_ns,before.st_mtime_ns)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),evidence[0]["sha256"])
            outputs={p.name:dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in directory.glob("*.parquet")}
            write_json(directory/"import_manifest.local.json",dict(schema_version="delta1_readonly_import_v1",source_id=SOURCE_ID,
                source_read_only=True,sources=[dict(path="Z:/source/example.pkl",read_only=True)],outputs=outputs))
            job["data"].update(source_id=SOURCE_ID,allow_readonly_z_import=True,source_manifest_path=str(directory/"import_manifest.local.json"))
            result=factor_stage(job)
            self.assertTrue(result.metadata["market"]["allow_readonly_z_import"])
            altered=pd.read_parquet(directory/"daily_close.parquet")
            altered.iloc[0,0]+=1
            altered.to_parquet(directory/"daily_close.parquet")
            with self.assertRaisesRegex(BacktestError,"Imported input"):
                factor_stage(job)

    def test_fixed_slot_accounts_hold_actual_contract_independently_and_saved_report_reconciles(self):
        with local_temp() as root:
            job=load_job(write_inputs(root/"inputs")/"structure.local.json")
            job["backtest"].update(initial_capital=1_000_000,start="2026-01-08",preserve_pair_lots=False)
            out=root/"study"
            result=run_slot_study(job,out,thresholds=(.9,),render=False)
            self.assertEqual(len(result["metrics"]),36)
            self.assertEqual(result["protocol"]["index_accounts"],16)
            saved=load_factors(out/"factors")
            original=load_result(out/"history_slot02_0_9/backtest").accounts["IC"]
            targets=load_cta(out/"history_slot02_0_9/cta").targets
            targets=targets.loc[:,targets.columns.str.startswith("IC")]
            execution=json.loads((out/"history_slot02_0_9/job.local.json").read_text())["backtest"]
            market=_load_market(DataConfig(**job["data"]),factor_spec(job).runtime(),None,None)
            alone=run_backtest(targets,market_data=market,config=BacktestConfig(**execution)).accounts["IC"]
            pd.testing.assert_frame_equal(alone.equity,original.equity)
            actual=original.positions.filter(regex=r"\.CFE$")
            self.assertLessEqual(actual.ne(0).sum(axis=1).max(),1)
            mismatched=False
            for stamp,row in actual.iterrows():
                held=row.loc[row.ne(0)]
                if len(held) and held.index[0]!=saved.panel.mapping.at[stamp,"IC02.CFE"]:
                    mismatched=True
            self.assertTrue(mismatched,"A changed slot must not roll the held actual contract")
            with patch("dashboard.backtest.slot_study._load_market",side_effect=AssertionError("Saved report must not read prices")):
                rendered=render_slot_report(out)
            self.assertEqual(len(rendered["groups"]),16)
            self.assertEqual(len(rendered["product"]),4)
            for method in ("history","regression"):
                pairs=rendered["pairs"]
                np.testing.assert_allclose(pairs[method+"_future_pnl"]+pairs[method+"_hedge_pnl"],pairs[method+"_net_pnl"],atol=1e-7)
                np.testing.assert_allclose(pairs[method+"_future_gross_pnl"]+pairs[method+"_hedge_gross_pnl"]-
                    pairs[method+"_future_fees"]-pairs[method+"_hedge_fees"],pairs[method+"_net_pnl"],atol=1e-7)
            self.assertTrue(Path(rendered["report"]).is_file())
            report=Path(rendered["report"]).read_text(encoding="utf-8")
            self.assertIn("净收益贡献",report)
            self.assertNotIn("p.pnl.map(v=>v/10000)",report)
            self.assertFalse((out/"pnl_0_9.png").exists())

            # Another side policy uses exactly the same saved factor bundle, with no fit.
            fingerprints={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/"factors").rglob("*") if p.is_file()}
            job["factor_input"]=str(out/"factors")
            job["cta"]["parameters"]["allowed_future_side"]="long"
            long_out=root/"long_study"
            with patch("dashboard.backtest.slot_study.factor_stage",side_effect=AssertionError("Reuse must not compute")):
                restricted=run_slot_study(job,long_out,thresholds=(.9,),render=False)
            self.assertEqual(restricted["protocol"]["factor_computations"],0)
            self.assertEqual(fingerprints,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/"factors").rglob("*") if p.is_file()})
            for case in restricted["protocol"]["cases"]:
                result=load_result(long_out/case/"backtest")
                for root_name,account in result.accounts.items():
                    if case.startswith("calendar"):
                        old=load_result(out/case/"backtest").accounts[root_name]
                        pd.testing.assert_frame_equal(account.equity,old.equity)
                        pd.testing.assert_frame_equal(account.actual_orders,old.actual_orders)
                    else:
                        self.assertTrue(account.positions.filter(regex=r"\.CFE$").ge(0).all().all())
                        self.assertTrue(account.positions.filter(regex=r"_spot$").le(0).all().all())
                        weights=load_cta(long_out/case/"cta").targets
                        self.assertTrue(weights.filter(regex=r"\.CFE$").ge(0).all().all())
            render_slot_report(long_out)
            self.assertIn("本组期现限制：仅多期货、空指数",(long_out/"report.html").read_text(encoding="utf-8"))
            job["factor"]["parameters"]["window_days"]=4
            job["backtest"]["start"]="2026-01-12"
            with self.assertRaisesRegex(BacktestError,"Saved factor declaration"):
                run_slot_study(job,root/"mismatch",thresholds=(.9,),render=False)
            job["factor"]["parameters"]["window_days"]=3
            changed=pd.read_parquet(job["data"]["daily_close_path"])
            changed.iloc[0,0]+=1
            changed.to_parquet(job["data"]["daily_close_path"])
            with self.assertRaisesRegex(BacktestError,"Saved factor source changed"):
                run_slot_study(job,root/"changed_source",thresholds=(.9,),render=False)


if __name__=="__main__":
    unittest.main()
