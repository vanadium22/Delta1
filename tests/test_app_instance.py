import json
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dashboard.app_instance import InstanceLease, data_scope, same_data, legacy_candidates
from dashboard.marketdata.bars import _writer_lock
from dashboard.session_guard import network_lease


def peer(root, cooperate=True, delay=.35):
    root=Path(root);config=dict(history_roots=[str(root/'history')],realtime_root=str(root/'quotes'))
    owner=InstanceLease(root/'runtime',config,root/'profile',timeout=2,discover_legacy=False)
    assert owner.acquire()['owned'],owner.summary()
    try:
        with network_lease(config):
            (root/'ready').write_text(json.dumps(owner.summary()))
            end=time.monotonic()+5
            while time.monotonic()<end:
                if cooperate and owner.stop_requested():break
                time.sleep(.02)
            time.sleep(delay)
            (root/'write_finished').write_text('complete')
    finally:owner.close()


def native_window_peer(root):
    root=Path(root);api=ctypes.WinDLL('user32',use_last_error=True)
    api.CreateWindowExW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
        ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,ctypes.c_void_p]
    api.CreateWindowExW.restype=wintypes.HWND
    for name in ('IsWindow','IsWindowVisible','DestroyWindow'):
        getattr(api,name).argtypes=[wintypes.HWND]
    api.PeekMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT,wintypes.UINT]
    api.DispatchMessageW.argtypes=[ctypes.POINTER(wintypes.MSG)]
    api.DispatchMessageW.restype=wintypes.LPARAM
    # WS_VISIBLE is deliberately absent. Neither test window can appear.
    target=api.CreateWindowExW(0,'STATIC','Delta1 compatibility fixture',0,0,0,10,10,None,None,None,None)
    other=api.CreateWindowExW(0,'STATIC','Unrelated hidden fixture',0,0,0,10,10,None,None,None,None)
    if not target or not other:raise ctypes.WinError(ctypes.get_last_error())
    try:
        (root/'window-ready').write_text(json.dumps(dict(pid=os.getpid(),hidden=not api.IsWindowVisible(target))))
        end=time.monotonic()+6;msg=wintypes.MSG()
        while api.IsWindow(target) and time.monotonic()<end:
            while api.PeekMessageW(ctypes.byref(msg),None,0,0,1):api.DispatchMessageW(ctypes.byref(msg))
            time.sleep(.01)
        (root/'window-result').write_text(json.dumps(dict(target_closed=not api.IsWindow(target),other_preserved=bool(api.IsWindow(other)))))
    finally:
        if api.IsWindow(target):api.DestroyWindow(target)
        api.DestroyWindow(other)


def qt_peer(root, label):
    os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['DELTA1_THEME']='public'
    from datetime import datetime,timezone
    from dashboard.native.editions_current import PresentationWindow
    from dashboard.current import main
    root=Path(root)
    class Window(PresentationWindow):
        def __init__(self,model):
            super().__init__(model)
            self.loaded.connect(lambda _:(root/('qt-ready-'+label)).write_text('ready'))
    state=dict(as_of=datetime.now(timezone.utc).isoformat(),versions={},overview=[],entities=[],selection=dict(overview_slot=0),
        market_overview=dict(indices=[],etfs=[],futures=[],previous_session=None,errors=[]))
    with patch('dashboard.native.data_pipeline.DataPipeline.inspect',lambda _:None),\
         patch('dashboard.native.data_pipeline.DataPipeline.tick',lambda self:self.write_report()),\
         patch('dashboard.native.market_overview.capture',return_value=state),\
         patch('requests.sessions.Session.request',side_effect=AssertionError('No real network')):
        code=main(['--local-root',str(root/'profile')],window_class=Window,public=True)
    (root/('qt-exit-'+label)).write_text(str(code))


class AppInstanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=dict(history_roots=[str(self.root/'history')],realtime_root=str(self.root/'quotes'))

    def lease(self, **kw):return InstanceLease(self.root/'runtime',self.config,self.root/'profile',discover_legacy=False,**kw)

    def launch_peer(self, cooperate=True):
        code='from tests.test_app_instance import peer;import sys;peer(sys.argv[1],sys.argv[2]=="yes")'
        process=subprocess.Popen([sys.executable,'-B','-s','-X','utf8','-c',code,str(self.root),'yes' if cooperate else 'no'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.addCleanup(lambda:process.communicate(timeout=10))
        end=time.monotonic()+5
        while not (self.root/'ready').exists() and time.monotonic()<end:
            if process.poll() is not None:break
            time.sleep(.02)
        self.assertTrue((self.root/'ready').is_file(),process.communicate(timeout=8) if process.poll() is not None else 'peer did not register')
        return process

    @unittest.skipUnless(os.name=='nt','Exact Windows creation identity')
    def test_real_replacement_waits_for_writer_then_takes_network_lease(self):
        process=self.launch_peer();new=self.lease(timeout=4);self.addCleanup(new.close)
        started=time.monotonic();result=new.acquire()
        self.assertTrue(result['owned'],result);self.assertGreaterEqual(time.monotonic()-started,.3)
        self.assertTrue((self.root/'write_finished').is_file())
        with network_lease(self.config):pass
        self.assertTrue(any(r['action']=='cooperative_stop_requested' for r in result['previous']))
        self.assertEqual(process.wait(timeout=3),0)

    @unittest.skipUnless(os.name=='nt','Exact Windows creation identity')
    def test_slow_or_unresponsive_owner_is_never_forced_or_bypassed(self):
        self.launch_peer(False);new=self.lease(timeout=.3);self.addCleanup(new.close)
        result=new.acquire();self.assertFalse(result['owned']);self.assertFalse(result['forced_termination'])
        self.assertFalse((self.root/'write_finished').exists())
        with self.assertRaises(OSError):
            with network_lease(self.config):pass

    def test_different_data_scopes_are_not_closed(self):
        other={**self.config,'history_roots':[str(self.root/'other')],'realtime_root':str(self.root/'other-quotes')}
        self.assertFalse(same_data(data_scope(self.config,self.root/'one'),data_scope(other,self.root/'two')))
        first=self.lease(timeout=.1);second=InstanceLease(self.root/'runtime',other,self.root/'two',timeout=.1,discover_legacy=False)
        self.addCleanup(first.close);self.addCleanup(second.close)
        self.assertTrue(first.acquire()['owned']);self.assertTrue(second.acquire()['owned'])

    def test_corrupt_owner_metadata_does_not_write_a_stop_marker(self):
        lease=self.lease(timeout=.1)
        self.assertFalse(lease._request_owner(dict(schema='app-owner-v1',scope=lease.scope['key'],token='../outside',pid=1,started_filetime=1)))
        self.assertFalse(self.root.joinpath('outside.stop').exists())

    def test_reused_pid_never_receives_stop_request(self):
        lease=self.lease();fake=SimpleNamespace(stopped=threading.Event())
        fake.stopped.set()
        context=Mock();context.__enter__=Mock(return_value=fake);context.__exit__=Mock(return_value=False)
        with patch('dashboard.app_instance.LauncherLifetime',return_value=context):
            result=lease._request_owner(dict(schema='app-owner-v1',scope=lease.scope['key'],token='a'*32,pid=123,started_filetime=1))
        self.assertFalse(result);self.assertFalse((lease.root/('a'*32+'.stop')).exists())

    @unittest.skipUnless(os.name=='nt','Windows file creation time')
    def test_legacy_requires_module_executable_scope_and_original_creation(self):
        from datetime import datetime,timezone
        sessions=self.root/'runtime/app_sessions';path=sessions/('a'*32)/'status.json';path.parent.mkdir(parents=True)
        report=dict(pid=123,python=sys.executable,observed_at=datetime.now(timezone.utc).isoformat(),
                    local_root=str(self.root/'profile'),paths=self.config)
        path.write_text(json.dumps(report));born=path.stat().st_birthtime_ns//100+116444736000000000
        process=dict(pid=123,module='dashboard.native.editions_current',executable=sys.executable,started_filetime=born-10000000,
                     local_root=str(self.root/'profile'))
        def rows(p):return legacy_candidates([sessions],data_scope(self.config,self.root/'profile'),dict(state='ok',items=[p]))
        self.assertEqual(len(rows(process)),1)
        for bad in ({**process,'module':'dashboard.numeric_excel'},{**process,'module':None},
                    {**process,'started_filetime':born+1},{**process,'executable':'C:/other/python.exe'},
                    {**process,'local_root':str(self.root/'unrelated')}):self.assertEqual(rows(bad),[])

    def test_released_lease_can_be_opened_again_without_removing_lock_files(self):
        first=self.lease(timeout=.1);self.assertTrue(first.acquire()['owned']);first.close()
        before=(first.root/'active/writer.lock').read_bytes()
        second=self.lease(timeout=.1);self.addCleanup(second.close);self.assertTrue(second.acquire()['owned'])
        self.assertEqual(before,b'0');self.assertTrue((first.root/'active/writer.lock').exists())

    @unittest.skipUnless(os.name=='nt','Windows legacy process identity')
    def test_legacy_close_accepts_cim_rounding_but_rejects_a_different_process(self):
        from datetime import datetime,timezone
        lease=self.lease();sessions=self.root/'runtime/app_sessions';path=sessions/('a'*32)/'status.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(pid=123,python=sys.executable,observed_at=datetime.now(timezone.utc).isoformat(),
            local_root=str(self.root/'profile'),paths=self.config)))
        started=path.stat().st_birthtime_ns//100+116444736000000000-10000000
        snapshot=dict(state='ok',items=[dict(pid=123,module='dashboard.native.editions_current',executable=sys.executable,
            started_filetime=started,local_root=str(self.root/'profile'))])
        for delta,expected in ((9,True),(10001,False)):
            watch=SimpleNamespace(stopped=threading.Event(),started_filetime=started+delta)
            context=Mock();context.__enter__=Mock(return_value=watch);context.__exit__=Mock(return_value=False)
            def close(_):watch.stopped.set();return [1234]
            with patch('dashboard.lock_processes.process_summary',return_value=snapshot),\
                 patch('dashboard.app_instance.LauncherLifetime',return_value=context) as lifetime,\
                 patch('dashboard.app_instance.close_legacy_windows',side_effect=close) as request:
                self.assertTrue(lease._close_legacy(time.monotonic()+1))
            lifetime.assert_called_once_with(123)
            self.assertEqual(request.called,expected)

    @unittest.skipUnless(os.name=='nt','Windows hidden WM_CLOSE')
    def test_legacy_close_posts_normal_message_only_to_target_delta_window(self):
        from dashboard.app_instance import close_legacy_windows
        process=subprocess.Popen([sys.executable,'-B','-s','-c','from tests.test_app_instance import native_window_peer;import sys;native_window_peer(sys.argv[1])',str(self.root)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda:process.communicate(timeout=10))
        end=time.monotonic()+5
        while not (self.root/'window-ready').exists() and time.monotonic()<end:time.sleep(.02)
        self.assertTrue((self.root/'window-ready').exists())
        self.assertTrue(json.loads((self.root/'window-ready').read_text())['hidden'])
        self.assertEqual(len(close_legacy_windows(process.pid)),1)
        self.assertEqual(process.wait(timeout=8),0)
        result=json.loads((self.root/'window-result').read_text())
        self.assertTrue(result['target_closed']);self.assertTrue(result['other_preserved'])

    @unittest.skipUnless(os.name=='nt','Windows production entry and process identity')
    def test_actual_app_entry_replaces_previous_qt_instance_offscreen(self):
        profile=self.root/'profile';profile.mkdir();path=profile/'native.json'
        path.write_text(json.dumps(self.config))
        before=path.read_bytes();processes=[]
        try:
            for label in ('first','second'):
                child=subprocess.Popen([sys.executable,'-B','-s','-X','utf8','-c','from tests.test_app_instance import qt_peer;import sys;qt_peer(sys.argv[1],sys.argv[2])',str(self.root),label],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
                processes.append(child)
                end=time.monotonic()+12
                while not (self.root/('qt-ready-'+label)).exists() and time.monotonic()<end:
                    if child.poll() is not None:break
                    time.sleep(.02)
                self.assertTrue((self.root/('qt-ready-'+label)).exists(),child.communicate(timeout=1) if child.poll() is not None else 'App did not become ready')
            self.assertEqual(processes[0].wait(timeout=5),0)
            self.assertEqual((self.root/'qt-exit-first').read_text(),'0')
            from dashboard.current import __file__ as current_file
            lease=InstanceLease(Path(current_file).parent/'runtime',self.config,profile,timeout=5,discover_legacy=False)
            self.assertTrue(lease.acquire()['owned'],lease.summary());lease.close()
            self.assertEqual(processes[1].wait(timeout=5),0)
            self.assertEqual((self.root/'qt-exit-second').read_text(),'0')
            self.assertEqual(path.read_bytes(),before)
        finally:
            # Only cooperative markers; no process termination, even on failure.
            from dashboard.current import __file__ as current_file
            registry=Path(current_file).parent/'runtime/app_instances'/data_scope(self.config,profile)['key']
            owner=json.loads((registry/'owner.json').read_text()) if (registry/'owner.json').exists() else {}
            if owner.get('token'):(registry/(owner['token']+'.stop')).touch()
            for child in processes:child.communicate(timeout=10)


if __name__=='__main__':unittest.main()
