from pathlib import Path
import tempfile
import threading
import unittest

import pandas as pd

from index_futures_basis.analytics import ROOTS
from index_futures_basis.demo import snapshot
from index_futures_basis.store import Store
from index_futures_basis.sync import Cancelled, synchronize


class FakeProvider:
    raw = None

    def __init__(self):
        if self.__class__.raw is None:
            self.__class__.raw = snapshot()
        self.calls = []
        self.mapping_values, self.quote_values, self.expiry_values = {}, {}, {}
        self.missing = set()
        self.fail_after = None
        for row in self.raw["records"]:
            day, code = row["trade_date"], row["instrument_id"]
            alias = f"{row['root']}0{row['slot']-1}.CFE"
            self.mapping_values[alias, day] = code
            self.quote_values[code, day, "close"] = row["futures_close"]
            self.quote_values[code, day, "oi"] = row["open_interest"]
            self.quote_values[ROOTS[row["root"]], day, "close"] = row["spot_close"]
            self.expiry_values[code] = row["expiry_date"]

    def record(self, kind, *args):
        self.calls.append((kind, *args))
        if self.fail_after and len(self.calls) >= self.fail_after:
            raise ConnectionError("模拟网络中断")

    def calendar(self, start, end):
        self.record("calendar", start, end)
        return [d for d in self.raw["calendar"] if start <= d <= end]

    def mapping(self, code, start, end):
        self.record("mapping", code, start, end)
        return {d: value for (alias, d), value in self.mapping_values.items() if alias == code and start <= d <= end}

    def expiries(self, codes):
        self.record("expiries", tuple(codes))
        return {code: self.expiry_values[code] for code in codes}

    def series(self, code, fields, start, end):
        self.record("series", code, tuple(fields), start, end)
        return {day: {f: self.quote_values.get((code, day, f)) if (code, day, f) not in self.missing else None for f in fields}
                for day in self.raw["calendar"] if start <= day <= end}


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "market.sqlite")
        self.provider = FakeProvider()
        self.start, self.end = "2026-07-06", "2026-07-10"

    def tearDown(self):
        self.temp.cleanup()

    def sync(self, **kwargs):
        return synchronize(self.store, self.provider, self.start, self.end, **kwargs)

    def test_second_sync_and_restart_make_no_provider_calls(self):
        result = self.sync()
        self.assertEqual(result["state"], "complete")
        self.assertEqual(len(self.store.panel(self.start, self.end)), 80)
        self.provider.calls.clear()
        self.store = Store(self.store.path)
        self.assertEqual(self.sync()["requests"], 0)
        self.assertEqual(self.provider.calls, [])

    def test_empty_long_calendar_response_is_not_cached_as_closed_dates(self):
        self.provider.calendar = lambda start, end: []
        with self.assertRaisesRegex(ValueError, "未返回任何交易日"):
            synchronize(self.store, self.provider, "2026-01-01", "2026-07-10")
        self.assertEqual(self.store.calendar("2026-01-01", "2026-07-10"), {})

    def test_only_missing_field_on_interior_date_is_requested(self):
        self.sync()
        code = self.store.mappings(self.start, self.end)[("2026-07-08", "IC", 4)]
        with self.store.connection() as con:
            con.execute("DELETE FROM quotes WHERE code=? AND day=? AND field='oi'", (code, "2026-07-08"))
        self.provider.calls.clear()
        self.assertEqual(self.sync()["missing_fields"], 0)
        self.assertEqual(self.provider.calls, [("series", code, ("oi",), "2026-07-08", "2026-07-08")])

    def test_invalid_existing_quote_is_repaired(self):
        self.sync()
        with self.store.connection() as con:
            con.execute("UPDATE quotes SET value=-1 WHERE code='000905.SH' AND day='2026-07-08'")
        self.provider.calls.clear()
        self.sync()
        self.assertEqual(self.provider.calls, [("series", "000905.SH", ("close",), "2026-07-08", "2026-07-08")])

    def test_invalid_existing_expiry_and_calendar_gap_are_repaired(self):
        self.sync()
        code = self.store.mappings(self.start, self.end)[("2026-07-08", "IC", 4)]
        with self.store.connection() as con:
            con.execute("UPDATE contracts SET expiry='2000-01-01' WHERE code=?", (code,))
            con.execute("DELETE FROM calendar WHERE day='2026-07-08'")
        with self.assertRaisesRegex(ValueError, "日历尚未完整"):
            self.store.panel(self.start, self.end)
        self.provider.calls.clear()
        self.assertEqual(self.sync()["state"], "complete")
        self.assertEqual(self.provider.calls, [("calendar", "2026-07-08", "2026-07-08"), ("expiries", (code,))])
        self.assertEqual(len(self.store.panel(self.start, self.end)), 80)

    def test_later_dates_only_and_new_contract_metadata(self):
        self.sync()
        self.provider.calls.clear()
        self.end = "2026-07-20"
        result = self.sync()
        self.assertEqual(result["state"], "complete")
        for call in self.provider.calls:
            if call[0] in {"series", "mapping"}:
                self.assertGreater(call[-2], "2026-07-10")
        self.assertTrue(any(c[0] == "expiries" for c in self.provider.calls))
        self.assertTrue(all("2026-07-17" <= expiry for expiry in self.store.expiries().values()))

    def test_missing_response_stays_a_gap_and_retry_only_fills_it(self):
        self.provider.missing.add(("000905.SH", "2026-07-08", "close"))
        result = self.sync()
        self.assertEqual(result["state"], "partial")
        with self.assertRaises(ValueError):
            self.store.panel(self.start, self.end)
        self.provider.missing.clear()
        self.provider.calls.clear()
        self.assertEqual(self.sync()["state"], "complete")
        self.assertEqual(self.provider.calls, [("series", "000905.SH", ("close",), "2026-07-08", "2026-07-08")])

    def test_interrupted_sync_persists_batches_and_resumes(self):
        self.provider.fail_after = 5
        with self.assertRaises(ConnectionError):
            self.sync()
        cached_mapping = set(self.store.mappings(self.start, self.end))
        self.assertTrue(cached_mapping)
        self.assertEqual(self.store.runs()[0]["state"], "failed")
        self.provider.fail_after = None
        self.provider.calls.clear()
        self.assertEqual(self.sync()["state"], "complete")
        requested_aliases = {c[1] for c in self.provider.calls if c[0] == "mapping"}
        self.assertNotIn("IF00.CFE", requested_aliases)

    def test_explicit_repair_only_replaces_selected_day(self):
        self.sync()
        self.provider.quote_values["000905.SH", "2026-07-08", "close"] = 9999
        self.provider.calls.clear()
        self.sync(repair=("2026-07-08", "2026-07-08"))
        for call in self.provider.calls:
            if call[0] in {"mapping", "series"}:
                self.assertEqual(call[-2:], ("2026-07-08", "2026-07-08"))
        self.assertEqual(self.store.quotes(self.start, self.end)["000905.SH", "2026-07-08", "close"], 9999)

    def test_cancel_and_single_writer_guard(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            self.sync(cancel=event)
        self.assertEqual(self.store.runs()[0]["state"], "cancelled")
        with self.store.writer_lock():
            with self.assertRaisesRegex(ValueError, "另一个窗口"):
                with Store(self.store.path).writer_lock():
                    pass

    def test_bad_import_does_not_replace_good_data(self):
        self.sync()
        before = self.store.panel(self.start, self.end)
        bad = {"records": [{"root": "IC"}], "calendar": []}
        with self.assertRaises(ValueError):
            self.store.import_raw(bad, {"kind": "offline"})
        pd.testing.assert_frame_equal(before, self.store.panel(self.start, self.end))
