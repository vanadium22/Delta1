"""Independent arithmetic and cached-data browsing, with no Wind or dividend dependency."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from index_futures_basis.service import BasisService, ROOTS
from index_futures_basis.report import plot_all, chart_catalog
from index_futures_basis.market_view import export_market_data


class ValuationMarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = BasisService(self.root, "demo")

    def tearDown(self):
        self.temp.cleanup()

    def test_raw_formula_terms_quantiles_and_cache_are_independent_of_dividends(self):
        adjusted = self.service.analyze()
        quotes = self.service.store.quotes("2020-01-01", "2030-01-01")
        with patch.object(self.service, "dividend_input", side_effect=AssertionError("dividends")), \
             patch("index_futures_basis.service.WindProvider", side_effect=AssertionError("network")):
            raw = self.service.analyze(valuation="raw")
            self.assertIs(raw, self.service.analyze(valuation="raw"))
        self.assertNotEqual(raw.fingerprint, adjusted.fingerprint)
        p = raw.panel
        np.testing.assert_allclose(p.basis_points, p.futures_close - p.spot_close)
        np.testing.assert_allclose(adjusted.panel.basis_points - p.basis_points, adjusted.panel.dividend_points, atol=1e-10)
        expected = ((p.futures_close / p.spot_close - 1) * 36500 / p.days_to_expiry).where(p.days_to_expiry.ge(5))
        np.testing.assert_allclose(p.annualized_basis_pct, expected, equal_nan=True, atol=1e-10)
        self.assertTrue(p.dividend_points.isna().all())
        self.assertTrue(p.dividend_adjustment_points.eq(0).all())
        np.testing.assert_allclose(raw.totals.open_interest, adjusted.totals.open_interest)
        for row in raw.calendar_annualized.itertuples():
            day = p[p.trade_date.eq(row.trade_date) & p.root.eq(row.root)].set_index("instrument_id")
            points = day.loc[row.far_contract, "futures_close"] - day.loc[row.near_contract, "futures_close"]
            self.assertAlmostEqual(row.spread_points, points)
            self.assertAlmostEqual(row.annualized_basis_pct, points / row.spot_close * 36500 / row.expiry_gap_days)
        row = raw.fixed.dropna(subset=["annualized_basis_pct"]).iloc[-1]
        day = p[p.trade_date.eq(row.trade_date) & p.root.eq(row.root)].set_index("instrument_id")
        rates = day.futures_close / day.spot_close - 1
        value = row.left_weight * rates[row.left_contract] + (1-row.left_weight) * rates[row.right_contract]
        self.assertAlmostEqual(row.annualized_basis_pct, value * 36500 / 60)
        q = raw.calendar_point_quantiles.iloc[0]
        s = raw.calendar_annualized
        history = s.loc[s.root.eq(q.root) & s.pair.eq(q.pair)
            & s.trade_date.ge(raw.end - pd.DateOffset(months=q.months)) & s.trade_date.lt(raw.end), "spread_points"]
        self.assertAlmostEqual(q.p50, history.median())
        self.assertAlmostEqual(q.percentile, ((history < q.current).sum() + .5*(history == q.current).sum()) / len(history)*100)
        self.assertEqual(self.service.store.quotes("2020-01-01", "2030-01-01"), quotes)

    def test_all_raw_chart_titles_and_exports_identify_the_selected_formula(self):
        from matplotlib.figure import Figure
        a = self.service.analyze(valuation="raw")
        seen = {}
        def capture(fig, path, **kwargs):
            seen[Path(path).stem] = "\n".join([t.get_text() for t in fig.texts] +
                [ax.get_title(loc=loc) for ax in fig.axes for loc in ("left", "center", "right")])
        with patch.object(Figure, "savefig", capture):
            plot_all(a.panel, a.fixed, a.spread, a.start, a.end, self.root / "plots", ROOTS,
                a.annual_quantiles, a.cross, a.cross_quantiles, valuation="raw",
                terms=(a.fixed90, a.fixed90_quantiles, a.calendar_annualized, a.calendar_quantiles),
                fixed_quantiles=a.fixed_quantiles, calendar_point_quantiles=a.calendar_point_quantiles)
        self.assertEqual(len(seen), len(chart_catalog()))
        for name, text in seen.items():
            self.assertTrue(name.endswith("__不调整分红"), name)
            self.assertIn("不调整分红", text, name)
            self.assertNotIn("分红调整后", text, name)
        folder = Path(self.service.export("data", valuation="raw"))
        manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["valuation"], "raw")
        self.assertEqual(manifest["basis_formula"], "futures_close - spot_close")
        self.assertFalse((folder / "dividend_input_snapshot.xlsx").exists())
        frame = pd.read_csv(folder / "adjusted_panel.csv")
        np.testing.assert_allclose(frame.basis_points, frame.futures_close - frame.spot_close)

    def test_raw_query_and_separate_saved_chart_choice(self):
        self.service.save_valuation("figures", "raw")
        loaded = BasisService(self.root, "demo")
        self.assertEqual(loaded.output_valuation("figures"), "raw")
        self.assertEqual(loaded.output_valuation("query"), "adjusted")
        with patch.object(loaded, "dividend_input", side_effect=AssertionError("dividends")):
            raw = loaded.query("IC", 4, "basis_points", valuation="raw")
            price = loaded.query("IC", 4, "futures_close")
        self.assertIn("未调整分红", raw["title"])
        self.assertEqual(price["current"], price["series"].loc[price["series"].trade_date.eq(price["actual_end"]), "value"].iloc[0])

    def test_cached_quotes_filter_by_alias_and_survive_missing_mapping_or_fields(self):
        day = "2026-10-08"
        actual = self.service.store.mappings(day, day)[(day, "IC", 1)]
        with self.service.store.connection() as con:
            con.execute("DELETE FROM quotes WHERE day=? AND code=? AND field='oi'", (day, actual))
        with patch.object(self.service, "dividend_input", side_effect=AssertionError("dividends")), \
             patch("index_futures_basis.service.WindProvider", side_effect=AssertionError("network")):
            result = self.service.local_market_data(root="IC", code="ic00.cfe", start=day, end=day)
            self.assertEqual(len(result["data"]), 1)
            row = result["data"].iloc[0]
            self.assertEqual(row.code, actual)
            self.assertTrue(pd.isna(row.open_interest))
            self.assertTrue(pd.notna(row.close))
            with self.service.store.connection() as con:
                con.execute("DELETE FROM mapping WHERE root='IC'")
                con.execute("DELETE FROM contracts WHERE code LIKE 'IC%'")
            result = self.service.local_market_data(root="IC", start=day, end=day)
        self.assertEqual(len(result["data"]), 5)
        self.assertIn("000905.SH", set(result["data"].code))
        self.assertTrue(result["data"].continuous_code.eq("").all())
        spot = self.service.local_market_data(root="IC", kind="spot", start=day, end=day)
        self.assertEqual(list(spot["data"].code), ["000905.SH"])
        folder = Path(export_market_data(result, self.root / "exports"))
        manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["network_requests"], 0)
        self.assertEqual(len(pd.read_csv(folder / "data.csv")), 5)

    def test_browsing_uses_real_offline_source_when_wind_cache_is_empty(self):
        from index_futures_basis.demo import snapshot
        offline = BasisService(self.root, "offline")
        offline.store.import_raw(snapshot(), {"kind": "test imported source"})
        live = BasisService(self.root, "wind")
        with patch("index_futures_basis.service.WindProvider", side_effect=AssertionError("network")):
            result = live.local_market_data(kind="spot", end="2026-10-08")
        self.assertEqual(result["provenance"]["source_database"], str(offline.store.path))
        self.assertEqual(set(result["data"].root), set(ROOTS))
        empty = BasisService(self.root / "empty", "wind").local_market_data()
        self.assertTrue(empty["data"].empty)
        self.assertIsNone(empty["provenance"]["actual_end"])
