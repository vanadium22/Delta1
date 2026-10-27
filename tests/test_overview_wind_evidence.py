"""Wind failures stay attributable and safe, including the real hidden IPC path."""
from copy import deepcopy
from datetime import datetime
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.marketdata.wind_terminal_worker import refresh,WindError,safe_diagnostics
from dashboard.marketdata.overview_windpy import refresh as terminal_refresh,TerminalFailure
from dashboard.marketdata.overview_reference import ranking
from dashboard.native.overview_reference_job import main as job_main
from dashboard.overview_wind_check import collect as stage_check
from tests.test_overview_data import FakeWind,response
from tests.test_market_overview import NOW


class FailingWind(FakeWind):
    def isconnected(self):return True
    def wset(self,kind,options):
        return SimpleNamespace(ErrorCode=-40522017,Fields=None,Times=None,Data=[['CANARY_RAW_PASSWORD token=SECRET']],Codes=[])


class WindEvidenceTests(unittest.TestCase):
    def request(self,stage='all'):
        return dict(day='2026-10-23',fetched_at=NOW.isoformat(),old={},config={},stage=stage)

    def test_all_group_failure_retains_each_index_and_sector_error_code(self):
        with self.assertRaises(WindError) as raised:refresh(FailingWind(),self.request())
        diag=raised.exception.diagnostics
        indices=[r for r in diag['failures'] if r['stage']=='index_weights']
        self.assertEqual({r['root'] for r in indices},{'IF','IH','IC','IM'})
        self.assertTrue(all(r['error_code']==-40522017 and r['day']=='2026-10-23' for r in indices))
        self.assertTrue(all(r['connected_before'] and r['connected_after'] for r in indices))
        self.assertTrue(any(r.get('sector') for r in diag['failures'] if r['stage']=='etf_universe'))
        self.assertNotIn('CANARY',json.dumps(diag))

    def test_connection_error_and_sdk_exception_do_not_export_exception_text(self):
        for reply in (SimpleNamespace(ErrorCode=-40520007),RuntimeError('CANARY password=hidden https://user:secret@host')):
            sdk=FailingWind()
            sdk.start=Mock(side_effect=reply if isinstance(reply,Exception) else None,return_value=reply)
            with self.assertRaises(WindError) as raised:refresh(sdk,self.request())
            failed=raised.exception.diagnostics['failures'][0]
            self.assertEqual(failed['stage'],'connect')
            self.assertEqual(failed.get('error_code'),None if isinstance(reply,Exception) else -40520007)
            self.assertNotIn('CANARY',json.dumps(raised.exception.diagnostics))
            self.assertNotIn('secret',str(raised.exception))

    def test_false_connected_state_with_zero_code_does_not_query_data(self):
        sdk=FakeWind();sdk.isconnected=lambda:False
        with self.assertRaises(WindError) as raised:refresh(sdk,self.request())
        self.assertEqual(sdk.calls,[])
        self.assertEqual(raised.exception.diagnostics['failures'][0]['stage'],'connect')
        self.assertFalse(raised.exception.diagnostics['connected_after'])

    def test_partial_reference_keeps_good_groups_and_failed_field_evidence(self):
        sdk=FakeWind();original=sdk.wss
        def fail_industry(codes,field,options):
            if field=='industry_sw':raise RuntimeError('CANARY dsn=secret')
            return original(codes,field,options)
        sdk.wss=fail_industry
        value=refresh(sdk,self.request())
        self.assertEqual(len(value['data']['indices']),4)
        failure=next(r for r in value['diagnostics']['failures'] if r['stage']=='industry')
        self.assertEqual(failure['field'],'industry_sw');self.assertEqual(failure['day'],'2026-10-23')
        self.assertEqual(failure['codes_count'],100)
        self.assertNotIn('CANARY',json.dumps(value))

    def test_complementary_tracking_fields_are_joined_without_dropping_unknowns(self):
        sdk=FakeWind();original=sdk.wss
        def partial(codes,field,options):
            value=original(codes,field,options)
            if field=='fund_trackindexcode':value.Data[0][-1]=None
            if field=='fund_trackindex' and '510301.SH' in codes:value.Data[0][codes.split(',').index('510301.SH')]=None
            return value
        sdk.wss=partial
        value=refresh(sdk,self.request('etfs'))
        rows,meta=ranking(value['data'],'IF',today='2026-10-26')
        self.assertEqual(len(rows),3);self.assertEqual(meta['universe_count'],4)
        step=next(r for r in value['diagnostics']['steps'] if r.get('field')=='fund_trackindex')
        self.assertEqual(step['codes_count'],1)
        with self.assertRaises(WindError):refresh(FakeWind(incomplete=True),self.request('etfs'))

    def test_explicit_stages_do_not_call_other_sources(self):
        for stage in ('connect','indices','etfs'):
            sdk=FakeWind();refresh(sdk,self.request(stage))
            if stage=='connect':self.assertFalse(sdk.calls)
            elif stage=='indices':
                self.assertTrue(any(c[1]=='industry_sw' for c in sdk.calls))
                self.assertFalse(any(c[1] in ('sectorconstituent','netasset_total') for c in sdk.calls))
            else:self.assertFalse(any(c[1] in ('indexconstituent','industry_sw','close') for c in sdk.calls))

    def test_real_hidden_worker_failure_reaches_saved_job_status_without_secret_or_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sdk=root/'sdk';sdk.mkdir()
            code='from datetime import datetime\nfrom types import SimpleNamespace\n'+inspect.getsource(response)+'\n'+inspect.getsource(FakeWind)+'\n'+inspect.getsource(FailingWind)+'\nw=FailingWind()\n'
            (sdk/'WindPy.py').write_text(code,encoding='utf8')
            reference=root/'overview_reference';reference.mkdir()
            old=reference/'latest.json';old.write_text('{"preserve":"old snapshot"}',encoding='utf8');before=old.read_bytes()
            (root/'native.json').write_text(json.dumps(dict(overview_wind_python=sys.executable)),encoding='utf8')
            with patch.dict(os.environ,{'PYTHONPATH':str(sdk)}),patch('dashboard.native.overview_reference_job.publish') as publish:
                self.assertEqual(job_main(['--local-root',str(root)]),0)
            status=json.loads((reference/'status.json').read_text(encoding='utf8'))
            self.assertEqual(status['status'],'unavailable');self.assertEqual(status['error_type'],'WindError')
            self.assertEqual(status['diagnostics']['failures'][0]['error_code'],-40522017)
            self.assertEqual(len([r for r in status['diagnostics']['failures'] if r['stage']=='index_weights']),4)
            self.assertEqual(old.read_bytes(),before);publish.assert_not_called()
            self.assertNotIn('CANARY',json.dumps(status));self.assertNotIn('SECRET',json.dumps(status))

    def test_bridge_timeout_keeps_last_safe_operation_not_stdout_or_stderr(self):
        def timeout(*args,**kwargs):
            request=json.loads(kwargs['input'])
            Path(request['progress_file']).write_text(json.dumps(dict(steps=[dict(stage='etf_scale',field='netasset_total',
                day=request['day'],status='started',connected_before=True)],password='CANARY_PROGRESS')),encoding='utf8')
            raise subprocess.TimeoutExpired(args[0],180,output='CANARY_STDOUT',stderr='CANARY_STDERR')
        with patch('subprocess.run',side_effect=timeout),self.assertRaises(TerminalFailure) as raised:
            terminal_refresh({},'.',{},now=NOW.to_pydatetime())
        diag=raised.exception.diagnostics
        self.assertEqual(diag['steps'][0]['stage'],'etf_scale');self.assertEqual(diag['steps'][-1]['stage'],'worker_timeout')
        self.assertNotIn('CANARY',json.dumps(diag))

    def test_sdk_field_validation_failure_remains_distinct_from_error_code(self):
        sdk=FakeWind();original=sdk.wset
        def short(kind,options):
            if kind=='indexconstituent':return response(['wind_code','sec_name','i_weight'],[['600001.SH'],['甲'],[100]])
            return original(kind,options)
        sdk.wset=short
        result=refresh(sdk,self.request())
        step=next(r for r in result['diagnostics']['failures'] if r['stage']=='index_weights')
        self.assertEqual(step['error_code'],0);self.assertEqual(step['status'],'invalid_response')
        self.assertEqual(step['expected'],300);self.assertEqual(step['actual'],1)

    def test_staged_report_does_not_publish_or_change_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'native.json'
            path.write_text(json.dumps(dict(password='CANARY_CONFIG')),encoding='utf8');before=path.read_bytes()
            result=refresh(FakeWind(),self.request('indices'))
            with patch('dashboard.overview_wind_check.refresh',return_value=result):
                report=stage_check(root,'indices',now=NOW.to_pydatetime())
            self.assertEqual(report['status'],'complete');self.assertTrue(report['profile_files_unchanged'])
            self.assertFalse(report['published']);self.assertFalse(report['vpn_changed']);self.assertNotIn('CANARY',json.dumps(report))
            self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'overview_reference').exists())

    def test_evidence_allowlist_filters_raw_messages_and_nested_connection_data(self):
        source=dict(steps=[dict(stage='connect',error_code=-1,reason='CANARY_REASON',Data='CANARY_DATA',
            connection=dict(password='CANARY_PASSWORD'),returned_fields=['wind_code','CANARY invalid field'])],
            etf_universe_attempts=[dict(sector='股票型ETF',error_code=-2,reason='CANARY_SECTOR')])
        safe=safe_diagnostics(source)
        self.assertEqual(safe['steps'][0]['error_code'],-1)
        self.assertEqual(safe['steps'][0]['returned_fields'],['wind_code'])
        self.assertNotIn('CANARY',json.dumps(safe))

    @unittest.skipUnless(os.name=='nt','Windows company launcher')
    def test_powershell_overview_does_not_import_wind_and_only_explicit_stage_enters_fake_sdk(self):
        repository=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sdk=root/'sdk';sdk.mkdir();marker=root/'sdk_entered'
            code='from datetime import datetime\nfrom types import SimpleNamespace\nfrom pathlib import Path\n'+inspect.getsource(response)+'\n'+inspect.getsource(FakeWind)
            code+='\nclass Wind(FakeWind):\n def start(self,**kw):\n  Path('+repr(str(marker))+').write_text("entered")\n  return super().start(**kw)\nw=Wind()\n'
            (sdk/'WindPy.py').write_text(code,encoding='utf8')
            path=root/'native.json';path.write_text(json.dumps(dict(overview_wind_python=sys.executable,password='CANARY_CONFIG')),encoding='utf8')
            before=path.read_bytes();env=dict(os.environ,SWHY_DELTA1_PYTHON=sys.executable,PYTHONPATH=str(sdk)+os.pathsep+os.environ.get('PYTHONPATH',''))
            command=['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','Bypass',
                '-File',str(repository/'dashboard/diagnose_presentation.ps1'),'-LocalRoot',str(root),'-NoPause']
            for arguments,requested in ((['-Overview'],False),(['-WindStage','Connect'],True)):
                done=subprocess.run(command+arguments,cwd=repository,env=env,capture_output=True,text=True,timeout=45,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(done.returncode,0,done.stderr)
                match=re.search(r'^Report: (.+)$',done.stdout,re.M);self.assertIsNotNone(match,done.stdout)
                report=json.loads(Path(match[1].strip()).read_text(encoding='utf-8-sig'))
                self.assertEqual(report['wind_requested'],requested);self.assertEqual(marker.exists(),requested)
                if requested:
                    wind=json.loads(Path(report['wind_report']).read_text(encoding='utf8'))
                    self.assertEqual(wind['status'],'complete');self.assertEqual(len(wind['diagnostics']['steps']),1)
                    self.assertEqual(wind['diagnostics']['steps'][0]['stage'],'connect')
                    self.assertTrue(wind['profile_files_unchanged']);self.assertFalse(wind['published'])
                    self.assertNotIn('CANARY',json.dumps(wind))
                else:
                    self.assertFalse(report['network_requested'])
                    self.assertEqual(report['overview_exit_code'],0)
                    self.assertNotIn('wind_report',report)
                self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
