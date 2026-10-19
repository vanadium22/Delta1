import copy
from datetime import date, datetime
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from index_futures_basis.config import DEFAULTS
from index_futures_basis.wind import WindProvider
from index_futures_basis.wind_worker import perform


class CalendarResponseTests(unittest.TestCase):
    def calendar(self, data, *, error=0):
        w = SimpleNamespace(tdays=lambda *args: SimpleNamespace(ErrorCode=error, Data=data))
        return perform(w, {"operation": "calendar", "start": "2026-07-06", "end": "2026-07-10"})

    def test_missing_or_malformed_column_is_diagnostic_error(self):
        for data in ([], None, [None], ["2026-07-06"], [[], []]):
            with self.subTest(data=data), self.assertRaises(ValueError) as caught:
                self.calendar(data)
            message = str(caught.exception)
            for part in ("TDAYS", "2026-07-06", "2026-07-10", "CFFEX", "DataColumns=", "未写入"):
                self.assertIn(part, message)
            self.assertNotIn("IndexError", message)

    def test_explicit_empty_and_valid_date_columns(self):
        self.assertEqual(self.calendar([[]]), [])
        self.assertEqual(self.calendar([[date(2026, 7, 6), datetime(2026, 7, 7), "20260708"]]),
                         ["2026-07-06", "2026-07-07", "2026-07-08"])

    def test_bad_duplicate_or_out_of_range_dates_are_rejected(self):
        for values in ([None], ["not-a-date"], ["2026-07-06", "2026-07-06"], ["2026-07-11"]):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "未写入"):
                self.calendar([values])

    def test_wind_error_code_still_precedes_data_parsing(self):
        with self.assertRaisesRegex(RuntimeError, "ErrorCode=-40520007"):
            self.calendar([], error=-40520007)


class WindProcessTests(unittest.TestCase):
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
        return R(ErrorCode=0, Data=[] if self.calls == 1 else [[start]])
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
                    with self.assertRaisesRegex(RuntimeError, "交易日历返回为空或结构不完整"):
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
