"""Independent arithmetic, missing-data and query checks for term additions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from index_futures_basis.analytics import attach_dividends, fixed_tenor
from index_futures_basis.service import BasisService
from index_futures_basis.term_structure import annualized_calendar_spreads, term_distributions, term_chart_catalog
from index_futures_basis.tests.test_analytics import sample_panel, dividend_fixture


class TermCalculationTests(unittest.TestCase):
    def setUp(self):
        p = sample_panel()
        self.panel = attach_dividends(p, dividend_fixture(p), p.trade_date.min())

    def test_ninety_days_interpolates_basis_rate_and_traces_both_legs(self):
        day = self.panel.trade_date.min()
        g = self.panel[self.panel.trade_date.eq(day)].set_index("slot")
        # Jul 6 -> Sep 18 = 74 days; Dec 18 = 165 days.
        weight = (165 - 90) / (165 - 74)
        row = fixed_tenor(self.panel, 90).iloc[0]
        expected = (weight * (15 / 4000) + (1-weight) * (20 / 4000)) * 36500 / 90
        self.assertAlmostEqual(row.annualized_basis_pct, expected)
        self.assertAlmostEqual(row.left_weight, weight)
        self.assertEqual(row.left_contract, g.loc[3, "instrument_id"])
        self.assertEqual(row.right_contract, g.loc[4, "instrument_id"])

    def test_exact_maturity_no_extrapolation_and_missing_input_are_distinct(self):
        p = self.panel[self.panel.trade_date.eq(self.panel.trade_date.min())].copy()
        exact = fixed_tenor(p, 74).iloc[0]
        self.assertAlmostEqual(exact.annualized_basis_pct, 15 / 4000 * 36500 / 74)
        self.assertEqual(exact.left_contract, exact.right_contract)
        self.assertFalse(fixed_tenor(p, 200).iloc[0].interpolable)
        p.loc[p.slot.eq(3), "basis_rate"] = np.nan
        missing = fixed_tenor(p, 90).iloc[0]
        self.assertTrue(missing.interpolable)
        self.assertTrue(np.isnan(missing.annualized_basis_pct))

    def test_calendar_annualization_uses_spot_and_expiry_gap_not_outright_rate_difference(self):
        result = annualized_calendar_spreads(self.panel)
        row = result[result.pair.eq("02-00")].iloc[0]
        self.assertEqual(row.expiry_gap_days, 63)
        self.assertEqual(row.raw_spread_points, -20)
        self.assertEqual(row.dividend_difference, 30)
        self.assertAlmostEqual(row.annualized_basis_pct, 10 / 4000 * 36500 / 63)
        other = result[result.pair.eq("03-02")].iloc[0]
        self.assertAlmostEqual(other.annualized_basis_pct, 5 / 4000 * 36500 / 91)
        p = self.panel.copy()
        p.loc[p.slot.eq(1), "annualized_basis_pct"] = np.nan
        p.loc[p.slot.eq(1), "annualized_plot_pct"] = 999
        p.loc[p.slot.eq(1), "expiry_date"] = p.loc[p.slot.eq(1), "trade_date"]
        current = annualized_calendar_spreads(p).iloc[0]
        self.assertAlmostEqual(current.annualized_basis_pct, 10 / 4000 * 36500 / 74)

    def test_calendar_missing_pair_bad_expiry_and_spot_mismatch_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "缺少同日配对"):
            annualized_calendar_spreads(self.panel.iloc[1:])
        p = self.panel.copy()
        p.loc[p.slot.eq(3), "expiry_date"] = pd.Timestamp("2026-07-17")
        with self.assertRaisesRegex(ValueError, "到期日顺序"):
            annualized_calendar_spreads(p)
        p = self.panel.copy()
        p.loc[p.slot.eq(3), "spot_close"] += 1
        with self.assertRaisesRegex(ValueError, "现货收盘值"):
            annualized_calendar_spreads(p)

    def test_six_and_twelve_month_windows_exclude_today_and_unbracketed_only(self):
        g = pd.DataFrame({"root": "IF", "trade_date": pd.to_datetime(
            ["2025-10-01", "2025-10-16", "2026-04-15", "2026-04-16", "2026-07-01", "2026-10-15", "2026-10-16"]),
            "annualized_basis_pct": [-100, 0, 0, 10, 20, np.nan, 20],
            "interpolable": [True, True, True, True, True, False, True]})
        q = term_distributions(g, pd.Timestamp("2026-10-16"), ["root"], "interpolable").set_index("months")
        self.assertEqual(list(q.index), [6, 12])
        self.assertEqual(q.loc[6, "n"], 2)
        self.assertEqual(q.loc[6, "p50"], 15)
        self.assertEqual(q.loc[6, "percentile"], 75)
        self.assertEqual(q.loc[12, "p50"], 5)
        g.loc[5, "interpolable"] = True
        bad = term_distributions(g, pd.Timestamp("2026-10-16"), ["root"], "interpolable")
        self.assertFalse(bad.complete.any())
        self.assertTrue(bad.percentile.isna().all())

    def test_queries_and_single_new_chart_use_same_analyzed_series(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BasisService(Path(directory), "demo")
            with patch("index_futures_basis.service.WindProvider", side_effect=AssertionError("network")):
                a = service.analyze()
                for metric in ("fixed_90d", "calendar_02_00", "calendar_03_02"):
                    q = service.query("IC", 1, metric)
                    self.assertEqual(q["statistics"].months.tolist(), [6, 12])
                    self.assertAlmostEqual(q["current"], service.query("IC", 4, metric)["current"])
                    expected = (a.fixed90_quantiles if metric == "fixed_90d" else
                        a.calendar_quantiles[a.calendar_quantiles.pair.eq(metric.removeprefix("calendar_").replace("_", "-"))])
                    expected = expected[expected.root.eq("IC")]
                    np.testing.assert_allclose(q["statistics"].percentile, expected.percentile)
                chosen = "90天固定期限_近1个月"
                folder = Path(service.export("figures", [chosen]))
            self.assertEqual([p.stem for p in (folder / "figures").glob("*.png")], [chosen])
            self.assertEqual(len(term_chart_catalog()), 9)
