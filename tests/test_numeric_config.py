import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.numeric_config import prepare_config, problems


class NumericConfigTests(unittest.TestCase):
    def test_original_and_existing_numeric_settings_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp)
            original = module/'localsetting/native.json'
            original.parent.mkdir()
            raw = b'{"history_roots": [], "company_only": "synthetic"}'
            original.write_bytes(raw)
            target = prepare_config(module_root=module)
            self.assertEqual(target, module/'localsetting/numeric_excel')
            self.assertEqual((target/'native.json').read_bytes(), raw)
            (target/'native.json').write_text('{"numeric_only": true}',encoding='utf8')
            prepare_config(module_root=module)
            self.assertEqual(original.read_bytes(), raw)
            self.assertEqual(json.loads((target/'native.json').read_text()), {'numeric_only':True})

    def test_explicit_root_is_respected_and_invalid_source_is_not_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp)
            explicit = module/'chosen'
            self.assertEqual(prepare_config(explicit,module_root=module),explicit)
            self.assertFalse(explicit.exists())
            original = module/'localsetting/native.json'
            original.parent.mkdir()
            original.write_text('invalid JSON',encoding='utf8')
            with self.assertRaises(ValueError):prepare_config(module_root=module)
            self.assertFalse((module/'localsetting/numeric_excel/native.json').exists())

    def test_missing_history_and_wind_database_do_not_pass_offline_check(self):
        with tempfile.TemporaryDirectory() as tmp, patch('requests.Session',side_effect=AssertionError('must be offline')):
            raw = Path(tmp)/'wind.sqlite3'
            raw.write_bytes(b'not a normalized dataset')
            result=problems(dict(history_roots=[str(raw)],reference_file='',realtime_root=''))
            self.assertTrue(any('标准化数据' in x for x in result))
            self.assertEqual(raw.read_bytes(), b'not a normalized dataset')
            self.assertTrue(any('未配置标准化历史' in x for x in problems({})))

    def test_new_config_is_private_and_has_independent_cache_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            module=Path(tmp)
            target=prepare_config(module_root=module)
            config=json.loads((target/'native.json').read_text(encoding='utf8'))
            self.assertEqual(config['history_roots'],[])
            self.assertTrue(config['realtime_root'].replace('\\','/').endswith('/dashboard/realtime'))
            self.assertFalse((module/'localsetting/native.json').exists())
