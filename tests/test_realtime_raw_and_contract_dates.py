"""Mock HTTP and temporary databases: source evidence and direct futures dates."""
from copy import deepcopy
from datetime import datetime
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from index_strategy.instant_dld.client import MarketDataClient
from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.contracts import ContractMappingError, MainContractResolver
from index_strategy.instant_dld.raw_store import publish_raw_batch
from index_strategy.instant_dld.reader import RealtimeReader
from index_strategy.instant_dld.realtime_store import DB_RELATIVE, RealtimeStore, SCHEMA
from tests.test_contract_storage import legacy_database
from tests.test_realtime import FakeTime


class RealtimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.calendar = self.root/'calendar.pkl'
        pd.DataFrame({'Date':pd.to_datetime(['2026-09-17','2026-09-18','2026-09-21',
                                             '2026-09-22','2026-09-23'])}).to_pickle(self.calendar)
        self.mapping = self.root/'mapping.pkl'
        pd.DataFrame({'AU.SHF':['AU2610.SHF','AU2612.SHF']},
                     index=pd.to_datetime(['2026-09-18','2026-09-21'])).to_pickle(self.mapping)
        self.now = '2026-09-18T23:59:59+08:00'
        self.resolver = MainContractResolver(self.mapping, self.calendar,
            now=lambda: datetime.fromisoformat(self.now))

    @staticmethod
    def body(symbol='AU2610.SHF', total=100):
        return {'code':'0','respSuccess':True,'respFail':False,'data':{
            symbol:{'securityId':symbol,'latestPrice':940.32,'tradedQuantities':total,
                    'quoteTimestamp':235959,'sourceExtra':'retained'}}}

    def record(self, symbol='AU2610.SHF', total=100, poll=1, at=None):
        at = at or self.now
        body = self.body(symbol,total)
        body['data'][symbol]['quoteTimestamp'] = int(datetime.fromisoformat(at).strftime('%H%M%S'))
        encoded = json.dumps(body,ensure_ascii=False,indent=2).encode('utf-8')
        return {'requested_at':at,'received_at':at,'elapsed_seconds':0.001,
                'symbols':[symbol],'requested_symbols':[symbol],'status':'success',
                'poll':poll,'batch':1,'batch_count':1,'http_status':200,
                'symbol_mapping':{symbol:self.resolver.resolve(symbol,datetime.fromisoformat(at))},
                'response':body,'source_response':deepcopy(body),
                'response_body':{'base64':base64.b64encode(encoded).decode('ascii'),
                    'sha256':hashlib.sha256(encoded).hexdigest(),'bytes':len(encoded),
                    'representation':'decoded_http_body_bytes'}}

    def test_direct_contract_uses_calendar_across_midnight_without_any_mapping_access(self):
        self.resolver.mapping_file = self.root/'absent-mapping.pkl'
        self.resolver.store = Mock()
        with patch.object(self.resolver,'_load_mapping',side_effect=AssertionError('mapping touched')):
            for at, expected in [('2026-09-18T23:59:59+08:00','2026-09-21'),
                                 ('2026-09-19T00:00:01+08:00','2026-09-21'),
                                 ('2026-09-21T21:00:00+08:00','2026-09-22')]:
                self.assertEqual(self.resolver.resolve('AU2610.SHF',datetime.fromisoformat(at)),
                    {'source_symbol':'AU2610.SHF','mapping_date':None,'trading_date':expected})
        self.resolver.store.pinned_contract.assert_not_called()
        self.resolver.store.pin_contract.assert_not_called()

    def test_direct_cffex_contract_does_not_apply_commodity_night_boundary(self):
        identity = self.resolver.resolve('IF2609.CFE',datetime.fromisoformat('2026-09-18T21:00:00+08:00'))
        self.assertEqual(identity['trading_date'],'2026-09-18')
        self.assertIsNone(identity['mapping_date'])

    def test_missing_calendar_is_explicit_for_direct_future_and_does_not_block_stock(self):
        self.resolver.calendar_file = self.root/'absent-calendar.pkl'
        good, errors = self.resolver.resolve_many(['AU2610.SHF','000001.SZ'])
        self.assertEqual(set(good),{'000001.SZ'})
        self.assertEqual(set(errors),{'AU2610.SHF'})
        self.assertIn('文件不可用',errors['AU2610.SHF'])
        with self.assertRaises(ContractMappingError):
            self.resolver.resolve('AU2610.SHF')

    def test_direct_contract_continues_across_midnight_then_resets_on_next_trade_day(self):
        with RealtimeStore(self.root/'market') as store:
            store.interval_seconds = 2
            store.batch(self.record(poll=1,total=100,at='2026-09-18T23:59:59+08:00'))
            store.batch(self.record(poll=2,total=107,at='2026-09-19T00:00:01+08:00'))
            store.batch(self.record(poll=3,total=110,at='2026-09-21T21:00:00+08:00'))
            rows = RealtimeReader(store.root).read_since()
            self.assertEqual(list(rows.trading_date),['2026-09-21','2026-09-21','2026-09-22'])
            self.assertTrue(pd.isna(rows.volume.iloc[0]))
            self.assertEqual(rows.volume.iloc[1],7)
            self.assertEqual(rows.volume_interval_seconds.iloc[1],2)
            self.assertFalse(int(rows.quality_flags.iloc[1]) & (8|16))
            self.assertTrue(pd.isna(rows.volume.iloc[2]))
            self.assertTrue(int(rows.quality_flags.iloc[2]) & 16)
            self.assertTrue(rows.mapping_date.isna().all())
            self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0],4)

    def test_http_success_and_invalid_json_keep_full_body_without_headers(self):
        for invalid in (False,True):
            with self.subTest(invalid=invalid):
                contents = b'<html>' + b'x'*10000 + b'</html>' if invalid else json.dumps(self.body()).encode()
                response = Mock(status_code=200,content=contents,text=contents.decode(),
                                headers={'Authorization':'secret-response-header'})
                if invalid:
                    response.json.side_effect = ValueError('invalid')
                else:
                    response.json.return_value = self.body()
                session = Mock()
                session.post.return_value = response
                result = MarketDataClient(session=session).fetch(['AU2610.SHF'])
                self.assertEqual(base64.b64decode(result['response_body']['base64']),contents)
                self.assertEqual(result['response_body']['sha256'],hashlib.sha256(contents).hexdigest())
                self.assertNotIn('headers',result)
                self.assertEqual(result['status'],'invalid_json' if invalid else 'success')
                response.close.assert_called_once()

    def test_collector_archives_actual_keys_before_alias_expansion_and_matches_content_hash(self):
        symbols = self.root/'symbols.json'
        symbols.write_text('["AU.SHF"]',encoding='utf-8')
        response_payload = self.body()
        contents = json.dumps(response_payload,indent=3).encode()
        response = Mock(status_code=200,content=contents,text=contents.decode())
        response.json.return_value = response_payload
        session = Mock()
        session.post.return_value = response
        timer = FakeTime()
        with RealtimeStore(self.root/'market') as store:
            collect(MarketDataClient(session=session),store,[symbols],max_polls=1,
                    resolver=self.resolver,stop=timer,clock=timer.clock)
            event = store.connection.execute("SELECT description FROM events WHERE kind='raw_http_batch'").fetchone()
            reference = json.loads(event[0])
            path = store.root/reference['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),reference['sha256'])
            archived = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(base64.b64decode(archived['response_body']['base64']),contents)
            self.assertEqual(set(json.loads(contents)['data']),{'AU2610.SHF'})
            metadata = archived['request_and_collection']
            self.assertEqual(metadata['requested_symbols'],['AU2610.SHF'])
            self.assertEqual(metadata['symbols'],['AU.SHF'])
            self.assertEqual(metadata['symbol_mapping']['AU.SHF']['trading_date'],'2026-09-21')
            self.assertEqual(RealtimeReader(store.root).latest().iloc[0].symbol,'AU.SHF')
            self.assertEqual(set(response_payload['data']),{'AU2610.SHF'})

    def test_invalid_json_archives_full_response_without_any_parsed_quote(self):
        contents = b'<html>' + b'x'*10000 + b'</html>'
        response = Mock(status_code=200,content=contents,text=contents.decode())
        response.json.side_effect = ValueError('invalid')
        session = Mock()
        session.post.return_value = response
        record = MarketDataClient(session=session).fetch(['AU2610.SHF'])
        record.update(poll=1,batch=1,batch_count=1,requested_symbols=['AU2610.SHF'],
                      symbol_mapping={'AU2610.SHF':self.resolver.resolve('AU2610.SHF')})
        with RealtimeStore(self.root/'market') as store:
            store.batch(record)
            self.assertEqual(store.last_report['status'],'failed')
            path = store.root/record['raw_response_reference']['path']
            archived = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(base64.b64decode(archived['response_body']['base64']),contents)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM quotes').fetchone()[0],0)

    def test_identical_raw_reuses_file_and_detects_existing_corruption(self):
        record = self.record()
        first = publish_raw_batch(self.root,'run',record)
        path = self.root/first['path']
        before = path.stat().st_mtime_ns
        self.assertEqual(publish_raw_batch(self.root,'run',record),first)
        self.assertEqual(path.stat().st_mtime_ns,before)
        path.write_bytes(b'damaged')
        with self.assertRaisesRegex(OSError,'校验失败'):
            publish_raw_batch(self.root,'run',record)
        self.assertEqual(path.read_bytes(),b'damaged')

    def test_raw_metadata_excludes_arbitrary_credentials_headers_and_errors(self):
        record = self.record()
        record.update(password='secret-password',headers={'Authorization':'secret-token'},
                      error='https://secret-user:secret-password@example.invalid/')
        reference = publish_raw_batch(self.root,'run',record)
        text = (self.root/reference['path']).read_text(encoding='utf-8')
        self.assertNotIn('secret-',text)
        self.assertNotIn('headers',text)
        with self.assertRaises(ValueError):
            publish_raw_batch(self.root,'../outside',record)
        with self.assertRaises(ValueError):
            publish_raw_batch(self.root,'run',{**record,'response_body':{**record['response_body'],'sha256':'wrong'}})

    def test_legacy_parsed_payload_and_no_http_response_have_explicit_fidelity(self):
        record = self.record()
        record.pop('response_body')
        record.pop('source_response')
        reference = publish_raw_batch(self.root,'run',record)
        self.assertEqual(reference['body_representation'],'legacy_store_record_json_reserialized')
        record.pop('response')
        record.update(status='timeout')
        reference = publish_raw_batch(self.root,'run',record)
        self.assertEqual(reference['body_representation'],'no_http_response')
        self.assertIsNone(reference['body_sha256'])

    def test_raw_write_failure_prevents_quote_or_successful_batch_commit(self):
        with RealtimeStore(self.root/'market') as store:
            with patch('index_strategy.instant_dld.realtime_store.publish_raw_batch',side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError,'disk full'):
                    store.batch(self.record())
            for table in ('quotes','batches','events'):
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
            self.assertEqual(store.last_rows,[])

    def test_quote_transaction_failure_keeps_raw_evidence_without_success_or_reference_commit(self):
        with RealtimeStore(self.root/'market') as store:
            store.connection.execute("CREATE TRIGGER reject_quote BEFORE INSERT ON quotes BEGIN SELECT RAISE(ABORT,'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                store.batch(self.record())
            self.assertEqual(len(list((store.root/'raw').rglob('*.json'))),1)
            for table in ('quotes','batches','events'):
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)

    def test_failed_http_batch_preserves_body_and_failed_state_without_quotes(self):
        record = self.record()
        record.update(status='http_error',http_status=503)
        with RealtimeStore(self.root/'market') as store:
            store.batch(record)
            self.assertEqual(store.last_report['status'],'failed')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM quotes').fetchone()[0],0)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM events WHERE kind='raw_http_batch'").fetchone()[0],1)
            self.assertTrue((store.root/record['raw_response_reference']['path']).is_file())

    def test_reader_of_legacy_database_and_parquet_does_not_migrate_or_create_raw(self):
        market = self.root/'legacy'
        part = legacy_database(market)
        database = market/DB_RELATIVE
        before = database.read_bytes(),part.read_bytes()
        reader = RealtimeReader(market)
        self.assertEqual(len(reader.read_since()),1)
        self.assertEqual(len(reader.read_parquet_day('AU.SHF','2026-09-18')),1)
        self.assertEqual((database.read_bytes(),part.read_bytes()),before)
        self.assertFalse((market/'raw').exists())
        self.assertEqual(SCHEMA.metadata[b'schema_version'],b'swhy_realtime_v4')

    def test_repeated_source_time_and_payload_remains_valid_zero_interval_quantity(self):
        record = self.record(total=100,poll=1)
        second = deepcopy(record)
        second.update(received_at='2026-09-19T00:00:01+08:00',poll=2)
        # An unchanged source snapshot can mean no new trade, not proven staleness.
        with RealtimeStore(self.root/'market') as store:
            store.interval_seconds = 2
            store.batch(record)
            store.batch(second)
            rows = RealtimeReader(store.root).read_since()
            self.assertEqual(rows.volume.iloc[-1],0)
            self.assertFalse(int(rows.quality_flags.iloc[-1]) & (8|16|128))
            self.assertEqual(len(list((store.root/'raw').rglob('*.json'))),2)


if __name__ == '__main__':
    unittest.main()
