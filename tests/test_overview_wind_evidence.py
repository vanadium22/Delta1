"""Wind failures stay attributable and safe, including the real hidden IPC path."""
from copy import deepcopy
from datetime import datetime
import inspect
import hashlib
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

from dashboard.marketdata.wind_terminal_worker import refresh,WindError,safe_diagnostics,daily,ROOTS
from dashboard.marketdata.overview_windpy import refresh as terminal_refresh,TerminalFailure
from dashboard.marketdata.overview_reference import ranking
from dashboard.native.overview_reference_job import main as job_main,ReferenceJob
from dashboard.overview_wind_check import collect as stage_check
from tests.test_overview_data import FakeWind,response
from tests.test_market_overview import NOW


class FailingWind(FakeWind):
    def isconnected(self):return True
    def wset(self,kind,options):
        return SimpleNamespace(ErrorCode=-40522017,Fields=None,Times=None,Data=[['CANARY_RAW_PASSWORD token=SECRET']],Codes=[])


class FullETFUniverseWind(FakeWind):
    """66 ordinary ETFs, four benchmark universes, SDK's actual daily layout."""
    def wset(self,kind,options):
        value=super().wset(kind,options)
        if kind=='sectorconstituent':
            day=value.Data[value.Fields.index('date')][0]
            value=response(['wind_code','sec_name','date'],[[f'{510100+i:06}.SH' for i in range(66)],
                ['普通ETF'+str(i) for i in range(66)],[day]*66])
        return value
    def wss(self,codes,field,options):
        if field in ('fund_trackindexcode','netasset_total'):
            self.calls.append(('WSS',field,options));symbols=codes.split(',')
            values=[list(ROOTS.values())[(int(s[:6])-510100)%4] if field=='fund_trackindexcode' else
                (int(s[:6])-510099)*1e8 for s in symbols]
            return response([field.upper()],[values],symbols)
        return super().wss(codes,field,options)


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

    def test_official_single_date_66_code_matrix_uses_returned_code_order(self):
        codes=[f'{510000+i:06}.SH' for i in range(66)]
        sdk=SimpleNamespace(wsd=Mock(return_value=SimpleNamespace(ErrorCode=0,Fields=['NETASSET_TOTAL'],
            Codes=list(reversed(codes)),Times=[datetime(2026,10,26)],Data=[list(range(1,67))])))
        values=daily(sdk,codes,'netasset_total','2026-10-26','unit=1')
        self.assertEqual(values[codes[0]],66);self.assertEqual(values[codes[-1]],1)
        self.assertIn('Fill=Blank;Days=Trading',sdk.wsd.call_args.args[-1])

    def test_single_day_matrix_keeps_strict_date_field_and_code_identity(self):
        codes=['510301.SH','510302.SH'];base=dict(ErrorCode=0,Fields=['netasset_total'],
            Codes=codes,Times=[datetime(2026,10,26)],Data=[[100,200]])
        cases=[dict(Times=[datetime(2026,10,23)]),dict(Codes=[codes[0],codes[0]]),
            dict(Fields=['close']),dict(Data=[[100,200,300]]),dict(Data=[[100,200],[300,400]]),dict(Data=['12'])]
        for change in cases:
            with self.subTest(change=list(change)):
                sdk=SimpleNamespace(wsd=Mock(return_value=SimpleNamespace(**dict(base,**change))))
                with self.assertRaises(ValueError):daily(sdk,codes,'netasset_total','2026-10-26','unit=1')
        for matrix in ([[100,200]],[[100],[200]]):
            sdk=SimpleNamespace(wsd=Mock(return_value=SimpleNamespace(**dict(base,Data=matrix))))
            self.assertEqual(daily(sdk,codes,'netasset_total','2026-10-26','unit=1'),dict(zip(codes,[100,200])))

    def test_compact_explicit_wset_day_and_dataset_dates_override_query_timestamp(self):
        sdk=FakeWind();original=sdk.wset
        def compact_only(kind,options):
            self.assertIn('date=20261023;',options)
            self.assertIn('field=date,wind_code,sec_name',options)
            result=original(kind,options);result.Times=[datetime(2026,10,27)]
            return result
        sdk.wset=compact_only
        result=refresh(sdk,self.request())
        self.assertEqual(len(result['data']['indices']),4)
        step=next(r for r in result['diagnostics']['steps'] if r['stage']=='index_weights')
        self.assertEqual(step['returned_dates'],['2026-10-27'])
        self.assertEqual(step['returned_row_dates'],['2026-10-23'])
        self.assertEqual(step['date_argument'],'20261023')
        self.assertEqual(step['missing_weight_count'],0)
        self.assertEqual(step['matrix_rows'],4);self.assertEqual(step['row_count'],300)

    def test_invalid_weights_retain_counts_row_dates_and_never_export_values(self):
        sdk=FakeWind();original=sdk.wset
        def invalid(kind,options):
            result=original(kind,options)
            if kind=='indexconstituent':
                result.Data[2][0]=None;result.Data[2][1]='CANARY_WEIGHT_PASSWORD'
                result.Data[2][2]=-1;result.Data[3]=[datetime(2026,10,27)]*len(result.Data[0])
            return result
        sdk.wset=invalid
        with self.assertRaises(WindError) as raised:refresh(sdk,self.request('indices'))
        for step in raised.exception.diagnostics['failures']:
            self.assertEqual(step['error_code'],0)
            self.assertEqual(step['missing_weight_count'],1);self.assertEqual(step['invalid_weight_count'],1)
            self.assertEqual(step['negative_weight_count'],1)
            self.assertEqual(step['returned_row_dates'],['2026-10-27'])
        self.assertNotIn('CANARY',json.dumps(raised.exception.diagnostics))

    def test_wrong_or_partially_missing_dataset_dates_never_publish_reference(self):
        for stage,kind,dates in [('indices','indexconstituent',[datetime(2026,10,26)]),
                                 ('indices','indexconstituent',[None]),('etfs','sectorconstituent',[None])]:
            with self.subTest(stage=stage,dates=dates):
                sdk=FakeWind();original=sdk.wset
                def wrong(kind_arg,options):
                    value=original(kind_arg,options)
                    if kind_arg==kind:
                        pos=value.Fields.index('date');value.Data[pos][0]=dates[0]
                    return value
                sdk.wset=wrong
                with self.assertRaises(WindError) as raised:refresh(sdk,self.request(stage))
                failed=raised.exception.diagnostics['failures'][0]
                self.assertIn(failed['reason_code'],('weight_date_mismatch','weight_date_unverified','universe_date_unverified'))
                self.assertEqual(failed['error_code'],0)

    def test_all_four_etf_rankings_survive_real_hidden_worker_with_66_code_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sdk=root/'sdk';sdk.mkdir()
            code='from datetime import datetime\nfrom types import SimpleNamespace\nROOTS='+repr(ROOTS)+'\n'
            code+=inspect.getsource(response)+'\n'+inspect.getsource(FakeWind)+'\n'+inspect.getsource(FullETFUniverseWind)+'\nw=FullETFUniverseWind()\n'
            (sdk/'WindPy.py').write_text(code,encoding='utf8')
            (root/'native.json').write_text(json.dumps(dict(overview_wind_python=sys.executable)),encoding='utf8')
            with patch.dict(os.environ,{'PYTHONPATH':str(sdk)}):
                result=stage_check(root,'etfs',now=NOW.to_pydatetime())
            self.assertEqual(result['status'],'complete');self.assertFalse(result['published'])
            self.assertTrue(result['profile_files_unchanged'])
            self.assertEqual(sum(g['universe_count'] for g in result['etfs'].values()),66)
            self.assertTrue(all(len(g['top3'])==3 for g in result['etfs'].values()))
            step=next(r for r in result['diagnostics']['steps'] if r['stage']=='etf_scale')
            self.assertEqual(step['matrix_rows'],1);self.assertEqual(step['matrix_row_lengths'],[66])
            self.assertEqual(step['matrix_layout'],'single_field_by_code')
            self.assertFalse((root/'overview_reference').exists())

    def test_worker_protocol_upgrade_retries_old_failure_once_then_keeps_weekly_limit(self):
        from dashboard.marketdata.wind_terminal_worker import PROTOCOL
        with tempfile.TemporaryDirectory() as tmp,patch('subprocess.Popen',side_effect=OSError('fixture')) as spawn:
            directory=Path(tmp)/'overview_reference';directory.mkdir()
            keys=('overview_reference_backend','overview_wind_python','overview_wind_config','overview_wind_aum_field',
                  'overview_wind_aum_multiplier','overview_wind_etf_sector','overview_wind_tracking_field','overview_wind_industry_field')
            old=hashlib.sha256(json.dumps(['wind-terminal-v3-evidence',dict.fromkeys(keys)],sort_keys=True).encode()).hexdigest()
            week='-'.join(map(str,NOW.isocalendar()[:2]))
            (directory/'attempt.json').write_text(json.dumps(dict(week=week,profile=old)),encoding='utf8')
            job=ReferenceJob(tmp);job.tick({},enabled=True,now=NOW.to_pydatetime())
            self.assertEqual(spawn.call_count,1)
            job.tick({},enabled=True,now=NOW.to_pydatetime());self.assertEqual(spawn.call_count,1)
            self.assertEqual(job.state()['status'],'attempted_this_week')
            self.assertNotEqual(json.loads((directory/'attempt.json').read_text())['profile'],old)
            self.assertNotEqual(PROTOCOL,'wind-terminal-v3-evidence')

    def test_readonly_day_can_be_frozen_and_invalid_dates_never_enter_sdk(self):
        value=refresh(FakeWind(),dict(self.request('indices'),day='2026-10-22'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{}',encoding='utf8')
            with patch('dashboard.overview_wind_check.refresh',return_value=value) as call:
                result=stage_check(root,'indices',now=NOW.to_pydatetime(),day='2026-10-22')
            self.assertEqual(call.call_args.kwargs['requested_day'],'2026-10-22')
            self.assertEqual(result['diagnostics']['requested_day'],'2026-10-22')
        for invalid in ('2026-10-26','2026-10-25','2026-10-01','20261022','2001-01-03'):
            with self.subTest(day=invalid),patch('subprocess.run') as sdk:
                with self.assertRaises(ValueError):
                    terminal_refresh({},'.',{},now=NOW.to_pydatetime(),stage='indices',requested_day=invalid)
                sdk.assert_not_called()

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
            code='from datetime import datetime\nfrom types import SimpleNamespace\nfrom pathlib import Path\nROOTS='+repr(ROOTS)+'\n'
            code+=inspect.getsource(response)+'\n'+inspect.getsource(FakeWind)+'\n'+inspect.getsource(FullETFUniverseWind)
            code+='\nclass Wind(FullETFUniverseWind):\n def start(self,**kw):\n  Path('+repr(str(marker))+').write_text("entered")\n  return super().start(**kw)\nw=Wind()\n'
            (sdk/'WindPy.py').write_text(code,encoding='utf8')
            path=root/'native.json';path.write_text(json.dumps(dict(overview_wind_python=sys.executable,password='CANARY_CONFIG')),encoding='utf8')
            before=path.read_bytes();env=dict(os.environ,SWHY_DELTA1_PYTHON=sys.executable,PYTHONPATH=str(sdk)+os.pathsep+os.environ.get('PYTHONPATH',''))
            command=['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','Bypass',
                '-File',str(repository/'dashboard/diagnose_presentation.ps1'),'-LocalRoot',str(root),'-NoPause']
            for arguments,requested in ((['-Overview'],False),(['-WindStage','Connect'],True),
                                        (['-WindStage','ETFs','-WindDay','2026-10-26'],True)):
                done=subprocess.run(command+arguments,cwd=repository,env=env,capture_output=True,text=True,timeout=45,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(done.returncode,0,done.stderr)
                match=re.search(r'^Report: (.+)$',done.stdout,re.M);self.assertIsNotNone(match,done.stdout)
                report=json.loads(Path(match[1].strip()).read_text(encoding='utf-8-sig'))
                self.assertEqual(report['wind_requested'],requested);self.assertEqual(marker.exists(),requested)
                if requested:
                    wind=json.loads(Path(report['wind_report']).read_text(encoding='utf8'))
                    self.assertEqual(wind['status'],'complete')
                    self.assertEqual(wind['diagnostics']['steps'][0]['stage'],'connect')
                    if 'ETFs' in arguments:
                        self.assertEqual(wind['diagnostics']['requested_day'],'2026-10-26')
                        self.assertTrue(all(len(g['top3'])==3 for g in wind['etfs'].values()))
                        self.assertEqual(report['wind_day'],'2026-10-26')
                    else:self.assertEqual(len(wind['diagnostics']['steps']),1)
                    self.assertTrue(wind['profile_files_unchanged']);self.assertFalse(wind['published'])
                    self.assertNotIn('CANARY',json.dumps(wind))
                else:
                    self.assertFalse(report['network_requested'])
                    self.assertEqual(report['overview_exit_code'],0)
                    self.assertNotIn('wind_report',report)
                self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
