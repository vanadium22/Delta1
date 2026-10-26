import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.app_check import check


class PreflightTests(unittest.TestCase):
    def test_profile_selected_explicitly_and_history_error_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text(json.dumps(dict(history_roots=['fixture-missing-history'])))
            with patch('dashboard.marketdata.history_quick.quick_check',side_effect=OSError('unavailable history')),\
                 patch('dashboard.app_config.credential_state',return_value={}),\
                 patch('dashboard.app_config.history_python',return_value='fixture-python'):
                report=check(root)
            self.assertTrue(report['ok']);self.assertEqual(report['profile'],str(root/'native.json'))
            self.assertEqual(report['quick']['error_type'],'OSError')
            self.assertFalse(report['network_requested']);self.assertFalse(report['vpn_changed'])

    def test_malformed_explicit_profile_is_reported_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'native.json';p.write_bytes(b'{invalid')
            with patch('dashboard.marketdata.history_quick.quick_check',return_value={}),\
                 patch('dashboard.app_config.credential_state',return_value={}),\
                 patch('dashboard.app_config.history_python',return_value='fixture-python'):
                report=check(root)
            self.assertFalse(report['ok']);self.assertEqual(report['profile_error'],'JSONDecodeError')
            self.assertEqual(p.read_bytes(),b'{invalid')


if __name__=='__main__':unittest.main()
