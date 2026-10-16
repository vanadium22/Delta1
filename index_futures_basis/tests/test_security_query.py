"""Exercise field semantics, missing data, incremental cache and the real worker protocol."""
import copy
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as R
import unittest
from unittest.mock import patch

import pandas as pd

from shared_data import DataPaths
from index_futures_basis.config import DEFAULTS
from index_futures_basis.security_model import SecurityQuery, calculate, expected_times
from index_futures_basis.security_data import (DemoSecurityProvider, SecurityProvider, SecurityService,
                                               export_result, read_document)
from index_futures_basis.security_wind import perform
from index_futures_basis.sync import Cancelled

NOW = "2026-10-16 16:00:00+08:00"


class Provider(DemoSecurityProvider):
    def __init__(self):
        self.calls = []
        self.omit = None
        self.fail = False

    def request(self, operation, **args):
        self.calls.append((operation, args))
        if self.fail:
            raise RuntimeError("模拟Wind权限错误")
        value = super().request(operation, **args)
        if operation == "history" and self.omit:
            value["rows"] = [r for r in value["rows"] if self.omit not in r["time"]]
        return value


class ContractTests(unittest.TestCase):
    def test_normalization_and_rejection(self):
        self.assertEqual(SecurityQuery(" 600519.sh ", "snapshot").code, "600519.SH")
        for kwargs in ({"code": "600519"}, {"code": "../../cache"}, {"fields": ()},
                       {"fields": ("unlisted_field",)}, {"frequency": "tick"}, {"adjustment": "front"},
                       {"start": "2026-10-15", "end": "2026-10-14"}, {"twap": True},
                       {"code": "000300.SH", "vwap": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SecurityQuery(**({"code": "600519.SH", "start": "2026-10-14", "end": "2026-10-15"} | kwargs))
        with self.assertRaisesRegex(ValueError, "对齐"):
            SecurityQuery("600519.SH", "5m", start="2026-10-14 09:32", end="2026-10-14 10:00")

    def test_minute_right_endpoints_and_lunch(self):
        q = SecurityQuery("600519.SH", "1m", start="2026-10-14 09:30", end="2026-10-14 15:00")
        times = expected_times(q, ["2026-10-14"])
        self.assertEqual(len(times), 240)
        self.assertIn("T09:31:00+08:00", times[0])
        self.assertIn("T11:30:00+08:00", times[119])
        self.assertIn("T13:01:00+08:00", times[120])
        q5 = replace(q, frequency="5m")
        self.assertEqual(len(expected_times(q5, ["2026-10-14"])), 48)
        self.assertEqual(len(expected_times(replace(q, start="2026-10-14 11:29", end="2026-10-14 13:01"), ["2026-10-14"])), 2)

    def test_hand_calculated_twap_vwap_unit_conversion_and_missing(self):
        q = SecurityQuery("600519.SH", "1m", ("close",), "2026-10-14 09:30", "2026-10-14 09:32",
                          True, True, "lot100", "thousand")
        frame = pd.DataFrame({"close": [10., 12.], "volume": [2., 3.], "amt": [2., 3.6]})
        result = calculate(q, frame)
        self.assertAlmostEqual(result["metrics"]["twap"], 11.)
        self.assertAlmostEqual(result["metrics"]["vwap"], 11.2)
        missing = frame.copy()
        missing.loc[0, ["volume", "close"]] = float("nan")
        result = calculate(q, missing)
        self.assertEqual(result["metrics"], {"twap": 12., "vwap": 12.})
        self.assertEqual(result["metric_details"]["vwap"], {"n": 1, "excluded": 1, "total": 2})
        self.assertEqual(len(result["notes"]), 2)
        unknown = calculate(replace(q, volume_unit="unknown"), frame)
        self.assertNotIn("vwap", unknown["metrics"])
        frame[["volume", "amt"]] = 0
        self.assertNotIn("vwap", calculate(q, frame)["metrics"])
        frame.loc[0, "amt"] = 1
        self.assertIn("零成交量", "".join(calculate(q, frame)["notes"]))

    def test_calculations_exclude_nonfinite_and_pair_volume_amount(self):
        q = SecurityQuery("600006.SH", "1m", ("close",), "2026-10-14 09:30", "2026-10-14 09:40",
                          True, True, "share", "yuan")
        frame = pd.DataFrame({"close": [10, 12, float("nan"), float("inf"), "bad", None, 0, -2],
                              "volume": [200, 300, None, 500, 0, -2, float("inf"), 0],
                              "amt": [2000, 3600, 100000, float("nan"), 800, 20, 400, 0]})
        result = calculate(q, frame)
        self.assertEqual(result["statistics"][0]["mean"], 11)
        self.assertEqual(result["statistics"][0]["missing"], 6)
        self.assertEqual(result["metrics"], {"twap": 11., "vwap": 11.2})
        self.assertEqual(result["metric_details"]["vwap"]["n"], 2)
        empty = calculate(q, frame.assign(close=float("nan"), volume=float("nan"), amt=float("inf")))
        self.assertEqual(empty["metrics"], {})
        self.assertIsNone(empty["statistics"][0]["mean"])
        json.dumps(empty, allow_nan=False)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = DataPaths.for_repo(Path(self.temp.name), data_root=Path(self.temp.name) / "data")
        self.service = SecurityService(self.paths, copy.deepcopy(DEFAULTS))
        self.provider = Provider()
        self.q = SecurityQuery("600519.SH", "1d", ("close",), "2026-10-12", "2026-10-14")

    def tearDown(self):
        self.temp.cleanup()

    def query(self, q=None, **kwargs):
        return self.service.query(q or self.q, provider=self.provider, now=NOW, **kwargs)

    def test_daily_reuse_extension_and_field_only_fetch(self):
        first = self.query()
        self.assertEqual(len(first.frame), 3)
        self.assertEqual(len([x for x in self.provider.calls if x[0] == "history"]), 1)
        self.provider.calls.clear()
        again = self.query()
        self.assertEqual(again.metadata["requests"], 0)
        pd.testing.assert_frame_equal(first.frame, again.frame)
        self.query(replace(self.q, fields=("close", "volume")))
        self.assertEqual(self.provider.calls[-1][1]["fields"], ["volume"])
        self.provider.calls.clear()
        self.query(replace(self.q, end="2026-10-15"))
        calls = [a for op, a in self.provider.calls if op == "history"]
        self.assertEqual([(a["start"], a["end"]) for a in calls], [("2026-10-15", "2026-10-15")])

    def test_minute_extension_only_downloads_new_bars_and_additional_fields(self):
        q = SecurityQuery("600519.SH", "1m", ("close",), "2026-10-14 09:30", "2026-10-14 09:32")
        self.query(q)
        self.provider.calls.clear()
        q = replace(q, end="2026-10-14 09:35")
        result = self.query(q)
        self.assertEqual(len(result.frame), 5)
        calls = [a for op, a in self.provider.calls if op == "history"]
        self.assertEqual(calls[0]["start"], "2026-10-14 09:32:00")
        self.assertEqual(calls[0]["end"], "2026-10-14 09:35:00")
        self.provider.calls.clear()
        result = self.query(replace(q, vwap=True, volume_unit="share", amount_unit="yuan"))
        self.assertEqual(self.provider.calls[-1][1]["fields"], ["volume", "amt"])
        self.assertIn("vwap", result.summary["metrics"])
        self.assertEqual(self.query(q).metadata["requests"], 0)

    def test_stock_wsi_table_through_cache_metrics_and_export(self):
        calls = []
        def wsi(code, fields, start, end, options):
            calls.append((code, fields, start, end, options))
            return R(ErrorCode=0, Codes=["1", "2"], Times=[],
                Fields=["time", "windcode", "amount", "close", "volume"],
                Data=[[datetime(2026, 10, 14, 9, 35), datetime(2026, 10, 14, 9, 40)],
                      [code, code], [2000., 3600.], [10., 12.], [200., 300.]])
        wind = R(wsi=wsi,
                 wss=lambda code, *args: R(ErrorCode=0, Codes=[code], Data=[["合成个股名称"]]),
                 tdays=lambda *args: R(ErrorCode=0, Data=[[datetime(2026, 10, 14)]]))
        provider = R(request=lambda operation, **args: perform(wind, {"operation": operation, **args}))
        q = SecurityQuery("600006.SH", "5m", ("close",), "2026-10-14 09:30", "2026-10-14 09:40",
                          True, True, "share", "yuan")
        result = self.service.query(q, provider=provider, now=NOW)
        self.assertEqual(result.metadata["missing_cells"], 0)
        self.assertEqual(result.summary["metrics"]["twap"], 11.)
        self.assertEqual(result.summary["metrics"]["vwap"], 11.2)
        self.assertEqual(result.metadata["batches"][0]["returned_fields"]["amt"], "amount")
        again = self.service.query(q, provider=provider, now=NOW)
        self.assertEqual(again.metadata["requests"], 0)
        self.assertEqual(len(calls), 1)
        folder = export_result(again, Path(self.temp.name) / "table-export")
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["batches"][0]["response_layout"], "table")

    def test_partial_bar_response_is_visible_and_retried(self):
        self.provider.omit = "09:32"
        q = SecurityQuery("600519.SH", "1m", ("close",), "2026-10-14 09:30", "2026-10-14 09:33", True)
        result = self.query(q)
        self.assertEqual(result.metadata["missing_cells"], 1)
        self.assertIn("twap", result.summary["metrics"])
        self.assertEqual(result.summary["metric_details"]["twap"], {"n": 2, "excluded": 1, "total": 3})
        self.provider.omit = None
        result = self.query(q)
        self.assertEqual(result.metadata["missing_cells"], 0)
        self.assertIn("twap", result.summary["metrics"])

    def test_today_window_downloads_only_completed_bars_and_preserves_requested_window(self):
        q = SecurityQuery("600006.SH", "5m", ("close",), "2026-10-16 09:30", "2026-10-16 15:00", True)
        for now, count, endpoint in [("2026-10-16 10:02:59+08:00", 6, "10:00"),
                                      ("2026-10-16 12:30:00+08:00", 24, "11:30"),
                                      ("2026-10-16 15:10:00+08:00", 48, "15:00")]:
            with self.subTest(now=now):
                self.provider.calls.clear()
                result = self.service.query(q, provider=self.provider, now=now)
                self.assertEqual(len(result.frame), count)
                self.assertEqual(result.metadata["pending_rows"], 48 - count)
                self.assertEqual(result.metadata["missing_cells"], 0)
                self.assertEqual(result.metadata["query"]["end"], "2026-10-16T15:00:00+08:00")
                self.assertEqual(result.metadata["grid_end"][11:16], endpoint)
                for operation, args in self.provider.calls:
                    if operation == "history":
                        self.assertLessEqual(pd.Timestamp(args["end"]), pd.Timestamp(now).tz_localize(None))
        with self.assertRaisesRegex(ValueError, "没有已完成"):
            self.service.query(q, provider=self.provider, now="2026-10-16 09:32:00+08:00")
        with self.assertRaisesRegex(ValueError, "结束时间"):
            self.service.query(replace(q, end="2026-10-17 15:00"), provider=self.provider, now=NOW)

    def test_name_lookup_refreshes_wind_and_offline_only_reads_cached_pair(self):
        name = self.service.lookup_name(" 600006.sh ", "5m", provider=self.provider)
        self.assertEqual(name["code"], "600006.SH")
        self.assertEqual(name["source"], "Wind")
        self.assertEqual([op for op, _ in self.provider.calls], ["info"])
        self.service.lookup_name("600006.SH", "5m", provider=self.provider)
        self.assertEqual(len(self.provider.calls), 2)
        offline = SecurityService(self.paths, DEFAULTS, "offline")
        with patch("index_futures_basis.security_data.SecurityProvider", side_effect=AssertionError("network")):
            self.assertEqual(offline.lookup_name("600006.SH")["name"], name["name"])
            self.assertIn("离线", offline.lookup_name("600006.SH")["source"])
            with self.assertRaisesRegex(ValueError, "没有"):
                offline.lookup_name("600007.SH")
        with self.assertRaisesRegex(ValueError, "完整沪深"):
            self.service.lookup_name("600006", provider=self.provider)

    def test_empty_response_does_not_claim_requested_dates_as_actual_coverage(self):
        self.provider.omit = "2026-10-"
        result = self.query()
        self.assertEqual(result.metadata["complete_rows"], 0)
        self.assertIsNone(result.metadata["actual_start"])
        self.assertIsNone(result.metadata["actual_end"])
        self.assertEqual(result.metadata["grid_start"], "2026-10-12")

    def test_refresh_failure_does_not_destroy_cache_or_return_stale_as_fresh(self):
        original = self.query()
        self.provider.fail = True
        with self.assertRaisesRegex(RuntimeError, "权限"):
            self.query(force=True)
        self.provider.fail = False
        pd.testing.assert_frame_equal(original.frame, self.query().frame)
        self.provider.omit = "2026-10-13"
        result = self.query(force=True)
        self.assertTrue(pd.isna(result.frame.close.iloc[1]))
        # The old valid cell remains available only as an explicitly labelled offline cache.
        offline = SecurityService(self.paths, DEFAULTS, "offline")
        cached = offline.query(self.q, now=NOW)
        self.assertEqual(cached.frame.close.iloc[1], original.frame.close.iloc[1])
        self.assertIn("离线", cached.metadata["source"])
        self.assertTrue(any("未定稿" in n for n in cached.metadata["notes"]))

    def test_current_day_refresh_and_next_day_finalization(self):
        q = replace(self.q, start="2026-10-16", end="2026-10-16")
        first = self.query(q)
        self.assertTrue(any("当前交易日" in n for n in first.metadata["notes"]))
        self.assertGreater(self.query(q).metadata["requests"], 0)
        finalized = self.service.query(q, provider=self.provider, now="2026-10-17 10:00+08:00")
        self.assertGreater(finalized.metadata["requests"], 0)
        self.assertEqual(self.service.query(q, provider=self.provider, now="2026-10-17 10:00+08:00").metadata["requests"], 0)

    def test_finalizing_volume_does_not_finalize_earlier_provisional_close(self):
        q = replace(self.q, start="2026-10-16", end="2026-10-16", fields=("close", "volume"))
        self.query(q)
        tomorrow = "2026-10-17 10:00+08:00"
        self.service.query(replace(q, fields=("volume",)), provider=self.provider, now=tomorrow)
        self.provider.calls.clear()
        self.service.query(replace(q, fields=("close",)), provider=self.provider, now=tomorrow)
        self.assertEqual(self.provider.calls[-1][1]["fields"], ["close"])
        self.assertEqual(self.service.query(q, provider=self.provider, now=tomorrow).metadata["requests"], 0)

    def test_snapshots_always_refresh_and_offline_never_connects(self):
        q = SecurityQuery("600519.SH", "snapshot", ("close", "volume"))
        for _ in range(2):
            result = self.query(q)
            self.assertEqual(len(result.frame), 1)
        self.assertEqual(len([x for x in self.provider.calls if x[0] == "snapshot"]), 2)
        self.query()
        offline = SecurityService(self.paths, DEFAULTS, "offline")
        with patch("index_futures_basis.security_data.SecurityProvider", side_effect=AssertionError("network")):
            self.assertEqual(offline.query(self.q, now=NOW).metadata["requests"], 0)
            with self.assertRaisesRegex(ValueError, "最新"):
                offline.query(q, now=NOW)
            with self.assertRaisesRegex(ValueError, "离线"):
                offline.query(replace(self.q, fields=("volume",)), now=NOW)

    def test_cache_integrity_acquisition_retention_and_demo_isolation(self):
        self.query()
        dataset, root = self.service.cache("1d")
        self.assertEqual(root, self.paths.root / "cache/market/security_query/wind/1d")
        self.assertEqual({x["date"] for x in self.service.inventory("1d")}, {"2026-10-16"})
        self.assertEqual(self.service.catalog.prune(dataset.key, today=pd.Timestamp("2026-10-17").date())["partitions"], [])
        expired = self.service.catalog.prune(dataset.key, today=pd.Timestamp("2026-10-24").date())
        self.assertEqual(len(expired["partitions"]), 1)
        demo = SecurityService(self.paths, DEFAULTS, "demo")
        with patch("index_futures_basis.security_data.SecurityProvider", side_effect=AssertionError("network")):
            result = demo.query(self.q, now=NOW)
        self.assertIn("合成演示", result.metadata["source"])
        self.assertNotEqual(demo.cache("1d")[1], root)
        file = next(root.glob("????-??-??/*.json"))
        file.write_text('{"sha256":"wrong","data":{}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            self.query()

    def test_export_includes_raw_precision_units_and_provenance(self):
        result = self.query()
        folder = export_result(result, Path(self.temp.name) / "export")
        saved = pd.read_csv(folder / "data.csv")
        pd.testing.assert_frame_equal(saved, result.frame)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["query"]["code"], "600519.SH")
        self.assertEqual(manifest["units"]["volume"], "unknown")
        self.assertEqual(manifest["retention_basis"], "acquisition_date")
        self.assertIn("data_fingerprint", manifest)

    def test_cancel_after_request_stops_without_publishing_incomplete_batch(self):
        original = self.provider.request
        def cancel(operation, **args):
            value = original(operation, **args)
            if operation == "history":
                self.service.cancel.set()
            return value
        self.provider.request = cancel
        with self.assertRaises(Cancelled):
            self.query()
        self.assertEqual(self.service.inventory("1d"), [])


class AdapterTests(unittest.TestCase):
    def minute_request(self, **updates):
        return dict(operation="history", code="600006.SH", fields=["close", "volume", "amt"],
                    frequency="5m", start="2026-10-15 09:30:00", end="2026-10-15 09:40:00") | updates

    def minute_result(self, **updates):
        return R(**(dict(ErrorCode=0, Codes=["600006.SH"], Fields=["CLOSE", "VOLUME", "AMT"],
                         Times=[datetime(2026, 10, 15, 9, 35), datetime(2026, 10, 15, 9, 40)],
                         Data=[[10., 12.], [200., 300.], [2000., 3600.]]) | updates))

    def test_wsi_arguments_and_amount_return_alias(self):
        seen = []
        def wsi(*args):
            seen.append(args)
            return self.minute_result(Fields=[" AMOUNT ", " Close ", "VOLUME"],
                                      Data=[[2000., 3600.], [10., 12.], [200., 300.]])
        data = perform(R(wsi=wsi), self.minute_request())
        self.assertEqual(seen, [("600006.SH", "close,volume,amt", "2026-10-15 09:30:00",
                                "2026-10-15 09:40:00", "BarSize=5;PriceAdj=U;Fill=Blank")])
        self.assertEqual(data["rows"][1], {"time": "2026-10-15T09:40:00+08:00", "close": 12.,
                                          "volume": 300., "amt": 3600.})
        self.assertEqual(data["wind_fields"]["amt"], "amt")
        self.assertEqual(data["returned_fields"]["amt"], " AMOUNT ")

    def test_wsi_table_uses_explicit_row_codes_and_time_columns(self):
        result = self.minute_result(Codes=["1", "2"], Times=[datetime(2026, 10, 16)],
            Fields=["volume", "time", "amount", "windcode", "close"],
            Data=[[200., 300.], [datetime(2026, 10, 15, 9, 35), datetime(2026, 10, 15, 9, 40)],
                  [2000., 3600.], ["600006.SH", "600006.SH"], [10., 12.]])
        data = perform(R(wsi=lambda *args: result), self.minute_request())
        self.assertEqual(data["rows"][0]["time"], "2026-10-15T09:35:00+08:00")
        self.assertEqual(data["rows"][1]["amt"], 3600.)
        self.assertEqual(data["response_layout"], "table")
        result.Data[3][1] = "600007.SH"
        with self.assertRaisesRegex(ValueError, "证券代码.*600007.SH"):
            perform(R(wsi=lambda *args: result), self.minute_request())

    def test_wsi_rejects_missing_unknown_or_ambiguous_fields_with_context(self):
        for names, values in [(["CLOSE", "VOLUME"], [[10., 12.], [200., 300.]]),
                              (["CLOSE", "VOLUME", "turnover"], [[10., 12.], [200., 300.], [1., 2.]]),
                              (["CLOSE", "VOLUME", "AMT", "AMOUNT"], [[10., 12.], [200., 300.], [1., 2.], [1., 2.]])]:
            with self.subTest(names=names), self.assertRaises(ValueError) as raised:
                perform(R(wsi=lambda *args: self.minute_result(Fields=names, Data=values)), self.minute_request())
            message = str(raised.exception)
            for text in ("WSI", "600006.SH", "字段", "2026-10-15 09:30:00", "BarSize=5", "Fields=", "DataLengths="):
                self.assertIn(text, message)

    def test_wsi_rejects_wrong_codes_and_ragged_columns(self):
        for updates, expected in [({"Codes": ["600007.SH"]}, "证券代码"),
                                   ({"Data": [[10., 12.], [200.], [2000., 3600.]]}, "长度")]:
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, expected):
                perform(R(wsi=lambda *args: self.minute_result(**updates)), self.minute_request())

    def test_wsi_table_does_not_accept_missing_identity_or_duplicate_times(self):
        for names, values, expected in [
            (["time", "close"], [[datetime(2026, 10, 15, 9, 35)], [10.]], "字段"),
            (["time", "windcode", "close"], [[datetime(2026, 10, 15, 9, 35)] * 2,
                                               ["600006.SH"] * 2, [10., 11.]], "重复"),
            (["time", "windcode", "close"], [[datetime(2026, 10, 15, 9, 35)] * 2,
                                               ["600006.SH"], [10., 11.]], "长度")]:
            with self.subTest(names=names, expected=expected), self.assertRaisesRegex(ValueError, expected):
                perform(R(wsi=lambda *args: self.minute_result(Fields=names, Data=values)),
                        self.minute_request(fields=["close"]))

    def test_daily_does_not_apply_minute_alias_and_keeps_wsd_options(self):
        seen = []
        result = self.minute_result(Fields=["AMOUNT"], Data=[[2000., 3600.]])
        def wsd(*args):
            seen.append(args)
            return result
        with self.assertRaisesRegex(ValueError, "WSD.*字段"):
            perform(R(wsd=wsd), self.minute_request(frequency="1d", fields=["amt"],
                                                    start="2026-10-14", end="2026-10-15"))
        self.assertEqual(seen[0][-1], "Period=D;Days=Trading;Fill=Blank;PriceAdj=U")
        result.Fields = ["AMT"]
        result.Times = [datetime(2026, 10, 14), datetime(2026, 10, 15)]
        data = perform(R(wsd=wsd), self.minute_request(frequency="1d", fields=["amt"],
                                                     start="2026-10-14", end="2026-10-15"))
        self.assertEqual(data["rows"], [{"time": "2026-10-14", "amt": 2000.}, {"time": "2026-10-15", "amt": 3600.}])

    def test_wind_error_preserves_api_message_and_request_context(self):
        result = self.minute_result(ErrorCode=-40520007, Fields=["ERROR"], Data=[["No authority"]])
        with self.assertRaises(RuntimeError) as raised:
            perform(R(wsi=lambda *args: result), self.minute_request())
        for text in ("WSI", "600006.SH", "-40520007", "No authority", "BarSize=5"):
            self.assertIn(text, str(raised.exception))

    def test_wsi_preserves_times_field_order_and_rejects_duplicates(self):
        result = R(ErrorCode=0, Codes=["600519.SH"], Fields=["VOLUME", "CLOSE"],
                   Times=[datetime(2026, 10, 14, 9, 31), datetime(2026, 10, 14, 9, 32)], Data=[[100, 200], [10, 11]])
        w = R(wsi=lambda *args: result)
        request = dict(operation="history", code="600519.SH", fields=["close", "volume"],
                       frequency="1m", start="2026-10-14 09:30", end="2026-10-14 09:32")
        data = perform(w, request)
        self.assertEqual(data["rows"][1], {"time": "2026-10-14T09:32:00+08:00", "close": 11, "volume": 200})
        result.Times[1] = result.Times[0]
        with self.assertRaisesRegex(ValueError, "重复"):
            perform(w, request)

    def test_snapshot_uses_rt_fields_and_does_not_invent_provider_time(self):
        seen = []
        def wsq(code, fields):
            seen.append(fields)
            return R(ErrorCode=0, Codes=[code], Fields=["RT_VOL", "RT_LAST"], Times=[], Data=[[123], [10.5]])
        data = perform(R(wsq=wsq), dict(operation="snapshot", code="600519.SH", fields=["close", "volume"]))
        self.assertEqual(seen, ["rt_last,rt_vol"])
        self.assertEqual(data["rows"], [{"time": None, "close": 10.5, "volume": 123}])
        self.assertIn("+08:00", data["received_at"])

    def test_real_subprocess_protocol_works_without_pandas_in_worker(self):
        source = '''
from types import SimpleNamespace as R
from datetime import datetime
print("synthetic Wind import noise")
class W:
    def start(self, **kwargs): return R(ErrorCode=0)
    def stop(self): pass
    def wsi(self, code, fields, start, end, options):
        if fields == 'volume':
            return R(ErrorCode=-40520007, Codes=[], Fields=[], Times=[], Data=[['No authority']])
        return R(ErrorCode=0, Codes=['1'], Fields=['time','windcode','amount','close'], Times=[],
                 Data=[[datetime(2026,10,14,9,31)], [code], [2000.], [10.]])
w=W()
'''
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "WindPy.py").write_text(source, encoding="utf-8")
            with patch.dict(os.environ, {"PYTHONPATH": folder}):
                provider = SecurityProvider(copy.deepcopy(DEFAULTS))
                try:
                    data = provider.request("history", code="600006.SH", fields=["close", "amt"], frequency="1m",
                                            start="2026-10-14 09:30:00", end="2026-10-14 09:31:00")
                    self.assertEqual(data["rows"][0]["time"], "2026-10-14T09:31:00+08:00")
                    self.assertEqual(data["rows"][0]["amt"], 2000.)
                    with self.assertRaisesRegex(RuntimeError, "WSI.*600006.SH.*No authority"):
                        provider.request("history", code="600006.SH", fields=["volume"], frequency="1m",
                                         start="2026-10-14 09:30:00", end="2026-10-14 09:31:00")
                    process = provider.process
                finally:
                    provider.close()
                self.assertIsNotNone(process.poll())


if __name__ == "__main__":
    unittest.main()
