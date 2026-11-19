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
from index_futures_basis.recent_brief.metrics import total_metrics, series_metrics, price_audit_lines
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
        self.assertIn("30/60日历史不足", report["text"])
        self.assertEqual([s["key"] for s in report["sections"]], ["absolute", "annualized", "activity", "calendar"])
        json.dumps(report,allow_nan=False)

    def history(self):
        base = panel().query("trade_date == trade_date.max()")
        frames = []
        for day in pd.bdate_range("2025-01-01", periods=100):
            for root in ("IF", "IH", "IC", "IM"):
                current = base.copy()
                current["root"], current["trade_date"] = root, day
                current["instrument_id"] = current.instrument_id.str.replace("IF", root)
                current["roll_day"] = False
                frames.append(current)
        return pd.concat(frames, ignore_index=True)

    def compose(self, p):
        c = calendar_series(p)
        return compose(p,c,None,None,None,p.trade_date.max())

    def test_flat_market_does_not_force_anomalies_and_windows_are_explicit(self):
        result = self.compose(self.history())
        self.assertEqual(result["absolute"]["selected"], [])
        self.assertEqual(result["annualized"]["selected"], [])
        self.assertEqual(result["activity"]["selected"], [])
        self.assertIn("未见明显", result["text"])
        self.assertEqual({r["window"] for r in result["activity"]["features"]}, {7,30,60})
        json.dumps(result,allow_nan=False)

    def test_product_overview_uses_multiple_tenors_then_selects_bounded_exceptions(self):
        p = self.history()
        p["basis_points"] = p.basis_points.astype(float)
        days = sorted(p.trade_date.unique())
        for i, day in enumerate(days):
            p.loc[p.root.eq("IF") & p.trade_date.eq(day) & p.slot.gt(1), "basis_points"] = -100+i*.8
        result = self.compose(p)
        self.assertTrue(result["absolute"]["overview"]["IF"]["majority"])
        self.assertEqual(result["absolute"]["overview"]["IF"]["majority_count"], 3)
        self.assertIn("IF近60日多数合约贴水幅度总体收敛", result["sections"][0]["text"])
        self.assertLessEqual(len(result["absolute"]["selected"]), 2)
        self.assertEqual(len({(r["root"],r["slot"]) for r in result["absolute"]["selected"]}), len(result["absolute"]["selected"]))

    def test_annual_excludes_00_and_missing_rows_do_not_shrink_windows(self):
        p = self.history()
        end = p.trade_date.max()
        p.loc[p.trade_date.eq(end) & p.slot.eq(1), "annualized_basis_pct"] = -9999
        days = sorted(p.trade_date.unique())
        p.loc[p.root.eq("IF") & p.slot.eq(2) & p.trade_date.eq(days[-12]), "annualized_basis_pct"] = np.nan
        result = self.compose(p)
        self.assertTrue(all(r["slot"] != 1 for r in result["annualized"]["features"]))
        self.assertFalse(any(r["root"] == "IF" and r["slot"] == 2 for r in result["annualized"]["features"]))
        # A genuinely complete 30-session history can be named explicitly.
        p = p[p.trade_date.isin(days[-35:])]
        result = self.compose(p)
        self.assertEqual(result["absolute"]["overview"]["IC"]["window"], 30)

    def test_recent_volatility_can_be_selected_even_when_current_near_history_mean(self):
        p = self.history()
        p["basis_points"] = p.basis_points.astype(float)
        days = sorted(p.trade_date.unique())
        for i, day in enumerate(days):
            value = -100+(.5 if i%2 else -.5)
            if i >= len(days)-7:
                value = -100+(25 if i%2 else -25)
            if i == len(days)-1:
                value = -100
            p.loc[p.root.eq("IF") & p.slot.eq(3) & p.trade_date.eq(day), "basis_points"] = value
        result = self.compose(p)
        picked = result["absolute"]["selected"]
        self.assertTrue(any(r["root"] == "IF" and r["slot"] == 3 and r["volatility_expansion"] for r in picked))
        self.assertIn("近7日日均变幅", result["sections"][0]["text"])
        # A previously constant history has no meaningful volatility ratio.
        mask = p.root.eq("IF") & p.slot.eq(3) & ~p.trade_date.isin(days[-7:])
        p.loc[mask, "basis_points"] = -100.
        result = self.compose(p)
        self.assertTrue(any(r["volatility_expansion"] for r in result["absolute"]["selected"]))
        self.assertIn("基本无波动", result["sections"][0]["text"])
        json.dumps(result,allow_nan=False)

    def test_activity_volume_means_are_disjoint_and_missing_constituents_stay_missing(self):
        p = self.history()
        days = sorted(p.trade_date.unique())
        mask = p.root.eq("IF") & p.trade_date.isin(days[-7:])
        p.loc[mask, "volume"] *= 2
        result = self.compose(p)
        volumes = [r for r in result["activity"]["features"] if r["root"] == "IF" and r["metric"] == "volume"]
        self.assertEqual(len(volumes), 3)
        self.assertTrue(all(abs(r["change_pct"]-100) < 1e-8 for r in volumes))
        self.assertIn("IF近7日日均成交", result["sections"][2]["text"])
        p.loc[p.root.eq("IF") & p.slot.eq(1) & p.trade_date.eq(days[-2]), "volume"] = np.nan
        result = self.compose(p)
        self.assertFalse(any(r["root"] == "IF" and r["metric"] == "volume" for r in result["activity"]["features"]))

    def test_price_cards_show_raw_prices_and_genuine_zero_dividend(self):
        p = panel()
        p.loc[p.slot.eq(1), "dividend_points"] = 0.
        single = series_metrics(p,p.trade_date.max(),"slot")
        audit = price_audit_lines(single[single.slot.eq(1)].iloc[0])
        self.assertEqual(audit, ["指数 1000.0000", "期货 990.0000", "分红 0.0000 点"])
        c = calendar_series(p)
        cross = series_metrics(c,p.trade_date.max(),"pair").iloc[0]
        self.assertEqual(cross.left_futures_close, 980)
        self.assertEqual(cross.right_dividend_points, 6)
        self.assertIn("左腿期货 980.0000 / 分红 3.0000", price_audit_lines(cross))
        single.loc[single.slot.eq(1), "dividend_points"] = np.nan
        self.assertEqual(price_audit_lines(single[single.slot.eq(1)].iloc[0])[-1], "分红 — 点")

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
            # Company current App / numeric profiles have independent raw caches.
            current = save('dashboard/localsetting/app/overview_dividends/raw/2026-05-01/latest.xlsx','2026-05-01',11)
            revised,info=adjust(p,cfg,paths)
            self.assertEqual(info['snapshot_date'],'2026-05-01')
            self.assertEqual(Path(info['path']),current.resolve())
            private=root/'dashboard/localsetting/numeric_excel'
            private.mkdir(parents=True,exist_ok=True)
            (private/'native.json').write_text(json.dumps({'overview_dividend_cache':'saved_dividend_cache'}),encoding='utf-8-sig')
            configured=save('saved_dividend_cache/raw/2026-06-01/current.xlsx','2026-06-01',13)
            revised,info=adjust(p,cfg,paths)
            self.assertEqual(info['snapshot_date'],'2026-06-01')
            self.assertEqual(Path(info['path']),configured.resolve())

    def test_three_stage_path_and_current_oi_high_position(self):
        values=-np.r_[np.linspace(10,70,20),np.linspace(70,10,20),np.linspace(10,45,20)]
        self.assertEqual(classify_path(values,60)['shape'],'widen_narrow_widen')
        p=self.history()
        p['open_interest']=p.open_interest.astype(float)
        days=sorted(p.trade_date.unique())
        p.loc[p.root.eq('IC') & p.trade_date.eq(days[-1]),'open_interest'] *= 1.15
        report=self.compose(p)
        self.assertIn('IC（P100.0%）',report['text'])
        self.assertNotIn('对冲需求显著',report['text'])
        json.dumps(report,allow_nan=False)

    def test_common_annual_state_and_next_month_are_not_hardcoded_to_reference(self):
        p=self.history()
        end=p.trade_date.max()
        p.loc[p.trade_date.eq(end) & p.slot.gt(1),'annualized_basis_pct']=-50.
        result=self.compose(p)
        self.assertIn('IF、IH、IC、IM多数合约处于60日20%以下',result['text'])
        self.assertIn('IF、IH、IC、IM次月合约近7日',result['text'])
        self.assertEqual(len(result['annualized']['selected']),1)
        p.loc[p.trade_date.eq(end),'roll_day']=True
        result=self.compose(p)
        self.assertNotIn('次月合约近7日',result['text'])


if __name__ == "__main__":
    unittest.main()
