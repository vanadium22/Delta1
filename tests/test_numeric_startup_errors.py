"""Startup diagnostics must preserve evidence and keep the clock independent."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import ctypes
from ctypes import wintypes
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dashboard import numeric_startup as startup


@contextmanager
def exclusive_file(path, share=0):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                                ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(path),0x80000000,share,None,3,0x80,None)
    if handle==ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:yield
    finally:kernel.CloseHandle(handle)


class StartupErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'native.json'
        self.config.write_text('{"history_roots":[]}',encoding='utf8')
        self.report=self.root/'summary.json'
        self.gate=dict(allowed=True,reason='fixture session',checked_at='2026-10-22T14:32:57+08:00')

    def run_main(self,action='summary'):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err), \
             patch('dashboard.session_clock.session_policy',return_value=self.gate), \
             patch('requests.Session',side_effect=AssertionError('startup summary must be offline')):
            code=startup.main([action,'--local-root',str(self.root),'--report',str(self.report)])
        return code,out.getvalue(),err.getvalue()

    def test_denied_history_keeps_fresh_clock_and_file_without_exception_secrets(self):
        path=self.root/'history/current.json'
        error=PermissionError(errno.EACCES,'fixture-secret-password',str(path))
        with patch.object(startup,'summary',side_effect=error):
            code,_,stderr=self.run_main()
        value=json.loads(self.report.read_text(encoding='utf8'))
        self.assertEqual(code,1)
        self.assertEqual(value['gate'],self.gate)
        self.assertEqual(value['local_root'],str(self.root.resolve()))
        self.assertEqual(value['error']['action'],'summary')
        self.assertEqual(value['error']['stage'],'summary')
        self.assertEqual(value['error']['filename'],str(path))
        self.assertEqual(value['error']['errno'],errno.EACCES)
        self.assertTrue(value['error']['frames'])
        self.assertIn('读取历史摘要',value['message'])
        self.assertIn('DELTA1_STARTUP_ERROR',stderr)
        self.assertNotIn('fixture-secret-password',stderr+self.report.read_text(encoding='utf8'))

    def test_prepare_failure_and_probe_failure_report_the_correct_stage(self):
        for action,stage in [('summary','prepare'),('probe','probe')]:
            with self.subTest(stage=stage):
                method='dashboard.numeric_startup.prepare_config' if stage=='prepare' else 'dashboard.session_guard.probe_realtime'
                with patch(method,side_effect=PermissionError(errno.EACCES,'fixture secret',str(self.config))):
                    code,_,_=self.run_main(action)
                value=json.loads(self.report.read_text(encoding='utf8'))
                self.assertEqual(code,1)
                self.assertEqual(value['error']['stage'],stage)
                self.assertEqual(value['error']['action'],action)
                self.assertEqual(value['gate'],self.gate)

    def test_report_failure_preserves_old_file_and_leaves_safe_stderr_evidence(self):
        self.report.write_text('{"state":"previous-complete"}',encoding='utf8')
        before=self.report.read_bytes()
        error=PermissionError(errno.EACCES,'fixture-secret-password',str(self.report))
        real_save=startup.save_diagnostic
        def write_diagnostic(payload,path):
            if Path(path)==self.report:
                raise error
            return real_save(payload,path)
        with patch.object(startup,'summary',return_value=dict(gate=self.gate)), \
             patch.object(startup,'save_snapshot',side_effect=error), \
             patch.object(startup,'save_diagnostic',side_effect=write_diagnostic):
            code,_,stderr=self.run_main()
        self.assertEqual(code,1)
        self.assertEqual(self.report.read_bytes(),before)
        records=[json.loads(s.split(' ',1)[1]) for s in stderr.splitlines() if s.startswith('DELTA1_STARTUP_ERROR ')]
        self.assertEqual(len(records),2)
        self.assertTrue(all(r['stage']=='report' and r['filename']==str(self.report) for r in records))
        self.assertNotIn('fixture-secret-password',stderr)

    def test_summary_records_actual_runtime_before_loading_numerical_dependencies(self):
        code,_,stderr=self.run_main()
        self.assertEqual(code,0)
        value=json.loads(self.report.read_text(encoding='utf8'))
        runtime=json.loads(Path(str(self.report)+'.runtime.json').read_text(encoding='utf8'))
        self.assertEqual(runtime,value['runtime'])
        self.assertEqual(runtime['python'],sys.executable)
        self.assertEqual(runtime['prefix'],sys.prefix)
        self.assertEqual(runtime['base_prefix'],sys.base_prefix)
        self.assertEqual(runtime['pid'],os.getpid())
        self.assertTrue(stderr.startswith('DELTA1_STARTUP_RUNTIME '))

    def run_without_site_packages(self):
        # A real child with no site-packages reproduces import failure before summary.
        untouched=self.root/'not-created'
        process=subprocess.run([sys.executable,'-S','-B','-X','utf8','-m','dashboard.numeric_startup',
            'summary','--local-root',str(untouched),'--report',str(self.report)],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf8',timeout=20)
        self.assertFalse(untouched.exists())
        return process

    def test_real_child_missing_pandas_preserves_runtime_and_writes_failure_without_pandas(self):
        process=self.run_without_site_packages()
        self.assertEqual(process.returncode,1,process.stderr)
        value=json.loads(self.report.read_text(encoding='utf8'))
        self.assertEqual(value['error']['stage'],'imports')
        self.assertEqual(value['error']['module'],'pandas')
        self.assertEqual(value['runtime']['python'],sys.executable)
        self.assertNotEqual(value['runtime']['pid'],os.getpid())
        self.assertIn(sys.executable,value['message'])
        self.assertNotIn('可使用现有数据',value['message'])
        self.assertTrue(process.stderr.startswith('DELTA1_STARTUP_RUNTIME '))
        self.assertIn('DELTA1_STARTUP_ERROR ',process.stderr)
        self.assertNotIn('Traceback (most recent call last)',process.stderr)
        self.assertEqual(json.loads(Path(str(self.report)+'.runtime.json').read_text(encoding='utf8')),value['runtime'])

    @unittest.skipUnless(os.name=='nt','native Windows sharing violations')
    def test_real_import_failure_also_leaves_stderr_when_failure_report_is_locked(self):
        before=b'{"state":"complete","ok":true}'
        self.report.write_bytes(before)
        with exclusive_file(self.report,share=1):
            process=self.run_without_site_packages()
        self.assertEqual(process.returncode,1)
        self.assertEqual(self.report.read_bytes(),before)
        records=[json.loads(s.split(' ',1)[1]) for s in process.stderr.splitlines() if s.startswith('DELTA1_STARTUP_ERROR ')]
        self.assertEqual([r['stage'] for r in records],['imports','report'])
        self.assertEqual(records[0]['module'],'pandas')
        self.assertEqual(records[1]['type'],'PermissionError')
        self.assertEqual(records[1]['filename2'],str(self.report))

    @unittest.skipUnless(os.name=='nt','native Windows sharing violations')
    def test_actual_locked_report_can_fail_while_the_summary_itself_succeeds(self):
        self.report.write_text('{"state":"previous-complete"}',encoding='utf8')
        before=self.report.read_bytes()
        # Allow reads while denying replacement, as a reader without DELETE sharing.
        with exclusive_file(self.report,share=1):
            code,_,stderr=self.run_main()
        self.assertEqual(code,1)
        self.assertEqual(self.report.read_bytes(),before)
        records=[json.loads(s.split(' ',1)[1]) for s in stderr.splitlines() if s.startswith('DELTA1_STARTUP_ERROR ')]
        self.assertEqual(len(records),2)
        self.assertTrue(all(r['stage']=='report' and r['type']=='PermissionError' for r in records))
        self.assertTrue(all(r.get('filename2')==str(self.report) for r in records))
        code,_,_=self.run_main()
        self.assertEqual(code,0)

    @unittest.skipUnless(os.name=='nt','native Windows sharing violations')
    def test_actual_locked_index_fails_then_direct_summary_succeeds_after_release(self):
        from dashboard.marketdata.bars import BarDataset
        import hashlib
        history=self.root/'history'
        store=BarDataset.create(history,dict(dataset_id='fixture',source_id='fixture',series_kind='concrete',
            price_adjustment='none',volume_unit='contracts',availability_policy='unverified',
            instruments={'IF2611.CFE':dict(asset_type='cn_index_future',market_region='CN')}))
        # A valid empty immutable manifest is enough to exercise the real reader.
        pointer=history/'current.json';manifest=history/'versions'/'fixture.json'
        manifest.parent.mkdir(exist_ok=True)
        raw=json.dumps(dict(dataset_id='fixture',version='fixture',parts=[],checkpoint={})).encode()
        manifest.write_bytes(raw)
        pointer.write_text(json.dumps(dict(manifest='versions/fixture.json',sha256=hashlib.sha256(raw).hexdigest())),encoding='utf8')
        self.config.write_text(json.dumps(dict(history_roots=[str(history)])),encoding='utf8')
        before={p:p.read_bytes() for p in (pointer,manifest,self.config)}
        with exclusive_file(pointer):
            code,_,_=self.run_main()
        value=json.loads(self.report.read_text(encoding='utf8'))
        self.assertEqual(code,1)
        self.assertEqual(value['error']['type'],'PermissionError')
        self.assertEqual(value['error']['filename'],str(pointer))
        self.assertEqual(value['error']['errno'],errno.EACCES)
        self.assertIn(value['error'].get('winerror'),(None,32))
        self.assertEqual(value['gate'],self.gate)
        code,_,_=self.run_main()
        self.assertEqual(code,0)
        self.assertNotIn('state',json.loads(self.report.read_text(encoding='utf8')))
        for path,raw in before.items():self.assertEqual(path.read_bytes(),raw)


if __name__=='__main__':
    unittest.main()
