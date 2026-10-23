from contextlib import contextmanager,redirect_stdout
import errno
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.connection_diagnostics import error_detail
from dashboard.session_guard import probe_realtime

SYMBOLS=[p+m+'.CFE' for p in ('IF','IH','IC','IM') for m in ('2611','2612','2703','2706')]
ALL=SYMBOLS+['000300.SH','000016.SH','000905.SH','000852.SH']


class ConnectionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.config={'history_roots':[str(self.root/'indexes'),str(self.root/'futures')],
                     'reference_file':str(self.root/'reference.json')}
        self.client=Mock()
        self.client.fetch.return_value={'status':'success','missing_symbols':[],
            'response':{'data':{s:{'securityId':s,'latestPrice':4000.} for s in ALL},'password':'SECRET'},
            'response_body':{'base64':'SECRET'},'headers':{'Authorization':'SECRET'}}
        for target,value in [('dashboard.session_clock.session_policy',{'allowed':True,'reason':'test session'}),
                             ('dashboard.marketdata.contract_reference.active_contracts',SYMBOLS),
                             ('dashboard.marketdata.repository.ReferenceBook',SimpleNamespace(data={}))]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)

    def run_probe(self,**kwargs):
        factory=Mock(return_value=self.client)
        result=probe_realtime(self.config,factory,**kwargs)
        return result,factory

    def test_success_contains_only_safe_diagnostics_and_no_payload(self):
        result,factory=self.run_probe(report_dir=self.root/'reports')
        self.assertTrue(result['ok']);self.assertTrue(result['diagnostics']['http_attempted'])
        self.assertEqual(result['diagnostics']['stage'],'complete')
        self.assertNotIn('SECRET',json.dumps(result))
        saved=json.loads(Path(result['diagnostic_file']).read_text(encoding='utf8'))
        self.assertNotIn('SECRET',json.dumps(saved));self.assertTrue(saved['ok'])
        self.client.close.assert_called_once()

    def test_reference_denial_is_distinguished_before_network(self):
        path=self.root/'reference.json'
        with patch('dashboard.marketdata.repository.ReferenceBook',side_effect=PermissionError(errno.EACCES,'SECRET',str(path))):
            result,factory=self.run_probe()
        self.assertFalse(result['ok']);self.assertEqual(result['error']['stage'],'reference_read')
        self.assertEqual(result['error']['filename'],str(path));self.assertFalse(result['diagnostics']['http_attempted'])
        factory.assert_not_called();self.assertNotIn('SECRET',json.dumps(result))

    def test_real_busy_lock_does_not_construct_http_client(self):
        from dashboard.marketdata.bars import _writer_lock
        from dashboard.marketdata.history_publication import maintenance_root
        root=maintenance_root(self.config['history_roots'])/'network_session'
        with _writer_lock(root):result,factory=self.run_probe()
        self.assertFalse(result['ok']);factory.assert_not_called()
        self.assertEqual(result['error']['stage'],'network_lock')
        self.assertEqual(result['error']['path'],str(root/'writer.lock'))
        self.assertFalse(result['diagnostics']['http_attempted'])

    def test_lock_file_denial_keeps_actual_path_and_error_code(self):
        path=self.root/'denied/writer.lock'
        with patch('dashboard.session_guard._writer_lock',side_effect=PermissionError(errno.EACCES,'SECRET',str(path))):
            result,factory=self.run_probe()
        self.assertEqual(result['error']['errno'],13);self.assertEqual(result['error']['filename'],str(path))
        self.assertIn('尚未请求行情',result['message']);factory.assert_not_called()

    def test_socket_permission_error_is_not_mislabelled_as_lock(self):
        error=PermissionError(errno.EACCES,'SECRET');error.winerror=10013
        self.client.fetch.side_effect=error
        result,_=self.run_probe()
        self.assertEqual(result['error']['stage'],'http_request');self.assertEqual(result['error']['winerror'],10013)
        self.assertTrue(result['diagnostics']['lock_acquired']);self.assertTrue(result['diagnostics']['http_attempted'])
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('锁未取得',result['message'])

    def test_response_timeout_and_http_errors_have_usable_stage_and_status(self):
        for status,http in [('timeout',None),('tls_error',None),('http_error',403),('business_error',200)]:
            self.client.fetch.return_value={'status':status,'http_status':http,'error':'SECRET'}
            result,_=self.run_probe()
            self.assertFalse(result['ok']);self.assertIn(status,result['message'])
            self.assertEqual(result['diagnostics']['http_status'],http)
            self.assertNotIn('SECRET',json.dumps(result))

    def test_transport_cause_is_preserved_without_exception_text(self):
        import requests
        from index_strategy.instant_dld.client import MarketDataClient
        session=Mock();session.post.side_effect=requests.exceptions.ReadTimeout('SECRET_ENDPOINT_PASSWORD')
        client=MarketDataClient(session=session)
        result=probe_realtime(self.config,lambda **_:client)
        self.assertFalse(result['ok']);self.assertEqual(result['diagnostics']['status'],'timeout')
        self.assertEqual(result['diagnostics']['transport_error']['type'],'ReadTimeout')
        self.assertNotIn('SECRET',json.dumps(result));session.close.assert_called_once()

    def test_client_init_certificate_file_denial_has_its_actual_file(self):
        path=self.root/'ca.pem'
        result=probe_realtime(self.config,Mock(side_effect=PermissionError(13,'SECRET',str(path))))
        self.assertEqual(result['error']['stage'],'client_init');self.assertEqual(result['error']['filename'],str(path))
        self.assertFalse(result['diagnostics']['http_attempted'])

    def test_unlock_and_close_failures_keep_their_own_stage(self):
        @contextmanager
        def release_failure(_):
            yield
            raise PermissionError(errno.EACCES,'SECRET')
        with patch('dashboard.session_guard.network_lease',release_failure):result,_=self.run_probe()
        self.assertEqual(result['error']['stage'],'network_lock_release')
        self.client.close.side_effect=OSError(errno.EIO,'SECRET')
        result,_=self.run_probe();self.assertEqual(result['error']['stage'],'client_close')

    def test_error_chain_does_not_copy_args_or_locals(self):
        try:
            try:raise PermissionError(errno.EACCES,'SECRET')
            except PermissionError as cause:raise RuntimeError('SECRET_TOKEN') from cause
        except RuntimeError as exc:detail=error_detail(exc,'http_request')
        self.assertEqual(detail['causes'][1]['errno'],13)
        self.assertNotIn('SECRET',json.dumps(detail));self.assertTrue(detail['frames'])

    def test_headless_command_only_reads_configs_and_does_not_replace_old_report(self):
        from dashboard.connection_check import main
        local=self.root/'profile';local.mkdir();config=local/'native.json'
        config.write_text(json.dumps(dict(history_roots=[],password='SECRET')),encoding='utf8')
        before=config.read_bytes();output=self.root/'diagnosis.json'
        with patch('socket.getaddrinfo',side_effect=AssertionError('offline command attempted DNS')),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--local-root',str(local),'--output',str(output)]),0)
        self.assertEqual(config.read_bytes(),before)
        report=output.read_bytes();self.assertNotIn(b'SECRET',report)
        with redirect_stdout(io.StringIO()):self.assertEqual(main(['--local-root',str(local),'--output',str(output)]),1)
        self.assertEqual(output.read_bytes(),report)

    def test_network_diagnosis_distinguishes_dns_and_socket_denial(self):
        from dashboard.connection_check import network_checks
        import socket
        with patch('socket.getaddrinfo',side_effect=socket.gaierror(-2,'SECRET')),patch('socket.create_connection') as tcp:
            result=network_checks()
        self.assertEqual(result['error']['stage'],'dns');tcp.assert_not_called()
        error=PermissionError(13,'SECRET');error.winerror=10013
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('192.0.2.1',11443))]),\
             patch('socket.create_connection',side_effect=error),patch('dashboard.connection_check.windows_routes',return_value={}):
            result=network_checks()
        self.assertEqual(result['tcp'][0]['error']['stage'],'tcp')
        self.assertEqual(result['tcp'][0]['error']['winerror'],10013)
        self.assertNotIn('SECRET',json.dumps(result))

    def test_all_existing_profiles_use_their_actual_config_and_leave_them_unchanged(self):
        from dashboard import connection_check as command
        module=self.root/'dashboard';profiles=[module/'localsetting/numeric_excel',module/'localsetting']
        originals={}
        for root in profiles:
            root.mkdir(parents=True,exist_ok=True);path=root/'native.json'
            path.write_text(json.dumps(dict(history_roots=[],password='SECRET')),encoding='utf8');originals[path]=path.read_bytes()
        output=self.root/'both.json'
        with patch.object(command,'__file__',str(module/'connection_check.py')),\
             patch('dashboard.session_guard.probe_realtime',return_value={'ok':False,'message':'fixture'}),\
             patch.object(command,'network_checks',return_value={'fixture':True}),redirect_stdout(io.StringIO()):
            self.assertEqual(command.main(['--all-profiles','--connect','--output',str(output)]),0)
        result=json.loads(output.read_text(encoding='utf8'))
        self.assertEqual(len(result['profiles']),2)
        self.assertTrue(all(path.read_bytes()==data for path,data in originals.items()))
        self.assertFalse(result['vpn_changed']);self.assertFalse(result['continuous_collection_started'])
        self.assertNotIn('SECRET',json.dumps(result))

    def test_connect_outside_session_keeps_all_transport_offline(self):
        from dashboard.connection_check import collect
        path=self.root/'native.json';path.write_text('{"history_roots":[]}',encoding='utf8')
        with patch('dashboard.session_clock.session_policy',return_value={'allowed':False,'reason':'closed'}),\
             patch('dashboard.connection_check.network_checks',side_effect=AssertionError('network outside session')):
            result=collect([self.root],connect=True)
        self.assertTrue(result['profiles'][0]['probe']['offline'])
        self.assertEqual(result['network']['skipped'],'outside_session')

    def test_dns_tcp_also_skip_when_history_or_live_network_lock_is_busy(self):
        from dashboard.connection_check import collect
        path=self.root/'native.json';path.write_text('{"history_roots":[]}',encoding='utf8')
        with patch('dashboard.session_guard.probe_realtime',return_value={'ok':False,'error':{'stage':'network_lock'}}),\
             patch('dashboard.connection_check.network_checks',side_effect=AssertionError('network while locked')):
            result=collect([self.root],connect=True)
        self.assertEqual(result['network']['skipped'],'network_lock_not_acquired')

    def test_numeric_excel_real_child_preserves_permission_stage_and_report(self):
        from dashboard.marketdata.bars import _writer_lock
        from dashboard.marketdata.history_publication import maintenance_root
        ref=Path(self.config['reference_file'])
        ref.write_text(json.dumps({'schema_version':'cn_index_reference_v1','contracts':[
            dict(instrument_id=s,listing_date='2000-01-01',expiry_date='2099-01-01',known_at='2000-01-01T00:00Z') for s in SYMBOLS]}),encoding='utf8')
        (self.root/'native.json').write_text(json.dumps(self.config),encoding='utf8')
        before=(self.root/'native.json').read_bytes();report=self.root/'excel_probe.json'
        script="""import sys
from unittest.mock import patch
from dashboard.numeric_startup import main
with patch('dashboard.session_clock.session_policy',return_value={'allowed':True,'reason':'fixture'}):
    raise SystemExit(main(['probe','--local-root',sys.argv[1],'--report',sys.argv[2]]))
"""
        with _writer_lock(maintenance_root(self.config['history_roots'])/'network_session'):
            child=subprocess.run([sys.executable,'-B','-X','utf8','-c',script,str(self.root),str(report)],
                cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf8',timeout=20,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(child.returncode,0,child.stderr)
        value=json.loads(report.read_text(encoding='utf8'))
        self.assertFalse(value['ok']);self.assertEqual(value['error']['stage'],'network_lock')
        self.assertFalse(value['diagnostics']['http_attempted']);self.assertEqual(value['diagnostic_file'],str(report))
        self.assertEqual(value['runtime']['python'],sys.executable)
        self.assertEqual((self.root/'native.json').read_bytes(),before)

    def test_company_command_wrong_python_still_writes_import_diagnosis(self):
        (self.root/'native.json').write_text('{"history_roots":[]}',encoding='utf8')
        report=self.root/'missing_dependency.json'
        child=subprocess.run([sys.executable,'-S','-B','-X','utf8','-m','dashboard.connection_check',
            '--local-root',str(self.root),'--output',str(report)],cwd=Path(__file__).resolve().parents[1],
            capture_output=True,text=True,encoding='utf8',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(child.returncode,1,child.stderr)
        result=json.loads(report.read_text(encoding='utf8'))
        self.assertEqual(result['error']['stage'],'imports');self.assertEqual(result['error']['module'],'pandas')
        self.assertEqual(result['python'],sys.executable)
        self.assertNotIn('Traceback',child.stderr)


if __name__=='__main__':unittest.main()
