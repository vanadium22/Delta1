"""Reference integrity, dated attribution and paired IOPV; all sources are stubs."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from dashboard.marketdata.overview_reference import validate, load, publish, ranking
from dashboard.marketdata.overview_contributions import contributions
from dashboard.native.overview_details import premium_pairs, enrich
from dashboard.native.overview_reference_job import ReferenceJob
from dashboard.native.equity_collection import EquitySampler
from dashboard.native.overview_instruments import etfs
from tests.test_market_overview import NOW, observation
from tests.test_realtime_store import quote


def reference():
    return dict(schema='overview-reference-v1', fetched_at='2026-10-26T09:00:00+08:00',
        indices={'IF':dict(index_id='000300.SH',as_of='2026-10-23',source='fixture',industry_standard='申万一级',
            rows=[dict(symbol='600001.SH',name='测试成分甲',weight_pct=50,industry='电子'),
                  dict(symbol='600002.SH',name='测试成分乙',weight_pct=30,industry='银行'),
                  dict(symbol='600003.SH',name='测试成分丙',weight_pct=20,industry='煤炭')])},
        etfs={'IF':dict(index_id='000300.SH',as_of='2026-10-23',source='fixture',complete=True,
            rows=[dict(symbol=s,name='测试ETF '+str(i),index_id='000300.SH',ordinary_etf=True,
                       aum_date='2026-10-23',aum_cny=a) for i,(s,a) in enumerate(
                [('510301.SH',500e8),('510302.SH',300e8),('510303.SH',100e8),('510304.SH',100e8)])])})


def equity_snapshot():
    return dict(schema='overview-equities-v1',snapshot_id='cycle1',reference_version='v1',finished_at=NOW.isoformat(),
        quotes={'600001.SH':observation(110,100), '600002.SH':observation(95,100),
                '600003.SH':observation(100,100),'000300.SH':observation(104,100)})


class ReferenceTests(unittest.TestCase):
    def test_top_three_use_whole_same_benchmark_universe_and_stable_ties(self):
        ranked, meta = ranking(validate(reference()), 'IF', today='2026-10-26')
        self.assertEqual([r['symbol'] for r in ranked],['510301.SH','510302.SH','510303.SH'])
        self.assertEqual([r['aum_share_pct'] for r in ranked],[50,30,10])
        self.assertEqual(meta['universe_count'],4)
        selected=etfs({},reference(),'2026-10-26')
        self.assertEqual({r['symbol'] for r in selected if r['root']=='IF'},set(r['symbol'] for r in ranked))
        value=reference();value['etfs']['IF']['complete']=False
        self.assertEqual(ranking(value,'IF',today='2026-10-26')[0],[])

    def test_invalid_publish_retains_prior_bytes_and_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'latest.json';publish(path,reference());before=path.read_bytes()
            for mutate in (lambda d:d['etfs']['IF']['rows'][0].update(aum_date='2026-10-22'),
                           lambda d:d['etfs']['IF']['rows'][0].update(ordinary_etf=False),
                           lambda d:d['indices']['IF']['rows'][0].update(weight_pct=.5),
                           lambda d:d['etfs']['IF']['rows'].append(d['etfs']['IF']['rows'][0])):
                bad=reference();mutate(bad)
                with self.assertRaises(ValueError):publish(path,bad)
                self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(list((path.parent/'archive').glob('*.json'))),1)

    def test_weekly_review_uses_china_week_and_rejects_future_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'latest.json';value=reference();value['fetched_at']='2026-10-23T12:00:00+08:00';publish(path,value)
            result=load(dict(overview_reference_file=str(path)),tmp,now=datetime.fromisoformat('2026-10-25T16:01:00+00:00'))
            self.assertTrue(result['due'])
            self.assertEqual(result['data']['etfs']['IF']['as_of'],'2026-10-23')
            self.assertIsNone(load(dict(overview_reference_file=str(path)),tmp,now=NOW.to_pydatetime())['error'])
            self.assertEqual(load(dict(overview_reference_file=str(path)),tmp,now=datetime.fromisoformat('2026-10-22T10:00:00+08:00'))['data'],{})

    def test_readonly_worker_does_not_spawn_and_failure_is_not_retried_same_week(self):
        with tempfile.TemporaryDirectory() as tmp,patch('subprocess.Popen',side_effect=OSError('fixture')) as spawn:
            job=ReferenceJob(tmp)
            job.tick({},enabled=False,now=NOW.to_pydatetime());spawn.assert_not_called()
            job.tick({},enabled=True,now=NOW.to_pydatetime());self.assertEqual(spawn.call_count,1)
            job.tick({},enabled=True,now=NOW.to_pydatetime());self.assertEqual(spawn.call_count,1)
            self.assertEqual(json.loads((Path(tmp)/'overview_reference/status.json').read_text())['status'],'unavailable')


class ContributionTests(unittest.TestCase):
    def calculate(self,snapshot=None,group=None,now=NOW):
        return contributions(group or reference()['indices']['IF'],snapshot or equity_snapshot(),
            dict(symbol='000300.SH',prev_close=999),now,'2026-10-23','v1')

    def test_weighted_returns_points_zero_and_residual_have_distinct_units(self):
        result=self.calculate()
        self.assertEqual(result['coverage_pct'],100)
        self.assertEqual((result['up'],result['down'],result['flat']),(1,1,1))
        self.assertAlmostEqual(result['contribution_points'],3.5)
        self.assertAlmostEqual(result['actual_points'],4)
        self.assertAlmostEqual(result['residual_points'],.5)
        self.assertEqual(result['leaders'][0]['name'],'电子')
        self.assertEqual(result['laggards'][0]['name'],'银行')
        self.assertEqual(result['rows'][2]['contribution_points'],0)
        self.assertEqual(result['source_at'],NOW.isoformat())

    def test_missing_and_late_quotes_reduce_coverage_without_renormalisation(self):
        snapshot=equity_snapshot();snapshot['quotes']['600002.SH']['source_event_time']=(NOW-pd.Timedelta(seconds=31)).isoformat()
        result=self.calculate(snapshot)
        self.assertEqual(result['coverage_pct'],70)
        self.assertEqual(result['covered'],2)
        self.assertEqual(result['laggards'],[])
        self.assertIsNone(next(r for r in result['industries'] if r['name']=='银行')['change_pct'])
        self.assertAlmostEqual(result['contribution_points'],5)

    def test_old_weights_keep_structure_and_stock_returns_but_not_fake_yesterday_points(self):
        group=reference()['indices']['IF'];group['as_of']='2026-10-22'
        result=self.calculate(group=group)
        self.assertEqual(result['coverage_pct'],100)
        self.assertIsNotNone(result['rows'][0]['change_pct'])
        self.assertIsNone(result['contribution_points']);self.assertEqual(result['leaders'],[])
        self.assertIn('不是准确上一交易日',result['reason'])

    def test_wrong_membership_future_and_prior_day_snapshots_are_not_current(self):
        for mutate in (lambda s:s.update(reference_version='v0'),
                       lambda s:s.update(finished_at=(NOW+pd.Timedelta(seconds=1)).isoformat()),
                       lambda s:s.update(finished_at='2026-10-23T10:00:05+08:00')):
            snapshot=equity_snapshot();mutate(snapshot);result=self.calculate(snapshot)
            self.assertEqual(result['covered'],0);self.assertIsNone(result['contribution_points'])


class PremiumTests(unittest.TestCase):
    def test_pair_uses_same_time_etf_price_not_the_later_headline(self):
        at=NOW-pd.Timedelta(seconds=6)
        rows=[dict(observation(4.01,4,at),instrument_id='510300.SH'),
              dict(observation(4,4,at),instrument_id='IOPV.510300'),
              dict(observation(4.09,4,NOW),instrument_id='510300.SH')]
        frame=pd.DataFrame(rows);frame['observed_at']=pd.to_datetime(frame.observed_at,utc=True)
        current,series=premium_pairs('510300.SH','IOPV.510300',frame,NOW)
        self.assertAlmostEqual(current['value'],25)
        self.assertEqual(pd.Timestamp(current['source_at']),at)
        self.assertEqual(len(series),1)
        current,_=premium_pairs('510300.SH','IOPV.510300',frame,NOW+pd.Timedelta(seconds=31))
        self.assertIsNone(current)

    def test_no_mapping_or_no_synchronised_leg_does_not_invent_premium(self):
        frame=pd.DataFrame([dict(observation(4,4),instrument_id='510300.SH')])
        frame['observed_at']=pd.to_datetime(frame.observed_at,utc=True)
        self.assertEqual(premium_pairs('510300.SH',None,frame,NOW),(None,[]))
        self.assertEqual(premium_pairs('510300.SH','IOPV.510300',frame,NOW),(None,[]))


class EquitySamplerTests(unittest.TestCase):
    def test_slow_equity_request_does_not_block_headlines_and_drains_before_unlock(self):
        from dashboard.native.collection import CollectionJob
        from dashboard.session_guard import network_lease
        from index_strategy.instant_dld.collector import collect as real_collect
        from index_strategy.instant_dld.reader import RealtimeReader
        entered=threading.Event();headlines_advanced=threading.Event();clients=[]
        class Client:
            url='https://fixture.invalid';verify=True;timeout=(.1,.1)
            def __init__(self,**kwargs):
                self.session=SimpleNamespace(trust_env=False);self.main=not clients;self.n=0;self.closed=False;clients.append(self)
            def fetch(self,symbols):
                if self.main:
                    entered.wait(2);self.n+=1
                    if self.n>=3:headlines_advanced.set()
                else:
                    entered.set()
                    if not headlines_advanced.wait(3):raise AssertionError('Headline collector was blocked')
                    time.sleep(.08)
                return dict(status='success',received_at=NOW.isoformat(),response=dict(data={s:{**quote(10,100,100005),'securityId':s} for s in symbols}))
            def close(self):self.closed=True
        class Resolver:
            index_ids=set();status={}
            def resolve_many(self,symbols):
                return {s:dict(source_symbol=(s[:2]+('2611','2612','2703','2706')[int(s[3])]+'.CFE') if s.endswith('.CFE') else s,mapping_date=None,trading_date=None) for s in symbols},{}
        def bounded(*a,**kw):
            kw.update(max_polls=4,interval=.02);return real_collect(*a,**kw)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);publish(root/'profile/overview_reference/latest.json',reference())
            config=dict(history_roots=[str(root/'history')])
            with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True)),\
                 patch('dashboard.native.collection.RollingResolver',return_value=Resolver()),\
                 patch('dashboard.native.collection.collect',side_effect=bounded):
                job=CollectionJob(root/'profile');job.start(root/'headlines',['000300.SH'],{'000300.SH'},auto_roll=True,config=config,client_factory=Client)
                job.worker.join(8)
            self.assertFalse(job.running());self.assertTrue(headlines_advanced.is_set())
            self.assertTrue(all(c.closed for c in clients));self.assertEqual(job.state()['polls'],4)
            with network_lease(config):pass
            with RealtimeReader(root/'headlines').connect() as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM quotes WHERE symbol LIKE '600%' ").fetchone()[0],0)
            self.assertTrue((root/'profile/overview_equities/observations/live/quotes.sqlite3').is_file())

    def test_separate_bounded_batches_preserve_raw_quotes_and_publish_one_cycle(self):
        from index_strategy.instant_dld.realtime_store import RealtimeStore
        value=reference();value['indices']['IF']['rows']=[dict(symbol=f'{600000+i:06}.SH',weight_pct=100/205) for i in range(205)]
        requested=[]
        class Client:
            def fetch(self,symbols):
                requested.append(symbols)
                return dict(status='success',received_at=NOW.isoformat(),response=dict(data={s:{**quote(10,100,100005),'securityId':s} for s in symbols}))
        with tempfile.TemporaryDirectory() as tmp:
            sampler=EquitySampler(tmp,{},lambda:dict(allowed=True),Mock())
            with RealtimeStore(Path(tmp)/'separate-observations') as store:
                sampler.cycle(Client(),store,dict(data=value,version='v1'),1)
            result=json.loads((Path(tmp)/'overview_equities/latest.json').read_text())
            self.assertEqual([len(s) for s in requested],[100,100,6])
            self.assertEqual(result['reference_version'],'v1');self.assertEqual(len(result['quotes']),206)
            self.assertEqual(result['quotes']['600000.SH']['source_event_time'],NOW.replace(microsecond=0).isoformat())
            self.assertTrue(list((Path(tmp)/'separate-observations').rglob('*.json')))

    def test_cancelled_cycle_keeps_prior_snapshot_and_does_not_start_next_batch(self):
        from index_strategy.instant_dld.realtime_store import RealtimeStore
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'overview_equities/latest.json';path.parent.mkdir();path.write_bytes(b'prior-cycle')
            sampler=EquitySampler(tmp,{},lambda:dict(allowed=True),Mock())
            class Client:
                def fetch(self,symbols):
                    sampler.stop()
                    return dict(status='success',received_at=NOW.isoformat(),response=dict(data={s:{**quote(10,100,100005),'securityId':s} for s in symbols}))
            with RealtimeStore(Path(tmp)/'separate-observations') as store:
                self.assertIsNone(sampler.cycle(Client(),store,dict(data=reference(),version='v1'),1))
            self.assertEqual(path.read_bytes(),b'prior-cycle')


class WindReferenceTests(unittest.TestCase):
    def test_failed_industry_query_does_not_discard_valid_weights_or_refetch_known_mapping(self):
        from dashboard.marketdata.overview_wind import refresh
        old=reference();old['industries']={'600001.SH':dict(industry='电子',as_of='2026-10-23')}
        source=Mock();source.weights.side_effect=[deepcopy(old['indices']['IF']),ValueError('missing'),ValueError('missing'),ValueError('missing')]
        source.funds.side_effect=ValueError('units not verified')
        source.classify.side_effect=RuntimeError('fixture unavailable');source.names.side_effect=RuntimeError('fixture unavailable')
        db=Mock();diagnostics={};source.columns={};source.comments={}
        with patch('dashboard.marketdata.overview_wind.WindReferences',return_value=source):
            value=refresh({},'unused',old,now=NOW.to_pydatetime(),connector=lambda *a:db,diagnostics=diagnostics)
        self.assertEqual(value['etfs'],old['etfs'])
        self.assertEqual(value['indices']['IF']['rows'][0]['industry'],'电子')
        self.assertNotIn('600001.SH',source.classify.call_args.args[0])
        self.assertTrue(any('行业资料待核验' in error for error in value['errors']))
        db.close.assert_called_once()

    def source(self, multiplier=None):
        from dashboard.marketdata.overview_wind import WindReferences
        source=object.__new__(WindReferences);source.config={} if multiplier is None else {'overview_wind_aum_multiplier':multiplier}
        source.columns={'CHINAMUTUALFUNDTRACKINGINDEX':{'S_INFO_WINDCODE','S_INFO_INDEXWINDCODE','ENTRY_DT','REMOVE_DT'},
            'CHINAETFINVESTCLASS':{'S_INFO_WINDCODE','S_INFO_NAME'},
            'CHINAMUTUALFUNDNAV':{'S_INFO_WINDCODE','PRICE_DATE','F_NAV_TOTAL'}}
        source.comments={}
        source.read=Mock(side_effect=[
            [dict(S_INFO_WINDCODE=s,S_INFO_NAME=n) for s,n in [('510301.SH','测试ETF甲'),('510302.SH','测试ETF乙'),('510303.SH','测试ETF丙'),('000001.OF','测试联接'),('510305.SH','测试增强ETF')]],
            [dict(PRICE_DATE='20261023')],
            [dict(S_INFO_WINDCODE=s,AUM_VALUE=a) for s,a in [('510301.SH',50),('510302.SH',30),('510303.SH',20)]]])
        return source

    def test_wind_asset_units_are_confirmed_before_size_query(self):
        source=self.source()
        with self.assertRaisesRegex(ValueError,'单位待核验'):source.funds('IF','20261023')
        self.assertEqual(source.read.call_count,1)
        source=self.source(10000);group=source.funds('IF','20261023')
        self.assertEqual([r['aum_cny'] for r in group['rows']],[500000,300000,200000])
        self.assertTrue(group['complete']);self.assertEqual(group['as_of'],'2026-10-23')
        args=source.read.call_args_list[1]
        self.assertIn('HAVING COUNT(DISTINCT S_INFO_WINDCODE)=:n',args.args[0])
        self.assertEqual(args.args[1]['n'],3)


class CompanyEvidenceTests(unittest.TestCase):
    def test_report_does_not_connect_or_export_credentials_and_checks_existing_iopv_fields(self):
        from dashboard.overview_check import collect
        from index_strategy.instant_dld.realtime_store import RealtimeStore
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profile';profile.mkdir();quotes=root/'quotes'
            config=dict(realtime_root=str(quotes),password='CANARY_SECRET',history_roots=[])
            path=profile/'native.json';path.write_text(json.dumps(config))
            with RealtimeStore(quotes) as store:
                row={**quote(100,4,100005),'securityId':'510300.SH','iopvCandidate':4,'secret':'CANARY_RAW'}
                store.batch(dict(poll=1,batch=1,batch_count=1,symbols=['510300.SH'],status='success',received_at=NOW.isoformat(),response=dict(data={'510300.SH':row})))
            before=path.read_bytes()
            with patch('requests.sessions.Session.request',side_effect=AssertionError('No HTTP')):
                result=collect(profile,samples=1,interval=0)
            raw=json.dumps(result,ensure_ascii=False)
            self.assertNotIn('CANARY_SECRET',raw);self.assertNotIn('CANARY_RAW',raw)
            self.assertFalse(result['network_requested']);self.assertFalse(result['wind_requested']);self.assertFalse(result['vpn_changed'])
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(result['samples'][0]['iopv_source_fields']['iopv_candidate_fields']['510300.SH'],['iopvCandidate'])


if __name__=='__main__':unittest.main()
