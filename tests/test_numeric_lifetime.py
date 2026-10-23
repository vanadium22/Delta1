from contextlib import contextmanager,ExitStack
from datetime import datetime,timedelta,timezone
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.process_lifetime import LauncherLifetime
from dashboard import numeric_recovery as recovery


@unittest.skipUnless(os.name=='nt','Windows process handles')
class NumericLifetimeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def child(self,script='import sys;sys.stdin.readline()',*args):
        child=subprocess.Popen([sys.executable,'-B','-X','utf8','-c',script,*map(str,args)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        def close():
            if child.poll() is None:
                try:child.communicate('\n',timeout=3)
                except subprocess.TimeoutExpired:
                    child.terminate();child.communicate(timeout=3)  # Only our fixture.
            else:child.communicate()
        self.addCleanup(close)
        return child

    def test_original_handle_detects_launcher_exit_and_retains_live_owner(self):
        child=self.child();callback=Mock()
        with LauncherLifetime(child.pid) as owner:
            owner.attach(callback)
            self.assertFalse(owner.stopped.wait(.25))
            self.assertGreater(owner.started_filetime,0)
            child.communicate('\n',timeout=3)
            self.assertTrue(owner.stopped.wait(2));self.assertEqual(owner.reason,'launcher_exited')
            owner.thread.join(timeout=2);callback.assert_called_once()
        self.assertIsNone(owner.handle)

    def test_reused_pid_identity_is_rejected_without_stopping_that_process(self):
        child=self.child()
        with LauncherLifetime(child.pid,1) as owner:
            self.assertTrue(owner.stopped.is_set());self.assertEqual(owner.reason,'launcher_identity_changed')
            callback=Mock();owner.attach(callback);callback.assert_called_once()
        self.assertIsNone(child.poll())

    def test_stop_marker_stops_service_signal_without_ending_the_launcher(self):
        child=self.child();marker=self.root/'stop';callback=Mock()
        with LauncherLifetime(child.pid,stop_file=marker) as owner:
            owner.attach(callback);marker.write_text('stop')
            self.assertTrue(owner.stopped.wait(2));owner.thread.join(timeout=2)
            self.assertEqual(owner.reason,'stop_requested');callback.assert_called_once()
        self.assertIsNone(child.poll())

    def test_dead_launcher_exits_numeric_main_before_loading_model_or_config(self):
        from dashboard.numeric_excel import main
        child=self.child();child.communicate('\n',timeout=3)
        with ExitStack() as stack:
            stack.enter_context(patch('dashboard.native.model.NativeModel',side_effect=AssertionError('model after owner death')))
            if importlib.util.find_spec('dashboard.numeric_config') is not None:
                stack.enter_context(patch('dashboard.numeric_config.prepare_config',side_effect=AssertionError('config after owner death')))
            main(['--feed',str(self.root/'feed.json'),'--launcher-pid',str(child.pid)])
        self.assertFalse((self.root/'feed.json').exists())

    def test_collector_releases_real_network_lock_when_launcher_dies_during_calculation(self):
        from dashboard.native.collection import CollectionJob
        from dashboard.marketdata.bars import _writer_lock
        from dashboard.marketdata.history_publication import maintenance_root
        child=self.child();roots=[str(self.root/'history')]
        (self.root/'native.json').write_text(json.dumps(dict(history_roots=roots)))
        client=Mock();client.fetch.return_value={'status':'success'};fetch=client.fetch
        fetched=threading.Event();store=SimpleNamespace(batch=Mock())
        @contextmanager
        def fake_store(root):yield store
        def polling(client,store,symbols,*,stop,**kwargs):
            if not stop.is_set():client.fetch(['IF2611.CFE']);fetched.set()
            while not stop.wait(.02):pass
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True)),\
             patch('dashboard.native.collection.ScopedResolver') as resolver,\
             patch('dashboard.native.collection.DualIdentityStore',fake_store),\
             patch('dashboard.native.collection.collect',side_effect=polling):
            resolver.return_value.resolve_many.return_value=({}, {})
            with LauncherLifetime(child.pid) as owner:
                job=CollectionJob(self.root,lifetime_stop=owner.stopped);owner.attach(job.stop)
                job.start('fixture',['IF2611.CFE'],set(),client_factory=lambda **kw:client)
                self.assertTrue(fetched.wait(3))
                child.communicate('\n',timeout=3)
                job.worker.join(timeout=3)
                self.assertFalse(job.running());self.assertTrue(owner.stopped.is_set())
        fetch.assert_called_once();client.close.assert_called_once()
        with _writer_lock(maintenance_root(roots)/'network_session'):pass

    def test_dead_owner_cannot_restart_collector_or_create_subscription_file(self):
        from dashboard.native.collection import CollectionJob
        stopped=threading.Event();stopped.set();client=Mock()
        job=CollectionJob(self.root,lifetime_stop=stopped)
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True)):
            job.start('fixture',['IF2611.CFE'],set(),client_factory=client)
        client.assert_not_called();self.assertFalse(job.running())
        self.assertFalse((self.root/'native_collection_symbols.json').exists())

    def test_real_numeric_service_exits_during_calculation_without_stop_marker(self):
        owner=self.child();feed=self.root/'feed.json';marker=self.root/'stop'
        script='''import pathlib,sys,time,importlib.util
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from dashboard import numeric_excel as service
root=pathlib.Path(sys.argv[1]);owner_pid=sys.argv[2]
model=SimpleNamespace(config={},local_root=root,path=root/'native.json',close=lambda:None)
def capture(model,*,stopped,**kwargs):
    while not stopped():time.sleep(.02)
    raise InterruptedError('fixture cancelled')
with ExitStack() as stack:
    stack.enter_context(patch('dashboard.native.model.NativeModel',return_value=model))
    stack.enter_context(patch.object(service,'capture',side_effect=capture))
    if importlib.util.find_spec('dashboard.numeric_config') is not None:
        stack.enter_context(patch('dashboard.numeric_config.prepare_config',return_value=root))
        stack.enter_context(patch('dashboard.numeric_config.problems',return_value=[]))
    service.main(['--feed',str(root/'feed.json'),'--stop-file',str(root/'stop'),
                  '--launcher-pid',owner_pid,'--iterations','1'])
'''
        child=self.child(script,self.root,owner.pid)
        import time
        deadline=time.monotonic()+5
        while not feed.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        if not feed.exists() and child.poll() is not None:
            out,err=child.communicate();self.fail(err)
        self.assertTrue(feed.exists())
        owner.communicate('\n',timeout=3)
        out,err=child.communicate(timeout=5)
        self.assertEqual(child.returncode,0,err);self.assertFalse(marker.exists())
        status=json.loads(feed.with_suffix('.status.json').read_text(encoding='utf8'))
        self.assertIn('已停止',status['message'])

    def fixture(self,pid,job_id='a'*32):
        job=self.root/job_id;job.mkdir();feed=job/'workbook.json';marker=job/'stop'
        feed.write_text('{"collector":"running","evidence":{"newest_source_time":"2026-10-23T10:39:43+08:00"}}')
        run=dict(run_id=job_id,producer_pid=pid,launcher_pid=111,excel_pid=222,feed=str(feed),
            output=str(self.root/'original.xlsx'),state='running',
            heartbeat_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat())
        record=job/'run.json';record.write_text(json.dumps(run))
        process=dict(pid=pid,module='dashboard.numeric_excel',feed_path=str(feed),stop_file=str(marker),started_filetime=123)
        snapshot=dict(state='ok',active_pids=[pid],items=[process])
        return job,record,run,process,snapshot

    def test_verified_orphan_stops_cooperatively_and_keeps_old_feed_and_run(self):
        job_id='b'*32;job=self.root/job_id;marker=job/'stop'
        child=self.child('import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile not p.exists():time.sleep(.02)',marker)
        job,record,run,process,snapshot=self.fixture(child.pid,job_id)
        with LauncherLifetime(child.pid) as observed:process['started_filetime']=observed.started_filetime
        before={p:p.read_bytes() for p in job.iterdir()}
        with patch.object(recovery,'process_summary',return_value=snapshot):
            result=recovery.recover(self.root,stop_orphans=True,wait_seconds=3)
        self.assertTrue(result['ok'],result);self.assertTrue(result['runs'][0]['exit_observed'])
        self.assertEqual(marker.read_text(),'stop');child.wait(timeout=2)
        self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))
        self.assertFalse(result['forced_termination']);self.assertFalse(result['vpn_changed'])

    def test_live_owner_or_live_excel_blocks_marker_even_with_stale_heartbeat(self):
        job,record,run,process,snapshot=self.fixture(19036)
        for active in (111,222):
            snapshot['active_pids']=[19036,active]
            with patch.object(recovery,'process_summary',return_value=snapshot):
                result=recovery.recover(self.root,stop_orphans=True,wait_seconds=0)
            self.assertFalse(result['runs'][0]['eligible']);self.assertFalse((job/'stop').exists())

    def test_paths_fresh_heartbeat_and_missing_metadata_never_request_stop(self):
        job,record,run,process,snapshot=self.fixture(19036)
        for change in ('different_feed','different_stop','missing_owner','fresh_heartbeat'):
            candidate=json.loads(record.read_text());metadata=dict(process)
            if change=='different_feed':metadata['feed_path']=str(self.root/'other/feed.json')
            if change=='different_stop':metadata['stop_file']=str(self.root/'other/stop')
            if change=='missing_owner':candidate['excel_pid']=None
            if change=='fresh_heartbeat':candidate['heartbeat_at']=datetime.now(timezone.utc).isoformat()
            record.write_text(json.dumps(candidate));snap={**snapshot,'items':[metadata]}
            with patch.object(recovery,'process_summary',return_value=snap):
                result=recovery.recover(self.root,stop_orphans=True,wait_seconds=0)
            self.assertFalse(result['runs'][0]['eligible'],change);self.assertFalse((job/'stop').exists())
            record.write_text(json.dumps(run))

    def test_read_only_mode_and_process_query_failure_never_create_marker(self):
        job,record,run,process,snapshot=self.fixture(19036)
        for value in (snapshot,dict(state='unavailable',exit_code=1)):
            with patch.object(recovery,'process_summary',return_value=value):result=recovery.recover(self.root)
            self.assertFalse((job/'stop').exists());self.assertFalse(result['stop_requested'])


if __name__=='__main__':unittest.main()
