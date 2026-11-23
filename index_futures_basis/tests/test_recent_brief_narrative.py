from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

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
        self.assertIn("60日分位待补", report["text"])
        self.assertEqual([s["key"] for s in report["sections"]], ["annualized", "calendar", "activity"])
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
        self.assertNotIn("绝对基差", result["text"])
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
        self.assertNotIn("绝对基差", result["text"])
        # A previously constant history has no meaningful volatility ratio.
        mask = p.root.eq("IF") & p.slot.eq(3) & ~p.trade_date.isin(days[-7:])
        p.loc[mask, "basis_points"] = -100.
        result = self.compose(p)
        self.assertTrue(any(r["volatility_expansion"] for r in result["absolute"]["selected"]))
        self.assertTrue(any(r['move_multiple'] is None for r in result['absolute']['selected']))
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
        self.assertIn("IF持仓平稳、成交扩张", result["sections"][2]["text"])
        p.loc[p.root.eq("IF") & p.slot.eq(1) & p.trade_date.eq(days[-2]), "volume"] = np.nan
        result = self.compose(p)
        self.assertFalse(any(r["root"] == "IF" and r["metric"] == "volume" for r in result["activity"]["features"]))

    def test_next_month_comment_groups_products_and_excludes_rolls(self):
        p = self.history()
        latest_next = p.trade_date.eq(p.trade_date.max()) & p.slot.eq(2)
        p.loc[latest_next, 'annualized_basis_pct'] -= 2
        report = self.compose(p)
        self.assertIn('四品种次月合约年化贴水扩大', report['sections'][0]['text'])
        p.loc[latest_next & p.root.eq('IM'), 'roll_day'] = True
        report = self.compose(p)
        self.assertIn('IF、IH、IC次月合约年化贴水扩大', report['sections'][0]['text'])
        self.assertNotIn('IM', [row['root'] for row in report['annualized']['next_month_changes']])

    def test_cross_comment_uses_long_distribution_and_labels_rolls(self):
        days = pd.bdate_range('2025-01-01', periods=181)
        base = panel().tail(4)
        p = pd.concat([base.assign(trade_date=day) for day in days], ignore_index=True)
        spreads = calendar_series(p)
        pair = spreads.pair.eq('03−02')
        spreads.loc[pair & spreads.trade_date.eq(days[-1]), ['basis_points', 'annualized_basis_pct']] = [-50, -30]
        spreads.loc[pair & spreads.trade_date.eq(days[-4]), 'roll_day'] = True
        result = compose(p, spreads, None, None, None, days[-1])
        text = result['sections'][1]['text']
        self.assertIn('调整后价差均为负，远腿低于近腿', text)
        self.assertIn('IF 03−02当前-50.00点', text)
        self.assertIn('IF 03−02当前-30.00%', text)
        self.assertIn('前180个交易日', text)
        self.assertIn('样本含换月', text)
        selected = result['calendar']['annualized_selected'][0]
        self.assertEqual(selected['n'], 180)
        self.assertIsNone(selected['change'])
        self.assertFalse(selected['volatility_expansion'])

    def test_price_cards_show_raw_prices_and_genuine_zero_dividend(self):
        p = panel()
        p.loc[p.slot.eq(1), "dividend_points"] = 0.
        single = series_metrics(p,p.trade_date.max(),"slot")
        audit = price_audit_lines(single[single.slot.eq(1)].iloc[0])
        self.assertEqual(audit, ["指数 1000.0000", "期货 990.0000", "分红 0.0000 点"])
        c = calendar_series(p)
        cross = series_metrics(c,p.trade_date.max(),"pair").iloc[0]
        self.assertEqual(cross.left_futures_close, 970)
        self.assertEqual(cross.right_dividend_points, 3)
        self.assertIn("远腿期货 970.0000 / 分红 6.0000", price_audit_lines(cross))
        single.loc[single.slot.eq(1), "dividend_points"] = np.nan
        self.assertEqual(price_audit_lines(single[single.slot.eq(1)].iloc[0])[-1], "分红 — 点")

    def test_history_added_automatically_and_carries_only_same_actual_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def save(name, day, points, actual="IF2602.CFE"):
                book = Workbook()
                sheet = book.active
                sheet.title = "Sheet1"
                sheet["B1"] = pd.Timestamp(day).to_pydatetime()
                sheet["G3"] = "分红"
                sheet["B4"], sheet["C4"], sheet["G4"] = "IF00.CFE", actual, points
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                book.save(path)
                book.close()
                return path

            cfg = {"dividends": {"directories": [str(root)], "layout": "snapshot_continuous",
                                 "estimate_from_previous_contract": False, "interpolate_history": False}}
            paths = SimpleNamespace(dividend_inputs=root, resolve_module_setting=lambda *a:root, repo_root=root)
            base = panel().tail(4)
            p = pd.concat([base.assign(trade_date=day) for day in pd.to_datetime(
                ['2026-01-02', '2026-01-05', '2026-01-06', '2026-01-07'])], ignore_index=True)
            late = p.trade_date.ge('2026-01-05')
            p.loc[late & p.slot.isin([1, 2]), 'instrument_id'] = p.loc[late & p.slot.isin([1, 2]), 'instrument_id'].replace(
                {'IF2602.CFE': 'IF2603.CFE', 'IF2603.CFE': 'IF2602.CFE'})
            save('2099_filename.xlsx', '2026-01-05', 8)
            save('newest_incomplete.xlsx', '2026-01-06', None)
            save('after_cutoff.xlsx', '2026-01-06 15:30', 12)
            save('future.xlsx', '2026-01-09', 50)
            cached = save('dashboard/localsetting/app/overview_dividends/raw/2026-01-07/cache.xlsx', '2026-01-07', 0)
            result, info = adjust(p, cfg, paths)
            history = result[result.instrument_id.eq('IF2602.CFE')]
            self.assertTrue(pd.isna(history.dividend_points.iloc[0]))
            np.testing.assert_allclose(history.dividend_points.iloc[1:], [8, 8, 0])
            self.assertTrue(result[result.instrument_id.eq('IF2603.CFE')].dividend_points.isna().all())
            self.assertEqual(history.dividend_source_date.iloc[2], pd.Timestamp('2026-01-05'))
            self.assertEqual(Path(info['path']), cached.resolve())
            self.assertEqual(info['adjustment_audit']['first_missing_date'], '2026-01-02')
            save('history/old.xlsx', '2026-01-02', 5)
            revised, _ = adjust(p, cfg, paths)
            self.assertEqual(revised[revised.instrument_id.eq('IF2602.CFE')].dividend_points.iloc[0], 5)
            save('history/conflict.xlsx', '2026-01-02', 9)
            conflict, _ = adjust(p, cfg, paths)
            self.assertTrue(pd.isna(conflict[conflict.instrument_id.eq('IF2602.CFE')].dividend_points.iloc[0]))
            raw, _ = adjust(p, cfg, paths, unadjusted=True)
            np.testing.assert_allclose(raw.basis_points, raw.futures_close-raw.spot_close)
            self.assertTrue(raw.dividend_points.isna().all())

    def test_nested_history_survives_bad_workbook_and_mixed_datetime_precision(self):
        from index_futures_basis.recent_brief.diagnostics import describe_inputs

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            month = root / "2026" / "01"
            month.mkdir(parents=True)
            book = Workbook()
            sheet = book.active
            sheet.title = "Sheet1"
            sheet["B1"], sheet["G3"] = "2026-01-05", "分红"
            sheet["B4"], sheet["C4"], sheet["G4"] = "IF00.CFE", "IF2602.CFE", 0
            file = month / "day.xlsx"
            book.save(file)
            book.close()
            (month / "duplicate.xlsx").write_bytes(file.read_bytes())
            with ZipFile(file) as good, ZipFile(month / "broken.xlsx", "w") as bad:
                for part in good.namelist():
                    bad.writestr(part, b"<broken" if part == "xl/worksheets/sheet1.xml" else good.read(part))
            p = panel()
            p["trade_date"] = p.trade_date.astype("datetime64[ns]")
            cfg = {"dividends": {"directories": [str(root)], "estimate_from_previous_contract": False}}
            paths = SimpleNamespace(dividend_inputs=root, resolve_module_setting=lambda *a: root)
            for explicit in (root, None):
                result, info = adjust(p, cfg, paths, explicit)
                self.assertEqual(len(info["input_inventory"]), 3)
                self.assertEqual(len(info["files"]), 1)
                self.assertEqual(len(info["source_errors"]), 1)
                self.assertEqual(result.dividend_points.dropna().tolist(), [0.0])
                lines = []
                describe_inputs(lines.append, result, info, p.trade_date.max(), {"kind": "sqlite", "path": "market.sqlite"})
                report = "\n".join(lines)
                for expected in ("broken.xlsx  读取失败", "内容相同", "采用 1", "缺分红 7"):
                    self.assertIn(expected, report)

    def test_pending_contract_uses_only_known_business_day_mapping_and_freezes_source(self):
        from index_futures_basis.recent_brief.diagnostics import describe_inputs

        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "pending.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "Sheet1"
            sheet["B1"], sheet["G3"] = "2026-01-02T07:00:00+00:00", " 分红 "
            for slot, (code, points) in enumerate(
                [(" Fetching… ", 5), ("IC2603.CFE", 6), ("Fetching...", None), ("#GETTING_DATA", 0)]
            ):
                row = slot + 4
                sheet[f"B{row}"], sheet[f"C{row}"], sheet[f"G{row}"] = f"IF0{slot}.CFE", code, points
            book.save(file)
            book.close()
            original = file.read_bytes()

            p = panel()
            end = p.trade_date.max()
            p.loc[p.trade_date.lt(end) & p.slot.eq(4), "calendar_known"] = False
            frozen_inputs = {}
            result, info = adjust(p, {"dividends": {"estimate_from_previous_contract": False}}, None, file,
                                  frozen_inputs=frozen_inputs)
            self.assertEqual(result.dividend_points.dropna().tolist(), [5., 5.])
            self.assertEqual(result.dividend_source_date.dropna().unique().tolist(), [pd.Timestamp("2026-01-02")])
            entry = info["input_inventory"][0]
            self.assertEqual(entry["mapped_from_history"], 1)
            self.assertEqual(entry["rejected_rows"], {"invalid_contract_code": 1, "no_business_day_mapping": 1})
            file.write_bytes(b"producer is replacing the workbook")
            self.assertEqual(frozen_inputs, {entry["sha256"]: original})
            lines = []
            describe_inputs(lines.append, result, info, end, {"kind": "sqlite", "path": "market.sqlite"})
            report = "\n".join(lines)
            for expected in ("使用表日实际合约映射 1", "G列缺失或无有效缓存 1", "缺表日映射 1",
                             "实际合约代码异常 1", "01-02 至 01-05"):
                self.assertIn(expected, report)

    def test_pending_contract_in_workbook_older_than_report_window(self):
        from index_futures_basis.recent_brief.data import load_market
        from index_futures_basis.store import Store

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            business_day, observation = "2025-09-30", "2025-10-09"
            store = Store(root / "market.sqlite")
            store.save_calendar(business_day, observation, {business_day, observation})
            store.save_rows("mapping", [
                (business_day, "IF", 2, "IF2510.CFE"),
                (business_day, "IF", 3, "IF2511.CFE"),
                (business_day, "IF", 4, "IF2511.CFE"),  # ambiguous source-day mapping
                ("2025-10-01", "IF", 4, "IF2512.CFE"),  # non-trading day
                (observation, "IF", 1, "IF2510.CFE"),
                (observation, "IF", 2, "IF2511.CFE"),
            ])
            store.save_rows("contracts", [("IF2510.CFE", "2025-10-17")])
            store.save_rows("quotes", [("IF2510.CFE", observation, "close", 1010),
                                       ("000300.SH", observation, "close", 1000)])
            earlier = {}
            p, _, _, cfg, paths = load_market(database=store.path, as_of="2026-11-20",
                                               earlier_mappings=earlier)
            cfg["dividends"].update(estimate_from_previous_contract=False, interpolate_history=False)
            self.assertEqual(earlier, {(business_day, "IF01.CFE"): "IF2510.CFE"})
            self.assertEqual(p.trade_date.min(), pd.Timestamp(observation))
            file = root / "archived.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "Sheet1"
            sheet["B1"], sheet["G3"] = business_day, "分红"
            sheet["B4"], sheet["C4"], sheet["G4"] = "IF01.CFE", "Fetching...", 5
            sheet["B5"], sheet["C5"], sheet["G5"] = "IF02.CFE", "IF02.CFE", 9
            book.save(file)
            book.close()

            result, info = adjust(p, cfg, paths, file, earlier_mappings=earlier)
            matched = result.loc[result.dividend_points.notna()].iloc[0]
            self.assertEqual(matched.instrument_id, "IF2510.CFE")
            self.assertEqual(matched.dividend_source_date, pd.Timestamp(business_day))
            self.assertEqual(matched.basis_points, 15)
            self.assertEqual(info["input_inventory"][0]["bound_rows"], 1)
            self.assertEqual(info["input_inventory"][0]["rejected_rows"], {"no_business_day_mapping": 1})

    def test_estimates_use_latest_known_observation_of_closest_earlier_contract(self):
        from index_futures_basis.recent_brief.data import session_quantiles
        from index_futures_basis.recent_brief.diagnostics import describe_inputs

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def save(name, day, values):
                book = Workbook()
                sheet = book.active
                sheet.title = "Sheet1"
                sheet["B1"], sheet["G3"] = day, "分红"
                for slot, (contract, points) in enumerate(values):
                    row = slot + 4
                    sheet[f"B{row}"], sheet[f"C{row}"], sheet[f"G{row}"] = f"{contract[:2]}0{slot}.CFE", contract, points
                book.save(root/name)
                book.close()

            save("older.xlsx", "2026-01-02", [("IF2601.CFE", 7), ("IF2605.CFE", 20), ("IH2603.CFE", 90)])
            save("near.xlsx", "2026-01-02 15:30:00", [("IF2602.CFE", 3)])
            save("direct.xlsx", "2026-01-05", [("IF2604.CFE", 0)])
            result, info = adjust(panel(), {"dividends": {}}, None, root)
            first, latest = (result[result.trade_date.eq(day)].set_index("instrument_id")
                             for day in result.trade_date.unique())
            self.assertEqual(first.loc["IF2603.CFE", "dividend_source_contract"], "IF2601.CFE")
            self.assertEqual(first.loc["IF2603.CFE", "dividend_points"], 7)
            self.assertEqual(latest.loc["IF2603.CFE", "dividend_source_contract"], "IF2602.CFE")
            self.assertEqual(latest.loc["IF2603.CFE", "dividend_points"], 3)
            self.assertTrue(latest.loc["IF2603.CFE", "dividend_is_estimated"])
            self.assertEqual(latest.loc["IF2604.CFE", "dividend_points"], 0)
            self.assertFalse(latest.loc["IF2604.CFE", "dividend_is_estimated"])
            self.assertEqual(latest.loc["IF2605.CFE", "dividend_points"], 20)
            ranks = session_quantiles(result, result.trade_date.max(), "slot", sessions=1).set_index("slot")
            self.assertEqual(ranks.loc[2, "estimated_sample_n"], 1)
            self.assertTrue(ranks.loc[2, "current_dividend_is_estimated"])
            self.assertTrue(ranks.loc[2, "complete"])
            lines = []
            describe_inputs(lines.append, result, info, result.trade_date.max(),
                            {"kind": "sqlite", "path": "market.sqlite"})
            self.assertIn("IF2603.CFE ← IF2602.CFE 1", "\n".join(lines))

    def test_dividend_interpolation_keeps_anchors_and_holds_active_contract_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for day, points in (("2026-01-02", (10, 8, 6)), ("2026-01-06", (2, None, None)),
                                ("2026-01-12", (80, 90, None))):
                book = Workbook()
                sheet = book.active
                sheet.title = "Sheet1"
                sheet["B1"], sheet["G3"] = day, "分红"
                for slot, (contract, value) in enumerate(zip(("IF2603.CFE", "IF2604.CFE", "IF2606.CFE"), points), 1):
                    row = slot + 3
                    sheet[f"B{row}"], sheet[f"C{row}"], sheet[f"G{row}"] = f"IF0{slot-1}.CFE", contract, value
                book.save(root/f"{day}.xlsx")
                book.close()

            days = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-09"])
            p = pd.concat([panel().head(4).assign(trade_date=day) for day in days], ignore_index=True)
            p.loc[p.slot.eq(2), "expiry_date"] = pd.Timestamp("2026-01-09")
            p.loc[p.slot.eq(4), "instrument_id"] = "IF2607.CFE"
            result, info = adjust(p, {"dividends": {}}, None, root)
            matured = result[result.instrument_id.eq("IF2603.CFE")].set_index("trade_date")
            self.assertEqual(matured.loc[days[0], "dividend_points"], 10)
            self.assertEqual(matured.loc[days[1], "dividend_points"], 4)
            self.assertEqual(matured.loc[days[2], "dividend_points"], 2)
            self.assertEqual(matured.loc[days[-1], "dividend_points"], 0)
            self.assertEqual(matured.loc[days[1], "dividend_end_date"], days[2])
            self.assertEqual(matured.loc[days[1], "dividend_interpolation"], "between_snapshots")
            self.assertTrue(matured.loc[days[1], "dividend_end_source_sha256"])
            self.assertEqual(matured.loc[days[3], "dividend_interpolation"], "to_expiry")
            active = result[result.instrument_id.eq("IF2604.CFE")]
            self.assertTrue(active.dividend_points.eq(8).all())
            self.assertFalse(active.dividend_is_estimated.any())
            proxy = result[result.instrument_id.eq("IF2607.CFE")]
            self.assertTrue(proxy.dividend_source_contract.eq("IF2606.CFE").all())
            self.assertTrue(proxy.dividend_points.eq(6).all())
            self.assertEqual(info["adjustment_audit"]["interpolated_dividend_rows"], 3)
            self.assertFalse(any(item["snapshot_date"] == "2026-01-12" for item in info["files"]))

    def test_three_stage_path_and_current_oi_high_position(self):
        values=-np.r_[np.linspace(10,70,20),np.linspace(70,10,20),np.linspace(10,45,20)]
        self.assertEqual(classify_path(values,60)['shape'],'widen_narrow_widen')
        p=self.history()
        p['open_interest']=p.open_interest.astype(float)
        days=sorted(p.trade_date.unique())
        p.loc[p.root.eq('IC') & p.trade_date.eq(days[-1]),'open_interest'] *= 1.15
        report=self.compose(p)
        self.assertIn('IC四合约总持仓处于近期高位',report['text'])
        self.assertNotIn('对冲需求显著',report['text'])
        json.dumps(report,allow_nan=False)

    def test_common_annual_state_and_next_month_are_not_hardcoded_to_reference(self):
        p=self.history()
        end=p.trade_date.max()
        p.loc[p.trade_date.eq(end) & p.slot.gt(1),'annualized_basis_pct']=-50.
        result=self.compose(p)
        self.assertTrue(all(r['all']['percentile']==0 for r in result['annualized']['current_groups']['products']))
        self.assertIn('四品种次月合约年化贴水扩大',result['sections'][0]['text'])
        self.assertEqual(len(result['annualized']['selected']),1)
        p.loc[p.trade_date.eq(end),'roll_day']=True
        result=self.compose(p)
        self.assertEqual(result['annualized']['current_groups']['selected_changes'],[])
        self.assertEqual(result['annualized']['next_month_changes'],[])


if __name__ == "__main__":
    unittest.main()
