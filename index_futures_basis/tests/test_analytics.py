"""Tests with explicit synthetic dividend fixtures, not investment data."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from index_futures_basis.analytics import (attach_dividends, fixed_tenor, historical_summary, read_dividends,
                           spreads, total_oi, validate_panel)
from index_futures_basis.wind_worker import series, perform


def sample_panel():
    rows = []
    for day in pd.date_range("2026-07-06", periods=3, freq="B"):
        for slot, expiry in enumerate(["2026-07-17", "2026-08-21", "2026-09-18", "2026-12-18"], 1):
            rows.append({"trade_date": day, "root": "IF", "slot": slot,
                         "instrument_id": "IF26" + expiry[5:7] + ".CFE", "expiry_date": expiry,
                         "futures_close": 4000 - 10 * slot, "spot_close": 4000,
                         "open_interest": 1000 * slot + (day.day - 6) * 10})
    return validate_panel(pd.DataFrame(rows), ["IF"])


def dividend_fixture(panel):
    return pd.DataFrame({"trade_date": panel.trade_date, "code": panel.continuous_code,
                         "dividend_points": panel.slot * 15.0})


class CalculationTests(unittest.TestCase):
    def test_static_snapshot_matches_slots_and_is_explicit(self):
        p = sample_panel()
        d = pd.DataFrame({"trade_date": pd.Timestamp("2026-09-18"),
                          "code": ["IF00.CFE", "IF01.CFE", "IF02.CFE", "IF03.CFE"],
                          "dividend_points": [0.0, 2.5, 16.5, 16.5]})
        a = attach_dividends(p, d, p.trade_date.min(), application="snapshot_continuous")
        np.testing.assert_allclose(a.dividend_points, np.tile([0, 2.5, 16.5, 16.5], 3))
        self.assertTrue(a.dividend_source_date.eq(pd.Timestamp("2026-09-18")).all())
        self.assertTrue(a.dividend_application.eq("fixed_snapshot_scenario").all())
        # The same single-date file may not silently become a daily forecast history.
        with self.assertRaisesRegex(ValueError, "缺少"):
            attach_dividends(p, d, p.trade_date.min())
        self.assertAlmostEqual(spreads(a).iloc[1].dividend_difference, 16.5)

    def test_static_snapshot_rejects_duplicates_and_incomplete_slots(self):
        p = sample_panel()
        d = pd.DataFrame({"trade_date": pd.Timestamp("2026-09-18"),
                          "code": ["IF00.CFE", "IF01.CFE", "IF02.CFE"],
                          "dividend_points": [0.0, 2.5, 16.5]})
        with self.assertRaisesRegex(ValueError, "缺少"):
            attach_dividends(p, d, p.trade_date.min(), application="snapshot_continuous")
        with self.assertRaisesRegex(ValueError, "重复键"):
            attach_dividends(p, pd.concat([d, d.iloc[:1]]), p.trade_date.min(), application="snapshot_continuous")

    def test_supplied_snapshot_reads_g_not_j_or_mismatched_expiry(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "指数基差情况_2026-09-18.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "Sheet1"
            sheet["B1"], sheet["G3"] = pd.Timestamp("2026-09-18").to_pydatetime(), "分红"
            codes = [f"{root}0{s}.CFE" for root in ("IF", "IC", "IM", "IH") for s in range(4)]
            for row, code in enumerate(codes, 4):
                sheet.cell(row, 2, code)
                sheet.cell(row, 3, "wrong-actual-contract")
                sheet.cell(row, 5, "1900-01-01")
                sheet.cell(row, 7, float(row))
                sheet.cell(row, 10, 999)
            book.save(source)
            book.close()
            config = {"file": str(source), "sheet": "Sheet1", "header_row": 3,
                      "layout": "snapshot_continuous", "snapshot_date_cell": "B1"}
            d, info = read_dividends(config, directory)
            self.assertEqual(d.set_index("code").loc["IF02.CFE", "dividend_points"], 6)
            self.assertEqual(info["cells"]["IF02.CFE"], "Sheet1!G6")
            self.assertEqual(info["snapshot_date"], "2026-09-18")
            self.assertEqual(info["historical_type"], "fixed_snapshot_scenario")
            self.assertEqual(len(d), 16)

    def test_dividends_enter_price_before_all_calculations(self):
        p = sample_panel()
        a = attach_dividends(p, dividend_fixture(p), p.trade_date.min())
        self.assertEqual(a.iloc[0].adjusted_futures_close, 4005)
        np.testing.assert_allclose(a.basis_points, a.slot * 5)
        np.testing.assert_allclose(a.annualized_basis_pct, a.slot * 5 / 4000 * 36500 / a.days_to_expiry)
        s = spreads(a)
        self.assertEqual(s.iloc[0].spread_points, 5)
        self.assertEqual(s.iloc[0].raw_spread_points, -10)
        np.testing.assert_allclose(s.spread_points, s.raw_spread_points + s.dividend_difference)

    def test_missing_dividend_never_zero_or_forward_filled(self):
        p = sample_panel()
        with self.assertRaisesRegex(ValueError, "缺少 1 条分红"):
            attach_dividends(p, dividend_fixture(p).iloc[1:], p.trade_date.min())

    def test_conflicting_concrete_and_continuous_dividend(self):
        p = sample_panel()
        d = dividend_fixture(p)
        d.loc[len(d)] = [p.iloc[0].trade_date, p.iloc[0].instrument_id, 99]
        with self.assertRaisesRegex(ValueError, "分红冲突"):
            attach_dividends(p, d, p.trade_date.min())

    def test_near_expiry_keeps_points_and_gaps_annualization(self):
        p = sample_panel()
        p.loc[p.slot.eq(1), "days_to_expiry"] = [4, 1, 0]
        a = attach_dividends(p, dividend_fixture(p), p.trade_date.min())
        self.assertTrue(a.loc[a.slot.eq(1), "annualized_plot_pct"].isna().all())
        self.assertTrue(a.loc[a.slot.eq(1), "basis_points"].eq(5).all())

    def test_near_expiry_flat_line_is_display_only(self):
        p = sample_panel()
        p.loc[p.slot.eq(1), "days_to_expiry"] = [5, 1, 0]
        a = attach_dividends(p, dividend_fixture(p), p.trade_date.min())
        g = a[a.slot.eq(1)]
        expected = 5 / 4000 * 36500 / 5
        np.testing.assert_allclose(g.annualized_plot_pct, [expected] * 3)
        self.assertTrue(g.annualized_basis_pct.iloc[1:].isna().all())
        self.assertEqual(g.annualized_plot_filled.tolist(), [False, True, True])
        self.assertTrue(g.basis_points.eq(5).all())
        history = historical_summary(a, a.trade_date.max())
        self.assertTrue(history.loc[history.slot.eq(1), "current"].isna().all())

    def test_near_expiry_flat_line_resets_on_roll(self):
        p = sample_panel()
        near = p.slot.eq(1)
        p.loc[near, "days_to_expiry"] = [5, 1, 30]
        # No valid observation yet for the newly mapped contract on the second day.
        p.loc[near & p.trade_date.gt(p.trade_date.min()), "instrument_id"] = "IF2701.CFE"
        p.loc[near & p.trade_date.gt(p.trade_date.min()), "expiry_date"] = pd.Timestamp("2027-01-15")
        a = attach_dividends(p, dividend_fixture(p), p.trade_date.min())
        g = a[a.slot.eq(1)]
        self.assertTrue(np.isnan(g.annualized_plot_pct.iloc[1]))
        self.assertEqual(g.annualized_plot_pct.iloc[2], g.annualized_basis_pct.iloc[2])
        self.assertFalse(g.annualized_plot_filled.any())

    def test_fixed_tenor_interpolates_rate_before_annualizing(self):
        p = sample_panel()
        a = attach_dividends(p, dividend_fixture(p), p.trade_date.min())
        g = a[a.trade_date.eq(a.trade_date.min())]
        left, right = g.iloc[1], g.iloc[2]
        w = (right.days_to_expiry - 60) / (right.days_to_expiry - left.days_to_expiry)
        expected = (w * left.basis_rate + (1-w) * right.basis_rate) * 36500 / 60
        self.assertAlmostEqual(fixed_tenor(a).iloc[0].annualized_basis_pct, expected)
        a.loc[(a.trade_date == a.trade_date.min()) & (a.slot == 2), "basis_rate"] = np.nan
        self.assertTrue(np.isnan(fixed_tenor(a).iloc[0].annualized_basis_pct))

    def test_roll_oi_uses_same_contract_not_previous_slot(self):
        p = sample_panel().iloc[:8].copy()
        day = p.trade_date.max()
        current = p.trade_date.eq(day)
        p.loc[current, "instrument_id"] = ["IF2608.CFE", "IF2609.CFE", "IF2612.CFE", "IF2703.CFE"]
        p.loc[current, "open_interest"] = [2015, 3015, 4015, 100]
        a = attach_dividends(p, dividend_fixture(p), p.trade_date.min())
        np.testing.assert_allclose(a.loc[current, "oi_change"].iloc[:3], [15, 15, 15])
        self.assertTrue(np.isnan(a.loc[current, "oi_change"].iloc[3]))
        self.assertTrue(a.loc[current, "roll_day"].all())
        self.assertEqual(total_oi(a).iloc[-1].oi_change, -855)

    def test_incomplete_history_cannot_be_called_one_year(self):
        p = sample_panel()
        a = attach_dividends(p, dividend_fixture(p), p.trade_date.min())
        history = historical_summary(a, a.trade_date.max())
        self.assertFalse(history.complete.any())
        self.assertTrue(history["mean"].isna().all())

    def test_duplicate_missing_calendar_and_wrong_expiry_fail(self):
        p = sample_panel()
        with self.assertRaisesRegex(ValueError, "重复键"):
            validate_panel(pd.concat([p, p.iloc[:1]]), ["IF"])
        with self.assertRaisesRegex(ValueError, "行情不完整"):
            validate_panel(p[p.trade_date.ne(p.trade_date.iloc[0])], ["IF"], p.trade_date.unique())
        p.loc[p.slot.eq(3), "expiry_date"] = pd.Timestamp("2026-08-01")
        with self.assertRaisesRegex(ValueError, "未严格递增"):
            validate_panel(p, ["IF"])

    def test_excel_mapping_and_missing_formula_cache(self):
        # Minimal cached-value fixture; source workbooks are never modified.
        p = sample_panel()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            d = dividend_fixture(p).rename(columns={"trade_date": "日期", "code": "合约", "dividend_points": "分红"})
            d.to_csv(path, index=False, encoding="utf-8-sig")
            result, info = read_dividends({"file": str(path)}, directory)
            self.assertEqual(len(result), 12)
            self.assertEqual(info["unit"], "index_points")
            d.loc[0, "分红"] = np.nan
            d.to_csv(path, index=False, encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "空值不等于零"):
                read_dividends({"file": str(path)}, directory)


def response(fields, data, times=None, codes=None, error=0):
    return SimpleNamespace(ErrorCode=error, Fields=fields, Data=data, Times=times or [], Codes=codes or [])


class FakeWind:
    def start(self, **kwargs):
        return response([], [])

    def tdays(self, start, end, options):
        return response([], [[pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-07")]])

    def wsd(self, code, fields, start, end, options):
        times = [pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-07")]
        if fields == "trade_hiscode":
            contract = ["IF2607", "IF2608", "IF2609", "IF2612"][int(code[2:4])]
            return response(["TRADE_HISCODE"], [[contract, contract]], times)
        if fields == "close,oi":
            return response(["OI", "CLOSE"], [[1000, 1010], [3990, 3995]], times)
        return response(["CLOSE"], [[4000, 4005]], times)

    def wss(self, codes, field, options):
        codes = codes.split(",")[::-1]
        dates = {"IF2607.CFE": "2026-07-17", "IF2608.CFE": "2026-08-21",
                 "IF2609.CFE": "2026-09-18", "IF2612.CFE": "2026-12-18"}
        return response(["LASTTRADE_DATE"], [[dates[c] for c in codes]], codes=codes)


class WindContractTests(unittest.TestCase):
    def test_field_and_code_order_are_matched_by_name(self):
        result = series(FakeWind(), "IF2607.CFE", ["close", "oi"], "2026-07-06", "2026-07-07")
        self.assertEqual(result["2026-07-06"]["oi"], 1000)
        self.assertEqual(result["2026-07-06"]["close"], 3990)
        expiry = perform(FakeWind(), {"operation": "expiries", "codes": ["IF2607.CFE", "IF2608.CFE"], "field": "lasttrade_date"})
        self.assertEqual(expiry["IF2607.CFE"], "2026-07-17")

    def test_wind_errors_and_missing_data_are_not_fallbacks(self):
        class ErrorWind(FakeWind):
            def wsd(self, *args):
                return response([], [], error=-40522017)
        with self.assertRaisesRegex(RuntimeError, "-40522017"):
            series(ErrorWind(), "IF00.CFE", ["trade_hiscode"], "2026-07-06", "2026-07-07", "")



if __name__ == "__main__":
    unittest.main()
