import json
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.marketdata import ddb_vpn as vpn
from dashboard.marketdata import history_maintenance as hm
from dashboard.app_config import vpn_profile
from dashboard.session_clock import realtime_prompt_policy
from tests import test_app_pipeline as pipeline_tests

pump=pipeline_tests.pump


class AppVpnHistoryTests(unittest.TestCase):
    def test_app_worker_defaults_to_auto_and_preserves_explicit_manual(self):
        from dashboard.native.history_maintenance import HistoryMaintenance
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=SimpleNamespace(local_root=root,config=dict(history_roots=[str(root/'history')]))
            for mode in ('auto','manual'):
                if mode=='manual':model.config['history_vpn_mode']=mode
                controller=HistoryMaintenance(model);controller.authorized=True
                with patch('dashboard.app_config.history_python',return_value='fixture-python.exe'),\
                     patch('dashboard.native.history_maintenance.subprocess.Popen') as popen:
                    self.assertTrue(controller.start())
                command=popen.call_args.args[0]
                self.assertEqual(command[command.index('--vpn-mode')+1],mode)
                self.assertIn('--incremental',command)
                self.assertIn('--owner-pid',command)

    def fixture(self):
        from tests.test_history_maintenance import HistoryMaintenanceTests
        c=HistoryMaintenanceTests();c.setUp();self.addCleanup(c.doCleanups);return c

    def credentials(self):
        return dict(host='fixture.invalid',port=8903,username='fixture',password='NEVER_EXPORT',enable_ssl=True)

    def test_gap_uses_auto_vpn_then_database_then_closes(self):
        c=self.fixture();events=[]
        def connect(connection,*args,**kwargs):
            events.append('vpn');self.assertEqual(connection['password'],'NEVER_EXPORT')
            return dict(state='connected',mode='native_login',tcp_verified=True,tls_pin_verified=True)
        def database(_):events.append('database');return c.client
        with patch('index_strategy.history.credentials.load_config',side_effect=lambda _:self.credentials()),\
             patch.object(vpn,'ensure_connected',side_effect=connect):
            result=hm.run_cycle(c.local,force=True,incremental=True,vpn_mode='auto',
                direct_factory=database,fetcher=c.full_fetch,today='2026-10-19')
        self.assertEqual(events,['vpn','database']);self.assertEqual(result['inserted'],4820)
        self.assertEqual(result['ddb_vpn']['mode'],'native_login');c.client.close.assert_called_once()
        self.assertNotIn('NEVER_EXPORT',json.dumps(result));self.assertEqual(result['state'],'complete')

    def test_no_gap_never_logs_in_or_reads_credentials(self):
        c=self.fixture();c.cycle()
        with patch.object(vpn,'ensure_connected') as ensure,patch('index_strategy.history.credentials.load_config') as credentials:
            result=c.cycle(incremental=True,vpn_mode='auto')
        ensure.assert_not_called();credentials.assert_not_called()
        self.assertEqual(result['ddb_vpn']['state'],'not_needed')

    def test_vpn_failure_is_safe_and_does_not_open_database(self):
        c=self.fixture();database=Mock()
        with patch('index_strategy.history.credentials.load_config',side_effect=lambda _:self.credentials()),\
             patch.object(vpn,'ensure_connected',side_effect=vpn.VPNError('interactive')):
            result=hm.run_cycle(c.local,force=True,vpn_mode='auto',direct_factory=database,today='2026-10-19')
        database.assert_not_called();self.assertEqual(result['state'],'waiting_vpn')
        self.assertIn('二次认证',result['message']);self.assertNotIn('NEVER_EXPORT',json.dumps(result))

    def test_owner_exit_cancels_vpn_before_database_authentication(self):
        c=self.fixture();database=Mock();lifetime=SimpleNamespace(stopped=threading.Event())
        def connect(*args,**kwargs):
            lifetime.stopped.set();vpn.check_stop(kwargs['stop_file'])
        with patch('index_strategy.history.credentials.load_config',side_effect=lambda _:self.credentials()),\
             patch.object(vpn,'ensure_connected',side_effect=connect):
            result=hm.run_cycle(c.local,force=True,vpn_mode='auto',direct_factory=database,today='2026-10-19',lifetime=lifetime)
        database.assert_not_called();self.assertEqual(result['state'],'stopped')
        self.assertEqual(result['ddb_vpn']['state'],'cancelled')

    def test_existing_app_copy_resolves_original_numeric_vpn_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);app=base/'app';numeric=base/'numeric_excel';app.mkdir();numeric.mkdir()
            original=json.dumps(dict(history_vpn_config='D:/existing/vpn.json',history_vpn_trust='D:/existing/trust.json',history_vpn_powershell='D:/PowerShell/pwsh.exe'))
            path=numeric/'native.json';path.write_text(original)
            selected=vpn_profile({},app)
            self.assertEqual(selected['config'],'D:/existing/vpn.json');self.assertEqual(selected['trust'],'D:/existing/trust.json')
            self.assertEqual(path.read_text(),original);self.assertEqual(list(app.iterdir()),[])
            self.assertEqual(vpn_profile({'history_vpn_config':'D:/explicit.json'},app)['config'],'D:/explicit.json')


class AppVpnPromptTests(unittest.TestCase):
    failure=dict(ok=False,message='fixture timeout',diagnostics=dict(stage='http_request',status='timeout'))
    allowed=dict(allowed=True,key='2026-10-23:am',reason='test')

    def fixture(self):
        w,p=pipeline_tests.PipelineTests.fixture(self);p.enabled=True
        self.addCleanup(p.readonly);return w,p

    def test_prompt_calendar_excludes_lunch_evening_weekends_and_holidays(self):
        for stamp,expected in [('2026-10-23T09:29:00+08:00',False),('2026-10-23T09:30:00+08:00',True),
            ('2026-10-23T11:29:59+08:00',True),('2026-10-23T11:30:00+08:00',False),
            ('2026-10-23T12:45:00+08:00',False),('2026-10-23T13:00:00+08:00',True),
            ('2026-10-23T15:00:00+08:00',False),('2026-10-24T10:00:00+08:00',False),
            ('2026-10-01T10:00:00+08:00',False)]:
            with self.subTest(stamp=stamp):self.assertEqual(realtime_prompt_policy(datetime.fromisoformat(stamp))['allowed'],expected)

    def test_prompt_only_after_history_exit_and_network_failure(self):
        w,p=self.fixture()
        with patch('dashboard.session_clock.realtime_prompt_policy',return_value=self.allowed):
            p.history.process=Mock();p.offer_realtime_prompt(self.failure);self.assertIsNone(p.realtime_dialog)
            p.history.process=None
            p.offer_realtime_prompt(dict(diagnostics=dict(stage='network_lock',status='timeout')))
            self.assertIsNone(p.realtime_dialog)
            p.offer_realtime_prompt(self.failure);self.assertIsNotNone(p.realtime_dialog)
            self.assertTrue(p.awaiting_realtime)

    def test_failed_probe_opens_prompt_and_confirmation_requests_validation(self):
        w,p=self.fixture()
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True)),\
             patch('dashboard.session_clock.realtime_prompt_policy',return_value=self.allowed),\
             patch('dashboard.session_guard.probe_realtime',return_value=self.failure):
            p.start_probe();pump(.12)
        self.assertIsNotNone(p.realtime_dialog)
        next(b for b in p.realtime_dialog.buttons() if b.text().startswith('已连接')).click();pump(.01)
        self.assertIsNone(p.realtime_dialog);self.assertEqual(p.action,'realtime')
        with patch('dashboard.session_clock.realtime_prompt_policy',return_value=self.allowed):p.offer_realtime_prompt(self.failure)
        self.assertIsNone(p.realtime_dialog)  # No repeated popups after a failed confirmation.

    def test_later_means_readonly_and_no_automatic_reprompt(self):
        w,p=self.fixture()
        with patch('dashboard.session_clock.realtime_prompt_policy',return_value=self.allowed):
            p.offer_realtime_prompt(self.failure)
            next(b for b in p.realtime_dialog.buttons() if b.text().startswith('稍后')).click();pump(.01)
            p.offer_realtime_prompt(self.failure)
        self.assertFalse(p.enabled);self.assertIsNone(p.realtime_dialog)

    def test_off_hours_never_open_and_close_an_existing_prompt(self):
        w,p=self.fixture()
        with patch('dashboard.session_clock.realtime_prompt_policy',return_value=dict(allowed=False,key=None)):
            p.offer_realtime_prompt(self.failure);self.assertIsNone(p.realtime_dialog)
        with patch('dashboard.session_clock.realtime_prompt_policy',return_value=self.allowed):p.offer_realtime_prompt(self.failure)
        with patch('dashboard.session_clock.realtime_prompt_policy',return_value=dict(allowed=False,key=None)),patch.object(p,'start_probe'):
            p.tick()
        self.assertIsNone(p.realtime_dialog);self.assertFalse(p.awaiting_realtime)

    def test_realtime_wait_never_restarts_ddb_automatically(self):
        w,p=self.fixture();p.phase='waiting_network';p.next_retry=time.monotonic()+999;p.history_retry=0
        with patch.object(p,'request_history') as history:
            for _ in range(5):p.tick()
        history.assert_not_called()


if __name__=='__main__':unittest.main()
