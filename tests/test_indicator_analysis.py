"""Indicator-page arithmetic, dated identity, missingness and reader isolation."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from dashboard.marketdata.indicator_analysis import (selection, plan, values, historical,
    statistics, display, point, maintenance_rows, summary, SERIES)
from dashboard.marketdata.overview_daily import publish_day, requests, seed_local
from dashboard.native.continuous import slot_map
from dashboard.native.indicator_analysis import IndicatorAnalysisEngine
from tests.test_overview_percentiles import metadata
from tests.test_market_overview import ZERO_DIVIDENDS, observation

DAY='2026-10-27'
NOW=pd.Timestamp(DAY+'T10:00:05+08:00')


def fixture(request=None, day=DAY, book=ZERO_DIVIDENDS):
    request=request or selection()
    meta=metadata();planned=plan(day,request,meta);tables={}
    for item in planned['rows']:
        s,d=item['symbol'],item['day']
        price=4000. if not s.endswith('.CFE') else 3950.+(date.fromisoformat(d).toordinal()%19)*2-int(s[4:6])
        tables.setdefault(s,{})[d]=dict(trade_date=d,is_final=True,close=price,event_time=pd.Timestamp(d+'T15:00:00+08:00'))
    history=historical(planned,meta,tables,book)
    return planned,meta,tables,history


def preview(request=None):
    planned,meta,tables,history=fixture(request)
    current={k:history[k][-1] for k in SERIES}
    result=display(planned,history,current)
    result.update(mode='completed_daily',version='synthetic-layout-only',errors=[],cache_hit=False)
    return result


class IndicatorFormulaTests(unittest.TestCase):
    def test_basis_sign_and_independent_calendar_formula_uses_spot_and_dividend_difference(self):
        day='2026-11-10';request=selection(slot=3)
        syms=['IF2611.CFE','IF2612.CFE','IF2703.CFE','IF2706.CFE']
        meta={s:dict(expiry_date=str(date.fromisoformat(day)+timedelta(days=t))) for s,t in zip(syms,(10,40,120,220))}
        mapping={f'IF0{i}.CFE':s for i,s in enumerate(syms)}
        divs=dict(zip(syms,(0,10,40,100)))
        book=SimpleNamespace(resolve=lambda s,d:dict(points=divs[s],revision='test'))
        prices=dict(zip(syms,(4100,4080,4000,3960)));prices['000300.SH']=4100
        result=values(day,request,mapping,meta,prices,book,current=True)
        self.assertEqual(result['raw']['value'],-140)
        self.assertEqual(result['adjusted']['value'],-40)
        self.assertAlmostEqual(result['annual']['value'],100*-40/4100*365/220)
        self.assertAlmostEqual(result['calendar_03_02']['value'],1.7804878048780488)
        self.assertAlmostEqual(result['calendar_02_01']['value'],100*(-80+30)/4100*365/80)
        self.assertNotAlmostEqual(result['calendar_03_02']['value'],result['annual']['value']-100*(-60)/4100*365/120)

    def test_default_and_manual_windows_are_bounded(self):
        self.assertEqual([selection(window=w)['stats'] for w in (90,30,10)],[20,15,5])
        self.assertEqual(selection(window=10,stats=120)['stats'],120)
        for kwargs in (dict(root='AU'),dict(slot=4),dict(slot=True),dict(window=366),dict(window=9),dict(stats=121),dict(stats=1)):
            with self.assertRaises(ValueError):selection(**kwargs)

    def test_window_counts_natural_days_and_reads_statistics_before_plot(self):
        p=plan('2026-11-10',selection(window=90),metadata())
        self.assertEqual(p['start'],'2026-08-13')
        p=plan(DAY,selection(window=10,stats=60),metadata())
        self.assertLess(p['days'][0],p['start'])
        self.assertEqual(len(p['reference_days']),60)
        self.assertNotIn(DAY,p['reference_days'])

    def test_statistics_sample_sigma_equal_half_weight_and_current_excluded(self):
        days=['2026-10-20','2026-10-21','2026-10-22']
        rows=[point(d,value=v) for d,v in zip(days,(1.,2.,3.))]
        rows.append(point(DAY,value=1000.))
        result=statistics(rows,days,point(DAY,value=3.))
        self.assertEqual((result['mean'],result['median'],result['std'],result['z']),(2,2,1,1))
        self.assertAlmostEqual(result['percentile'],100*2.5/3)

    def test_unknown_gap_blocks_all_statistics_without_older_substitution(self):
        days=['2026-10-20','2026-10-21','2026-10-22']
        rows=[point('2026-10-19',value=99),point(days[0],value=1),point(days[2],value=3)]
        result=statistics(rows,days,point(DAY,value=2))
        self.assertFalse(result['complete']);self.assertEqual(result['samples'],2)
        self.assertEqual(result['missing'][0]['day'],days[1])
        for k in ('mean','median','z','percentile'):self.assertIsNone(result[k])

    def test_known_expiry_exclusion_does_not_replenish_window(self):
        rows=[point('2026-10-20',value=1),point('2026-10-21',excluded=True,reason='T_LT_5'),point('2026-10-22',value=3)]
        result=statistics(rows,[r['day'] for r in rows],point(DAY,value=2))
        self.assertTrue(result['complete']);self.assertEqual(result['samples'],2)
        self.assertEqual(result['excluded_dates'],['2026-10-21']);self.assertEqual(result['mean'],2)

    def test_zero_variance_and_missing_current_keep_reference_lines(self):
        rows=[point('2026-10-20',value=2),point('2026-10-21',value=2)]
        days=[r['day'] for r in rows]
        result=statistics(rows,days,point(DAY,value=2))
        self.assertEqual(result['percentile'],50);self.assertIsNone(result['z'])
        result=statistics(rows,days,point(DAY))
        self.assertEqual(result['mean'],2);self.assertEqual(result['median'],2)
        self.assertIsNone(result['percentile']);self.assertIsNone(result['z'])

    def test_daily_mapping_changes_and_display_keeps_gaps(self):
        planned,meta,tables,history=fixture()
        rows=history['raw'];before=next(r for r in rows if r['day']=='2026-10-16');after=next(r for r in rows if r['day']=='2026-10-19')
        self.assertEqual(before['symbols'],['IF2610.CFE']);self.assertEqual(after['symbols'],['IF2611.CFE'])
        day='2026-10-26';symbol=slot_map(meta,'IF',day)[0]['IF00.CFE'];tables[symbol].pop(day)
        history=historical(planned,meta,tables,ZERO_DIVIDENDS)
        result=display(planned,history,{k:history[k][-1] for k in SERIES})
        self.assertIsNone(next(r for r in result['series']['raw']['rows'] if r['day']==day)['value'])
        self.assertFalse(result['series']['raw']['statistics']['complete'])
        self.assertTrue(result['series']['calendar_03_02']['statistics']['complete'])

    def test_historical_missing_dividend_zero_is_derived_current_missing_is_not_zero(self):
        missing=SimpleNamespace(resolve=lambda s,d:None,version='missing')
        planned,meta,tables,history=fixture(book=missing)
        self.assertTrue(history['annual'][-1]['zero_dividend_symbols'])
        mapping=planned['mappings'][DAY]['mapping'];prices={s:r[DAY]['close'] for s,r in tables.items() if DAY in r}
        result=values(DAY,planned['selection'],mapping,meta,prices,missing,current=True)
        self.assertIsNone(result['annual']['value']);self.assertIsNotNone(result['raw']['value'])

    def test_real_dividend_conflict_blocks_adjusted_not_raw(self):
        conflict=SimpleNamespace(resolve=lambda s,d:dict(points=None,reason='conflict'))
        planned,meta,tables,history=fixture(book=conflict)
        self.assertIsNone(history['annual'][-1]['value']);self.assertIsNotNone(history['raw'][-1]['value'])
        self.assertFalse(history['annual'][-1]['zero_dividend_symbols'])

    def test_maintenance_is_selected_root_daily_only_and_does_not_change_old_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta=metadata();old=requests({},tmp,DAY,meta,reference_data={})
            request=selection(root='IM',window=120,stats=60)
            added=maintenance_rows(DAY,request,meta)
            self.assertTrue(all(r['symbol'].startswith('IM') or r['symbol']=='000852.SH' for r in added))
            self.assertTrue(all(r['day']<=DAY for r in added))
            expanded=requests({'_indicator_analysis_request':request},tmp,DAY,meta,reference_data={})
            self.assertLess(min(j['day'] for j in expanded),min(j['day'] for j in old))
            self.assertFalse(any(j.get('frequency')=='1m' for j in expanded))
            self.assertEqual(old,requests({},tmp,DAY,meta,reference_data={}))

    def test_company_summary_keeps_values_and_excludes_unlisted_records(self):
        result=preview();result['password']='do-not-export'
        result['series']['annual']['current']['inputs']['secret']='do-not-export'
        safe=summary(result)
        self.assertEqual(safe['series']['annual']['statistics'],result['series']['annual']['statistics'])
        self.assertNotIn('password',safe);self.assertNotIn('inputs',safe['series']['annual']['current'])
        self.assertEqual(summary(safe),safe)


class IndicatorReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.planned,self.meta,self.tables,self.history=fixture()
        self.model=SimpleNamespace(config={},local_root=Path(self.tmp.name))
        mapping=slot_map(self.meta,'IF',DAY)[0]
        self.model._overview_latest={s:observation(at=NOW,price=4000) for s in ['000300.SH',*mapping.values()]}
        self.repo=SimpleNamespace(read_window=Mock(side_effect=lambda s,*a,**k:pd.DataFrame(self.tables.get(s,{}).values())))
        self.engine=IndicatorAnalysisEngine(self.model)
        self.args=dict(now=NOW,completed='2026-10-26',metadata=self.meta,dividends=ZERO_DIVIDENDS,repo=self.repo,frozen={'one':{'version':'v1'}})

    def snapshot(self,**kwargs):
        return self.engine.snapshot(selection(),**dict(self.args,**kwargs))

    def test_same_history_versions_only_refresh_live_endpoint(self):
        first=self.snapshot();count=self.repo.read_window.call_count
        self.model._overview_latest['IF2611.CFE']['close']=4010
        second=self.snapshot()
        self.assertTrue(second['cache_hit']);self.assertEqual(count,self.repo.read_window.call_count)
        self.assertNotEqual(first['series']['raw']['current']['value'],second['series']['raw']['current']['value'])
        self.assertEqual(first['series']['raw']['statistics']['mean'],second['series']['raw']['statistics']['mean'])

    def test_price_publication_and_dividend_version_invalidate_cache(self):
        first=self.snapshot();calls=self.repo.read_window.call_count
        day='2026-10-26'
        row=dict(symbol='000300.SH',trade_date=day,is_final=True,close=4100,source_at=day+'T15:00:00+08:00',source='fixture')
        publish_day({},self.model.local_root,day,{'000300.SH':row})
        second=self.snapshot();self.assertNotEqual(first['version'],second['version']);self.assertGreater(self.repo.read_window.call_count,calls)
        changed=SimpleNamespace(points=lambda s,d:5.,version='new-D',info={},reason='')
        third=self.snapshot(dividends=changed)
        self.assertNotEqual(second['version'],third['version'])
        self.assertNotEqual(second['series']['annual']['statistics']['mean'],third['series']['annual']['statistics']['mean'])

    def test_stale_or_skewed_calendar_leg_does_not_use_history_to_fill_current(self):
        self.model._overview_latest['IF2706.CFE']=observation(at=NOW-pd.Timedelta(seconds=31))
        result=self.snapshot()
        self.assertIsNone(result['series']['calendar_03_02']['current']['value'])
        self.assertIsNotNone(result['series']['calendar_02_01']['current']['value'])
        self.assertIsNotNone(result['series']['calendar_03_02']['statistics']['mean'])
        self.assertIsNone(result['series']['calendar_03_02']['statistics']['percentile'])
        self.model._overview_latest['IF2706.CFE']=observation(at=NOW-pd.Timedelta(seconds=4))
        self.assertIsNone(self.snapshot()['series']['calendar_03_02']['current']['value'])

    def test_close_view_freezes_day_and_excludes_its_comparison_sample(self):
        result=self.snapshot(now=pd.Timestamp(DAY+'T08:00:00+08:00'))
        self.assertEqual(result['pricing_day'],'2026-10-26');self.assertEqual(result['mode'],'completed_daily')
        self.assertNotIn('2026-10-26',result['reference_days'])
        self.assertEqual(result['series']['raw']['current']['source_at'],'2026-10-26T15:00:00+08:00')

    def test_warm_start_count_extends_beyond_fixed_sixty(self):
        self.engine.snapshot(selection(window=10,stats=120),**self.args)
        self.assertGreater(self.repo.read_window.call_args.kwargs['count'],120)

    def test_history_read_error_isolated_to_affected_channel(self):
        original=self.repo.read_window.side_effect
        def read(s,*args,**kwargs):
            if s=='IF2611.CFE':raise OSError('fixture')
            return original(s,*args,**kwargs)
        self.repo.read_window.side_effect=read
        result=self.snapshot()
        self.assertTrue(result['errors']);self.assertFalse(result['series']['raw']['statistics']['complete'])
        self.assertTrue(result['series']['calendar_03_02']['statistics']['complete'])

    def test_reader_does_not_request_network_or_change_book(self):
        config=deepcopy(self.model.config)
        with patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            result=self.snapshot()
        self.assertFalse(result['network_requested']);self.assertEqual(self.model.config,config)

    def test_main_snapshot_adds_page_only_when_selected_and_keeps_fixed_percentiles(self):
        from dashboard.native.market_overview import MarketOverviewEngine
        contracts=[dict(instrument_id=s,known_at='2020-01-01T00:00:00+08:00',**r) for s,r in self.meta.items()]
        ref=SimpleNamespace(data={'contracts':contracts},version='fixture')
        self.repo.freeze=Mock(return_value={'one':{'version':'v1'}});self.repo.symbols=Mock(return_value={})
        source=self.repo.read_window.side_effect
        def read(s,*args,**kwargs):
            frame=source(s,*args,**kwargs)
            return frame[frame.event_time.le(kwargs['as_of'])] if not frame.empty else frame
        self.repo.read_window.side_effect=read
        self.model.configure_repository=lambda demo:self.repo
        self.model._live=lambda *args:self.model._overview_latest
        self.model.live_rows=pd.DataFrame()
        engine=MarketOverviewEngine(self.model)
        with patch('dashboard.native.market_overview.ReferenceBook',return_value=ref),patch('dashboard.native.market_overview.load_dividends',return_value=ZERO_DIVIDENDS):
            first=engine.snapshot(now=NOW)
            self.assertNotIn('indicator_analysis',first);self.assertFalse(hasattr(engine,'indicator_analysis'))
            self.model.indicator_analysis_request=selection()
            second=engine.snapshot(now=NOW)
        self.assertIn('series',second['indicator_analysis'])
        for old,new in zip(first['market_overview']['futures'],second['market_overview']['futures']):
            self.assertEqual((old['percentile_20'],old['percentile_60']),(new['percentile_20'],new['percentile_60']))

    def test_expanded_local_seed_reads_original_window_without_ddb(self):
        request=selection(window=365,stats=120)
        config={'_indicator_analysis_request':request}
        repo=SimpleNamespace(read_window=Mock(return_value=pd.DataFrame()))
        with patch('dashboard.marketdata.overview_daily.requests',return_value=[dict(day='2026-02-02',asset='index',symbols=['000300.SH'])]):
            seed_local(repo,{},config,self.model.local_root,DAY,self.meta)
        self.assertGreater(repo.read_window.call_args.kwargs['count'],65)

    def test_selected_window_is_passed_to_owned_history_worker_without_saving_native_config(self):
        from dashboard.native.history_maintenance import HistoryMaintenance
        from dashboard.marketdata.history_maintenance import _run_cycle
        request=selection(root='IC',slot=2,window=180,stats=60)
        self.model.config={'history_roots':['fixture-root']}
        self.model.indicator_history_request=request
        owner=HistoryMaintenance(self.model);owner.authorized=True
        with patch('dashboard.app_config.history_python',return_value=sys.executable),patch('subprocess.Popen') as spawn:
            self.assertTrue(owner.start(force=True))
            cmd=spawn.call_args.args[0]
            self.assertEqual(cmd[cmd.index('--indicator-root')+1],'IC')
            self.assertEqual(cmd[cmd.index('--indicator-window')+1],'180')
            self.assertIn('--overview-only',cmd)
        native=self.model.local_root/'native.json'
        raw=json.dumps(self.model.config).encode();native.write_bytes(raw)
        with patch('dashboard.marketdata.history_maintenance._run_overview_cycle',return_value={'state':'complete'}) as cycle:
            _run_cycle(self.model.local_root,overview_only=True,indicator_request=request)
            self.assertEqual(cycle.call_args.args[1]['_indicator_analysis_request'],request)
        self.assertEqual(native.read_bytes(),raw)


if __name__=='__main__':unittest.main()
