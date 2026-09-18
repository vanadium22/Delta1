"""Quantity deltas must describe actual observation intervals, not 1s bars."""
from datetime import datetime
import unittest

from index_strategy.instant_dld.quotes import QUOTE_COLUMNS, VOLUME_COLUMNS, normalize_quote, update_volume


def quote(total=1000, clock=210000):
    value = {"securityId": "AU2610.SHF", "latestPrice": 940.32,
             "tradedQuantities": total, "quoteTimestamp": clock, "tradeVolume": 940320000}
    for side in ("b", "s"):
        for level in range(1, 6):
            value[f"{side}{level}Price"] = 940 + level / 100
            value[f"{side}{level}Stocks"] = level * 2
    return value


def observe(total=1000, received="2026-09-18T21:00:00.200000+08:00", previous=None,
            *, clock=210000, **kwargs):
    identity = {"source_symbol": "AU2610.SHF", "mapping_date": "2026-09-18",
                "trading_date": "2026-09-21"}
    identity.update(kwargs)
    return normalize_quote("AU.SHF", quote(total, clock), received, previous, **identity)


class VolumeObservationTests(unittest.TestCase):
    def assert_unmeasured(self, row):
        for name in ("volume", *VOLUME_COLUMNS):
            self.assertIsNone(row[name], name)

    def test_first_sample_is_unknown_and_precision_stays_internal(self):
        row = observe()
        self.assert_unmeasured(row)
        self.assertTrue(row["quality_flags"] & 16)
        self.assertEqual(row["volume_total"], 1000)
        self.assertEqual(row["received_at"], "2026-09-18T21:00:00.200000+08:00")
        self.assertNotIn("received_at", QUOTE_COLUMNS)
        self.assertTrue(set(VOLUME_COLUMNS).issubset(QUOTE_COLUMNS))

    def test_precise_interval_and_quantities_do_not_change_units(self):
        previous = observe()
        row = observe(1042, "2026-09-18T21:00:05.550000+08:00", previous,
                      clock=210005, expected_interval=5)
        self.assertEqual(row["volume"], 42)
        self.assertEqual(row["volume_total"], 1042)
        self.assertEqual(row["volume_start"], previous["timestamp"])
        self.assertAlmostEqual(row["volume_interval_seconds"], 5.35)
        self.assertEqual(row["bid_volume_1"], 2)
        self.assertEqual(row["ask_volume_5"], 10)

    def test_zero_increment_is_valid_with_a_measured_interval(self):
        previous = observe()
        row = observe(1000, "2026-09-18T21:00:01.200000+08:00", previous)
        self.assertEqual(row["volume"], 0)
        self.assertEqual(row["volume_interval_seconds"], 1)
        self.assertEqual(row["volume_start"], previous["timestamp"])

    def test_gap_limit_is_strict_and_does_not_assign_unobserved_quantity(self):
        previous = observe()
        at_limit = observe(1100, "2026-09-18T21:00:10.200000+08:00", previous,
                           clock=210010, expected_interval=5)
        self.assertEqual(at_limit["volume"], 100)
        gap = observe(1101, "2026-09-18T21:00:10.201000+08:00", previous,
                      clock=210010, expected_interval=5)
        self.assert_unmeasured(gap)
        self.assertTrue(gap["quality_flags"] & 128)
        recovered = observe(1108, "2026-09-18T21:00:15.201000+08:00", gap,
                            clock=210015, expected_interval=5)
        self.assertEqual(recovered["volume"], 7)
        self.assertFalse(recovered["quality_flags"] & 128)

    def test_restart_or_failed_request_resets_observation_baseline(self):
        row = observe(1080, "2026-09-18T21:00:05.200000+08:00", observe(),
                      reset_volume=True, expected_interval=5)
        self.assert_unmeasured(row)
        self.assertTrue(row["quality_flags"] & 16)
        self.assertEqual(row["volume_total"], 1080)

    def test_capture_clock_reversal_is_rejected_despite_valid_source_clock(self):
        row = observe(1050, "2026-09-18T21:00:00.100000+08:00", observe(), clock=210001)
        self.assert_unmeasured(row)
        self.assertTrue(row["quality_flags"] & 8)

    def test_futures_midnight_keeps_trading_day_baseline(self):
        previous = observe(received="2026-09-18T23:59:59.900000+08:00", clock=235959)
        row = observe(1020, "2026-09-19T00:00:01.100000+08:00", previous,
                      clock=1, expected_interval=1)
        self.assertEqual(row["volume"], 20)
        self.assertAlmostEqual(row["volume_interval_seconds"], 1.2)
        new_day = observe(5000, "2026-09-21T21:00:00.100000+08:00", row,
                          trading_date="2026-09-22")
        self.assert_unmeasured(new_day)
        self.assertTrue(new_day["quality_flags"] & 16)

    def test_contract_roll_does_not_compare_two_contract_cumulative_totals(self):
        previous = observe()
        changed = quote(5000)
        changed["securityId"] = "AU2612.SHF"
        row = normalize_quote("AU.SHF", changed, "2026-09-18T21:00:05.200000+08:00", previous,
                              source_symbol="AU2612.SHF", trading_date="2026-09-21")
        self.assert_unmeasured(row)
        self.assertTrue(row["quality_flags"] & 64)

    def test_legacy_seconds_and_absent_timestamp_baselines_remain_readable(self):
        previous = observe()
        previous.pop("received_at")
        row = observe(1050, "2026-09-18T21:00:05.900000+08:00", previous)
        self.assertEqual(row["volume_interval_seconds"], 5)
        self.assertEqual(row["volume_start"], previous["timestamp"])
        previous.pop("timestamp")
        legacy = observe(1050, "2026-09-18T21:00:05.900000+08:00", previous)
        self.assertEqual(legacy["volume"], 50)
        self.assertIsNone(legacy["volume_interval_seconds"])
        self.assertIsNone(legacy["volume_start"])

    def test_missing_negative_or_reset_cumulative_never_becomes_quantity(self):
        for total in (None, -10, float("nan"), 999):
            with self.subTest(total=total):
                row = observe(total, "2026-09-18T21:00:05.200000+08:00", observe())
                self.assert_unmeasured(row)
                self.assertTrue(row["quality_flags"] & 8)
        missing_previous = observe(None)
        row = observe(1000, "2026-09-18T21:00:05.200000+08:00", missing_previous)
        self.assert_unmeasured(row)
        self.assertTrue(row["quality_flags"] & 8)

    def test_recompute_replaces_old_volume_flags_and_preserves_other_quality(self):
        previous = observe()
        row = observe(1020, "2026-09-18T21:00:05.200000+08:00", previous)
        row.update(volume=9999, volume_start=1, volume_interval_seconds=9999,
                   quality_flags=1 | 2 | 4 | 8 | 16 | 32 | 64 | 128)
        update_volume(row, previous, expected_interval=5)
        self.assertEqual(row["volume"], 20)
        self.assertEqual(row["quality_flags"], 2 | 4 | 32)
        self.assertEqual(row["volume_interval_seconds"], 5)
        self.assertEqual(row["volume_start"], int(datetime.fromisoformat(previous["received_at"]).timestamp()))


if __name__ == "__main__":
    unittest.main()
