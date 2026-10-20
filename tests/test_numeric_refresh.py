"""Refresh semantics: calculation clocks are not market timestamps."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from dashboard.display_state import daily_saved_pairs
from dashboard.numeric_evidence import annotate, cache_scope
from dashboard.numeric_excel import workbook_payload
from dashboard.numeric_snapshot import freeze_state, save_snapshot
from tests import test_numeric_excel as display_tests


def payload():
    fixture = display_tests.DisplayTests()
    model, refs, book = fixture.fixture(live=True)
    result = freeze_state(fixture.run_display(model, refs, book))
    result['generated_at'] = '2026-10-20T01:00:00Z'
    result['mode'] = '只读缓存'
    return result


def feed(value, previous=None):
    result = workbook_payload(value)
    result['ready'] = True
    return annotate(result, value, previous=previous, acquisition='只读缓存 · 不创建采集器')


class RefreshEvidenceTests(unittest.TestCase):
    def test_excel_decimal_roundtrip_is_not_a_mismatch_but_zero_is_not_missing(self):
        from dashboard.numeric_diagnose import same_cell
        self.assertTrue(same_cell(-0.1303571428571429,-0.13035714285714287))
        self.assertFalse(same_cell(0.,None))
        self.assertFalse(same_cell(4300.,4300.01))

    def test_one_model_reads_new_sqlite_records_without_restarting_or_collecting(self):
        from dashboard.native.model import NativeModel
        from index_strategy.instant_dld.contract_aliases import DualIdentityStore
        from tests.test_numeric_model import fixture
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); history=fixture(root/'history'); settings=root/'settings';settings.mkdir()
            reference=root/'reference.json'
            reference.write_text(json.dumps(dict(schema_version='cn_index_reference_v1',contracts=[
                dict(instrument_id='IC'+month+'.CFE',underlying_id='000905.SH',listing_date='2026-01-01',
                     expiry_date=expiry,known_at='2026-01-01T00:00:00Z')
                for month,expiry in [('2610','2026-10-16'),('2611','2026-11-20'),('2612','2026-12-18'),('2703','2027-03-19')]])),encoding='utf8')
            model=NativeModel(settings)
            model.config.update(history_roots=[str(history.root)],reference_file=str(reference),
                realtime_root=str(root/'live'),dividend_root=str(root/'dividend'),dashboard_mode='nonregression')
            request=dict(cards=True,category='basis',overview_slot=0,distribution_input='annual')
            from dashboard.display_state import display_snapshot
            def view(now):
                with patch('dashboard.display_state.daily_saved_pairs',return_value={}):
                    value=freeze_state(display_snapshot(model,request,now=now))
                result=feed(value)
                return next(r for r in result['sheets']['数字看板'] if r[0]=='IC')
            try:
                with DualIdentityStore(root/'live') as writer:
                    def append(poll,clock,price):
                        quotes={s:dict(securityId=s,latestPrice=p,quoteTimestamp=clock,tradedQuantities=100.+poll,
                            b1Price=p,s1Price=p+1,b1Stocks=3,s1Stocks=5) for s,p in [('IC2610.CFE',price),('000905.SH',7000.)]}
                        writer.batch(dict(symbols=list(quotes),status='success',received_at=f'2026-09-30T10:00:0{poll}+08:00',
                            response=dict(data=quotes),poll=poll,batch=1,batch_count=1,
                            symbol_mapping={s:dict(source_symbol=s,mapping_date=None,trading_date=None) for s in quotes}))
                    with patch('requests.Session',side_effect=AssertionError('reader must stay offline')):
                        append(1,100001,6900.)
                        first=view('2026-09-30T10:00:02+08:00')
                        cursor=model.live_cursor
                        same=view('2026-09-30T10:00:03+08:00')
                        self.assertEqual(first,same);self.assertEqual(model.live_cursor,cursor)
                        append(4,100004,6910.)
                        changed=view('2026-09-30T10:00:05+08:00')
                        self.assertGreater(model.live_cursor,cursor)
                        self.assertEqual(first[3],6900.);self.assertEqual(changed[3],6910.)
                        self.assertNotEqual(first[11],changed[11])
            finally:model.close()

    def test_new_calculation_time_keeps_original_quote_time_and_table_revision(self):
        value = payload()
        first = feed(value)
        value['generated_at'] = '2026-10-20T01:00:03Z'
        second = feed(value, first)
        value['generated_at'] = '2026-10-20T01:00:06Z'
        third = feed(value, second)
        self.assertFalse(second['evidence']['display_inputs_changed'])
        self.assertIn('未观察到', second['evidence']['note'])
        self.assertEqual(first['evidence']['newest_source_time'], second['evidence']['newest_source_time'])
        self.assertEqual(first['sheet_revisions']['数字看板'], second['sheet_revisions']['数字看板'])
        self.assertEqual(second['content_revision'], third['content_revision'])
        self.assertNotEqual(first['generated_at'], second['generated_at'])

    def test_changed_quote_updates_value_time_and_revision_without_claiming_live(self):
        value = payload(); first = feed(value)
        card = value['snapshots'][0]['overview'][0]
        card['quote'].update(close=4300., source_event_time='2026-10-20T09:31:00+08:00')
        card['spot']['source_event_time'] = '2026-10-20T09:31:00+08:00'
        card['chart']['time'] = '2026-10-20T09:31:00+08:00'
        value['generated_at'] = '2026-10-20T01:31:03Z'
        second = feed(value, first)
        self.assertTrue(second['evidence']['display_inputs_changed'])
        self.assertEqual(second['sheets']['数字看板'][0][3], 4300.)
        self.assertNotEqual(first['sheets']['数字看板'][0][11], second['sheets']['数字看板'][0][11])
        self.assertIn('只读缓存', second['acquisition'])

    def test_daily_fallback_excludes_other_config_and_legacy_untagged_cache(self):
        with tempfile.TemporaryDirectory() as tmp, patch('dashboard.marketdata.paths.DATA_ROOT', Path(tmp)):
            value = payload(); dest=Path(tmp)/'cache/dashboard/numeric/2026-10-19/latest.json'
            now=pd.Timestamp('2026-10-20T09:00:00+08:00')
            save_snapshot(value, dest)
            self.assertTrue(daily_saved_pairs(now))  # Existing App compatibility.
            self.assertFalse(daily_saved_pairs(now, scope='numeric-A'))
            value['cache_scope']='numeric-B';save_snapshot(value, dest)
            self.assertFalse(daily_saved_pairs(now, scope='numeric-A'))
            value['cache_scope']='numeric-A';save_snapshot(value, dest)
            self.assertTrue(daily_saved_pairs(now, scope='numeric-A'))

    def test_config_scope_tracks_data_roots_but_not_ui_or_credentials(self):
        config=dict(history_roots=['history'], realtime_root='cache-A', reference_file='ref.json')
        self.assertNotEqual(cache_scope(config), cache_scope({**config, 'realtime_root':'cache-B'}))
        self.assertEqual(cache_scope(config), cache_scope({**config, 'product':'IC', 'password':'synthetic'}))

    def test_cache_diagnosis_is_read_only_and_does_not_create_missing_database(self):
        from dashboard.numeric_diagnose import cache_state
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertFalse(cache_state(root)['exists']);self.assertFalse((root/'live').exists())
            path=root/'live/quotes.sqlite3';path.parent.mkdir()
            with sqlite3.connect(path) as con:
                con.execute('CREATE TABLE quotes(sequence INTEGER, symbol TEXT, source_event_time TEXT, received_at TEXT, close REAL)')
                con.execute('INSERT INTO quotes VALUES(1,?,?,?,?)',
                            ('IF2611.CFE','2026-10-20T01:30:00Z','2026-10-20T01:30:02Z',0.))
            con.close()
            before=path.read_bytes()
            self.assertEqual(cache_state(root)['tail']['close'],0.)
            self.assertEqual(path.read_bytes(),before)
