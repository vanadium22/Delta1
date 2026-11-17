"""Card arithmetic, T>=1 rendering, exact marker placement and automatic refresh."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from index_futures_basis.recent_brief.automation import input_fingerprint, watch
from index_futures_basis.recent_brief.card_charts import _candle_panel
from index_futures_basis.recent_brief.data import adjust, session_quantiles
from index_futures_basis.recent_brief.metrics import series_metrics, total_metrics
from index_futures_basis.tests.test_recent_brief import panel


class Cycles:
    def __init__(self, count, observe=lambda: None):
        self.count, self.observe = count, observe

    def is_set(self):
        return self.count <= 0

    def wait(self, _):
        self.observe()
        self.count -= 1


class BriefCardTests(unittest.TestCase):
    def history(self):
        days = pd.bdate_range("2025-01-01", periods=100)
        return pd.DataFrame({"trade_date": days, "root": "IF", "slot": 2,
            "basis_points": np.arange(100.), "annualized_basis_pct": np.arange(100.)/10,
            "days_to_expiry": 1., "calendar_known": True, "instrument_id": "IF2610.CFE", "roll_day": False})

    def test_day_one_calculates_real_annualized_value_and_day_zero_stays_missing(self):
        p = panel()
        p["days_to_expiry"] = 1
        dividends = pd.DataFrame({"trade_date": [pd.Timestamp("2025-12-31")]*4,
            "code": [f"IF{i:02d}.CFE" for i in range(4)], "dividend_points": [1,3,6,10]})
        with patch("index_futures_basis.recent_brief.data.read_dividends", return_value=(dividends, {"application": "snapshot_continuous"})):
            result, _ = adjust(p, {"dividends": {"directories": []}}, None)
            np.testing.assert_allclose(result.annualized_basis_pct, result.basis_points/result.spot_close*36500)
            self.assertFalse(result.annualized_plot_filled.any())
            p["days_to_expiry"] = 0
            expired, _ = adjust(p, {"dividends": {"directories": []}}, None)
            self.assertTrue(expired.annualized_basis_pct.isna().all())
            self.assertTrue(expired.annualized_plot_pct.isna().all())

    def test_day_one_enters_full_sixty_session_sample(self):
        p = self.history()
        q = session_quantiles(p, p.trade_date.max(), "slot").iloc[0]
        self.assertTrue(q.complete)
        self.assertEqual(q.n, 60)
        self.assertEqual(q.expiry_day_excluded_n, 0)

    def test_card_changes_in_points_basis_points_and_rolling_percentiles(self):
        p = self.history()
        p.loc[p.index[-1], "annualized_basis_pct"] = -99
        p.loc[p.index[-3], "roll_day"] = True
        r = series_metrics(p, p.trade_date.max(), "slot").iloc[0]
        self.assertEqual(r.basis_change_1d, 1)
        self.assertEqual(r.basis_change_5d, 5)
        self.assertAlmostEqual(r.annual_change_1d_bp, (-99-9.8)*100)
        self.assertEqual(r.percentile, 0)
        self.assertEqual(r.percentile_change_1d, -100)
        self.assertTrue(r.roll_5d)
        self.assertFalse(r.roll_1d)
        p.loc[p.index[-2], "calendar_known"] = False
        missing = series_metrics(p, p.trade_date.max(), "slot").iloc[0]
        self.assertTrue(np.isnan(missing.basis_change_1d))
        self.assertTrue(np.isnan(missing.percentile_change_1d))

    def test_total_card_relative_change_zero_denominator_and_partial_total(self):
        p = panel()
        p.loc[p.trade_date.eq(p.trade_date.min()), "volume"] = 0
        r = total_metrics(p, p.trade_date.max()).iloc[0]
        self.assertEqual(r.volume_change_1d, 200)
        self.assertTrue(np.isnan(r.volume_change_1d_pct))
        self.assertEqual(r.oi_change_1d, 40)
        self.assertAlmostEqual(r.oi_change_1d_pct, 4)
        p.loc[p.index[-1], "open_interest"] = np.nan
        missing = total_metrics(p, p.trade_date.max()).iloc[0]
        self.assertTrue(np.isnan(missing.oi_current))
        self.assertTrue(np.isnan(missing.oi_change_1d))

    def test_current_diamonds_are_centered_on_corresponding_candles(self):
        qs = pd.DataFrame([{"slot": i, "complete": True, "n": 60, "percentile": 10,
            "p05": -30, "p25": -20, "p50": -15, "p75": -10, "p95": 5} for i in range(1, 5)])
        current = pd.DataFrame({"slot": [1,2,3,4], "annual_current": [-112.,-10.,-9.,-8.]})
        fig, ax = plt.subplots(figsize=(7, 6))
        try:
            _candle_panel(ax, qs, "slot", [1,2,3,4], current)
            points = [tuple(c.get_offsets()[0]) for axis in fig.axes for c in axis.collections if c.get_gid() == "current-value"]
            self.assertEqual(sorted(points), [(0.,-112.),(1.,-10.),(2.,-9.),(3.,-8.)])
            for axis in fig.axes:
                for text in axis.texts:
                    if text.get_gid() == "current-value-label":
                        self.assertTrue(text.get_clip_on())
        finally:
            plt.close(fig)

    def test_input_fingerprint_detects_snapshot_and_wal_but_ignores_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, dividend = root/"source.json", root/"dividend.xlsx"
            source.write_text("a", encoding="utf-8")
            dividend.write_text("a", encoding="utf-8")
            args = SimpleNamespace(snapshot=source, database=None, dividends=dividend,
                no_volume_supplement=True, volume_dataset=None, output=root/"outputs")
            before = input_fingerprint(args)
            (root/"output.txt").write_text("unrelated", encoding="utf-8")
            self.assertEqual(before, input_fingerprint(args))
            source.write_text("b", encoding="utf-8")
            self.assertNotEqual(before, input_fingerprint(args))
            args.snapshot, args.database = None, source
            before = input_fingerprint(args)
            Path(str(source)+"-wal").write_text("changed", encoding="utf-8")
            self.assertNotEqual(before, input_fingerprint(args))

    def test_watch_generates_only_when_inputs_change_and_retains_good_result_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root, poll_seconds=5)
            signatures, calls, states = iter(["a", "a", "b", "c"]), [], []
            def generate(run):
                calls.append(run.output)
                if len(calls) == 2:
                    raise ValueError("test invalid input")
                run.output.mkdir(parents=True)
                (run.output/"index.html").write_text("preview", encoding="utf-8")
                (run.output/"run_manifest.json").write_text(json.dumps({"as_of": "2026-01-05", "created_at": str(len(calls))}), encoding="utf-8")
                return run.output
            def observe():
                states.append(json.loads((root/"automation_state.json").read_text(encoding="utf-8"))["state"])
                if states[-1] == "failed":
                    self.assertEqual(json.loads((root/"latest.json").read_text(encoding="utf-8"))["created_at"], "1")
                    self.assertIn("本次自动更新未成功", (root/"latest.html").read_text(encoding="utf-8"))
            watch(args, generate=generate, fingerprint=lambda _: next(signatures), stop=Cycles(4, observe))
            self.assertEqual(len(calls), 3)
            self.assertEqual(states, ["waiting", "waiting", "failed", "waiting"])
            self.assertEqual(json.loads((root/"latest.json").read_text(encoding="utf-8"))["created_at"], "3")


if __name__ == "__main__":
    unittest.main()
