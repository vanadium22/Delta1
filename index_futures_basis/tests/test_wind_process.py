import copy
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from index_futures_basis.config import DEFAULTS
from index_futures_basis.wind import WindProvider
from index_futures_basis.wind_worker import iso, perform
from index_futures_basis.wind_worker import CALENDAR_OPTIONS


class CalendarResponseTests(unittest.TestCase):
    def calendar(self, data, *, error=0, times=(), count="auto", start="2026-07-06", end="2026-07-10"):
        original = data
        def tdays(first, last, options):
            first = iso(first)
            if first != start:
                return SimpleNamespace(ErrorCode=0, Data=[[(date.fromisoformat(start) - timedelta(days=3)).isoformat()]])
            return SimpleNamespace(ErrorCode=error, Data=original, Times=times)
        def tdayscount(first, last, options):
            first = iso(first)
            value = count if count != "auto" else len(data[0] if data and isinstance(data[0], list) else times)
            return SimpleNamespace(ErrorCode=0, Data=[[1 if first != start else value]])
        w = SimpleNamespace(tdays=tdays, tdayscount=tdayscount)
        return perform(w, {"operation": "calendar", "start": start, "end": end})

    def test_missing_or_malformed_column_is_diagnostic_error(self):
        for data in (None, [None], ["2026-07-06"], [[], []]):
            with self.subTest(data=data), self.assertRaises(ValueError) as caught:
                self.calendar(data)
            message = str(caught.exception)
            for part in ("TDAYS", "2026-07-06", "2026-07-10", "CFFEX;", "DataColumns=", "未写入"):
                self.assertIn(part, message)
            self.assertNotIn("IndexError", message)

    def test_explicit_empty_and_valid_date_columns(self):
        self.assertEqual(self.calendar([]), [])
        self.assertEqual(self.calendar([[]]), [])
        self.assertEqual(self.calendar([[date(2026, 7, 6), datetime(2026, 7, 7), "20260708"]]),
                         ["2026-07-06", "2026-07-07", "2026-07-08"])

    def test_times_can_recover_dates_when_wind_leaves_data_empty(self):
        self.assertEqual(self.calendar([], times=[datetime(2026, 7, 6)]), ["2026-07-06"])
        with self.assertRaisesRegex(ValueError, "Data与Times不一致"):
            self.calendar([["2026-07-06"]], times=[datetime(2026, 7, 7)])

    def test_weekend_and_weekday_holiday_empty_results_are_not_errors(self):
        for start, end in (("2026-10-17", "2026-10-18"), ("2026-10-01", "2026-10-07")):
            for data in ([], [[]]):
                with self.subTest(start=start, data=data):
                    self.assertEqual(self.calendar(data, start=start, end=end, count=0), [])

    def test_count_positive_retries_surrounding_dates_with_correct_options(self):
        calls = []
        def tdays(start, end, options):
            calls.append((start, end, options))
            return SimpleNamespace(ErrorCode=0, Data=[] if len(calls) == 1 else
                                   [["2026-07-03", "2026-07-06", "2026-07-07", "2026-07-13"]])
        def count(start, end, options):
            self.assertEqual((start, end, options), ("20260706", "20260710", CALENDAR_OPTIONS))
            return SimpleNamespace(ErrorCode=0, Data=[[2]])
        w = SimpleNamespace(tdays=tdays, tdayscount=count)
        self.assertEqual(perform(w, {"operation": "calendar", "start": "2026-07-06", "end": "2026-07-10"}),
                         ["2026-07-06", "2026-07-07"])
        self.assertEqual(calls, [("20260706", "20260710", CALENDAR_OPTIONS),
                                 ("20260622", "20260724", CALENDAR_OPTIONS)])

    def test_invalid_count_cannot_mark_dates_closed(self):
        for count in (None, -1, 1.5, True, float("nan"), 6):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "数量无效"):
                self.calendar([], count=count)

    def test_nonempty_calendar_must_match_count(self):
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.calendar([["2026-07-06"]], count=0)

    def test_bad_duplicate_or_out_of_range_dates_are_rejected(self):
        for values in ([None], ["not-a-date"], ["2026-07-06", "2026-07-06"], ["2026-07-11"]):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "未写入"):
                self.calendar([values])

    def test_wind_error_code_still_precedes_data_parsing(self):
        with self.assertRaisesRegex(RuntimeError, "ErrorCode=-40520007"):
            self.calendar([], error=-40520007)


class WindProcessTests(unittest.TestCase):
    def test_silent_zero_service_cannot_overwrite_calendar_or_existing_quotes(self):
        from index_futures_basis.store import Store
        from index_futures_basis.sync import synchronize
        from index_futures_basis.tests.test_sync import FakeProvider
        source = '''
from types import SimpleNamespace as R
class W:
    def start(self, **kwargs):
        return R(ErrorCode=0)
    def tdays(self, *args):
        return R(ErrorCode=0, Data=[], Times=[])
    def tdayscount(self, *args):
        return R(ErrorCode=0, Data=[[0]])
    def stop(self):
        pass
w = W()
'''
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "WindPy.py").write_text(source, encoding="utf-8")
            store = Store(Path(folder) / "market.sqlite")
            store.save_rows("quotes", [("000300.SH", "2026-10-16", "close", 3900)])
            store.save_calendar("2026-10-16", "2026-10-16", {"2026-10-16"})
            before = store.quotes("2026-10-16", "2026-10-18")
            with patch.dict(os.environ, {"PYTHONPATH": folder}):
                provider = WindProvider(copy.deepcopy(DEFAULTS))
                combined = FakeProvider()
                combined.calendar = provider.calendar
                try:
                    with self.assertRaisesRegex(RuntimeError, "不能据此认定周末或节假日"):
                        synchronize(store, combined, "2026-10-16", "2026-10-18")
                    self.assertEqual(store.calendar("2026-10-16", "2026-10-18"), {"2026-10-16": 1})
                    self.assertEqual(store.quotes("2026-10-16", "2026-10-18"), before)
                    self.assertEqual(store.meta("calendar_verification", {}), {})
                    self.assertEqual(combined.calls, [])
                finally:
                    provider.close()

    def test_weekend_empty_worker_result_then_monday_incremental_update(self):
        from index_futures_basis.store import Store
        from index_futures_basis.sync import synchronize
        from index_futures_basis.tests.test_sync import FakeProvider
        source = '''
from datetime import datetime
from types import SimpleNamespace as R
class W:
    def start(self, **kwargs):
        return R(ErrorCode=0)
    def tdays(self, start, end, options):
        assert options == "TradingCalendar=CFFEX;Days=Trading"
        start, end = [datetime.strptime(d, "%Y%m%d").date().isoformat() for d in (start, end)]
        days = [d for d in ["2026-07-10", "2026-07-13"] if start <= d <= end]
        return R(ErrorCode=0, Data=[days] if days else [], Times=days)
    def tdayscount(self, start, end, options):
        start, end = [datetime.strptime(d, "%Y%m%d").date().isoformat() for d in (start, end)]
        return R(ErrorCode=0, Data=[[sum(start <= d <= end for d in ["2026-07-10", "2026-07-13"])]])
    def stop(self):
        pass
w = W()
'''
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "WindPy.py").write_text(source, encoding="utf-8")
            store = Store(Path(folder) / "market.sqlite")
            with patch.dict(os.environ, {"PYTHONPATH": folder}):
                provider = WindProvider(copy.deepcopy(DEFAULTS))
                combined = FakeProvider()
                combined.calendar = provider.calendar
                try:
                    self.assertEqual(synchronize(store, combined, "2026-07-10", "2026-07-10")["state"], "complete")
                    before = store.quotes("2026-07-10", "2026-07-10")
                    combined.calls.clear()
                    closed = synchronize(store, combined, "2026-07-11", "2026-07-12")
                    self.assertEqual(closed["state"], "empty")
                    self.assertIn("无需补齐行情", closed["message"])
                    self.assertEqual(closed["errors"], [])
                    self.assertEqual(combined.calls, [])
                    self.assertEqual(store.calendar("2026-07-11", "2026-07-12"),
                                     {"2026-07-11": 0, "2026-07-12": 0})
                    self.assertEqual(synchronize(store, combined, "2026-07-11", "2026-07-12")["requests"], 0)
                    opened = synchronize(store, combined, "2026-07-10", "2026-07-13")
                    self.assertEqual(opened["state"], "complete")
                    self.assertEqual(store.quotes("2026-07-10", "2026-07-10"), before)
                    self.assertTrue(all(c[-2:] == ("2026-07-13", "2026-07-13")
                                        for c in combined.calls if c[0] in {"mapping", "series"}))
                finally:
                    provider.close()

    def test_empty_calendar_does_not_poison_store_and_retry_recovers(self):
        from index_futures_basis.store import Store
        from index_futures_basis.sync import synchronize
        from index_futures_basis.tests.test_sync import FakeProvider
        source = '''
from types import SimpleNamespace as R
class W:
    calls = 0
    def start(self, **kwargs):
        return R(ErrorCode=0)
    def tdays(self, start, end, options):
        self.calls += 1
        return R(ErrorCode=0, Data=[] if self.calls <= 2 else [[start]])
    def tdayscount(self, start, end, options):
        return R(ErrorCode=0, Data=[[1]])
    def stop(self):
        pass
w = W()
'''
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "WindPy.py").write_text(source, encoding="utf-8")
            store = Store(Path(folder) / "market.sqlite")
            store.save_rows("quotes", [("000300.SH", "2026-07-03", "close", 3900)])
            before = store.quotes("2026-07-01", "2026-07-10")
            with patch.dict(os.environ, {"PYTHONPATH": folder}):
                provider = WindProvider(copy.deepcopy(DEFAULTS))
                combined = FakeProvider()
                combined.calendar = provider.calendar
                try:
                    with self.assertRaisesRegex(RuntimeError, "日历返回不一致"):
                        synchronize(store, combined, "2026-07-06", "2026-07-06")
                    self.assertEqual(store.calendar("2026-07-06", "2026-07-06"), {})
                    self.assertEqual(store.mappings("2026-07-06", "2026-07-06"), {})
                    self.assertEqual(store.quotes("2026-07-01", "2026-07-10"), before)
                    self.assertEqual(store.runs()[0]["state"], "failed")
                    result = synchronize(store, combined, "2026-07-06", "2026-07-06")
                    self.assertEqual(result["state"], "complete")
                    self.assertEqual(store.calendar("2026-07-06", "2026-07-06"), {"2026-07-06": 1})
                finally:
                    provider.close()

    def test_hidden_process_protocol_reuses_session_and_ignores_import_noise(self):
        source = '''
from types import SimpleNamespace as R
print("synthetic Wind banner")
class W:
    def start(self, **kwargs):
        print("synthetic connection banner")
        return R(ErrorCode=0)
    def tdays(self, start, end, options):
        return R(ErrorCode=0, Data=[[start]])
    def tdayscount(self, start, end, options):
        return R(ErrorCode=0, Data=[[1]])
    def stop(self):
        pass
w = W()
'''
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "WindPy.py").write_text(source, encoding="utf-8")
            with patch.dict(os.environ, {"PYTHONPATH": folder}):
                provider = WindProvider(copy.deepcopy(DEFAULTS))
                try:
                    self.assertEqual(provider.calendar("2026-07-06", "2026-07-06"), ["2026-07-06"])
                    process = provider.process
                    self.assertEqual(provider.calendar("2026-07-07", "2026-07-07"), ["2026-07-07"])
                    self.assertIs(process, provider.process)
                finally:
                    provider.close()
                self.assertIsNotNone(process.poll())

    def test_missing_wind_fails_once_and_process_is_cleaned_up(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "WindPy.py").write_text('raise ImportError("SIMULATED_WIND_MISSING")', encoding="utf-8")
            with patch.dict(os.environ, {"PYTHONPATH": folder}):
                provider = WindProvider(copy.deepcopy(DEFAULTS))
                try:
                    with self.assertRaisesRegex(ConnectionError, "SIMULATED_WIND_MISSING"):
                        provider.calendar("2026-07-06", "2026-07-06")
                    process = provider.process
                finally:
                    provider.close()
                self.assertIsNotNone(process.poll())
