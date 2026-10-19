import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication,QDialog
from dashboard.native.launch_wizard import LaunchWizard
from dashboard.native.history_maintenance import HistoryMaintenance
from dashboard.session_guard import network_lease,probe_realtime


class LaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.model=SimpleNamespace(local_root=self.root,config={'history_roots':[]})

    def tearDown(self):self.temp.cleanup()

    def test_no_work_before_explicit_choice_and_offline_never_probes(self):
        c=HistoryMaintenance(self.model)
        probe=Mock()
        w=LaunchWizard(self.model,maintenance=c,probe=probe)
        with patch.object(c,'retry',wraps=c.retry) as retry:
            w.tick();self.assertIsNone(c.process);retry.assert_not_called()
        w.company_prompt();w.offline()
        self.assertFalse(w.realtime);probe.assert_not_called();w.deleteLater()

    def test_pause_or_complete_status_does_not_prove_exit(self):
        c=HistoryMaintenance(self.model);w=LaunchWizard(self.model,maintenance=c)
        process=Mock();process.poll.return_value=None;c.process=process;c.root=self.root;c.started=10**20
        c.stop_file=self.root/'stop';w.phase='history'
        w.drain('company');w.tick()
        self.assertEqual(w.phase,'draining_company');self.assertTrue(c.stop_file.exists())
        process.poll.return_value=2;process.returncode=2;w.tick()
        self.assertEqual(w.phase,'company');self.assertIsNone(c.process)
        w.reject();w.deleteLater()

    def test_cancel_waits_until_child_reaped(self):
        c=HistoryMaintenance(self.model);w=LaunchWizard(self.model,maintenance=c)
        process=Mock();process.poll.return_value=None;c.process=process;c.root=self.root;c.started=10**20
        w.reject();self.assertEqual(w.phase,'draining_cancel')
        process.poll.return_value=2;process.returncode=2;w.tick()
        self.assertIsNone(c.process);self.assertFalse(w.timer.isActive());w.deleteLater()

    def test_probe_failure_keeps_realtime_disabled_and_can_retry(self):
        w=LaunchWizard(self.model);w.probed(dict(ok=False,message='失败'))
        self.assertFalse(w.realtime);self.assertEqual(w.phase,'company')
        w.probed(dict(ok=True));self.assertTrue(w.realtime);w.deleteLater()

    def test_cancel_during_probe_never_enables_realtime(self):
        w=LaunchWizard(self.model);w.task=object();w.reject()
        self.assertEqual(w.phase,'cancel_probe')
        w.probed(dict(ok=True));self.assertFalse(w.realtime);w.deleteLater()

    def test_networks_exclude_each_other_and_release_on_error(self):
        config={'history_roots':[str(self.root/'a'),str(self.root/'b')]}
        with network_lease(config):
            with self.assertRaises(OSError):
                with network_lease(config):pass
        with network_lease(config):pass

    def test_realtime_probe_closes_client_and_rejects_partial(self):
        factory=Mock();client=factory.return_value;client.fetch.return_value={'status':'partial'}
        with patch('dashboard.marketdata.contract_reference.active_contracts',return_value=[f'IF{i}.CFE' for i in range(16)]):
            r=probe_realtime({},factory)
        self.assertFalse(r['ok']);client.close.assert_called_once()

    def test_runtime_retry_requires_network_authorization(self):
        c=HistoryMaintenance(self.model);c.authorized=False;c.retry()
        self.assertIsNone(c.process);self.assertFalse(c.control.exists())

    def test_http_success_requires_valid_prices_and_identities(self):
        symbols=[f'IF{i}.CFE' for i in range(16)]+['000300.SH','000016.SH','000905.SH','000852.SH']
        client=Mock();factory=Mock(return_value=client)
        data={s:dict(securityId=s,latestPrice=4000.) for s in symbols}
        client.fetch.return_value=dict(status='success',response={'data':data})
        with patch('dashboard.marketdata.contract_reference.active_contracts',return_value=symbols[:16]):
            self.assertTrue(probe_realtime({},factory)['ok'])
            data[symbols[0]]['latestPrice']=0
            self.assertFalse(probe_realtime({},factory)['ok'])
        self.assertEqual(client.close.call_count,2)

    def test_complete_child_is_reaped_before_switch_prompt(self):
        import json
        c=HistoryMaintenance(self.model);w=LaunchWizard(self.model,maintenance=c)
        c.root=self.root;(self.root/'status.json').write_text(json.dumps({'state':'complete','missing_bars':0}))
        process=Mock();process.poll.return_value=0;process.returncode=0;c.process=process
        w.phase='history';w.tick()
        self.assertEqual(w.phase,'company');self.assertIsNone(c.process);self.assertTrue(c.closing)
        w.reject();w.deleteLater()


if __name__=='__main__':unittest.main()
