from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from index_strategy.instant_dld.cli import main, parser
from index_strategy.instant_dld.client import MarketDataClient
from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.storage import JsonlStore
from index_strategy.instant_dld.symbols import SymbolFileError, load_symbols


def payload(data=None, **overrides):
    result = {"code": "0", "respSuccess": True, "respFail": False,
              "data": {"000001.SZ": {"latestPrice": 11.7, "unknownField": None}} if data is None else data}
    result.update(overrides)
    return result


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def symbols(self, value, name="symbols.json"):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path


class SymbolTests(TemporaryCase):
    def test_multiple_formats_merge_deduplicate_and_preserve_leading_zeros(self):
        first = self.symbols([" 000001.sz ", "603110.SH"])
        second = self.root / "extra.txt"
        second.write_text("\ufeff# extra\n603110.SH\nIF2609.CFE # future\n", encoding="utf-8")
        third = self.root / "literal.list"
        third.write_text("['IF2609.CFE', '510300.SH']", encoding="utf-8")
        self.assertEqual(load_symbols([first, second, third]), ["000001.SZ", "603110.SH", "IF2609.CFE", "510300.SH"])

    def test_empty_non_list_numeric_or_invalid_symbols_fail(self):
        for value in ([], {}, [1], ["../000001.SZ"], ["000001"], [None]):
            with self.subTest(value=value), self.assertRaises(SymbolFileError):
                load_symbols([self.symbols(value)])

    def test_missing_file_fails(self):
        with self.assertRaises(SymbolFileError):
            load_symbols([self.root / "missing.json"])

    def test_python_literal_does_not_execute_code(self):
        path = self.root / "unsafe.list"
        path.write_text("[__import__('pathlib').Path('unexpected').touch()]", encoding="utf-8")
        with self.assertRaises(SymbolFileError):
            load_symbols([path])


class ClientTests(unittest.TestCase):
    def client(self, body, status=200, json_error=False):
        response = Mock(status_code=status, text="<html>failure</html>")
        if json_error:
            response.json.side_effect = ValueError("invalid json")
        else:
            response.json.return_value = body
        session = Mock()
        session.post.return_value = response
        return MarketDataClient(session=session), session, response

    def test_success_preserves_response_and_verified_direct_request(self):
        body = payload()
        client, session, response = self.client(body)
        result = client.fetch(["000001.SZ"])
        self.assertEqual(result["status"], "success")
        self.assertIs(result["response"], body)
        self.assertEqual(result["received_symbols"], ["000001.SZ"])
        self.assertFalse(session.trust_env)
        self.assertIs(session.post.call_args.kwargs["verify"], True)
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
        self.assertEqual(session.post.call_args.kwargs["json"], ["000001.SZ"])
        response.close.assert_called_once()

    def test_http_200_is_not_business_success(self):
        for overrides in ({"respSuccess": False}, {"respFail": True}, {"code": "1"}, {"code": False}):
            with self.subTest(overrides=overrides):
                client, _, _ = self.client(payload(**overrides))
                self.assertEqual(client.fetch(["000001.SZ"])["status"], "business_error")
        client, _, _ = self.client({"data": {"000001.SZ": {"latestPrice": 1}}})
        self.assertEqual(client.fetch(["000001.SZ"])["status"], "business_error")

    def test_missing_symbols_are_explicit_and_never_filled(self):
        body = payload()
        client, _, _ = self.client(body)
        result = client.fetch(["000001.SZ", "603110.SH"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["missing_symbols"], ["603110.SH"])
        self.assertNotIn("603110.SH", result["response"]["data"])

    def test_empty_or_null_symbol_values_are_not_success(self):
        for data in ({}, {"000001.SZ": None}, {"000001.SZ": {}}):
            with self.subTest(data=data):
                client, _, _ = self.client(payload(data))
                self.assertEqual(client.fetch(["000001.SZ"])["status"], "empty")

    def test_invalid_json_and_http_error_keep_evidence(self):
        for status, expected in ((200, "invalid_json"), (503, "http_error"), (302, "http_error")):
            with self.subTest(status=status):
                client, _, response = self.client(None, status=status, json_error=True)
                result = client.fetch(["000001.SZ"])
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["response_preview"], "<html>failure</html>")
                self.assertEqual(result["http_status"], status)
                response.close.assert_called_once()

    def test_invalid_response_shapes(self):
        for body in (None, [], payload(data=[])):
            with self.subTest(body=body):
                client, _, _ = self.client(body)
                self.assertEqual(client.fetch(["000001.SZ"])["status"], "invalid_response")

    def test_network_errors_are_classified_without_throwing(self):
        cases = ((requests.exceptions.SSLError, "tls_error"),
                 (requests.exceptions.ProxyError, "proxy_error"),
                 (requests.exceptions.ReadTimeout, "timeout"),
                 (requests.exceptions.ConnectionError, "connection_error"))
        for exception, expected in cases:
            with self.subTest(exception=exception):
                client, session, _ = self.client(None)
                session.post.side_effect = exception("simulated")
                result = client.fetch(["000001.SZ"])
                self.assertEqual(result["status"], expected)
                self.assertIn("received_at", result)
                self.assertNotIn("response", result)


class StorageTests(TemporaryCase):
    def test_day_rollover_and_run_isolation(self):
        first, second = JsonlStore(self.root, "run1"), JsonlStore(self.root, "run2")
        record = {"received_at": "2026-09-18T23:59:59+08:00", "status": "success", "response": payload()}
        first.batch(record)
        first.batch({**record, "received_at": "2026-09-19T00:00:00+08:00"})
        second.batch(record)
        paths = list(self.root.glob("*/*/batches.jsonl"))
        self.assertEqual(len(paths), 3)
        records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        self.assertEqual({row["run_id"] for row in records}, {"run1", "run2"})
        self.assertTrue(all(row["response"] == payload() for row in records))

    def test_existing_run_is_never_overwritten(self):
        JsonlStore(self.root, "existing")
        with self.assertRaises(FileExistsError):
            JsonlStore(self.root, "existing")

    def test_non_json_number_does_not_leave_partial_record(self):
        store = JsonlStore(self.root)
        with self.assertRaises(ValueError):
            store.batch({"received_at": "2026-09-18T12:00:00+08:00", "value": float("nan")})
        self.assertEqual(list(self.root.glob("*/*/batches.jsonl")), [])


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.stopped = False

    def clock(self):
        return self.now

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, delay):
        self.now += delay
        return self.stopped


class FakeClient:
    url = "https://example.invalid/market"
    session = SimpleNamespace(trust_env=False)
    verify = True
    timeout = (10, 30)

    def __init__(self, timer, hook=None):
        self.timer, self.hook = timer, hook
        self.requests = []
        self.starts = []

    def fetch(self, symbols):
        self.requests.append(symbols[:])
        self.starts.append(self.timer.clock())
        status = self.hook(self) if self.hook else "success"
        return {"received_at": "2026-09-18T12:00:00+08:00", "status": status or "success", "symbols": symbols,
                "response": payload({symbol: {"latestPrice": 1} for symbol in symbols})}

    def close(self):
        pass


class CollectorTests(TemporaryCase):
    def setup_run(self, values=None, hook=None):
        symbols = self.symbols(values or ["000001.SZ", "603110.SH"])
        timer = FakeTime()
        client = FakeClient(timer, hook)
        store = JsonlStore(self.root / "data")
        return symbols, timer, client, store

    def test_many_symbols_batch_and_poll_without_real_waits(self):
        path, timer, client, store = self.setup_run()
        summary = collect(client, store, [path], interval=2, batch_size=1, max_polls=3, stop=timer, clock=timer.clock)
        self.assertEqual(client.starts, [0, 0, 2, 2, 4, 4])
        self.assertEqual(summary["requests_saved"], 6)
        self.assertEqual(summary["batch_status_counts"], {"success": 6})
        records = [json.loads(line) for line in next((self.root / "data").glob("*/*/batches.jsonl")).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(row["poll"], row["batch"]) for row in records], [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)])

    def test_slow_requests_skip_slots_instead_of_catching_up(self):
        path, timer, client, store = self.setup_run()
        client.hook = lambda _: setattr(timer, "now", timer.now + 12)
        collect(client, store, [path], interval=5, max_polls=3, stop=timer, clock=timer.clock)
        self.assertEqual(client.starts, [0, 15, 30])
        events = [json.loads(line) for line in (store.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["skipped_intervals"] for event in events if event["event"] == "schedule_skipped"], [2, 2])

    def test_hot_reload_recovers_after_invalid_intermediate_save(self):
        path, timer, client, store = self.setup_run(["000001.SZ"])

        def edit(client):
            if len(client.requests) == 1:
                path.write_text('["incomplete', encoding="utf-8")
            elif len(client.requests) == 2:
                path.write_text('["603110.SH"]', encoding="utf-8")

        client.hook = edit
        collect(client, store, [path], max_polls=3, stop=timer, clock=timer.clock)
        self.assertEqual(client.requests, [["000001.SZ"], ["000001.SZ"], ["603110.SH"]])
        events = [json.loads(line)["event"] for line in (store.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn("symbol_reload_error", events)
        self.assertIn("symbols_changed", events)

    def test_request_failure_does_not_stop_later_round(self):
        path, timer, client, store = self.setup_run()
        client.hook = lambda client: "timeout" if len(client.requests) == 1 else "success"
        summary = collect(client, store, [path], max_polls=2, stop=timer, clock=timer.clock)
        self.assertEqual(summary["batch_status_counts"], {"timeout": 1, "success": 1})

    def test_stop_finishes_current_request_without_starting_next_batch(self):
        path, timer, client, store = self.setup_run()
        client.hook = lambda _: timer.set()
        summary = collect(client, store, [path], batch_size=1, stop=timer, clock=timer.clock)
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(summary["requests_saved"], 1)
        self.assertEqual(json.loads((store.run_dir / "run.json").read_text(encoding="utf-8"))["status"], "stopped")

    def test_storage_failure_stops_before_more_requests(self):
        path, timer, client, store = self.setup_run()
        with patch.object(store, "batch", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                collect(client, store, [path], max_polls=5, stop=timer, clock=timer.clock)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(json.loads((store.run_dir / "run.json").read_text(encoding="utf-8"))["status"], "failed")


class CliTests(TemporaryCase):
    def test_defaults_are_continuous_and_direct(self):
        args = parser().parse_args([])
        self.assertEqual(args.max_polls, 0)
        self.assertFalse(args.use_environment)
        self.assertEqual(parser().parse_args(["--once"]).max_polls, 1)
        self.assertTrue(parser().parse_args(["--use-env-proxy"]).use_environment)

    def test_nonfinite_or_nonpositive_intervals_fail(self):
        for value in ("0", "-1", "nan", "inf", "-inf"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args(["--interval", value])

    def test_invalid_initial_symbols_do_not_request_or_create_output(self):
        output = self.root / "data"
        with patch("index_strategy.instant_dld.cli.MarketDataClient") as client:
            result = main(["--symbols-file", str(self.root / "missing.json"), "--output-dir", str(output), "--once"])
        self.assertEqual(result, 1)
        self.assertFalse(output.exists())
        client.assert_not_called()

    def test_failed_bounded_run_has_nonzero_exit_status(self):
        symbols = self.symbols(["000001.SZ"])
        for status, expected in (("success", 0), ("partial", 2), ("timeout", 2)):
            with self.subTest(status=status):
                client = FakeClient(FakeTime(), lambda _: status)
                with patch("index_strategy.instant_dld.cli.MarketDataClient", return_value=client):
                    result = main(["--symbols-file", str(symbols), "--output-dir", str(self.root / status), "--once"])
                self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
