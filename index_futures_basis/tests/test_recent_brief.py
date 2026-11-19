"""Numerical and evidence-boundary checks for the separate three-picture brief."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np
import pandas as pd

from index_futures_basis.analytics import attach_dividends
from index_futures_basis.recent_brief.data import (ReadOnlyStore, activity_totals, add_volumes, calendar_series,
    change, load_market, quantiles, session_quantiles)
from index_futures_basis.recent_brief.brief import explanations


def panel():
    rows = []
    for day in pd.to_datetime(["2026-01-02", "2026-01-05"]):
        for slot in range(1, 5):
            rows.append({"trade_date": day, "root": "IF", "slot": slot,
                         "instrument_id": f"IF26{slot+1:02d}.CFE", "expiry_date": pd.Timestamp(f"2026-{slot+1:02d}-20"),
                         "days_to_expiry": 30*slot, "futures_close": 1000-10*slot,
                         "spot_close": 1000, "open_interest": 100*slot + (day.day == 5)*10,
                         "continuous_code": f"IF{slot-1:02d}.CFE", "calendar_known": True, "volume": 20*slot})
    raw = pd.DataFrame(rows)
    dividends = pd.DataFrame({"trade_date": [pd.Timestamp("2025-12-31")]*4,
                             "code": [f"IF{i:02d}.CFE" for i in range(4)], "dividend_points": [1,3,6,10]})
    return attach_dividends(raw, dividends, raw.trade_date.min(), "snapshot_continuous")


class RecentBriefTests(unittest.TestCase):
    def test_adjusted_absolute_and_literal_calendar_sign(self):
        p = panel()
        np.testing.assert_allclose(p[p.trade_date.eq(p.trade_date.max())].basis_points, [-9,-17,-24,-30])
        spreads = calendar_series(p)
        values = spreads[spreads.trade_date.eq(p.trade_date.max())].set_index("pair").basis_points
        self.assertEqual(values["02−01"], -7)
        self.assertEqual(values["03−02"], -6)
        self.assertEqual(set(values.index), {"02−01", "03−02"})

    def test_cross_points_do_not_require_spot(self):
        p = panel()
        p["spot_close"] = np.nan
        p["basis_points"] = np.nan
        self.assertTrue(calendar_series(p).basis_points.notna().all())
        self.assertTrue(calendar_series(p).annualized_basis_pct.isna().all())

    def test_calendar_annualization_uses_spot_and_actual_expiry_gap(self):
        p = panel()
        spreads = calendar_series(p)
        row = spreads[spreads.pair.eq("02−01")].iloc[-1]
        expected = -7 / 1000 * 36500 / (pd.Timestamp("2026-04-20") - pd.Timestamp("2026-03-20")).days
        self.assertAlmostEqual(row.annualized_basis_pct, expected)
        legs = p[p.trade_date.eq(p.trade_date.max())].set_index("slot")
        self.assertNotAlmostEqual(row.annualized_basis_pct,
                                 legs.loc[3, "annualized_basis_pct"]-legs.loc[2, "annualized_basis_pct"])
        p.loc[p.slot.eq(3), "expiry_date"] = pd.NaT
        missing = calendar_series(p)
        self.assertTrue(missing.basis_points.notna().all())
        self.assertTrue(missing.annualized_basis_pct.isna().all())

    def test_missing_dividend_leg_does_not_become_zero(self):
        p = panel()
        p.loc[p.slot.eq(3), "adjusted_futures_close"] = np.nan
        self.assertTrue(calendar_series(p).basis_points.isna().all())

    def history(self):
        days = pd.date_range("2025-01-01", "2026-01-05", freq="D")
        return pd.DataFrame({"trade_date": days, "root": "IF", "slot": 2,
                             "basis_points": 10., "calendar_known": True})

    def test_quantiles_exclude_current_and_half_weight_ties(self):
        p = self.history()
        q = quantiles(p, p.trade_date.max(), "slot")
        self.assertTrue(q.complete.all())
        self.assertTrue(q.percentile.eq(50).all())
        p.loc[p.index[-1], "basis_points"] = 10000
        q = quantiles(p, p.trade_date.max(), "slot")
        self.assertTrue(q.p95.eq(10).all())
        self.assertTrue(q.percentile.eq(100).all())

    def test_missing_or_unknown_calendar_invalidates_window(self):
        for column, value in [("basis_points", np.nan), ("calendar_known", False)]:
            p = self.history()
            p.loc[p.index[-3], column] = value
            q = quantiles(p, p.trade_date.max(), "slot")
            self.assertFalse(q.complete.any())
            self.assertTrue(q.p50.isna().all())

    def test_short_history_does_not_claim_twelve_months(self):
        p = self.history().tail(110)
        q = quantiles(p, p.trade_date.max(), "slot").set_index("months")
        self.assertTrue(q.loc[3, "complete"])
        self.assertFalse(q.loc[12, "complete"])

    def annual_history(self):
        days = pd.bdate_range("2025-01-01", periods=100)
        return pd.DataFrame({"trade_date": days, "root": "IF", "slot": 2,
                             "annualized_basis_pct": 1., "days_to_expiry": 30., "calendar_known": True})

    def test_sixty_sessions_excludes_current_and_weights_ties(self):
        p = self.annual_history()
        end = p.trade_date.max()
        row = session_quantiles(p, end, "slot").iloc[0]
        self.assertEqual(row.n, 60)
        self.assertEqual(row.percentile, 50)
        self.assertEqual(row.window_start, p.trade_date.iloc[-61])
        self.assertEqual(row.sample_end, p.trade_date.iloc[-2])
        p.loc[p.index[-1], "annualized_basis_pct"] = 10000
        row = session_quantiles(p, end, "slot").iloc[0]
        self.assertEqual(row.p95, 1)
        self.assertEqual(row.percentile, 100)

    def test_sixty_session_window_does_not_use_short_or_missing_history(self):
        for field, value in [("calendar_known", False), ("annualized_basis_pct", np.nan)]:
            p = self.annual_history()
            p.loc[p.index[-3], field] = value
            row = session_quantiles(p, p.trade_date.max(), "slot").iloc[0]
            self.assertFalse(row.complete)
            self.assertTrue(np.isnan(row.p50))
        p = self.annual_history().tail(60)  # Only 59 prior sessions.
        self.assertFalse(session_quantiles(p, p.trade_date.max(), "slot").iloc[0].complete)

    def test_expiry_day_excluded_but_missing_expiry_not_discarded(self):
        p = self.annual_history()
        p.loc[p.index[-3], ["days_to_expiry", "annualized_basis_pct"]] = [0, np.nan]
        p["annualized_plot_pct"] = 9999  # Display fills must not enter the candle sample.
        row = session_quantiles(p, p.trade_date.max(), "slot").iloc[0]
        self.assertTrue(row.complete)
        self.assertEqual(row.n, 59)
        self.assertEqual(row.expiry_day_excluded_n, 1)
        self.assertEqual(row.p95, 1)
        p.loc[p.index[-3], "days_to_expiry"] = np.nan
        self.assertFalse(session_quantiles(p, p.trade_date.max(), "slot").iloc[0].complete)

    def test_cross_sixty_session_percentile_uses_annualized_values(self):
        p = self.annual_history().drop(columns=["slot", "days_to_expiry"])
        p["pair"] = "02−01"
        p["basis_points"] = -9999.
        row = session_quantiles(p, p.trade_date.max(), "pair").iloc[0]
        self.assertTrue(row.complete)
        self.assertEqual(row.p50, 1)
        self.assertEqual(row.percentile, 50)

    def test_four_contract_totals_do_not_turn_missing_legs_into_partial_sums(self):
        p = panel()
        totals = activity_totals(p)
        self.assertEqual(totals.iloc[-1].volume, 200)
        self.assertEqual(totals.iloc[-1].open_interest, 1040)
        self.assertEqual(totals.iloc[-1].oi_change, 40)
        p.loc[p.index[-1], "volume"] = np.nan
        missing = activity_totals(p).iloc[-1]
        self.assertTrue(np.isnan(missing.volume))
        self.assertEqual(missing.open_interest, 1040)
        p["volume"] = 0
        self.assertTrue(activity_totals(p).volume.eq(0).all())

    def test_change_preserves_missing_and_can_require_same_contract(self):
        p = panel().query("slot == 2").copy()
        p.loc[p.index[0], "basis_points"] = np.nan
        self.assertTrue(np.isnan(change(p, p.trade_date.max())))
        p.loc[p.index[0], "basis_points"] = 1
        p.loc[p.index[-1], "instrument_id"] = "IF2604.CFE"
        self.assertTrue(np.isnan(change(p, p.trade_date.max(), same_contract=True)))

    def test_oi_change_uses_same_actual_contract_on_roll(self):
        p = panel()
        day = p.trade_date.max()
        p.loc[p.trade_date.eq(day) & p.slot.eq(1), "instrument_id"] = "IF2603.CFE"
        p.loc[p.trade_date.eq(day) & p.slot.eq(2), "instrument_id"] = "IF2606.CFE"
        result = attach_dividends(p, pd.DataFrame(), p.trade_date.min(), "not_applied")
        now = result[result.trade_date.eq(day)].set_index("slot")
        self.assertEqual(now.loc[1, "oi_change"], -90)  # 110 minus this contract's prior 200
        self.assertTrue(np.isnan(now.loc[2, "oi_change"]))

    def test_readonly_store_cannot_mutate_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"market.sqlite"
            with sqlite3.connect(path) as con:
                con.execute("CREATE TABLE evidence (value INTEGER)")
            con.close()
            store = ReadOnlyStore(path)
            with store.connection() as con:
                with self.assertRaises(sqlite3.OperationalError):
                    con.execute("INSERT INTO evidence VALUES (1)")

    def test_explicit_cutoff_has_no_carried_prices_and_unknown_gap(self):
        rows = []
        p = panel()
        for root in ("IF", "IH", "IC", "IM"):
            g = p.copy()
            g["root"] = root
            g["instrument_id"] = g.instrument_id.str.replace("IF", root, regex=False)
            rows.extend(g.to_dict("records"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"real_format_fixture.json"
            path.write_text(json.dumps({"source": "unit-test fixture, not market evidence",
                "calendar": ["2026-01-02", "2026-01-05"], "records": rows}, default=str), encoding="utf-8")
            result, cutoff, *_ = load_market(snapshot=path, as_of="2026-01-07")
            self.assertEqual(cutoff, pd.Timestamp("2026-01-07"))
            missing = result[result.trade_date.gt("2026-01-05")]
            self.assertEqual(len(missing), 32)
            self.assertTrue(missing.futures_close.isna().all())
            self.assertFalse(missing.calendar_known.any())

    def test_volume_matches_actual_code_and_day_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = pd.DataFrame({"trade_date": [pd.Timestamp("2026-01-05")],
                                 "instrument_id": ["IF2603.CFE"], "volume": [88.],
                                 "revision": [0], "is_final": [True]})
            part = root/"part.parquet"
            rows.to_parquet(part)
            from index_futures_basis.analytics import sha256
            manifest = {"version": "frozen", "descriptor": {"volume_unit": "contracts"},
                        "parts": [{"frequency": "1d", "trade_date": "2026-01-05",
                                   "instrument_id": "IF2603.CFE", "path": part.name, "sha256": sha256(part)}]}
            mp = root/"manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            (root/"current.json").write_text(json.dumps({"version": "frozen", "manifest": mp.name,
                                                         "sha256": sha256(mp)}), encoding="utf-8")
            p = panel()
            p["volume"] = np.nan
            result, info = add_volumes(p, root)
            self.assertEqual(info["matched_missing_rows"], 1)
            actual = result[result.volume.notna()].iloc[0]
            self.assertEqual(actual.instrument_id, "IF2603.CFE")
            self.assertEqual(actual.trade_date, pd.Timestamp("2026-01-05"))
            self.assertEqual(actual.volume, 88)
            self.assertTrue(p.volume.isna().all())
            mp.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "哈希"):
                add_volumes(p, root)

    def test_volume_threshold_excludes_current(self):
        p = panel()
        days = pd.bdate_range("2025-11-01", periods=22)
        history = []
        for day in days:
            r = p[p.trade_date.eq(p.trade_date.max())].copy()
            r["trade_date"] = day
            r["volume"] = 10 if day != days[-1] else 40
            history.append(r)
        p = pd.concat(history, ignore_index=True)
        q = session_quantiles(p, days[-1], "slot")
        _, table = explanations(p, calendar_series(p), q, days[-1])
        self.assertTrue(table.previous_20_sessions_median.eq(40).all())
        self.assertTrue(table.volume_multiple.eq(4).all())


if __name__ == "__main__":
    unittest.main()
