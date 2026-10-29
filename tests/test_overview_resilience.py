"""Optional corrupt inputs cannot suppress unrelated, verified display data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import pandas as pd

from dashboard.marketdata.overview_reference import load,validate,ranking
from dashboard.marketdata.overview_contributions import read_equities,contributions
from dashboard.marketdata.quote_quality import quote_quality,aligned_quotes
from dashboard.marketdata.overview_basis import calculate,input_summary
from dashboard.native.market_overview import MarketOverviewEngine,futures_values
from tests.test_overview_details import reference,equity_snapshot
from tests.test_market_overview import NOW,ZERO_DIVIDENDS,observation,frame


class ReferenceIsolationTests(unittest.TestCase):
    def read(self,value):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'latest.json';raw=json.dumps(value).encode();path.write_bytes(raw)
            result=load(dict(overview_reference_file=str(path)),tmp,now=NOW.to_pydatetime())
            self.assertEqual(path.read_bytes(),raw)
            if result['version']:self.assertEqual(result['version'],hashlib.sha256(raw).hexdigest())
            return result

    def nav_reference(self):
        value=reference()
        value['etf_nav']=dict(schema='etf-nav-v1',rows={s:dict(symbol=s,as_of='2026-10-23',source='fixture',nav_cny=4,close_cny=4.1)
            for s in ('510301.SH','510302.SH')})
        return value

    def test_one_bad_nav_preserves_other_nav_rankings_and_memberships_without_writes(self):
        for invalid in (None,-1,False,float('inf')):
            value=self.nav_reference();value['etf_nav']['rows']['510301.SH']['nav_cny']=invalid
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):validate(value)
                result=self.read(value)
                self.assertEqual(len(ranking(result['data'],'IF',today='2026-10-26')[0]),3)
                self.assertEqual(len(result['data']['indices']['IF']['rows']),3)
                self.assertEqual(set(result['data']['etf_nav']['rows']),{'510302.SH'})
                self.assertEqual(result['issues'],[dict(scope='etf_nav.510301.SH',error_type='InvalidRow')])
                self.assertTrue(result['due']);self.assertIn('部分',result['error'])

    def test_invalid_optional_containers_do_not_remove_intact_other_sections(self):
        for kind in ('etf_nav','indices','etfs'):
            value=self.nav_reference();value[kind]=['CANARY_RAW_SECRET']
            result=self.read(value)
            self.assertTrue(result['issues']);self.assertNotIn('CANARY',json.dumps(result))
            other='indices' if kind!='indices' else 'etfs'
            self.assertIn('IF',result['data'][other])

    def test_one_bad_index_does_not_become_partial_complete_or_hide_other_root(self):
        value=reference();ih=deepcopy(value['indices']['IF']);ih['index_id']='000016.SH';value['indices']['IH']=ih
        value['indices']['IF']['rows'][0]['weight_pct']=None
        result=self.read(value)
        self.assertNotIn('IF',result['data']['indices']);self.assertIn('IH',result['data']['indices'])
        self.assertEqual(len(result['data']['etfs']['IF']['rows']),4)

    def test_conflicting_etf_identity_is_never_ranked_by_salvaging_groups_separately(self):
        value=reference();ih=deepcopy(value['etfs']['IF']);ih['index_id']='000016.SH'
        for row in ih['rows']:row['index_id']='000016.SH'
        value['etfs']['IH']=ih
        result=self.read(value)
        self.assertFalse(result['data']['etfs']);self.assertTrue(result['data']['indices'])
        self.assertTrue(all(i['error_type']=='ConflictingBenchmark' for i in result['issues']))

    def test_bad_global_clock_cannot_be_salvaged_as_current_reference(self):
        for time in ('not-a-date','2026-10-26T09:00:00','2027-01-01T09:00:00+08:00'):
            value=reference();value['fetched_at']=time
            self.assertEqual(self.read(value)['data'],{})


class QuoteIsolationTests(unittest.TestCase):
    def test_one_corrupt_equity_does_not_hide_healthy_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=equity_snapshot();value['quotes']['600002.SH']='broken'
            value['quotes']['600003.SH']['source_event_time']='CANARY_INVALID_TIME'
            path=Path(tmp)/'overview_equities/latest.json';path.parent.mkdir();path.write_text(json.dumps(value))
            raw=path.read_bytes();snapshot=read_equities({},tmp)
            result=contributions(reference()['indices']['IF'],snapshot,dict(symbol='000300.SH'),NOW,'2026-10-23','v1')
            self.assertEqual(result['covered'],1);self.assertAlmostEqual(result['rows'][0]['change_pct'],10)
            self.assertEqual(snapshot['invalid_quote_count'],1);self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(result['inputs']['missing_quotes'],2)
            self.assertFalse(next(i for i in result['industries'] if i['name']=='银行')['complete'])

    def test_malformed_or_naive_source_clock_is_unusable_without_aborting_other_leg(self):
        for field in ('source_event_time','observed_at'):
            for invalid in ('broken','2026-10-26T10:00:05',None,{},False):
                q=observation();q[field]=invalid
                with self.subTest(field=field,invalid=invalid):
                    self.assertFalse(quote_quality(q,NOW)['usable']);self.assertFalse(aligned_quotes([q,observation()],NOW)[0])
        self.assertTrue(quote_quality(observation(),NOW)['usable'])

    def test_one_history_io_failure_keeps_all_current_prices_and_other_history(self):
        live={'000300.SH':observation(),'000016.SH':observation(2000,1990),'510300.SH':observation(4,3.9)}
        repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={}
        def read(symbol,*args,**kwargs):
            if symbol=='000300.SH':raise OSError('CANARY_PRIVATE_PATH')
            return frame(['2026-10-23'],lambda _:1990) if symbol=='000016.SH' else pd.DataFrame()
        repo.read_window.side_effect=read
        model=SimpleNamespace(config={},configure_repository=lambda _:repo,_live=lambda *a:live,live_rows=pd.DataFrame())
        with patch('dashboard.native.market_overview.load_dividends',return_value=ZERO_DIVIDENDS):
            engine=MarketOverviewEngine(model)
            for _ in range(2):
                result=engine.snapshot(now=NOW)['market_overview']
                by_symbol={r['symbol']:r for r in result['indices']}
                self.assertEqual(by_symbol['000300.SH']['price'],4000)
                self.assertEqual(by_symbol['000016.SH']['yesterday_close'],1990)
                self.assertEqual(result['etfs'][0]['price'],4)
                self.assertTrue(any('000300.SH' in e for e in result['errors']))
                self.assertNotIn('CANARY',json.dumps(result))


class BasisReconciliationTests(unittest.TestCase):
    def test_dividend_change_matches_simple_excel_formula_and_preserves_provenance(self):
        symbol='IF2611.CFE';meta={symbol:dict(expiry_date='2026-11-20')}
        live={symbol:observation(99,100),'000300.SH':observation(100,100)}
        results=[]
        for points in (0.,.5):
            book=SimpleNamespace(resolve=lambda *a:dict(points=points,source_snapshot='2026-10-23',
                file_sha256='a'*64,effective_from='2026-10-23T00:00:00+08:00',revision='revision',source_kind='spreadsheet_concrete'),version='v')
            row=dict(symbol=symbol,root='IF')
            futures_values(row,live,{},meta,NOW,dividends=book)
            self.assertEqual(row['basis_future_price'],99);self.assertEqual(row['basis_spot_price'],100)
            self.assertEqual(row['days'],25);self.assertEqual(row['pricing_day'],'2026-10-26')
            self.assertEqual(row['dividend_file_sha256'],'a'*64)
            self.assertAlmostEqual(row['annual_pct'],(99-100+points)*365/25/100*100)
            self.assertIn('F=99 · S=100 · D=',input_summary(row))
            results.append(row['annual_pct'])
        self.assertAlmostEqual(results[1]-results[0],.5/100*365/25*100)

    def test_missing_dividend_retains_raw_basis_without_assuming_zero(self):
        symbol='IF2611.CFE';live={symbol:observation(99,100),'000300.SH':observation(100,100)}
        row=dict(symbol=symbol,root='IF')
        futures_values(row,live,{}, {symbol:dict(expiry_date='2026-11-20')},NOW)
        self.assertEqual(row['raw_basis_points'],-1);self.assertEqual(row['basis_future_price'],99)
        self.assertIsNone(row['dividend_points']);self.assertIsNone(row['annual_pct'])
        self.assertIsNone(calculate(99,100,None,25)['annual_pct'])
