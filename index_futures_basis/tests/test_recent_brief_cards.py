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
from index_futures_basis.recent_brief.card_charts import _candle_panel, _quantile_table, _trend
from index_futures_basis.recent_brief.data import adjust, session_quantiles, multi_session_quantiles
from index_futures_basis.recent_brief.metrics import highlights, series_metrics, total_metrics, activity_commentary
from index_futures_basis.recent_brief.brief import main, refresh_market
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
        self.assertAlmostEqual(r.annual_change_1d_pct_points, -99-9.8)
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

    def test_rank_table_keeps_00_current_value_and_all_three_windows(self):
        p = self.history()
        q = multi_session_quantiles(p, p.trade_date.max(), "slot")
        metric = series_metrics(p, p.trade_date.max(), "slot")
        fig, ax = plt.subplots(figsize=(8, 6))
        try:
            table = _quantile_table(ax, q, "slot", [1,2,3,4], metric)
            texts = [c.get_text().get_text() for c in table.get_celld().values()]
            self.assertIn("30日分位", texts)
            self.assertIn("60日分位", texts)
            self.assertIn("120日分位", texts)
            self.assertIn("00", texts)
            self.assertIn("9.90%", texts)
            self.assertIn("P100.0%\nn=60", texts)
            self.assertIn("—\nn=99/120", texts)
        finally:
            plt.close(fig)

    def test_annualized_trend_has_no_00_line_or_secondary_axis(self):
        p = self.history()
        p["annualized_plot_filled"] = False
        p["annualized_plot_pct"] = p.annualized_basis_pct
        fig, ax = plt.subplots()
        try:
            _trend(ax, p, "IF", "slot", [2,3,4], sorted(p.trade_date.unique()), "annualized_basis_pct", annual=True)
            self.assertEqual(len(fig.axes), 1)
            self.assertEqual([x.get_text() for x in ax.get_legend().get_texts()], ["01","02","03"])
        finally:
            plt.close(fig)

    def test_30_60_120_windows_exclude_current_and_do_not_shorten_history(self):
        p = self.history()
        result = multi_session_quantiles(p, p.trade_date.max(), "slot").set_index("window_sessions")
        self.assertEqual(set(result.index), {30,60,120})
        self.assertTrue(result.loc[30,"complete"])
        self.assertTrue(result.loc[60,"complete"])
        self.assertFalse(result.loc[120,"complete"])
        self.assertAlmostEqual(result.loc[60,"mean"], 6.85)
        p.loc[p.index[-1], "annualized_basis_pct"] = -999
        revised = multi_session_quantiles(p, p.trade_date.max(), "slot").set_index("window_sessions")
        self.assertEqual(revised.loc[60,"mean"], result.loc[60,"mean"])

    def test_activity_comments_describe_sustained_growth_and_reversal(self):
        days = pd.bdate_range("2026-01-01", periods=11)
        p = pd.DataFrame([{"trade_date": day, "root": "IF", "slot": slot, "volume": (100+i*10),
                           "open_interest": (300+i*20), "calendar_known": True}
                          for i,day in enumerate(days) for slot in range(1,5)])
        text = activity_commentary(p, days[-1])["IF"]
        self.assertIn("连续10日增加", text)
        self.assertIn("增仓与成交扩张同向", text)
        alternating = [100+i*10+(12 if i%2 else 0) for i in range(len(days))]
        p["volume"] = [alternating[i] for i in range(len(days)) for _ in range(4)]
        self.assertIn("5日均值连续", activity_commentary(p, days[-1])["IF"])
        p.loc[p.trade_date.eq(days[-1]), "open_interest"] = 100
        text = activity_commentary(p, days[-1])["IF"]
        self.assertIn("此前5日中5日增加，最新转为减少", text)
        p.loc[p.trade_date.eq(days[-1]), "calendar_known"] = False
        self.assertIn("数据不足", activity_commentary(p, days[-1])["IF"])

    def test_summary_uses_percentage_points_instead_of_basis_points(self):
        p = self.history()
        single = series_metrics(p, p.trade_date.max(), "slot")
        cross = single.drop(columns="slot").assign(pair="02−01")
        totals = total_metrics(panel(), panel().trade_date.max())
        cards = highlights(single, cross, totals)
        self.assertEqual(cards[1]["value"], "+3.05 个百分点")
        self.assertIn("60均", cards[1]["detail"])
        self.assertIn("60日均幅1.00倍", cards[1]["detail"])
        self.assertEqual(cards[2]["value"], "+3.05 个百分点")
        self.assertNotIn("bp", json.dumps(cards))

    def test_refresh_reuses_original_incremental_service_and_requested_cutoff(self):
        service = SimpleNamespace(sync=unittest.mock.Mock(return_value={"state": "complete", "requests": 0}))
        factory = unittest.mock.Mock(return_value=service)
        result = refresh_market("2026-01-05", factory=factory,
                                volume_refresher=lambda service, day: {"state": "complete", "requests": 0})
        factory.assert_called_once_with(mode="wind")
        self.assertEqual(service.sync.call_args.kwargs["end"], "2026-01-05")
        self.assertEqual(result["state"], "complete")
        self.assertTrue(result["requested"])

    def test_refresh_failure_is_not_reported_as_success(self):
        factory = unittest.mock.Mock(side_effect=TimeoutError("test timeout"))
        result = refresh_market(factory=factory)
        self.assertEqual(result["state"], "failed")
        self.assertIn("test timeout", result["reason"])

    def test_daily_refresh_still_exports_partial_data_and_returns_nonzero(self):
        with patch("index_futures_basis.recent_brief.brief.refresh_market", return_value={"requested": True, "state": "partial"}), \
             patch("index_futures_basis.recent_brief.brief.build", return_value=Path("fixture")) as generate, \
             patch("index_futures_basis.recent_brief.automation.publish_latest") as publish:
            self.assertEqual(main(["--refresh"]), 2)
            generate.assert_called_once()
            self.assertEqual(generate.call_args.args[0].refresh_result["state"], "partial")
            publish.assert_called_once()

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
                (run.output/"股指基差简报.pdf").write_bytes(b"%PDF-test")
                (run.output/"股指基差简报.docx").write_bytes(b"PK-test")
                (run.output/"run_manifest.json").write_text(json.dumps({"as_of": "2026-01-05", "created_at": str(len(calls))}), encoding="utf-8")
                return run.output
            def observe():
                states.append(json.loads((root/"automation_state.json").read_text(encoding="utf-8"))["state"])
                if states[-1] == "failed":
                    self.assertEqual(json.loads((root/"latest.json").read_text(encoding="utf-8"))["created_at"], "1")
                    self.assertIn("本次自动更新未成功", (root/"last_failure.json").read_text(encoding="utf-8"))
                    self.assertFalse((root/"latest.html").exists())
            watch(args, generate=generate, fingerprint=lambda _: next(signatures), stop=Cycles(4, observe))
            self.assertEqual(len(calls), 3)
            self.assertEqual(states, ["waiting", "waiting", "failed", "waiting"])
            self.assertEqual(json.loads((root/"latest.json").read_text(encoding="utf-8"))["created_at"], "3")


if __name__ == "__main__":
    unittest.main()
