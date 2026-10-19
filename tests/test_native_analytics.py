from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from dashboard.native.analytics import carry_values, cross_product_metrics, enrich_state


def frame(prices, start="2026-09-30T01:31:00Z", frequency="1m"):
    events = pd.date_range(start, periods=len(prices), freq="min" if frequency == "1m" else "s")
    return pd.DataFrame({"event_time":events, "trade_date":[event.tz_convert("Asia/Shanghai").date() for event in events],
                         "session_id":"day_am", "close":prices, "available_at":events+pd.Timedelta(seconds=1)})


def state(count=80, product="IF", scale=1.):
    i = np.arange(count-1)
    x = .0002*np.sin(i*.37)+.0001*np.cos(i*.13)
    noise = .000015*np.sin(i*.83)
    spot = scale*4000*np.exp(np.r_[0, np.cumsum(x)])
    near = scale*3992*np.exp(np.r_[0, np.cumsum(.000005+1.2*x+noise)])
    spot_frame, near_frame = frame(spot), frame(near)
    spread = near_frame[["event_time", "trade_date", "session_id"]].copy()
    spread["value"] = 12+np.sin(np.arange(count)*.2)
    basis = spread[["event_time", "trade_date", "session_id"]].copy()
    basis["value"] = (near/spot-1)*10000
    return {"product":product, "frequency":"1m", "as_of":(near_frame.iloc[-1].event_time+pd.Timedelta(seconds=2)).isoformat(),
            "near":near_frame, "spot":spot_frame, "basis":basis, "spread":spread,
            "roles":{"$near":product+"2610.CFE"}, "demo":False, "replay":False, "history_limited":False}


class NativeAnalyticsTests(unittest.TestCase):
    def test_regression_uses_prior_returns_and_current_residual(self):
        value = state()
        answer = enrich_state(value)["analytics"]
        x = np.diff(np.log(value["spot"].close.to_numpy()))[-31:]
        y = np.diff(np.log(value["near"].close.to_numpy()))[-31:]
        beta, alpha = np.polyfit(x[:-1], y[:-1], 1)
        residual = y[-1]-alpha-beta*x[-1]
        self.assertAlmostEqual(answer["beta"], beta, places=10)
        self.assertAlmostEqual(answer["residual_bp"], residual*10000, places=9)
        self.assertEqual(answer["samples"], 30)
        self.assertGreater(answer["r_squared"], .9)

    def test_current_shock_does_not_change_estimated_beta_or_r_squared(self):
        baseline = enrich_state(state())
        shocked = state()
        shocked["near"].loc[len(shocked["near"])-1, "close"] *= 1.02
        shocked = enrich_state(shocked)
        self.assertEqual(baseline["analytics"]["beta"], shocked["analytics"]["beta"])
        self.assertEqual(baseline["analytics"]["r_squared"], shocked["analytics"]["r_squared"])
        self.assertGreater(abs(shocked["analytics"]["residual_z"]), 100)
        pd.testing.assert_frame_equal(baseline["regression"].iloc[:-1], shocked["regression"].iloc[:-1])

    def test_future_data_is_excluded_by_event_and_availability_time(self):
        complete = state()
        earlier = deepcopy(complete)
        earlier["as_of"] = (complete["near"].iloc[-4].event_time+pd.Timedelta(seconds=2)).isoformat()
        truncated = deepcopy(earlier)
        for key in ("near", "spot", "basis", "spread"):
            truncated[key] = truncated[key].iloc[:-3].copy()
        a, b = enrich_state(earlier), enrich_state(truncated)
        self.assertEqual(a["analytics"], b["analytics"])
        pd.testing.assert_frame_equal(a["regression"], b["regression"])
        late = deepcopy(complete)
        late["near"].loc[len(late["near"])-1, "available_at"] = pd.Timestamp(complete["as_of"])+pd.Timedelta(seconds=10)
        self.assertIsNone(enrich_state(late)["analytics"]["beta"])

    def test_short_history_and_constant_variance_return_none(self):
        short = enrich_state(state(20))["analytics"]
        self.assertIsNone(short["beta"])
        self.assertIn("32", short["reasons"]["beta"])
        value = state()
        value["spot"]["close"] = 4000.
        answer = enrich_state(value)["analytics"]
        self.assertIsNone(answer["beta"])
        self.assertIn("无有效波动", answer["reasons"]["beta"])

    def test_perfect_regression_has_no_infinite_residual_z(self):
        value = state()
        value["near"]["close"] = value["spot"].close*.997
        answer = enrich_state(value)["analytics"]
        self.assertAlmostEqual(answer["beta"], 1.)
        self.assertIsNone(answer["residual_z"])
        self.assertAlmostEqual(answer["r_squared"], 1.)

    def test_latest_time_mismatch_gap_and_session_boundary_block_regression(self):
        mismatch = state()
        mismatch["spot"] = mismatch["spot"].iloc[:-1]
        self.assertIsNone(enrich_state(mismatch)["analytics"]["beta"])
        gap = state()
        gap["spot"] = gap["spot"].drop(index=65)
        self.assertIsNone(enrich_state(gap)["analytics"]["beta"])
        crossed = state()
        crossed["near"].loc[60:, "session_id"] = "day_pm"
        crossed["spot"].loc[60:, "session_id"] = "day_pm"
        self.assertIsNone(enrich_state(crossed)["analytics"]["beta"])

    def test_calendar_and_cross_products_compare_bp_not_index_points(self):
        value = enrich_state(state())
        self.assertAlmostEqual(value["analytics"]["calendar_bp"], value["spread"].iloc[-1].value/value["spot"].iloc[-1].close*10000)
        other = enrich_state(state(product="IH", scale=.6))
        rows = cross_product_metrics({"IF":value, "IH":other})
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(rows[0]["basis_gap_bp"], 0., places=10)
        self.assertAlmostEqual(rows[0]["beta"], 1., places=9)
        self.assertIsNone(rows[0]["residual_z"])
        other["roles"]["$near"] = "IH2611.CFE"
        different = cross_product_metrics({"IF":value, "IH":other})[0]
        self.assertIsNone(different["basis_gap_bp"])
        self.assertIsNone(different["beta"])

    def test_threshold_episode_is_debounced_and_stale_events_are_observations(self):
        value = state(70)
        # A bounded alternating basis has no natural threshold episodes; insert
        # five real price shocks followed by recovery to test event collapsing.
        value["near"]["close"] = value["spot"].close*(1+np.where(np.arange(70)%2, 1., -1.)/10000)
        value["near"].loc[63:67, "close"] *= 1.02
        with patch("dashboard.native.analytics._utc_now", return_value=pd.Timestamp(value["as_of"])):
            enriched = enrich_state(value)
        basis_events = [event for event in enriched["events"] if event["type"] == "basis"]
        self.assertEqual(len(basis_events), 1)
        self.assertEqual(basis_events[0]["lifecycle"], "recovered")
        self.assertEqual(basis_events[0]["status"], "recovered")
        self.assertEqual(basis_events[0]["event_time"], value["near"].iloc[65].event_time.isoformat())
        self.assertEqual(basis_events[0]["last_time"], value["near"].iloc[68].event_time.isoformat())
        self.assertEqual(basis_events[0]["duration"], 5)
        self.assertGreater(basis_events[0]["peak"], 2.)
        self.assertTrue({"duration", "peak", "event_time", "last_time", "lifecycle"}.issubset(basis_events[0]))
        old = deepcopy(value)
        old["as_of"] = (pd.Timestamp(value["as_of"])+pd.Timedelta(days=1)).isoformat()
        self.assertTrue(all(event["status"] == "observed" for event in enrich_state(old)["events"]))
        # A new unmatched bar must not leave the preceding fresh episode active.
        mismatch = deepcopy(value)
        mismatch["spot"] = mismatch["spot"].iloc[:68]
        with patch("dashboard.native.analytics._utc_now", return_value=pd.Timestamp(value["as_of"])):
            mismatch_events = enrich_state(mismatch)["events"]
        self.assertTrue(all(event["status"] == "observed" for event in mismatch_events if event["type"] == "basis"))
        self.assertLessEqual(len(enriched["events"]), 12)

    def test_mismatched_latest_prices_downgrade_regression_episode(self):
        value = state()
        value["near"].loc[76:, "close"] *= np.exp(.01*np.arange(1, 5))
        value["spot"] = value["spot"].iloc[:-1]
        with patch("dashboard.native.analytics._utc_now", return_value=pd.Timestamp(value["as_of"])):
            enriched = enrich_state(value)
        events = [event for event in enriched["events"] if event["type"] == "regression"]
        self.assertTrue(events)
        self.assertTrue(all(event["status"] == "observed" for event in events))
        self.assertIsNone(enriched["analytics"]["residual_z"])

    def test_event_first_trigger_is_stable_and_old_snapshot_is_not_current(self):
        value = state(70)
        value["near"]["close"] = value["spot"].close*(1+np.where(np.arange(70)%2, 1., -1.)/10000)
        value["near"].loc[63:67, "close"] *= 1.02
        earlier = deepcopy(value)
        for key in ("near", "spot", "basis", "spread"):
            earlier[key] = earlier[key].iloc[:66].copy()
        earlier["as_of"] = (earlier["near"].iloc[-1].event_time+pd.Timedelta(seconds=2)).isoformat()
        with patch("dashboard.native.analytics._utc_now", return_value=pd.Timestamp(earlier["as_of"])):
            initial = next(event for event in enrich_state(earlier)["events"] if event["type"] == "basis")
        self.assertEqual(initial["status"], "active")
        self.assertEqual(initial["lifecycle"], "active")
        self.assertEqual(initial["duration"], 3)
        with patch("dashboard.native.analytics._utc_now", return_value=pd.Timestamp(value["as_of"])):
            recovered = next(event for event in enrich_state(value)["events"] if event["type"] == "basis")
        self.assertEqual(initial["event_time"], recovered["event_time"])
        self.assertLess(initial["last_time"], recovered["last_time"])
        with patch("dashboard.native.analytics._utc_now", return_value=pd.Timestamp(value["as_of"])+pd.Timedelta(hours=1)):
            historical = enrich_state(value)["events"]
        self.assertTrue(all(event["status"] == "observed" and event["quality"] == "observed" for event in historical))

    def test_carry_requires_actual_expiry_and_model_cost_inputs(self):
        inputs = dict(spot=4000., future=4010., near=4010., far=4025., as_of="2026-09-30T07:00:00Z",
                      near_expiry="2026-10-16", far_expiry="2026-11-20")
        values = carry_values(**inputs)
        self.assertIsNone(values["fair_value"])
        self.assertIsNotNone(values["implied_carry_pct"])
        self.assertEqual(values["near_days"], 16.)
        missing = carry_values(**{**inputs, "near_expiry":None}, financing_rate=.03, dividend_yield=.02, cost_bp=3.)
        self.assertIsNone(missing["fair_value"])
        self.assertIsNone(missing["implied_carry_pct"])
        modeled = carry_values(**inputs, financing_rate=.03, dividend_yield=.02, cost_bp=3.)
        self.assertAlmostEqual(modeled["fair_value"], 4000*(1+.01*16/365))
        self.assertAlmostEqual(modeled["net_space_bp"], abs(modeled["fair_deviation_bp"])-3.)
        expiring = carry_values(**{**inputs, "as_of":"2026-10-14T07:00:00Z"}, financing_rate=.03, dividend_yield=.02, cost_bp=3.)
        self.assertIsNone(expiring["annualized_basis_pct"])
        self.assertIsNotNone(expiring["fair_value"])


if __name__ == "__main__":
    unittest.main()
