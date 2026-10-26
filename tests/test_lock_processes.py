import ctypes
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

from dashboard import lock_processes as locks


class LockProcessTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    @unittest.skipUnless(os.name=='nt','Windows Restart Manager')
    def test_native_query_finds_real_file_user_without_changing_lock(self):
        from dashboard.marketdata.bars import _writer_lock
        with _writer_lock(self.root):
            path=self.root/'writer.lock';before=path.stat();data=path.open('r+b')
            # Opening write access succeeds while reading the locked byte fails,
            # matching the company report. Do not read or mutate that byte.
            data.close()
            result=locks.file_users([path,path])
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['state'],'ok',result)
            self.assertIn(os.getpid(),[p['pid'] for p in result[0]['file_users']])
            self.assertTrue(all(p['started_filetime']>0 for p in result[0]['file_users']))
            after=path.stat()
            self.assertEqual((before.st_size,before.st_mtime_ns),(after.st_size,after.st_mtime_ns))
            self.assertNotIn('cleanup_error',result[0])
            with self.assertRaises(PermissionError):path.read_bytes()
        self.assertEqual(path.read_bytes(),b'0')
        released=locks.file_users([path])
        self.assertEqual(released[0]['state'],'ok',released)
        self.assertEqual(released[0]['file_users'],[])

    @unittest.skipUnless(os.name=='nt','Windows Restart Manager')
    def test_missing_file_is_not_created_or_claimed_unlocked(self):
        path=self.root/'missing/writer.lock'
        result=locks.file_users([path])
        self.assertEqual(result[0]['state'],'missing')
        self.assertFalse(path.parent.exists())

    @unittest.skipUnless(os.name=='nt','Windows Restart Manager')
    def test_native_users_are_separate_for_unicode_paths_with_shell_characters(self):
        from dashboard.marketdata.bars import _writer_lock
        root=self.root/"中文 space' $test";root.mkdir()
        free=root/'free.lock';free.write_bytes(b'0')
        with _writer_lock(root):
            result=locks.file_users([root/'writer.lock',free])
        self.assertTrue(all(row['state']=='ok' for row in result),result)
        self.assertIn(os.getpid(),[p['pid'] for p in result[0]['file_users']])
        self.assertEqual(result[1]['file_users'],[])

    @unittest.skipUnless(os.name=='nt','Windows Restart Manager')
    def test_resource_access_failure_ends_only_our_session(self):
        path=self.root/'writer.lock';path.write_bytes(b'0')
        api=Mock()
        def start(handle,flags,key):
            handle._obj.value=42;return 0
        api.RmStartSession.side_effect=start
        api.RmRegisterResources.return_value=5
        api.RmEndSession.return_value=0
        with patch.object(ctypes,'WinDLL',return_value=api):result=locks._windows_file_users(path)
        self.assertEqual(result['state'],'unavailable')
        self.assertEqual(result['error']['winerror'],5)
        self.assertEqual(result['error']['stage'],'lock_users_register')
        api.RmEndSession.assert_called_once()
        self.assertEqual(api.RmEndSession.call_args.args[0].value,42)
        api.RmGetList.assert_not_called();api.RmShutdown.assert_not_called();api.RmRestart.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows Restart Manager')
    def test_changing_native_list_is_bounded_and_never_claimed_empty(self):
        path=self.root/'writer.lock';path.write_bytes(b'0');api=Mock()
        api.RmStartSession.return_value=0;api.RmRegisterResources.return_value=0;api.RmEndSession.return_value=0
        api.RmGetList.return_value=234
        with patch.object(ctypes,'WinDLL',return_value=api):result=locks._windows_file_users(path)
        self.assertEqual(result['state'],'unavailable');self.assertEqual(result['error']['winerror'],234)
        self.assertEqual(api.RmGetList.call_count,4);api.RmEndSession.assert_called_once()

    def test_timeout_error_is_safe_and_hidden_child_is_bounded(self):
        error=subprocess.TimeoutExpired('SECRET',20,output=b'SECRET',stderr=b'SECRET')
        with patch.object(locks.os,'name','nt'),patch.object(locks.subprocess,'run',side_effect=error) as run:
            result=locks.file_users([self.root/'writer.lock'])
        self.assertEqual(result[0]['state'],'unavailable')
        self.assertEqual(result[0]['error']['type'],'TimeoutExpired')
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(run.call_args.kwargs['timeout'],20)
        if os.name=='nt':self.assertEqual(run.call_args.kwargs['creationflags'],subprocess.CREATE_NO_WINDOW)

    @unittest.skipUnless(os.name=='nt','Windows PowerShell')
    def test_quoted_and_plain_module_detection_without_raw_command_lines(self):
        # Run the exact production PowerShell formatter with fixture objects;
        # this avoids needing permission to query real company processes.
        fixtures=[
            ('python.exe','python.exe "-B" "-m" "dashboard.numeric_excel" "--feed" "C:\\space path\\workbook.json" "--stop-file" "C:\\space path\\stop" "--token" "SECRET"','dashboard.numeric_excel'),
            ('python.exe','python.exe -m dashboard.marketdata.history_maintenance --password SECRET','dashboard.marketdata.history_maintenance'),
            ('pythonw.exe','"D:\\Python Path\\pythonw.exe" -m "dashboard.current" SECRET','dashboard.current'),
            ('python.exe','python.exe private.py SECRET',None),
            ('EXCEL.EXE','EXCEL.EXE "private_SECRET.xlsx"',None),
            ('python.exe','python.exe -m dashboard.numeric_excel --feed "https://SECRET" --stop-file relative_SECRET','dashboard.numeric_excel'),
            ('python.exe','python.exe "-m" "dashboard.native.editions_current" "--local-root" "C:\\profile space\\app" --token SECRET','dashboard.native.editions_current'),
            ('python.exe','python.exe -m dashboard.current --local-root https://SECRET','dashboard.current'),
        ]
        captured=[]
        def run_fixture(command,**kwargs):
            script=command[-1]
            fixture_json=json.dumps([dict(Name=name,ProcessId=n+1,ParentProcessId=0,CommandLine=cmd,
                ExecutablePath='C:\\python.exe') for n,(name,cmd,expected) in enumerate(fixtures)])
            safe=fixture_json.replace("'","''")
            script=script.replace('Get-CimInstance Win32_Process',"(ConvertFrom-Json '"+safe+"')")
            result=original(command[:-1]+[script],**kwargs)
            captured.append(result.stdout)
            return result
        original=subprocess.run
        with patch.object(locks.subprocess,'run',side_effect=run_fixture):result=locks.process_summary([1])
        self.assertEqual(result['state'],'ok',result)
        self.assertEqual([row['module'] for row in result['items']],[f[2] for f in fixtures])
        self.assertEqual(result['items'][6]['local_root'],'C:\\profile space\\app')
        self.assertIsNone(result['items'][7]['local_root'])
        self.assertEqual(result['items'][0]['feed_path'],'C:\\space path\\workbook.json')
        self.assertEqual(result['items'][0]['stop_file'],'C:\\space path\\stop')
        self.assertEqual(result['active_pids'],list(range(1,len(fixtures)+1)))
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn(b'SECRET',b''.join(captured))
        self.assertTrue(all('CommandLine' not in row for row in result['items']))

    def test_company_cli_owner_check_keeps_network_and_config_untouched(self):
        from dashboard import connection_check as command
        module=self.root/'dashboard';profile=module/'localsetting/numeric_excel';profile.mkdir(parents=True)
        config=profile/'native.json';original=b'{"history_roots":[],"password":"SECRET"}';config.write_bytes(original)
        report=self.root/'diagnostic.json'
        with patch.object(command,'__file__',str(module/'connection_check.py')),\
             patch.object(locks,'file_users',return_value=[]) as query,\
             patch.object(locks,'process_summary',return_value={'state':'ok','items':[]}),\
             patch('dashboard.session_guard.probe_realtime',side_effect=AssertionError('unexpected HTTP')),\
             patch.object(command,'network_checks',side_effect=AssertionError('unexpected DNS/TCP')),redirect_stdout(io.StringIO()):
            self.assertEqual(command.main(['--all-profiles','--lock-owners','--output',str(report)]),0)
        result=json.loads(report.read_text(encoding='utf8'))
        query.assert_called_once_with([])
        self.assertEqual(result['network']['skipped'],'connect_not_requested')
        self.assertEqual(result['processes']['state'],'ok')
        self.assertEqual(config.read_bytes(),original);self.assertNotIn('SECRET',json.dumps(result))
        self.assertFalse(result['vpn_changed']);self.assertFalse(result['continuous_collection_started'])

    def test_two_profiles_share_one_query_and_keep_their_own_file_users(self):
        from dashboard import connection_check as command
        from dashboard.marketdata.history_publication import maintenance_root
        profiles=[];paths=[]
        for name in ('excel','app'):
            profile=self.root/name;profile.mkdir();roots=[str(profile/'history')]
            (profile/'native.json').write_text(json.dumps(dict(history_roots=roots)),encoding='utf8')
            lock=maintenance_root(roots)/'network_session/writer.lock';lock.parent.mkdir(parents=True);lock.write_bytes(b'0')
            profiles.append(profile);paths.append(str(lock.resolve()))
        users=[dict(path=p,state='ok',file_users=[dict(pid=n+100,started_filetime=1)]) for n,p in enumerate(paths)]
        with patch.object(locks,'file_users',return_value=users),\
             patch.object(locks,'process_summary',return_value={'state':'unavailable'}) as processes:
            result=command.collect(profiles,lock_owners=True)
        for n,profile in enumerate(result['profiles']):
            self.assertEqual(profile['network_lock']['file_users_query']['file_users'][0]['pid'],n+100)
        processes.assert_called_once_with([100,101])


if __name__=='__main__':unittest.main()
