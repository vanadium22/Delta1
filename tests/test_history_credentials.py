import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from index_strategy.history import protected_config as credentials


@unittest.skipUnless(os.name=='nt','Windows DPAPI credentials')
class ProtectedCredentialsTests(unittest.TestCase):
    def test_encrypted_roundtrip_and_no_plaintext_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ddb.connection.local.json'
            original=dict(host='fixture.invalid',port=1234,username='fixture-only-account',password='fixture-only-password',enable_ssl=True)
            credentials.save_config(path,original)
            raw=path.read_text(encoding='utf8')
            self.assertNotIn(original['username'],raw);self.assertNotIn(original['password'],raw)
            self.assertEqual(credentials.load_config(path),original)
            self.assertEqual(json.loads(raw)['protected_credentials']['scheme'],'windows-dpapi-current-user-v1')

    def test_corrupt_profile_fails_without_secret_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ddb.connection.local.json'
            path.write_text('{"protected_credentials":{"scheme":"windows-dpapi-current-user-v1","data":"not-valid"}}',encoding='utf8')
            with self.assertRaises(credentials.CredentialError) as result:credentials.load_config(path)
            self.assertNotIn('not-valid',str(result.exception))

    def test_fresh_checkout_uses_bundled_provider(self):
        from index_strategy.history.credentials import provider
        with patch('index_strategy.history.credentials.Path.is_file',return_value=False):
            self.assertIs(provider(),credentials)


if __name__=='__main__':unittest.main()
