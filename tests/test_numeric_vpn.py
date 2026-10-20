from contextlib import nullcontext
import ctypes
from ctypes import wintypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from dashboard.marketdata import ddb_vpn as vpn
from dashboard import numeric_startup as startup
from dashboard.numeric_vpn_config import configure as configure_vpn
from index_strategy.history.protected_config import load_config, save_config


class VPNTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'vpn.json';self.trust=self.root/'trust.json'
        self.config.write_text(json.dumps(dict(url='https://vpn.example:10443',
            protected_credentials=dict(scheme='windows-dpapi-current-user-v1',data='fixture'))))
        self.trust.write_text(json.dumps(dict(endpoint='https://vpn.example:10443',certificate_sha256='A'*64)))
        self.connection=dict(host='fixture.invalid',port=8903,enable_ssl=True)

    def test_gateway_and_trust_are_exact_and_protected(self):
        self.assertEqual(vpn.normalize_gateway('[https://VPN.example:10443](https://VPN.example:10443)\u00a0'),'https://vpn.example:10443')
        for url in ('http://vpn.example','https://user:password@vpn.example','https://vpn.example/path','https://vpn.example/?secret=x'):
            with self.subTest(url=url),self.assertRaises(vpn.VPNError):vpn.normalize_gateway(url)
        self.trust.write_text(json.dumps(dict(endpoint='https://other.example',certificate_sha256='A'*64)))
        with patch.object(vpn.subprocess,'Popen') as popen,self.assertRaises(vpn.VPNError):
            vpn.invoke('fixture.invalid',8903,self.config,self.trust)
        popen.assert_not_called()

    def test_existing_manual_tunnel_does_not_load_vpn_profile(self):
        with patch.object(vpn,'reachable',return_value=True),patch.object(vpn,'invoke') as invoke:
            result=vpn.ensure_connected(self.connection,self.root/'missing',self.root/'missing')
        self.assertEqual(result['mode'],'existing_tunnel')
        invoke.assert_not_called()

    def test_second_route_check_avoids_duplicate_login(self):
        with patch.object(vpn,'reachable',side_effect=[False,True]),\
             patch.object(vpn,'login_lock',return_value=nullcontext()),patch.object(vpn,'invoke') as invoke:
            vpn.ensure_connected(self.connection,self.config,self.trust)
        invoke.assert_not_called()

    def test_web_auth_without_verified_route_is_not_success(self):
        with patch.object(vpn,'reachable',return_value=False),patch.object(vpn,'login_lock',return_value=nullcontext()),\
             patch.object(vpn,'invoke',return_value=dict(state='connected')):
            with self.assertRaisesRegex(vpn.VPNError,'unreachable'):
                vpn.ensure_connected(self.connection,self.config,self.trust)

    def test_cancel_before_start_never_launches_helper(self):
        stop=self.root/'stop';stop.touch()
        with patch.object(vpn.subprocess,'Popen') as popen,self.assertRaises(vpn.VPNCancelled):
            vpn.invoke('fixture.invalid',8903,self.config,self.trust,stop_file=stop)
        popen.assert_not_called()

    def test_helper_protocol_and_output_are_sanitized(self):
        for output,returncode in [('private-password',1),('{"state":"failed","reason":"interactive_auth_required","password":"private-password"}',2),
                                  ('{"state":"connected","tcp_verified":true,"password":"private-password"}',0)]:
            child=Mock();child.stdin=io.StringIO();child.returncode=returncode
            child.communicate.return_value=(output,'private-password');child.poll.return_value=returncode
            with patch.object(vpn,'powershell',return_value='pwsh.exe'),\
                 patch.object(vpn,'child_lifetime',return_value=nullcontext()),\
                 patch.object(vpn.subprocess,'Popen',return_value=child) as popen:
                if returncode:
                    with self.assertRaises(vpn.VPNError) as raised:
                        vpn.invoke('fixture.invalid',8903,self.config,self.trust)
                    self.assertNotIn('private-password',str(raised.exception))
                    self.assertEqual(raised.exception.code, 'interactive' if returncode==2 else 'helper')
                else:
                    self.assertNotIn('password',vpn.invoke('fixture.invalid',8903,self.config,self.trust))
            self.assertNotIn('private-password',' '.join(popen.call_args.args[0]))
            self.assertEqual(child.stdin,None)

    @unittest.skipUnless(os.name=='nt','Windows process lifetime')
    def test_timeout_stops_actual_helper_before_return(self):
        real_popen=subprocess.Popen
        processes=[]
        def launch(*args,**kwargs):
            child=real_popen([sys.executable,'-B','-m','tests.numeric_vpn_worker','--child',
                             '--record',str(self.root/'child.json')],**kwargs)
            processes.append(child)
            return child
        try:
            with patch.object(vpn,'powershell',return_value='fixture'),patch.object(vpn.subprocess,'Popen',side_effect=launch),\
                 self.assertRaisesRegex(vpn.VPNError,'timeout'):
                vpn.invoke('fixture.invalid',8903,self.config,self.trust,timeout=.5)
            self.assertIsNotNone(processes[0].poll())
        finally:
            for child in processes:
                if child.poll() is None:child.kill()
                child.wait()

    @unittest.skipUnless(os.name=='nt','Windows process lifetime')
    def test_cancel_waits_until_actual_owned_helper_exits(self):
        real_popen=subprocess.Popen
        record=self.root/'child.json';stop=self.root/'stop';processes=[]
        def launch(*args,**kwargs):
            child=real_popen([sys.executable,'-B','-m','tests.numeric_vpn_worker','--child','--record',str(record)],**kwargs)
            processes.append(child)
            return child
        def cancel():
            deadline=time.monotonic()+10
            while not record.exists() and time.monotonic()<deadline:time.sleep(.03)
            stop.touch()
        thread=threading.Thread(target=cancel);thread.start()
        try:
            with patch.object(vpn,'powershell',return_value='fixture'),patch.object(vpn.subprocess,'Popen',side_effect=launch),\
                 self.assertRaises(vpn.VPNCancelled):
                vpn.invoke('fixture.invalid',8903,self.config,self.trust,stop_file=stop)
            self.assertTrue(record.exists())
            self.assertIsNotNone(processes[0].poll())
        finally:
            stop.touch();thread.join(12)
            for child in processes:
                if child.poll() is None:child.kill()
                child.wait()

    @unittest.skipUnless(os.name=='nt','Windows parent death')
    def test_parent_death_ends_helper_without_killing_unrelated_processes(self):
        record=self.root/'child.json'
        parent=subprocess.Popen([sys.executable,'-B','-m','tests.numeric_vpn_worker','--record',str(record)],
            creationflags=subprocess.CREATE_NO_WINDOW)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=None
        try:
            deadline=time.monotonic()+10
            while not record.exists() and parent.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(record.exists())
            pid=json.loads(record.read_text())['child']
            handle=kernel.OpenProcess(0x100001,False,pid)  # SYNCHRONIZE | TERMINATE for fixture cleanup
            self.assertTrue(handle)
            parent.kill();parent.wait(5)
            self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
        finally:
            if parent.poll() is None:parent.kill()
            parent.wait()
            if handle:
                if kernel.WaitForSingleObject(handle,0)!=0:kernel.TerminateProcess(handle,1)
                kernel.CloseHandle(handle)

    def test_history_auto_and_manual_paths_close_database_before_return(self):
        (self.root/'native.json').write_text('{}')
        events=[]
        client=Mock();client.close.side_effect=lambda:events.append('db_closed')
        def cycle(root,**kwargs):
            c=kwargs['direct_factory']('fixture')
            events.append('download')
            c.close()
            return dict(state='complete',message='complete')
        for mode in ('auto','manual'):
            events.clear()
            with patch('dashboard.marketdata.history_maintenance.run_cycle',side_effect=cycle),\
                 patch('dashboard.marketdata.history_maintenance.open_direct',side_effect=lambda _:events.append('db_open') or client),\
                 patch('index_strategy.history.credentials.load_config',side_effect=lambda _:dict(host='fixture',port=1,username='u',password='p')),\
                 patch('dashboard.numeric_startup.importlib.util.find_spec',return_value=True),\
                 patch.object(vpn,'ensure_connected',side_effect=lambda *a,**kw:events.append('vpn')):
                result=startup.history(self.root,self.root/'report',self.root/'stop',vpn_mode=mode)
            self.assertEqual(result['state'],'complete')
            self.assertEqual(events,(['vpn'] if mode=='auto' else [])+['db_open','download','db_closed'])

    def test_no_history_gap_never_logs_in(self):
        (self.root/'native.json').write_text('{}')
        with patch('dashboard.marketdata.history_maintenance.run_cycle',return_value=dict(state='complete')),\
             patch('index_strategy.history.credentials.load_config',return_value=dict(host='fixture',port=1,username='u',password='p')),\
             patch('dashboard.numeric_startup.importlib.util.find_spec',return_value=True),patch.object(vpn,'ensure_connected') as connect:
            startup.history(self.root,self.root/'report',self.root/'stop')
        connect.assert_not_called()

    def test_vpn_error_is_distinct_and_does_not_open_database(self):
        (self.root/'native.json').write_text('{}')
        def cycle(root,**kwargs):
            try:kwargs['direct_factory']('fixture')
            except ConnectionError:return dict(state='waiting_network')
            self.fail('expected failure')
        with patch('dashboard.marketdata.history_maintenance.run_cycle',side_effect=cycle),\
             patch('index_strategy.history.credentials.load_config',side_effect=lambda _:dict(host='fixture',port=1,username='u',password='p')),\
             patch('dashboard.numeric_startup.importlib.util.find_spec',return_value=True),\
             patch.object(vpn,'ensure_connected',side_effect=vpn.VPNError('powershell7')),\
             patch('dashboard.marketdata.history_maintenance.open_direct') as direct:
            result=startup.history(self.root,self.root/'report',self.root/'stop')
        self.assertEqual(result['state'],'waiting_vpn')
        self.assertIn('PowerShell 7',result['message']);direct.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_vpn_credentials_local_and_database_reentry_preserves_them(self):
        native=self.root/'native.json'
        native.write_text(json.dumps(dict(history_roots=['unchanged'])))
        with patch('builtins.input',return_value='vpn-test-user'),patch('getpass.getpass',return_value='vpn-test-password'),\
             patch('dashboard.numeric_vpn_config.powershell',return_value='fixture-pwsh'):
            configure_vpn(self.root,gateway='https://vpn.example:10443',fingerprint='A'*64)
        config=json.loads(native.read_text(encoding='utf8'))
        vpn_path=Path(config['history_vpn_config']);protected=vpn_path.read_bytes()
        self.assertNotIn(b'vpn-test-password',protected);self.assertNotIn(b'vpn-test-user',protected)
        for password in ('wrong-test-password','corrected-test-password'):
            with patch('builtins.input',side_effect=['fixture.invalid','8903','ddb-test-user','Y',sys.executable]),\
                 patch('getpass.getpass',return_value=password):
                startup.configure(self.root)
            c=json.loads(native.read_text(encoding='utf8'))
            self.assertEqual(load_config(c['history_connection_file'])['password'],password)
            self.assertEqual(c['history_roots'],['unchanged'])
            self.assertEqual(c['history_vpn_config'],str(vpn_path))
            self.assertEqual(vpn_path.read_bytes(),protected)

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_reuse_does_not_rewrite_old_vpn_profile(self):
        (self.root/'native.json').write_text('{}')
        save_config(self.config,dict(url='https://vpn.example:10443',id='fixture-user',password='fixture-password'))
        before=self.config.read_bytes(),self.trust.read_bytes()
        with patch('dashboard.numeric_vpn_config.powershell',return_value='fixture-pwsh'):
            configure_vpn(self.root,reuse_config=self.config,trust_file=self.trust)
        self.assertEqual(before,(self.config.read_bytes(),self.trust.read_bytes()))


if __name__=='__main__':
    unittest.main()
