from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

import pandas as pd
import pyarrow.parquet as pq

from dashboard.formulas import definition, evaluate
from dashboard.formula_worker import validate
from dashboard.results import ResultStore
from dashboard.server import DashboardServer
from dashboard.service import DashboardService
from dashboard.templates import TEMPLATES
from index_strategy.instant_dld.contract_aliases import DualIdentityStore, ExpiryAliasResolver, index_months
from index_strategy.instant_dld.contracts import ContractMappingError
from index_strategy.instant_dld.quotes import CHINA
from index_strategy.instant_dld.reader import RealtimeReader


def quote(symbol, value, stamp=100000):
    return {"securityId": symbol, "latestPrice": value, "tradedQuantities": 100,
            "quoteTimestamp": stamp, "b1Price": value-1, "s1Price": value+1, "b1Stocks": 4, "s1Stocks": 2}


class FormulaTests(unittest.TestCase):
    def test_sequence_expansion_cannot_allocate_unbounded_memory(self):
        spec=definition({**TEMPLATES[2],"code":'def compute(quotes, history, params):\n    x = [1] * 1000000000000\n    return {"x": len(x)}\n'})
        with self.assertRaisesRegex(ValueError,"列表扩增"):
            evaluate(spec,{"510300.SH":{}},{})

    def test_calculation_is_side_aware_and_missing_input_is_explicit(self):
        spec=definition(TEMPLATES[0])
        quotes={"IC00.CFE":{"mid":100,"bid_price_1":99,"ask_price_1":101},"IC01.CFE":{"mid":98,"bid_price_1":97,"ask_price_1":99}}
        self.assertEqual(evaluate(spec,quotes,{}),{"中间价差":2,"买入价差":4,"卖出价差":0})
        with self.assertRaisesRegex(ValueError,"缺少输入"):
            evaluate(spec,{},{})

    def test_import_attribute_file_access_recursion_loops_rejected(self):
        for body in ('import os\n    return {"x": 1}', 'return {"x": quotes.__class__}', 'return {"x": open("a")}',
                     'return compute(quotes, history, params)', 'while True:\n        pass',
                     'quotes["x"] = 1\n    return {"x": 1}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate('def compute(quotes, history, params):\n    '+body+'\n')

    def test_history_warmup_and_parameter_version(self):
        spec=definition(TEMPLATES[3])
        self.assertEqual(evaluate(spec,{"AU.SHF":{"close":100}},{"AU.SHF":[]}),{"均值偏离":None})
        changed=definition({**spec,"params":{"symbol":"AU.SHF","window":2}})
        self.assertNotEqual(spec["version"],changed["version"])
        self.assertAlmostEqual(evaluate(changed,{"AU.SHF":{"close":110}},{"AU.SHF":[{"close":90},{"close":110}]})["均值偏离"],1000)

    def test_worker_timeout_is_bounded(self):
        import subprocess
        with patch("dashboard.formulas.subprocess.run",side_effect=subprocess.TimeoutExpired("worker",3)):
            with self.assertRaisesRegex(ValueError,"已终止"):
                evaluate(definition(TEMPLATES[2]),{"510300.SH":{}},{})

    def test_nan_parameters_and_invalid_outputs_rejected(self):
        with self.assertRaises(ValueError):
            definition({**TEMPLATES[0],"params":{"x":float('nan')}})
        spec=definition({**TEMPLATES[2],"code":'def compute(quotes, history, params):\n    return {"x": "text"}\n'})
        with self.assertRaisesRegex(ValueError,"有限数字"):
            evaluate(spec,{"510300.SH":{}},{})


class AliasTests(unittest.TestCase):
    def test_expiry_roll_holiday_and_year_boundary(self):
        cal=[x.date() for x in pd.bdate_range('2026-09-01','2027-02-01')]
        self.assertEqual(index_months(date(2026,9,18),cal),['2609','2610','2612','2703'])
        self.assertEqual(index_months(date(2026,9,21),cal),['2610','2611','2612','2703'])
        cal.remove(date(2026,9,18))
        self.assertEqual(index_months(date(2026,9,21),cal),['2609','2610','2612','2703'])
        self.assertEqual(index_months(date(2026,9,22),cal),['2610','2611','2612','2703'])
        self.assertEqual(index_months(date(2026,12,21),cal),['2701','2702','2703','2706'])

    def test_fanout_single_request_does_not_duplicate_actual_row(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            with DualIdentityStore(path) as store:
                actual='IC2610.CFE'
                record={'symbols':['IC00.CFE',actual], 'status':'success','received_at':'2026-09-29T10:00:00+08:00',
                        'response':{'data':{'IC00.CFE':quote(actual,100),actual:quote(actual,100)}},
                        'symbol_mapping':{'IC00.CFE':{'source_symbol':actual,'mapping_date':None,'trading_date':'2026-09-29'},
                                          actual:{'source_symbol':actual,'mapping_date':None,'trading_date':'2026-09-29'}},
                        'poll':1,'batch':1,'batch_count':1}
                store.batch(record)
            frame=RealtimeReader(path).latest()
            self.assertEqual(len(frame),2)
            self.assertEqual(set(frame.source_symbol),{actual})
            self.assertEqual(len(RealtimeReader(path).read_parquet_day(actual,'2026-09-29')),1)

    def test_ambiguous_commodity_alias_fails_explicitly(self):
        with self.assertRaisesRegex(ContractMappingError,'尚未配置'):
            ExpiryAliasResolver().resolve('AU01.SHF')


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.local=self.root/'local'
        self.local.mkdir()
        now=datetime.now(CHINA)
        calendar=[x.date() for x in pd.bdate_range(now.date()-timedelta(days=35),now.date()+timedelta(days=75))]
        pd.DataFrame({'Date':calendar}).to_pickle(self.root/'calendar.pkl')
        pd.DataFrame({'AU.SHF':['AU2612.SHF']*len(calendar)},index=calendar).to_pickle(self.root/'mapping.pkl')
        self.config={'market_root':str(self.root/'market'),'results_root':str(self.root/'results'),
                     'mapping_file':str(self.root/'mapping.pkl'),'calendar_file':str(self.root/'calendar.pkl'),
                     'symbols':['IC00.CFE','IC01.CFE'],'interval':2,'max_age_seconds':20,'max_skew_seconds':3}
        (self.local/'dashboard.json').write_text(json.dumps(self.config),encoding='utf-8')
        (self.local/'formulas.json').write_text(json.dumps([TEMPLATES[0]]),encoding='utf-8')
        self.service=DashboardService(self.local,background=False)
        self.addCleanup(self.service.close)
        self.resolver=ExpiryAliasResolver(self.root/'mapping.pkl',self.root/'calendar.pkl')

    def seed(self, mismatched=False, concrete_only=False):
        mappings,_=self.resolver.resolve_many(self.config['symbols'])
        now=datetime.now(CHINA)
        with DualIdentityStore(self.root/'market') as store:
            for i,alias in enumerate(self.config['symbols']):
                identity=mappings[alias]
                symbol=identity['source_symbol'] if concrete_only else alias
                at=now-timedelta(seconds=30 if mismatched and i==0 else 0)
                store.batch({'symbols':[symbol],'status':'success','received_at':at.isoformat(),
                    'response':{'data':{symbol:quote(identity['source_symbol'],100-i*2)}},
                    'symbol_mapping':{symbol:identity},'poll':1,'batch':i+1,'batch_count':2})

    def test_live_read_aliases_compute_and_deduplicate_results(self):
        self.seed()
        self.service.tick()
        state=self.service.snapshot()
        self.assertIsNone(state['error'])
        self.assertEqual(state['formulas'][0]['result']['values']['中间价差'],2)
        self.assertNotEqual(state['formulas'][0]['result']['quality'],'live')
        count=state['storage']['rows']
        self.service.tick()
        self.assertEqual(self.service.snapshot()['storage']['rows'],count)
        self.service.flush()
        paths=list((self.root/'results'/'factors').rglob('*.parquet'))
        self.assertTrue(paths)
        row=pq.read_table(paths[0]).to_pylist()[0]
        self.assertIn('source_symbol',row['inputs_json'])
        self.assertEqual(json.loads(row['values_json'])['中间价差'],2)
        self.assertTrue((self.root/'results'/'formulas'/'calendar_spread'/(row['version']+'.json')).is_file())

    def test_concrete_only_history_can_be_previewed_through_alias(self):
        self.seed(concrete_only=True)
        result=self.service.preview(TEMPLATES[0])
        self.assertEqual(result['values']['中间价差'],2)

    def test_new_observation_is_saved_even_when_price_repeats(self):
        self.seed();self.service.tick()
        before=self.service.snapshot()['storage']['rows']
        self.seed();self.service.tick()
        self.assertEqual(self.service.snapshot()['storage']['rows'],before+1)

    def test_expired_alias_is_not_reused_for_new_contract(self):
        self.seed()
        mapping,_=self.resolver.resolve_many(self.config['symbols'])
        mapping['IC00.CFE']['source_symbol']='IC9901.CFE'
        with patch.object(self.service.gateway,'resolver') as resolver:
            resolver.return_value.resolve_many.return_value=(mapping,{})
            quotes,_,_=self.service._read(self.config['symbols'])
        self.assertNotIn('IC00.CFE',quotes)

    def test_formula_inputs_join_collection_and_reload_while_running(self):
        self.service.publish(TEMPLATES[2])
        with patch.object(self.service.gateway,'start') as start:
            self.service.collect(once=True)
            self.assertIn('510300.SH',start.call_args.args[0]['symbols'])
        with patch.object(self.service.gateway,'running',return_value=True):
            self.service.publish(TEMPLATES[3])
        symbols=json.loads((self.local/'collection_symbols.json').read_text())
        self.assertIn('AU.SHF',symbols)

    def test_launcher_reopens_existing_matching_service(self):
        import io
        from dashboard.server import main
        boot={'application':'delta1-dashboard','local_root':str(self.local)}
        with patch('dashboard.server.urlopen',return_value=io.BytesIO(json.dumps(boot).encode())), \
             patch('dashboard.server.webbrowser.open') as browser, \
             patch('dashboard.server.DashboardService') as service:
            self.assertEqual(main(['--open','--local-root',str(self.local)]),0)
        browser.assert_called_once_with('http://127.0.0.1:8768')
        service.assert_not_called()

    def test_misaligned_legs_cannot_produce_result(self):
        self.seed(mismatched=True)
        self.service.tick()
        result=self.service.snapshot()['formulas'][0]['result']
        self.assertEqual(result['values'],{})
        self.assertIn('时间不齐',result['error'])
        self.assertEqual(self.service.snapshot()['storage']['rows'],0)

    def test_missing_database_and_formula_failure_are_visible(self):
        self.service.tick()
        self.assertIn('尚未创建',self.service.snapshot()['error'])
        self.seed()
        broken={**TEMPLATES[0],'id':'broken','code':'def compute(quotes, history, params):\n    return {"x": 1 / 0}\n'}
        self.service.publish(broken)
        self.service.tick()
        formulas={f['id']:f for f in self.service.snapshot()['formulas']}
        self.assertEqual(formulas['broken']['result']['quality'],'error')
        self.assertEqual(formulas['calendar_spread']['result']['values']['中间价差'],2)

    def test_config_switch_preserves_old_results_and_disallows_active_collection(self):
        self.seed();self.service.tick();self.service.flush()
        previous=self.config['results_root']
        new={**self.config,'results_root':str(self.root/'results2')}
        saved=self.service.save_config(new)
        self.assertIn(previous,saved['previous_result_roots'])
        self.assertTrue(list((self.root/'results'/'factors').rglob('*.parquet')))
        self.assertEqual(self.service.snapshot()['storage']['rows'],0)
        with patch.object(self.service.gateway,'running',return_value=True):
            with self.assertRaisesRegex(ValueError,'先停止'):
                self.service.save_config(self.config)

    def test_publication_is_versioned_persistent_and_toggleable(self):
        first=self.service.publish(TEMPLATES[0])
        second=self.service.publish({**TEMPLATES[0],'code':TEMPLATES[0]['code'].replace('"中间价差"','"我的价差"')})
        self.assertNotEqual(first['version'],second['version'])
        self.assertEqual(len(list((self.local/'formula_versions'/'calendar_spread').glob('*.json'))),2)
        self.service.toggle('calendar_spread',False)
        self.assertFalse(json.loads((self.local/'formulas.json').read_text())[0]['enabled'])

    def test_loopback_api_requires_token_and_rejects_cross_origin(self):
        server=DashboardServer(0,self.service)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}'
            with urlopen(url+'/api/bootstrap') as response:
                data=json.load(response)
            self.assertIn('templates',data)
            req=Request(url+'/api/collection/stop',data=b'{}',headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as error:
                urlopen(req)
            self.assertEqual(error.exception.code,403)
            req.add_header('X-Delta1-Token',data['token'])
            with urlopen(req) as response:
                self.assertEqual(response.status,200)
            req.add_header('Origin','https://example.invalid')
            with self.assertRaises(HTTPError) as error:
                urlopen(req)
            self.assertEqual(error.exception.code,403)
        finally:
            server.shutdown();server.server_close();worker.join()


if __name__=='__main__':
    unittest.main()
