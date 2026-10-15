import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from index_futures_basis.config import DEFAULTS
from index_futures_basis.wind import WindProvider


class WindProcessTests(unittest.TestCase):
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
