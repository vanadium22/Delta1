import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from index_strategy.data_dld.wind_connection import credentials


class WindSettingsTests(unittest.TestCase):
    def test_environment_can_supply_all_settings_without_reading_file(self):
        values = {"WIND_DB_USER": "test-user", "WIND_DB_PASSWORD": "test-password", "WIND_DB_DSN": "test-dsn"}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(credentials(Path("nonexistent.json")), {"user": "test-user", "password": "test-password", "dsn": "test-dsn"})

    def test_environment_overrides_only_provided_fields(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"user": "local-user", "password": "local-password", "dsn": "local-dsn"}))
            with patch.dict(os.environ, {"WIND_DB_PASSWORD": "override"}, clear=True):
                self.assertEqual(credentials(path), {"user": "local-user", "password": "override", "dsn": "local-dsn"})

    def test_missing_configuration_fails_without_legacy_code_fallback(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            credentials(Path("nonexistent.json"))

    def test_non_object_or_invalid_values_fail(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for values in ([], {"user": 10, "password": "test", "dsn": "test"}):
                path.write_text(json.dumps(values))
                with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                    credentials(path)


if __name__ == "__main__":
    unittest.main()
