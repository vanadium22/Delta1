"""Separate low-frequency capabilities and bounded daily reference repair."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as R
import unittest
from unittest.mock import patch

from dashboard.marketdata.etf_capability_worker import probe,specification
from dashboard.data_capabilities import collect
from dashboard.native.overview_reference_job import ReferenceJob,repair_needs
from dashboard.marketdata.overview_contributions import contributions
from tests.test_overview_details import reference,equity_snapshot,NOW


class Wind:
    def __init__(self):self.calls=[];self.fail=False
    def isconnected(self):return True
    def start(self,**kwargs):return R(ErrorCode=0,Data=[],Fields=[],Codes=[],Times=[])
    def wsd(self,codes,field,start,end,options):
        self.calls.append((field,start,options));codes=codes.split(',')
        return R(ErrorCode=-40522017 if self.fail else 0,Fields=[field],Codes=codes,Times=[start],Data=[[4.]*len(codes)])
    def wsq(self,codes,field):return R(ErrorCode=0,Fields=[field],Codes=codes.split(','),Times=[NOW],Data=[[4.]*len(codes.split(','))])
    def wset(self,dataset,options):
        parts=dict(p.split('=',1) for p in options.split(';'));self.calls.append((dataset,options))
        return R(ErrorCode=0,Fields=['date','wind_code','state'],Codes=[],Times=[],Data=[[parts['date']],[parts['windcode']],[1]])


class CapabilityTests(unittest.TestCase):
    def request(self,fields=None):
        return dict(day='2026-10-23',previous_day='2026-10-22',codes=['510300.SH','510050.SH'],stage='etf_capabilities',fields=fields or {})

    def test_default_etf_probe_only_known_daily_nav_and_close_and_safe_errors(self):
        w=Wind();value=probe(w,self.request())
        self.assertEqual([c[0] for c in w.calls],['nav','close'])
        self.assertEqual(value['checks']['close_nav']['valid_pairs'],2)
        for key in ('iopv','net_creation','pcf'):self.assertEqual(value['checks'][key]['status'],'mapping_required')
        w.fail=True;failed=probe(w,self.request())
        self.assertEqual(failed['checks']['close_nav']['status'],'unavailable')
        self.assertEqual(failed['diagnostics']['failures'][0]['error_code'],-40522017)

    def test_explicit_verified_spec_has_counts_dates_units_and_no_false_net_flows(self):
        spec=dict(schema='overview-etf-fields-v1',
            iopv=dict(field='verified_iopv',definition_source='test fixture definition'),
            shares=dict(field='verified_shares',units='shares',definition_source='test fixture definition'),
            pcf=dict(dataset='verified_pcf',fields=['state'],date_field='date',code_field='wind_code',
                options='date={day};windcode={code}',definition_source='test fixture definition'))
        value=probe(Wind(),self.request(spec))['checks']
        self.assertEqual(value['iopv']['nonempty'],2);self.assertFalse(value['iopv']['source_timestamp_verified'])
        self.assertEqual(value['net_creation']['valid_two_day_pairs'],2);self.assertFalse(value['net_creation']['net_flow_computed'])
        self.assertEqual(value['pcf']['matching_codes'],2);self.assertEqual(value['pcf']['nonempty_rows'],2)
        for bad in (dict(schema='wrong'),dict(schema=spec['schema'],iopv=dict(field='reference')),
                    dict(schema=spec['schema'],iopv=dict(field='exec();x',definition_source='fixture'))):
            with self.assertRaises(ValueError):specification(bad)

    def test_local_no_sdk_and_real_private_worker_missing_sdk_report_preserves_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'native.json';config.write_text(json.dumps(dict(overview_wind_python=sys.executable)),encoding='utf8')
            before=config.read_bytes()
            with patch('dashboard.data_capabilities.run_readonly_worker',side_effect=AssertionError('offline must not spawn')):
                result=collect(root,now=NOW.to_pydatetime())
            self.assertFalse(result['network_requested']);self.assertEqual(result['status'],'inventory_only')
            result=collect(root,'etf',now=NOW.to_pydatetime())
            self.assertEqual(result['status'],'unavailable');self.assertEqual(result['error_type'],'ModuleNotFoundError')
            self.assertEqual(result['diagnostics']['steps'][0]['stage'],'import')
            self.assertTrue(result['profile_files_unchanged']);self.assertEqual(config.read_bytes(),before)
            self.assertFalse((root/'overview_reference').exists())

    def test_daily_quality_repair_bounded_same_day_then_next_day_persistent(self):
        with tempfile.TemporaryDirectory() as tmp,patch('subprocess.Popen',side_effect=OSError('fixture')) as spawn:
            job=ReferenceJob(tmp);job.tick({},enabled=True,now=NOW.to_pydatetime())
            self.assertEqual(spawn.call_count,1)
            ReferenceJob(tmp).tick({},enabled=True,now=NOW.to_pydatetime()+timedelta(minutes=1))
            self.assertEqual(spawn.call_count,1)
            ReferenceJob(tmp).tick({},enabled=True,now=NOW.to_pydatetime()+timedelta(days=1))
            self.assertEqual(spawn.call_count,2)
            ReferenceJob(tmp).tick({},enabled=True,now=NOW.to_pydatetime()+timedelta(days=1,minutes=1))
            self.assertEqual(spawn.call_count,2)
        self.assertIn('IH:membership',repair_needs(reference(),'2026-10-23'))

    def test_industry_partial_never_full_basket_and_diagnostics_identify_each_input(self):
        group=reference()['indices']['IF'];snap=equity_snapshot()
        quote=next(r['symbol'] for r in group['rows']);snap['quotes'].pop(quote,None)
        result=contributions(group,snap,dict(symbol='000300.SH'),NOW,'2026-10-23',snap['reference_version'])
        self.assertEqual(result['inputs']['missing_quotes'],1)
        self.assertIn('缺有效报价1只',result['reason'])
        partial=[r for r in result['industries'] if any(m['symbol']==quote for m in r['members'])][0]
        self.assertIsNone(partial['change_pct']);self.assertIsNone(partial['contribution_points'])
        self.assertIn('缺有效行情',partial['reason'])
        empty=contributions({},snap,dict(symbol='000300.SH'),NOW,'2026-10-23','x')
        self.assertFalse(empty['inputs']['membership_available']);self.assertIn('数量尚未知',empty['reason'])
        self.assertIsNone(empty['inputs']['missing_quotes']);self.assertIsNone(empty['inputs']['missing_weights'])


if __name__=='__main__':unittest.main()
