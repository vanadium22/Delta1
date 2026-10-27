"""Company gaps are local evidence, never network guesses or blank=zero claims."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import pandas as pd

from dashboard.marketdata.overview_audit import collect,inspect_history
from dashboard.marketdata import overview_daily
from dashboard.marketdata.overview_reference import publish
from dashboard.marketdata.history_publication import maintenance_root
from dashboard.overview_check import read_status
from tests.test_overview_percentiles import metadata,daily_data,NOW,DAY
from tests.test_overview_details import reference


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')


def profile(root):
    meta=metadata();path=Path(root)/'contracts.json'
    save(path,dict(schema_version='cn_index_reference_v1',contracts=[dict(instrument_id=s,known_at='2026-10-27T00:00:00+08:00',**r) for s,r in meta.items()]))
    config=dict(reference_file=str(path),password='CANARY_CONFIG_SECRET')
    save(Path(root)/'native.json',config)
    return config,meta


class OverviewAuditTests(unittest.TestCase):
    def test_absent_wind_universe_is_a_dependency_gap_not_zero_missing_stocks(self):
        with tempfile.TemporaryDirectory() as tmp,patch('requests.sessions.Session.request',side_effect=AssertionError('offline only')):
            config,meta=profile(tmp);before=Path(tmp,'native.json').read_bytes()
            result=collect(config,tmp,now=NOW)
            self.assertFalse(result['ddb']['all_four_equity_universes_known'])
            self.assertFalse(result['ddb']['equity_universe_known'])
            self.assertEqual(set(result['summary']['missing_index_reference_roots']),{'IF','IH','IC','IM'})
            self.assertEqual(len(result['summary']['continuous_windows_incomplete']),32)
            self.assertEqual(Path(tmp,'native.json').read_bytes(),before)
            self.assertNotIn('CANARY_CONFIG',json.dumps(result))
            self.assertFalse(result['network_requested']);self.assertFalse(result['wind_requested'])
            self.assertFalse(result['summary']['company_acceptance_passed'])

    def test_seed_uses_existing_local_closes_without_ddb_and_audit_reports_complete_slot_histories(self):
        with tempfile.TemporaryDirectory() as tmp,patch('requests.sessions.Session.request',side_effect=AssertionError('offline only')):
            config,meta=profile(tmp);data=daily_data(meta);earlier=daily_data(meta,day='2026-10-26')
            for symbol,frame in earlier.items():data[symbol]=pd.concat([frame,data.get(symbol,pd.DataFrame())],ignore_index=True).drop_duplicates('trade_date')
            repo=Mock();repo.read_window.side_effect=lambda symbol,*a,**kw:data.get(symbol,pd.DataFrame())
            inserted=overview_daily.seed_local(repo,{},config,tmp,'2026-10-26',meta)
            self.assertGreater(inserted,0)
            jobs=overview_daily.requests(config,tmp,'2026-10-26',meta)
            self.assertTrue(jobs);self.assertTrue(all(j['asset']=='etf' for j in jobs))
            result=collect(config,tmp,now=NOW)
            self.assertEqual(len(result['continuous_annual']['mapping_gaps']),0)
            self.assertTrue(all(w['complete'] for slot in result['continuous_annual']['slots'].values() for w in slot['windows'].values()))
            # Audit history is complete, but it has never claimed a live marker.
            self.assertTrue(all(w['percentile'] is None for slot in result['continuous_annual']['slots'].values() for w in slot['windows'].values()))
            row=overview_daily.read_day(config,tmp,'2026-10-26')['rows']['IF2706.CFE']
            self.assertEqual(row['acquisition'],'local_copy_no_network')
            self.assertEqual(row['unit_factors'],{})

    def test_wind_reports_missing_industries_and_keeps_worker_secrets_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,_=profile(tmp);ref=reference();ref['indices']['IF']['rows'][0]['industry']=None
            publish(Path(tmp)/'overview_reference/latest.json',ref)
            save(Path(tmp)/'overview_reference/status.json',dict(status='unavailable',provider='windpy',password='CANARY_JOB_SECRET',
                diagnostics=dict(provider='WindPy',password='CANARY_NESTED',tracking_attempts=[dict(field='fund_trackindexcode',unresolved=2,password='CANARY_ATTEMPT')])) )
            save(Path(tmp)/'overview_daily/status.json',dict(status='partial',pending_rows=4,password='CANARY_DDB_STATUS'))
            result=collect(config,tmp,now=NOW)
            self.assertEqual(result['wind']['indices']['IF']['missing_industry'],['600001.SH'])
            self.assertEqual(result['wind']['indices']['IF']['selected_etfs'][0]['symbol'],'510301.SH')
            self.assertEqual(result['wind']['last_job']['diagnostics']['tracking_attempts'][0]['unresolved'],2)
            self.assertNotIn('CANARY',json.dumps(result))
            self.assertNotIn('CANARY',json.dumps(read_status(Path(tmp)/'overview_reference/status.json')))

    def test_unknown_scan_or_stale_pending_never_claims_zero_history_gaps(self):
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.marketdata.repository.MarketDataRepository') as constructor:
            root=Path(tmp)/'bars';root.mkdir();maintenance=maintenance_root([str(root)])
            constructor.return_value.freeze.return_value={'index':dict(version='v1',parts=[],descriptor={})}
            constructor.return_value.datasets={'index':SimpleNamespace(root=root,descriptor={})}
            state=dict(state='complete',scan_id='new',scan_complete=True,pending_scan_id='new',pending_target='2026-10-26',
                target='2026-10-26',pending_symbol_days=0,missing_bars=0,versions={'index':'v1'})
            save(maintenance/'status.json',state)
            save(maintenance/'pending.json',dict(scan_id='old',target='2026-10-26',versions={'index':'v1'},jobs=[]))
            _,_,result=inspect_history(dict(history_roots=[str(root)]))
            self.assertFalse(result['pending_current']);self.assertIsNone(result['known_pending_symbol_days'])
            job=dict(symbol='IF2609.CFE',frequency='1d',day='2026-09-01',missing=1,password='CANARY_JOB')
            state['pending_symbol_days']=1;save(maintenance/'status.json',state)
            save(maintenance/'pending.json',dict(scan_id='new',target='2026-10-26',versions={'index':'v1'},jobs=[job]))
            _,_,result=inspect_history(dict(history_roots=[str(root)]))
            self.assertTrue(result['pending_current']);self.assertEqual(result['known_pending_symbol_days'],1)
            self.assertEqual(result['pending_jobs'][0]['day'],'2026-09-01');self.assertNotIn('CANARY',json.dumps(result))
            constructor.return_value.freeze.return_value={'index':dict(version='v2',parts=[],descriptor={})}
            _,_,result=inspect_history(dict(history_roots=[str(root)]))
            self.assertFalse(result['pending_current']);self.assertIsNone(result['known_pending_symbol_days'])


if __name__=='__main__':unittest.main()
