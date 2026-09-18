from __future__ import annotations

from datetime import datetime
from functools import partial
from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest

from index_strategy.frontend.server import ConsoleServer
from index_strategy.frontend.service import ConflictError, DownloadService
from index_strategy.instant_dld.collector import collect


class TestClient:
    url = "https://example.invalid/market"
    session = SimpleNamespace(trust_env=False)
    timeout = (10, 30)
    verify = True

    def __init__(self, entered=None, release=None):
        self.entered, self.release, self.closed = entered, release, False

    def fetch(self, symbols):
        if self.entered:
            self.entered.set()
        if self.release and not self.release.wait(3):
            raise TimeoutError("Test did not release the request")
        return {"received_at": datetime.now().astimezone().isoformat(), "elapsed_seconds": .012,
                "symbols": symbols, "status": "success", "http_status": 200,
                "response": {"respSuccess": True, "code": "0", "data": {symbol: {"latestPrice": 10} for symbol in symbols}}}

    def close(self):
        self.closed = True


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        path = self.root / "index_strategy/instant_dld/config/symbols.json"
        path.parent.mkdir(parents=True)
        path.write_text('["000001.SZ", "603110.SH"]', encoding="utf-8")
        self.service = DownloadService(self.root, client_factory=TestClient, collector=partial(collect, max_polls=1))
        self.addCleanup(self.service.close)
        self.config = {"symbols": "000001.sz, 603110.SH\n000001.SZ", "interval": 1.5, "output_dir": "data/test"}

    def finish(self):
        self.service.worker.join(3)
        self.assertFalse(self.service.worker.is_alive())


class ServiceTests(ServiceCase):
    def test_settings_persist_and_symbols_remain_strings(self):
        result = self.service.save(self.config)
        self.assertEqual(result["symbols"], ["000001.SZ", "603110.SH"])
        self.assertEqual(Path(result["output_dir"]), self.root / "data/test")
        reloaded = DownloadService(self.root)
        self.assertEqual(reloaded.config(), result)
        self.assertFalse((self.root / "data/test").exists())

    def test_invalid_settings_cannot_replace_saved_configuration(self):
        self.service.save(self.config)
        original = self.service.settings_path.read_bytes()
        for changes in ({"symbols": []}, {"symbols": [1]}, {"interval": 0}, {"interval": True},
                        {"interval": float("nan")}, {"output_dir": ""}, {"output_dir": 12}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.service.save({**self.config, **changes})
        self.assertEqual(self.service.settings_path.read_bytes(), original)

    def test_corrupt_saved_settings_are_not_silently_reset(self):
        self.service.settings_path.parent.mkdir(exist_ok=True)
        self.service.settings_path.write_text('{"broken', encoding="utf-8")
        with self.assertRaises(ValueError):
            DownloadService(self.root)
        self.assertEqual(self.service.settings_path.read_text(), '{"broken')

    def test_job_writes_data_reports_counts_and_can_restart(self):
        self.service.start(self.config)
        self.finish()
        first = self.service.snapshot()
        self.assertEqual(first["status"], "stopped")
        self.assertEqual(first["stats"]["batches"], 1)
        self.assertEqual(first["stats"]["successful"], 1)
        self.assertEqual(first["stats"]["last_latency_ms"], 12)
        self.assertTrue(Path(first["run_dir"], "run.json").is_file())
        self.service.start(self.config)
        self.finish()
        self.assertNotEqual(self.service.snapshot()["run_id"], first["run_id"])
        self.assertEqual(len(list((self.root / "data/test").glob("*/*/batches.jsonl"))), 2)

    def test_stop_waits_for_inflight_save_and_rejects_duplicate_start(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        client = TestClient(entered, release)
        self.service.client_factory = lambda: client
        self.service.start(self.config)
        self.assertTrue(entered.wait(2))
        with self.assertRaises(ConflictError):
            self.service.start(self.config)
        with self.assertRaises(ConflictError):
            self.service.save(self.config)
        self.assertEqual(self.service.stop()["status"], "stopping")
        self.assertEqual(self.service.stop()["status"], "stopping")
        release.set()
        self.finish()
        self.assertTrue(client.closed)
        self.assertEqual(self.service.snapshot()["stats"]["batches"], 1)
        summary = json.loads(Path(self.service.run_dir, "run.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "stopped")

    def test_background_failure_is_visible_and_does_not_leave_running_state(self):
        def unavailable():
            raise OSError("simulated unavailable storage")
        self.service.client_factory = unavailable
        self.service.start(self.config)
        self.finish()
        state = self.service.snapshot()
        self.assertEqual(state["status"], "failed")
        self.assertIn("simulated", state["error"])
        self.assertTrue(any(row["level"] == "ERROR" for row in state["logs"]))

    def test_log_window_is_bounded_and_cursor_is_monotonic(self):
        for number in range(650):
            self.service.log("INFO", str(number))
        state = self.service.snapshot()
        self.assertEqual(len(state["logs"]), 600)
        self.assertEqual(self.service.snapshot(state["log_cursor"])["logs"], [])
        self.service.log("WARNING", "next")
        new = self.service.snapshot(state["log_cursor"])
        self.assertEqual([row["message"] for row in new["logs"]], ["next"])


class ServerTests(ServiceCase):
    def setUp(self):
        super().setUp()
        self.server = ConsoleServer(0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown_server)

    def shutdown_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, value=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {"Content-Type": "application/json", "X-Delta1-Token": self.server.token}
        request_headers.update(headers or {})
        body = json.dumps(value).encode() if value is not None else None
        try:
            connection.request("POST" if value is not None else "GET", path, body, request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_page_and_assets_are_local_and_have_correct_media_types(self):
        for path, media in (("/", "text/html"), ("/app.js", "text/javascript"), ("/styles.css", "text/css")):
            with self.subTest(path=path):
                status, headers, content = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn(media, headers["Content-Type"])
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
                self.assertTrue(content)

    def test_bootstrap_save_start_stop_and_log_refresh(self):
        status, _, raw = self.request("/api/bootstrap")
        self.assertEqual(status, 200)
        bootstrap = json.loads(raw)
        self.assertEqual(bootstrap["config"]["symbols"], ["000001.SZ", "603110.SH"])
        self.assertEqual(self.request("/api/config", self.config)[0], 200)
        self.assertEqual(self.request("/api/start", self.config)[0], 200)
        self.finish()
        status, _, raw = self.request("/api/state?after=0")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["stats"]["batches"], 1)
        self.assertEqual(self.request("/api/stop", {})[0], 200)

    def test_multiple_imported_files_are_merged_without_execution(self):
        status, _, raw = self.request("/api/symbols/parse", {"files": [
            {"name": "first.json", "text": '["000001.SZ"]'},
            {"name": "second.list", "text": "['000001.SZ', '603110.SH']"}]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["symbols"], ["000001.SZ", "603110.SH"])
        self.assertEqual(self.request("/api/symbols/parse", {"files": [{"name": "bad.py", "text": "print('not executed')"}]})[0], 400)

    def test_foreign_origin_or_host_or_missing_token_cannot_change_settings(self):
        for headers in ({"Origin": "https://example.invalid"}, {"Host": "example.invalid"}, {"X-Delta1-Token": ""}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/config", self.config, headers)[0], 403)
        self.assertFalse(self.service.settings_path.exists())

    def test_private_files_and_path_traversal_are_not_served(self):
        self.service.save(self.config)
        for path in ("/localsetting/realtime_ui.json", "/../localsetting/realtime_ui.json", "/api/state?after=oops"):
            with self.subTest(path=path):
                self.assertIn(self.request(path)[0], {400, 404})

    def test_invalid_configuration_and_content_type_return_errors(self):
        self.assertEqual(self.request("/api/config", {**self.config, "interval": -1})[0], 400)
        self.assertEqual(self.request("/api/config", self.config, {"Content-Type": "text/plain"})[0], 415)


if __name__ == "__main__":
    unittest.main()
