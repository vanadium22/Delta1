"""Synthetic SDK subprocesses exercise the company entry without real Wind."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from index_futures_basis.config import DEFAULTS
from index_futures_basis.diagnostic_worker import snapshot
from index_futures_basis.store import Store
from index_futures_basis.tests.test_sync import FakeProvider
from index_futures_basis.wind_diagnostics import DiagnosticProvider, Report, main
from shared_data import DataPaths
from types import SimpleNamespace


SDK_SOURCE = '''
from datetime import date, datetime
import json
from pathlib import Path
from types import SimpleNamespace as R
fixture = json.loads(Path(__file__).with_name("sdk_fixture.json").read_text())
class W:
    def start(self, **kwargs):
        print("SDK startup banner must not corrupt JSON")
        return R(ErrorCode=0)
    def isconnected(self):
        return True
    def stop(self):
        pass
    def tdays(self, start, end, options):
        assert options == "TradingCalendar=CFFE;Days=Trading"
        days = [datetime.fromisoformat(d) for d in fixture["calendar"] if start <= d <= end]
        return R(ErrorCode=0, Data=[days] if days else [], Times=days, Codes=[], Fields=[])
    def tdayscount(self, start, end, options):
        days = [d for d in fixture["calendar"] if start <= d <= end]
        return R(ErrorCode=0, Data=[[len(days)]], Times=[], Codes=[], Fields=[])
    def wsd(self, code, fields, start, end, options):
        names = fields.split(",")
        values = [fixture["mapping"].get(code) if f == "trade_hiscode" else fixture["quotes"].get(code, {}).get(f)
                  for f in names]
        return R(ErrorCode=0, Fields=[f.upper() for f in names], Codes=[code],
                 Times=[datetime.fromisoformat(start)], Data=[[v] for v in values])
    def wss(self, codes, field, options):
        codes = codes.split(",")
        return R(ErrorCode=0, Fields=[field.upper()], Codes=codes,
                 Data=[[fixture["expiries"][c] for c in codes]])
w = W()
'''


class WindDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "app"
        self.sdk = Path(self.temp.name) / "sdk"
        self.sdk.mkdir()
        fake = FakeProvider()
        session = "2026-07-10"
        fixture = {"calendar": [d for d in fake.raw["calendar"] if d != "2026-07-01"],
                   "mapping": {alias: code for (alias, day), code in fake.mapping_values.items() if day == session},
                   "quotes": {}, "expiries": fake.expiry_values}
        for (code, day, field), value in fake.quote_values.items():
            if day == session:
                fixture["quotes"].setdefault(code, {})[field] = value
        self.fixture = fixture
        (self.sdk / "sdk_fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
        (self.sdk / "WindPy.py").write_text(SDK_SOURCE, encoding="utf-8")
        self.env = patch.dict(os.environ, {"PYTHONPATH": str(self.sdk),
            "DELTA1_DATA_ROOT": str(self.root / "data"), "DELTA1_OUTPUTS_ROOT": str(self.root / "outputs")})
        self.env.start()
        self.production = Store(DataPaths.for_module(self.root).basis("wind") / "market.sqlite")
        self.production.save_rows("quotes", [("000300.SH", "2026-07-09", "close", 999123.456)])
        self.production_hash = hashlib.sha256(self.production.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def run_diagnostic(self, *extra):
        output = Path(self.temp.name) / "result"
        with redirect_stdout(io.StringIO()) as console:
            code = main(["--root", str(self.root), "--as-of", "2026-07-10", "--output", str(output), *extra])
        pointer = json.loads((output / "latest.json").read_text(encoding="utf-8"))
        folder = Path(pointer["folder"])
        report = json.loads((folder / "diagnostic.json").read_text(encoding="utf-8"))
        return code, report, folder, console.getvalue()

    def test_full_diagnosis_weekend_holiday_fill_repeat_and_repair_without_production_writes(self):
        code, report, folder, console = self.run_diagnostic()
        self.assertEqual(code, 0, console)
        self.assertTrue(report["finished"])
        self.assertEqual(len(report["checks"]), 8)
        self.assertTrue(all(c["status"] == "PASS" for c in report["checks"]))
        weekend, holiday = report["checks"][3:5]
        self.assertEqual(weekend["detail"]["normalized_count"], 0)
        self.assertEqual(holiday["detail"]["raw"]["start"], "2026-07-01")
        self.assertEqual(holiday["detail"]["normalized_count"], 0)
        self.assertEqual(report["checks"][6]["detail"]["actual_provider_requests"], 0)
        self.assertEqual(report["checks"][7]["detail"]["requests"], 1)
        self.assertEqual(hashlib.sha256(self.production.path.read_bytes()).hexdigest(), self.production_hash)
        text = (folder / "可复制.txt").read_text(encoding="utf-8-sig")
        self.assertIn("请从这里完整复制", text)
        self.assertIn("data_columns", text)
        self.assertNotIn("999123.456", text)
        self.assertTrue((folder / "probe.sqlite").is_file())
        self.assertEqual((folder.parent / "latest.txt").read_text(encoding="utf-8-sig"), text)

    def test_missing_sdk_is_reported_and_later_checks_do_not_reconnect(self):
        (self.sdk / "WindPy.py").write_text('raise ImportError("SYNTHETIC_SDK_MISSING")', encoding="utf-8")
        code, report, folder, console = self.run_diagnostic()
        self.assertEqual(code, 2)
        self.assertTrue(report["finished"])
        self.assertIn("SYNTHETIC_SDK_MISSING", (folder / "可复制.txt").read_text(encoding="utf-8-sig"))
        self.assertEqual(report["checks"][0]["status"], "FAIL")
        self.assertTrue(any(c["status"] == "SKIP" for c in report["checks"]))
        self.assertNotIn("probe.sqlite", [p.name for p in folder.iterdir()])

    def test_hung_sdk_times_out_with_copyable_report(self):
        (self.sdk / "WindPy.py").write_text("import time\ntime.sleep(30)", encoding="utf-8")
        code, report, folder, _ = self.run_diagnostic("--timeout", "1", "--max-seconds", "3")
        self.assertEqual(code, 2)
        self.assertTrue(report["finished"])
        self.assertIn("Wind 请求超时", (folder / "可复制.txt").read_text(encoding="utf-8-sig"))
        self.assertTrue(all("后续连接检查已跳过" in r["error"] for r in report["requests"][1:]))

    def test_damaged_local_path_configuration_still_produces_report(self):
        local = self.root / "localsetting/data.local.json"
        local.parent.mkdir(parents=True)
        local.write_text("broken", encoding="utf-8")
        code, report, folder, _ = self.run_diagnostic()
        self.assertEqual(code, 2)
        self.assertEqual(report["requests"], [])
        self.assertIn("JSONDecodeError", (folder / "可复制.txt").read_text(encoding="utf-8-sig"))

    def test_partial_quotes_cannot_be_reported_as_success(self):
        actual = self.fixture["mapping"]["IF00.CFE"]
        self.fixture["quotes"][actual].pop("oi")
        (self.sdk / "sdk_fixture.json").write_text(json.dumps(self.fixture), encoding="utf-8")
        code, report, _, console = self.run_diagnostic()
        self.assertEqual(code, 2, console)
        self.assertEqual(report["checks"][5]["status"], "FAIL")
        self.assertEqual(report["checks"][-1]["status"], "SKIP")
        self.assertEqual(hashlib.sha256(self.production.path.read_bytes()).hexdigest(), self.production_hash)

    def test_bad_requested_dates_still_save_copyable_setup_error(self):
        code, report, folder, console = self.run_diagnostic("--holiday-date", "2026-07-11")
        self.assertEqual(code, 2)
        self.assertEqual(report["requests"], [])
        self.assertIn("样例不能晚于截止日", (folder / "可复制.txt").read_text(encoding="utf-8-sig"))

    def test_budget_exhaustion_is_bounded_and_saved(self):
        report = Report(Path(self.temp.name) / "budget", {})
        provider = DiagnosticProvider(DEFAULTS, report, timeout=5, budget=1)
        provider.deadline = 0
        with self.assertRaisesRegex(TimeoutError, "总时限"):
            provider.request("diagnostic_environment")
        with self.assertRaisesRegex(ConnectionError, "后续连接检查已跳过"):
            provider.request("diagnostic_environment")
        self.assertIsNone(provider.process)
        self.assertEqual(len(report.data["requests"]), 2)
        provider.close()

    def test_calendar_snapshot_bounds_samples_and_preserves_empty_shape(self):
        result = SimpleNamespace(ErrorCode=0, Data=[], Times=[], Codes=[], Fields=[])
        self.assertEqual(snapshot(result)["data_columns"], 0)
        result.Data = [list(range(100))]
        self.assertEqual(snapshot(result)["data_sample"], [[0, 1, 2]])
        self.assertEqual(snapshot(result)["data_lengths"], [100])

    @unittest.skipUnless(os.name == "nt", "Windows CMD launcher")
    def test_company_cmd_from_other_directory_uses_existing_python_and_returns_report(self):
        launcher = Path(__file__).resolve().parents[1] / "diagnose_wind.cmd"
        output = Path(self.temp.name) / "CMD 中文 result"
        env = dict(os.environ, SWHY_DELTA1_PYTHON=sys.executable)
        env.pop("BASIS_APP_PYTHON", None)
        result = subprocess.run([os.environ["ComSpec"], "/d", "/c", str(launcher), "--no-pause",
                                 "--root", str(self.root), "--as-of", "2026-07-10", "--output", str(output)],
                                cwd=self.temp.name, env=env, capture_output=True, text=True, encoding="utf-8", timeout=40,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((output / "latest.txt").is_file())
