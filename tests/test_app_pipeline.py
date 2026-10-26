import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication,QMainWindow
from dashboard.native.data_pipeline import DataPipeline
from dashboard.native.history_maintenance import HistoryMaintenance
from dashboard.native.model import NativeModel
from dashboard.native.editions_current import PresentationWindow,DeveloperWindow

APP=QApplication.instance() or QApplication([])

def pump(seconds):
    until=time.monotonic()+seconds
    while time.monotonic()<until:APP.processEvents();time.sleep(.003)


class PipelineTests(unittest.TestCase):
    def test_overview_runtime_reports_readonly_scheduler_without_starting_wind(self):
        from dashboard.native.overview_reference_job import ReferenceJob
        w,p=self.fixture();p.overview_reference=ReferenceJob(w.model.local_root)
        with patch('subprocess.Popen') as spawn:
            p.tick();spawn.assert_not_called()
        state=p.report()['overview_runtime']
        self.assertEqual(state['schema'],'overview-runtime-v2');self.assertFalse(state['pipeline_enabled'])
        self.assertEqual(state['reference_scheduler']['status'],'waiting')
        self.assertIn('只读',state['reference_scheduler']['reason'])

    def fixture(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        w=QMainWindow();w.model=SimpleNamespace(local_root=Path(tmp.name),config={},refresh_trace={})
        w.collection=Mock();w.collection.running.return_value=False;w.collection.state.return_value={}
        w.busy=False;w.pending=False
        p=DataPipeline(w,enabled=False,auto_inspect=False);p.timer.stop()
        p.report_path=Path(tmp.name)/'status.json'
        self.addCleanup(w.deleteLater)
        return w,p

    def test_finite_success_starts_continuous_collection_after_exit(self):
        w,p=self.fixture();p.enabled=True
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True,reason='test')),\
             patch('dashboard.session_guard.probe_realtime',return_value=dict(ok=True)):
            p.start_probe();pump(.12)
        w.collection.start.assert_called_once()
        self.assertFalse(w.collection.start.call_args.kwargs['once']);self.assertEqual(p.phase,'collecting')

    def test_unfinished_instance_handover_blocks_all_network_actions(self):
        w,p=self.fixture();w.instance_lease=SimpleNamespace(owned=False,summary=lambda:dict(owned=False))
        with patch('dashboard.session_guard.probe_realtime') as probe,patch.object(p.history,'start') as history:
            p.request_realtime();p.request_history();p.start_probe();p.tick()
            probe.assert_not_called();history.assert_not_called()
        self.assertEqual(p.phase,'waiting_previous_app');w.collection.start.assert_not_called()

    def test_cancel_during_slow_probe_never_starts_collector(self):
        w,p=self.fixture();p.enabled=True
        def slow(_):time.sleep(.06);return dict(ok=True)
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True,reason='test')),\
             patch('dashboard.session_guard.probe_realtime',side_effect=slow):
            p.start_probe();p.readonly();pump(.16)
        w.collection.start.assert_not_called();self.assertIsNone(p.task)

    def test_history_exit_is_required_before_probe(self):
        w,p=self.fixture();p.history.process=Mock();p.history.process.poll.return_value=None
        p.request_realtime()
        with patch.object(p,'start_probe') as probe:p.tick();probe.assert_not_called()
        p.history.process.poll.return_value=0;p.history.process.returncode=0
        with patch.object(p,'start_probe') as probe:p.tick();probe.assert_called_once()

    def test_history_waits_for_collector_drain(self):
        w,p=self.fixture();w.collection.running.return_value=True;p.request_history()
        with patch.object(p.history,'start') as start:p.tick();start.assert_not_called()
        w.collection.running.return_value=False
        with patch.object(p.history,'start',return_value=True) as start:p.tick();start.assert_called_once()

    def test_realtime_restart_waits_for_current_request_and_keeps_reference_intent(self):
        w,p=self.fixture();w.collection.running.return_value=True
        p.request_realtime(force_reference=True)
        w.collection.stop.assert_called_once()
        with patch.object(p,'start_probe') as probe:p.tick();probe.assert_not_called()
        self.assertEqual(p.action,'realtime');self.assertTrue(p.force_reference)
        w.collection.running.return_value=False
        with patch.object(p,'start_probe') as probe:p.tick();probe.assert_called_once()
        self.assertIsNone(p.action)

    def test_disconnect_retry_is_bounded_and_market_closed_does_not_probe(self):
        w,p=self.fixture();p.enabled=True
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True,reason='test')),\
             patch('dashboard.session_guard.probe_realtime',return_value=dict(ok=False,message='timeout')) as probe:
            p.start_probe();pump(.1)
            for _ in range(20):p.tick()
            self.assertEqual(probe.call_count,1)
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=False,reason='休市')),\
             patch('dashboard.session_guard.probe_realtime') as probe,\
             patch('dashboard.native.latest_snapshot.collect',return_value=dict(status='snapshot_received')) as snapshot:
            p.start_probe();pump(.1);probe.assert_not_called();snapshot.assert_called_once()
            self.assertEqual(p.phase,'market_closed');w.collection.start.assert_not_called()

    def test_slow_history_close_never_terminates_writer(self):
        w,p=self.fixture();p.history.process=Mock();p.history.process.poll.return_value=None
        p.history.started=time.monotonic()-10000;p.history.stop_file=Path(w.model.local_root)/'stop'
        p.stop()
        for _ in range(10):p.history.tick()
        p.history.process.terminate.assert_not_called();p.history.process.kill.assert_not_called()
        self.assertTrue(p.history.stop_file.exists());self.assertFalse(p.drained())

    def test_one_click_waits_for_reference_then_drains_collector_before_ddb(self):
        w,p=self.fixture();p.overview_reference=Mock();job=p.overview_reference
        job.closed=False;job.running.return_value=True;job.state.return_value={}
        w.collection.running.return_value=True;p.one_click()
        with patch.object(p.history,'start',return_value=True) as start:
            p.tick();job.tick.assert_called_once();start.assert_not_called()
            self.assertEqual(p.action,'reference_before_history')
            job.running.return_value=False;p.tick();self.assertEqual(p.action,'history')
            p.tick();start.assert_not_called()
            w.collection.running.return_value=False;p.tick();start.assert_called_once()
        self.assertIsNone(p.action)

    def test_cancelled_reference_owner_is_retained_until_its_query_drains(self):
        w,p=self.fixture();job=p.overview_reference=Mock()
        job.closed=True;job.running.return_value=True;job.state.return_value={}
        p.request_realtime();self.assertIs(p.overview_reference,job)
        p.one_click();p.tick();self.assertIs(p.overview_reference,job)
        self.assertEqual(p.action,'reference_before_history')
        p.stop();job.stop.assert_called_once();self.assertFalse(p.drained())

    def test_side_cache_progress_continues_bounded_history_but_http_retry_never_does(self):
        w,p=self.fixture();p.enabled=True
        p.history.tick=Mock(return_value=0)
        p.history.state=Mock(return_value=dict(state='partial',inserted=0,overview_daily=dict(inserted=100,pending_rows=100),next_retry=time.time()+5))
        with patch.object(p,'submit',return_value=True),patch.object(p,'request_history') as history:
            p.tick();history.assert_called_once_with(force=False)
        p.history.tick=Mock(return_value=None);p.phase='waiting_network';p.next_retry=0
        with patch.object(p,'request_history') as history,patch.object(p,'start_probe') as probe:
            p.tick();probe.assert_called_once();history.assert_not_called()

    def test_newly_completed_close_requests_history_only_when_maintenance_enabled(self):
        for enabled in (True,False):
            w,p=self.fixture();p.enabled=True;p.next_retry=time.monotonic()+60
            p.model.config['history_maintenance_enabled']=enabled;p.completed_target='2026-10-23'
            with patch('dashboard.marketdata.overview_sessions.latest_completed_session',return_value='2026-10-26'),\
                 patch.object(p,'request_history') as history:
                p.tick()
                if enabled:history.assert_called_once_with(force=False)
                else:history.assert_not_called()


class RefreshQueueTests(unittest.TestCase):
    def window(self,cls):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        model=NativeModel(Path(tmp.name));model.config['dashboard_mode']='nonregression'
        w=cls(model)
        (w.timer if hasattr(w,'timer') else w.refresh_timer).stop()
        return w

    def test_slow_calculation_timer_does_not_discard_result_or_grow_queue(self):
        for cls in (PresentationWindow,DeveloperWindow):
            with self.subTest(edition=cls.__name__):
                calls=[];rendered=[];active=0;maximum=0
                def capture(*a,**kw):
                    nonlocal active,maximum
                    active+=1;maximum=max(active,maximum);calls.append(len(calls)+1)
                    time.sleep(.07);active-=1;return {'number':calls[-1]}
                target='dashboard.native.market_overview.capture' if cls is PresentationWindow else 'dashboard.native.research_pages_view.capture'
                with patch(target,side_effect=capture):
                    w=self.window(cls);w.render=lambda s:rendered.append(s['number'])
                    for _ in range(30):w.refresh();pump(.004)
                    issued=len(calls)
                    pump(.2)
                    self.assertTrue(rendered);self.assertEqual(maximum,1)
                    self.assertLessEqual(len(calls),issued+1)
                    self.assertEqual(rendered[-1],calls[-1])
                    self.assertEqual(w.generation,0)
                    w.close();pump(.1)

    def test_rapid_selection_drops_old_result_but_applies_latest(self):
        for cls in (PresentationWindow,DeveloperWindow):
            with self.subTest(edition=cls.__name__):
                delivered=[];calls=[]
                def capture(*a,**kw):
                    number=len(calls);calls.append(number);time.sleep(.06);return number
                target='dashboard.native.market_overview.capture' if cls is PresentationWindow else 'dashboard.native.research_pages_view.capture'
                with patch(target,side_effect=capture):
                    w=self.window(cls);w.render=delivered.append
                    w.refresh();pump(.01)
                    for _ in range(12):w.selection_changed()
                    pump(.2)
                    self.assertNotIn(0,delivered);self.assertTrue(delivered)
                    self.assertLessEqual(len(calls),3);w.close();pump(.1)

    def test_failure_clears_busy_and_latest_retry_runs(self):
        for cls in (PresentationWindow,DeveloperWindow):
            with self.subTest(edition=cls.__name__):
                target='dashboard.native.market_overview.capture' if cls is PresentationWindow else 'dashboard.native.research_pages_view.capture'
                with patch(target,side_effect=[ValueError('synthetic'),{}]):
                    w=self.window(cls);rendered=[];w.render=rendered.append
                    pump(.05);self.assertFalse(w.busy)
                    w.refresh();pump(.1);self.assertTrue(rendered);self.assertFalse(w.busy)
                    w.close();pump(.1)


if __name__=='__main__':unittest.main()
