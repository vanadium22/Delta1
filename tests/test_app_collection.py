import json
from datetime import datetime,timezone
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.native.collection import CollectionJob
from dashboard.marketdata.bars import _writer_lock
from dashboard.marketdata.history_publication import maintenance_root
from index_strategy.instant_dld.collector import collect as real_collect
from index_strategy.instant_dld.reader import RealtimeReader


class FakeClient:
    url='https://fixture.invalid';verify=True;timeout=(.1,.1)
    def __init__(self,**kwargs):self.session=SimpleNamespace(trust_env=False);self.n=0;self.closed=False
    def fetch(self,symbols):
        from tests.test_realtime_store import quote
        self.n+=1;time.sleep(.05)
        return dict(status='timeout' if self.n==2 else 'success',elapsed_seconds=.05,
            received_at=f'2026-10-23T10:00:0{self.n}+08:00',symbols=symbols,
            response=dict(data={} if self.n==2 else {s:{**quote(100+self.n,4000,100000+self.n),'securityId':s} for s in symbols}))
    def close(self):self.closed=True


class AppCollectionTests(unittest.TestCase):
    def test_old_twenty_code_feed_can_update_indices_while_new_etfs_are_blocked(self):
        from dashboard.native.collection import RollingResolver
        from dashboard.native.model import NativeModel
        from dashboard.native.market_overview import MarketOverviewEngine
        from dashboard.native.overview_instruments import quote_registry
        from dashboard.session_guard import network_lease,probe_realtime
        from index_strategy.instant_dld.realtime_store import RealtimeStore
        from tests.test_realtime_store import quote
        import pandas as pd
        now=pd.Timestamp('2026-10-26T10:00:05+08:00')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);profile=root/'profile';reference=root/'reference.json'
            contracts=[dict(instrument_id=f'{r}{m}.CFE',listing_date='2026-01-01',expiry_date=e,known_at='2026-01-01T00:00:00Z')
                for r in ('IF','IH','IC','IM') for m,e in (('2611','2026-11-20'),('2612','2026-12-18'),('2703','2027-03-19'),('2706','2027-06-18'))]
            reference.write_text(json.dumps(dict(schema_version='cn_index_reference_v1',contracts=contracts,aliases=[])))
            indexes={'000300.SH','000016.SH','000905.SH','000852.SH'}
            config=dict(history_roots=[str(root/'history')],reference_file=str(reference),realtime_root=str(root/'quotes'),realtime_id='fixture')
            model=NativeModel(profile);model.config.update(config);engine=MarketOverviewEngine(model)
            class Client:
                url='https://fixture.invalid';verify=True;timeout=(.1,.1)
                def __init__(self,**kwargs):self.session=SimpleNamespace(trust_env=False)
                def fetch(self,symbols):
                    return dict(status='success',elapsed_seconds=0,received_at=now.isoformat(),symbols=symbols,
                        response=dict(data={s:{**quote(1000,4 if s in quote_registry({}) else 4000,100005),
                            'securityId':s,'yesterdayClosePrice':4 if s in quote_registry({}) else 3980} for s in symbols}))
                def close(self):pass
            old_symbols=[r['instrument_id'] for r in contracts]+sorted(indexes)
            old=Client().fetch(old_symbols);old.update(poll=1,batch=1,batch_count=1)
            with RealtimeStore(root/'quotes') as store:store.batch(old)
            gate=patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True,reason='fixture'))
            with gate:
                with network_lease(config):
                    state=engine.snapshot(now=now)['market_overview']
                    self.assertEqual(sum(r['quality']['usable'] for r in state['indices']),4)
                    self.assertTrue(all(r['price'] is None for r in state['etfs']))
                    factory=Mock();result=probe_realtime(config,factory)
                    factory.assert_not_called();self.assertEqual(result['error']['stage'],'network_lock')
                resolver=RollingResolver(indexes|set(quote_registry({})),reference,root/'reference-cache',
                    now=lambda:now.to_pydatetime(),synchronizer=lambda *a,**k:dict(reference_file=str(reference),active_contracts=[r['instrument_id'] for r in contracts]))
                def bounded(*args,**kwargs):kwargs.update(interval=.01,max_polls=1);return real_collect(*args,**kwargs)
                with patch('dashboard.native.collection.RollingResolver',return_value=resolver),patch('dashboard.native.collection.collect',side_effect=bounded):
                    job=CollectionJob(profile);job.start(root/'quotes',sorted(indexes),indexes,auto_roll=True,config=config,client_factory=Client)
                    job.worker.join(5)
            self.assertFalse(job.running())
            state=engine.snapshot(now=now)['market_overview']
            self.assertEqual(sum(r['price'] is not None for r in state['etfs']),4)
            self.assertEqual(sum(r['quality']['usable'] for r in state['etfs']),4)
            model.close()

    def test_rolling_collector_subscribes_etfs_and_preserves_partial_market_data(self):
        from dashboard.marketdata.adapters import read_realtime_observations
        from dashboard.native.overview_instruments import quote_registry
        from dashboard.native.collection import RollingResolver
        with tempfile.TemporaryDirectory() as t:
            local=Path(t);reference=local/'reference.json'
            contracts=[dict(instrument_id=f'{r}{m}.CFE',listing_date='2026-01-01',expiry_date=e,
                            known_at='2026-01-01T00:00:00Z')
                       for r in ('IF','IH','IC','IM')
                       for m,e in (('2611','2026-11-20'),('2612','2026-12-18'),('2703','2027-03-19'),('2706','2027-06-18'))]
            reference.write_text(json.dumps(dict(schema_version='cn_index_reference_v1',contracts=contracts,aliases=[])))
            config=dict(history_roots=[str(local/'history')]);client=FakeClient()
            resolver=RollingResolver({'000300.SH'}|set(quote_registry({})),reference,local/'reference-cache',
                now=lambda:datetime(2026,10,26,2,tzinfo=timezone.utc),
                synchronizer=lambda *a,**k:dict(reference_file=str(reference),active_contracts=[r['instrument_id'] for r in contracts]))
            def bounded(*args,**kwargs):
                kwargs.update(interval=.01,max_polls=1);return real_collect(*args,**kwargs)
            with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True,reason='fixture')),\
                 patch('dashboard.native.collection.RollingResolver',return_value=resolver) as resolver_factory,\
                 patch('dashboard.native.collection.collect',side_effect=bounded):
                job=CollectionJob(local);job.start(local/'quotes', ['000300.SH'],{'000300.SH'},
                    auto_roll=True,config=config,client_factory=lambda **kw:client)
                job.worker.join(8)
            self.assertFalse(job.running());self.assertEqual(job.state()['polls'],1)
            self.assertTrue(set(quote_registry({})).issubset(resolver_factory.call_args.args[0]))
            rows,_=read_realtime_observations(local/'quotes',dataset_id='fixture',instruments=quote_registry({}))
            self.assertEqual(set(rows.instrument_id),set(quote_registry({})))
            self.assertTrue(client.closed)

    def test_slow_request_reconnect_commits_versions_and_reports_each_stage(self):
        with tempfile.TemporaryDirectory() as t:
            local=Path(t);config=dict(history_roots=[str(local/'history')]);client=FakeClient()
            (local/'native.json').write_text(json.dumps(config))
            def bounded(*args,**kwargs):
                kwargs.update(interval=.01,max_polls=3);return real_collect(*args,**kwargs)
            with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True,reason='fixture')),\
                 patch('dashboard.native.collection.collect',side_effect=bounded):
                job=CollectionJob(local);job.start(local/'quotes',['000300.SH'],{'000300.SH'},client_factory=lambda **kw:client)
                job.worker.join(8)
            self.assertFalse(job.running());self.assertTrue(client.closed)
            state=job.state();self.assertEqual(state['polls'],3);self.assertEqual(state['data_sequence'],2)
            self.assertEqual(state['last_failure_status'],'timeout');self.assertEqual(state['valid_rows'],1)
            self.assertGreaterEqual(state['request_seconds'],.045);self.assertIn('storage_finished_at',state)
            with RealtimeReader(local/'quotes').connect() as con:
                self.assertEqual(con.execute('SELECT MAX(sequence) FROM quotes').fetchone()[0],state['data_sequence'])
            with _writer_lock(maintenance_root(config['history_roots'])/'network_session'):pass

    def test_second_instance_cannot_collect_while_network_lease_is_owned(self):
        with tempfile.TemporaryDirectory() as t:
            local=Path(t);config=dict(history_roots=[str(local/'history')]);factory=Mock()
            (local/'native.json').write_text(json.dumps(config))
            with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True)),\
                 _writer_lock(maintenance_root(config['history_roots'])/'network_session'):
                job=CollectionJob(local);job.start(local/'quotes',['000300.SH'],{'000300.SH'},client_factory=factory)
                job.worker.join(3)
            factory.assert_not_called();self.assertEqual(job.state()['status'],'failed')
            self.assertEqual(job.state()['diagnostics']['stage'],'network_lock')

    def test_startup_preview_rejects_other_profile_and_retains_source_time(self):
        from dashboard import app_preview
        from dashboard.numeric_evidence import cache_scope
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);config=dict(history_roots=[str(root/'one')]);scope=cache_scope(config)
            path=root/scope/'latest.json';path.parent.mkdir()
            payload=dict(cache_scope=scope,snapshots=[dict(as_of='2026-10-23T01:00Z',selection=dict(overview_slot=0),
                overview=[dict(quote={'source_event_time':'2026-10-22T07:00Z'},chart={},quality={})])])
            path.write_text(json.dumps(payload))
            with patch.object(app_preview,'ROOT',root):
                state=app_preview.load(config)
                self.assertEqual(state['overview'][0]['quote']['source_event_time'],'2026-10-22T07:00Z')
                self.assertFalse(state['overview'][0]['quality']['usable'])
                self.assertIsNone(app_preview.load(dict(history_roots=[str(root/'two')])))


if __name__=='__main__':unittest.main()
