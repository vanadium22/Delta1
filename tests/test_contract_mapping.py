from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.contracts import ContractMappingError, MainContractResolver
from index_strategy.instant_dld.realtime_store import DB_RELATIVE
from index_strategy.instant_dld.service import DownloadService


class MemoryStore:
    run_id = "mapping-test"
    run_dir = Path("mapping-test")

    def __init__(self):
        self.records, self.events = [], []

    def manifest(self, value):
        self.summary = deepcopy(value)

    def batch(self, record):
        self.records.append(deepcopy(record))

    def event(self, kind, **details):
        self.events.append({"kind": kind, **details})


class MappingClient:
    url = "https://example.invalid/market"
    session = SimpleNamespace(trust_env=False)
    verify = True
    timeout = (10, 30)

    def __init__(self):
        self.requests = []

    def fetch(self, symbols):
        self.requests.append(symbols[:])
        return {
            "status": "success", "symbols": symbols[:],
            "received_at": "2026-09-18T21:01:02+08:00", "elapsed_seconds": 0.01,
            "response": {"code": "0", "respSuccess": True, "respFail": False,
                         "data": {symbol: {"securityId": symbol, "latestPrice": 940.32,
                                           "tradedQuantities": 100, "quoteTimestamp": 210102}
                                  for symbol in symbols}},
        }


class ContractMappingTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mapping = self.root / "month_contract_code.pkl"
        self.calendar = self.root / "Date.pkl"
        calendar = [date.fromisoformat(value) for value in (
            "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21",
            "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29",
        )]
        pd.DataFrame({"Date": calendar}, index=calendar).to_pickle(self.calendar)
        self.write_mapping({
            "2026-09-16": "AU2608.SHF", "2026-09-17": "AU2610.SHF",
            "2026-09-18": "AU2610.SHF", "2026-09-21": "AU2612.SHF",
            "2026-09-24": "AU2612.SHF", "2026-09-28": "AU2702.SHF",
        })

    def write_mapping(self, values):
        stamp = self.mapping.stat().st_mtime_ns if self.mapping.exists() else 0
        frame = pd.DataFrame({"AU.SHF": list(values.values())},
                             index=[date.fromisoformat(day) for day in values])
        frame.to_pickle(self.mapping)
        if stamp:
            os.utime(self.mapping, ns=(stamp + 1_000_000, stamp + 1_000_000))

    def resolver(self, now="2026-09-18T21:01:02+08:00"):
        return MainContractResolver(self.mapping, self.calendar,
                                    now=lambda: datetime.fromisoformat(now))

    def assert_identity(self, at, trade_day, mapping_day, actual="AU2610.SHF"):
        self.assertEqual(self.resolver(at).resolve("AU.SHF"), {
            "source_symbol": actual, "mapping_date": mapping_day, "trading_date": trade_day,
        })

    def test_friday_night_saturday_early_and_monday_day_share_friday_mapping(self):
        for at in ("2026-09-18T21:01:02+08:00", "2026-09-19T00:30:00+08:00",
                   "2026-09-21T10:00:00+08:00"):
            with self.subTest(at=at):
                self.assert_identity(at, "2026-09-21", "2026-09-18")

    def test_day_session_uses_previous_day_even_when_today_row_exists(self):
        self.write_mapping({"2026-09-17": "AU2610.SHF", "2026-09-18": "AU2612.SHF"})
        self.assert_identity("2026-09-18T15:00:00+08:00", "2026-09-18", "2026-09-17")

    def test_holiday_previous_day_comes_from_calendar(self):
        self.assert_identity("2026-09-28T10:00:00+08:00", "2026-09-28", "2026-09-24",
                             "AU2612.SHF")

    def test_night_boundary_and_cffex_day_only(self):
        resolver = self.resolver()
        self.assertEqual(resolver.trading_dates("AU.SHF", datetime.fromisoformat("2026-09-18T19:59:59+08:00")),
                         ("2026-09-18", "2026-09-17"))
        self.assertEqual(resolver.trading_dates("AU.SHF", datetime.fromisoformat("2026-09-18T20:00:00+08:00")),
                         ("2026-09-21", "2026-09-18"))
        self.assertEqual(resolver.trading_dates("IF.CFE", datetime.fromisoformat("2026-09-18T21:00:00+08:00")),
                         ("2026-09-18", "2026-09-17"))

    def test_utc_timestamp_is_converted_to_china_before_cutoff(self):
        self.assert_identity("2026-09-18T13:01:02+00:00", "2026-09-21", "2026-09-18")

    def test_missing_previous_row_does_not_fallback_to_old_or_future_row(self):
        self.write_mapping({"2026-09-17": "AU2610.SHF", "2026-09-21": "AU2612.SHF"})
        with self.assertRaisesRegex(ContractMappingError, "2026-09-18"):
            self.resolver().resolve("AU.SHF")

    def test_empty_wrong_product_or_exchange_never_guess_contract(self):
        for actual in (None, float("nan"), "", "AU.SHF", "AG2610.SHF", "AU2610.DCE", "AU2610.SHF/other"):
            with self.subTest(actual=actual):
                self.write_mapping({"2026-09-17": "AU2610.SHF", "2026-09-18": actual})
                with self.assertRaises(ContractMappingError):
                    self.resolver().resolve("AU.SHF")

    def test_missing_alias_column_is_reported(self):
        with self.assertRaisesRegex(ContractMappingError, "AG.SHF"):
            self.resolver().resolve("AG.SHF")

    def test_monthly_contract_map_index_is_rejected(self):
        pd.DataFrame({"AU.SHF": ["AU2610.SHF"]}, index=["202610"]).to_pickle(self.mapping)
        with self.assertRaises(ContractMappingError):
            self.resolver().resolve("AU.SHF")

    def test_integer_and_duplicate_mapping_dates_are_rejected(self):
        for index in ([20260918], [date(2026, 9, 18), date(2026, 9, 18)]):
            with self.subTest(index=index):
                pd.DataFrame({"AU.SHF": ["AU2610.SHF"] * len(index)}, index=index).to_pickle(self.mapping)
                with self.assertRaises(ContractMappingError):
                    self.resolver().resolve("AU.SHF")

    def test_insufficient_calendar_does_not_guess_weekdays(self):
        for at in ("2026-09-15T10:00:00+08:00", "2026-09-29T21:00:00+08:00"):
            with self.subTest(at=at), self.assertRaisesRegex(ContractMappingError, "覆盖不足"):
                self.resolver(at).resolve("AU.SHF")

    def test_calendar_weekend_or_duplicate_is_rejected(self):
        for values in ([date(2026, 9, 18), date(2026, 9, 19)],
                       [date(2026, 9, 18), date(2026, 9, 18)]):
            with self.subTest(values=values):
                pd.DataFrame({"Date": values}).to_pickle(self.calendar)
                with self.assertRaises(ContractMappingError):
                    self.resolver().resolve("AU.SHF")

    def test_explicit_stock_and_contract_never_touch_mapping_or_calendar(self):
        resolver = MainContractResolver(self.root / "missing-map.pkl", self.root / "missing-calendar.pkl")
        with patch.object(resolver, "_stamp", side_effect=AssertionError("unexpected file access")):
            resolved, errors = resolver.resolve_many([
                "000001.SZ", "603110.SH", "AU2610.SHF", "IF2609.CFE",
                "GC.CMX", "CL.NYM", "ES.CME", "AAPL.US",
            ])
        self.assertEqual(errors, {})
        for symbol, identity in resolved.items():
            self.assertEqual(identity, {"source_symbol": symbol, "mapping_date": None, "trading_date": None})

    def test_same_trading_day_freezes_contract_but_next_day_reloads(self):
        resolver = self.resolver()
        original = resolver.resolve("AU.SHF")
        self.write_mapping({"2026-09-18": "AU2612.SHF", "2026-09-21": "AU2702.SHF"})
        self.assertEqual(resolver.resolve("AU.SHF", datetime.fromisoformat("2026-09-21T14:30:00+08:00")), original)
        self.assertEqual(resolver.resolve("AU.SHF", datetime.fromisoformat("2026-09-21T21:00:00+08:00")), {
            "source_symbol": "AU2702.SHF", "mapping_date": "2026-09-21", "trading_date": "2026-09-22",
        })

    def test_missing_mapping_can_recover_after_daily_file_update(self):
        self.write_mapping({"2026-09-17": "AU2610.SHF"})
        resolver = self.resolver()
        with self.assertRaises(ContractMappingError):
            resolver.resolve("AU.SHF")
        self.write_mapping({"2026-09-18": "AU2612.SHF"})
        self.assertEqual(resolver.resolve("AU.SHF")["source_symbol"], "AU2612.SHF")

    def run_poll(self, symbols, resolver=None):
        symbols_file = self.root / "symbols.json"
        symbols_file.write_text(json.dumps(symbols), encoding="utf-8")
        client, store = MappingClient(), MemoryStore()
        collect(client, store, [symbols_file], max_polls=1, resolver=resolver or self.resolver())
        return client, store

    def test_alias_and_actual_request_once_preserve_security_id_and_logical_rows(self):
        client, store = self.run_poll(["AU.SHF", "AU2610.SHF", "000001.SZ"])
        self.assertEqual(client.requests, [["AU2610.SHF", "000001.SZ"]])
        record = store.records[0]
        self.assertEqual(record["symbols"], ["AU.SHF", "AU2610.SHF", "000001.SZ"])
        self.assertEqual(record["requested_symbols"], ["AU2610.SHF", "000001.SZ"])
        self.assertEqual(record["missing_symbols"], [])
        self.assertEqual(record["received_symbols"], record["symbols"])
        self.assertEqual(record["response"]["data"]["AU.SHF"]["securityId"], "AU2610.SHF")
        self.assertEqual(record["symbol_mapping"]["AU.SHF"], {
            "source_symbol": "AU2610.SHF", "mapping_date": "2026-09-18", "trading_date": "2026-09-21",
        })
        self.assertEqual(len([event for event in store.events if event["kind"] == "main_contract_resolved"]), 1)

    def test_missing_alias_mapping_keeps_stock_success_and_reports_partial(self):
        self.write_mapping({"2026-09-17": "AU2610.SHF"})
        client, store = self.run_poll(["AU.SHF", "000001.SZ"])
        self.assertEqual(client.requests, [["000001.SZ"]])
        record = store.records[0]
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["missing_symbols"], ["AU.SHF"])
        self.assertEqual(record["received_symbols"], ["000001.SZ"])
        self.assertEqual(list(record["mapping_errors"]), ["AU.SHF"])
        self.assertEqual(list(record["response"]["data"]), ["000001.SZ"])

    def test_all_mapping_errors_make_no_http_request(self):
        self.write_mapping({"2026-09-17": "AU2610.SHF"})
        client, store = self.run_poll(["AU.SHF"])
        self.assertEqual(client.requests, [])
        record = store.records[0]
        self.assertEqual(record["status"], "mapping_error")
        self.assertEqual(record["missing_symbols"], ["AU.SHF"])
        self.assertNotIn("response", record)

    def test_http_timeout_and_alias_mapping_error_both_remain_visible(self):
        self.write_mapping({"2026-09-17": "AU2610.SHF"})
        failure = {"status": "timeout", "received_at": "2026-09-18T21:01:02+08:00",
                   "elapsed_seconds": 30, "error": "ReadTimeout: timed out waiting for market API"}
        with patch.object(MappingClient, "fetch", return_value=failure):
            _, store = self.run_poll(["AU.SHF", "000001.SZ"])
        record = store.records[0]
        self.assertEqual(record["status"], "timeout")
        self.assertIn("ReadTimeout", record["error"])
        self.assertIn("2026-09-18", record["error"])
        self.assertEqual(list(record["mapping_errors"]), ["AU.SHF"])
        self.assertEqual(record["missing_symbols"], ["AU.SHF", "000001.SZ"])

    def preview_service(self, output):
        config = {"symbols": ["AU.SHF"], "interval": 5, "output_dir": str(output),
                  "mapping_file": str(self.mapping), "calendar_file": str(self.calendar)}
        settings_path = self.root / "localsetting" / "realtime_ui.json"
        settings_path.parent.mkdir(exist_ok=True)
        settings_path.write_text(json.dumps(config), encoding="utf-8")
        service = DownloadService(self.root)
        now = datetime.fromisoformat("2026-09-18T21:01:02+08:00")
        with patch("index_strategy.instant_dld.service.MainContractResolver",
                   side_effect=lambda *args, **kwargs: MainContractResolver(*args, now=lambda: now, **kwargs)):
            return service.preview_mapping(config)

    def test_preview_respects_persisted_pin_despite_changed_mapping_file(self):
        output = self.root / "existing-output"
        database = output / DB_RELATIVE
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE main_contract_resolutions "
                               "(symbol TEXT, trading_date TEXT, source_symbol TEXT, mapping_date TEXT)")
            connection.execute("INSERT INTO main_contract_resolutions VALUES (?,?,?,?)",
                               ("AU.SHF", "2026-09-21", "AU2610.SHF", "2026-09-18"))
        connection.close()
        before = database.read_bytes()
        self.write_mapping({"2026-09-18": "AU2612.SHF"})
        self.assertEqual(self.preview_service(output), [{
            "symbol": "AU.SHF", "source_symbol": "AU2610.SHF",
            "mapping_date": "2026-09-18", "trading_date": "2026-09-21",
        }])
        self.assertEqual(database.read_bytes(), before)

    def test_preview_does_not_create_output_directory_or_database(self):
        output = self.root / "absent-output"
        self.assertEqual(self.preview_service(output)[0]["source_symbol"], "AU2610.SHF")
        self.assertFalse(output.exists())

    def test_preview_reads_legacy_database_without_schema_changes(self):
        output = self.root / "legacy-output"
        database = output / DB_RELATIVE
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE quotes (sequence INTEGER PRIMARY KEY, symbol TEXT)")
            connection.execute("PRAGMA user_version=1")
        connection.close()
        before = database.read_bytes()
        self.assertEqual(self.preview_service(output)[0]["source_symbol"], "AU2610.SHF")
        self.assertEqual(database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
