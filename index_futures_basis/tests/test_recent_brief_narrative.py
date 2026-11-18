from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from openpyxl import Workbook

from index_futures_basis.recent_brief.data import adjust, calendar_series, multi_session_quantiles
from index_futures_basis.recent_brief.metrics import total_metrics
from index_futures_basis.recent_brief.narrative import classify_path, compose
from index_futures_basis.tests.test_recent_brief import panel


class NarrativeTests(unittest.TestCase):
    def test_two_phase_discount_pattern_and_direction(self):
        peak = -np.r_[np.linspace(5,30,20), np.linspace(30,10,20)]
        self.assertEqual(classify_path(peak)["shape"], "widen_then_narrow")
        trough = -np.r_[np.linspace(30,5,20), np.linspace(5,25,20)]
        self.assertEqual(classify_path(trough)["shape"], "narrow_then_widen")
        self.assertEqual(classify_path(-np.linspace(30,5,40))["shape"], "narrow")
        self.assertIn("升水", classify_path(np.linspace(5,30,40))["text"])
        self.assertEqual(classify_path(np.zeros(40))["shape"], "flat")

    def test_gaps_and_sign_changes_do_not_become_fabricated_patterns(self):
        self.assertEqual(classify_path(np.arange(39))["shape"], "insufficient")
        values = -np.ones(40)
        values[15] = np.nan
        self.assertEqual(classify_path(values)["shape"], "insufficient")
        self.assertEqual(classify_path(np.linspace(-5,5,40))["shape"], "sign_change")

    def test_insufficient_data_is_explicit_and_json_remains_finite(self):
        p = panel()
        c = calendar_series(p)
        report = compose(p,c,multi_session_quantiles(p,p.trade_date.max(),"slot"),
                         multi_session_quantiles(c,p.trade_date.max(),"pair"),
                         total_metrics(p,p.trade_date.max()),p.trade_date.max())
        self.assertIn("40日历史不足", report["text"])
        json.dumps(report,allow_nan=False)

    def test_latest_local_dividend_uses_business_date_and_unpinned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def save(name, day, points):
                book=Workbook();sheet=book.active;sheet.title="Sheet1";sheet['B1']=pd.Timestamp(day).to_pydatetime()
                sheet["G3"] = "分红"
                for i in range(4):
                    sheet.cell(4+i,2,f"IF{i:02d}.CFE");sheet.cell(4+i,7,points)
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);book.save(path);book.close();return path
            old=save("2099_filename.xlsx","2026-01-01",1)
            fresh=save("fresh_without_standard_name.xlsx","2026-02-01",7)
            cfg={"dividends":{"selection":"fixed_file","file":str(old),"directories":[str(root)],
                "layout":"snapshot_continuous","sheet":"Sheet1","header_row":3,"code_column":"B","dividend_column":"G"}}
            paths=SimpleNamespace(dividend_inputs=root,resolve_module_setting=lambda *a:root)
            p=panel()
            result,info=adjust(p,cfg,paths)
            self.assertEqual(info["snapshot_date"],"2026-02-01")
            self.assertEqual(Path(info["path"]),fresh.resolve())
            self.assertTrue(result.dividend_points.eq(7).all())
            np.testing.assert_allclose(result.basis_points,result.raw_basis_points+7)
            pinned,pin_info=adjust(p,cfg,paths,old)
            self.assertEqual(pin_info["snapshot_date"],"2026-01-01")
            self.assertTrue(pinned.dividend_points.eq(1).all())
            save("newest_incomplete.xlsx","2026-03-01",None)
            missing,missing_info=adjust(p,cfg,paths)
            self.assertEqual(missing_info["snapshot_date"],"2026-03-01")
            self.assertTrue(missing.dividend_points.isna().all())
            self.assertTrue(missing.basis_points.isna().all())
            paths.repo_root = root
            cached = save("dashboard/localsetting/overview_dividends/raw/2026-04-01/cache.xlsx","2026-04-01",9)
            revised,revised_info=adjust(p,cfg,paths)
            self.assertEqual(revised_info["snapshot_date"],"2026-04-01")
            self.assertEqual(Path(revised_info["path"]),cached.resolve())
            self.assertTrue(revised.dividend_points.eq(9).all())


if __name__ == "__main__":
    unittest.main()
