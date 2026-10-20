"""Offline numeric producer uses real backend fixtures without any GUI imports."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard import numeric_excel
from tests.test_numeric_model import fixture


class NumericServiceTests(unittest.TestCase):
    def test_producer_writes_four_sheets_and_daily_cache_without_network_or_source_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=fixture(root/'history')
            reference=root/'reference.json'
            reference.write_text(json.dumps({'schema_version':'cn_index_reference_v1','contracts':[
                dict(instrument_id=f'{product}{month}.CFE',underlying_id=index,listing_date='2026-01-01',
                     expiry_date=expiry,known_at='2026-01-01T00:00:00Z')
                for product,index in [('IF','000300.SH'),('IH','000016.SH'),('IC','000905.SH'),('IM','000852.SH')]
                for month,expiry in [('2610','2026-10-16'),('2611','2026-11-20'),('2612','2026-12-18'),('2703','2027-03-19')]
            ]}),encoding='utf8')
            local=root/'numeric-settings';local.mkdir()
            config=dict(history_roots=[str(store.root)],reference_file=str(reference),
                        realtime_root=str(root/'quotes'),dividend_root=str(root/'dividends'))
            raw=json.dumps(config).encode();(local/'native.json').write_bytes(raw)
            pointer=(store.root/'current.json').read_bytes()
            feed=root/'feed.json';capture=numeric_excel.capture
            stages=[]
            def traced_capture(model,**kw):
                initial=json.loads(feed.read_text(encoding='utf8'))
                self.assertFalse(initial['ready'])
                self.assertTrue(all(not rows for rows in initial['sheets'].values()))
                callback=kw['progress']
                def progress(slot,complete,payload):
                    callback(slot,complete,payload)
                    if complete:
                        partial=json.loads(feed.read_text(encoding='utf8'))
                        self.assertFalse(partial['ready'])
                        self.assertEqual(len(partial['sheets']['数字看板']),4*(slot+1))
                        self.assertFalse(list((root/'data').rglob('latest.json')))
                        stages.append(slot)
                return capture(model,now='2026-10-02T10:00:00Z',**{**kw,'progress':progress})
            with patch('requests.Session',side_effect=AssertionError('offline must not create HTTP client')), \
                 patch('dashboard.marketdata.paths.DATA_ROOT',root/'data'), \
                 patch('dashboard.session_clock.session_policy',return_value=dict(allowed=False,reason='offline test')), \
                 patch('dashboard.numeric_excel.capture',side_effect=traced_capture):
                numeric_excel.main(['--local-root',str(local),'--feed',str(feed),'--iterations','1','--collect'])
            value=json.loads(feed.read_text(encoding='utf8'))
            self.assertTrue(value['ready']);self.assertEqual(stages,[0,1,2,3])
            self.assertEqual(set(value['sheets']),set(numeric_excel.HEADERS))
            self.assertEqual(len(value['sheets']['数字看板']),16)
            self.assertTrue(value['sheets']['研究指标'])
            from dashboard.numeric_view import METRICS
            self.assertEqual({r[3] for r in value['sheets']['研究指标']},
                             {m[0] for m in METRICS}|{'X','B04.Q.intraday','B09.same_time'})
            self.assertEqual(len(value['workspace']['selection']['rows']),4)
            self.assertTrue((root/'data/cache/dashboard/numeric/2026-10-02/latest.json').is_file())
            self.assertEqual((local/'native.json').read_bytes(),raw)
            self.assertEqual((store.root/'current.json').read_bytes(),pointer)

    def test_capture_stops_between_slots_without_publishing_a_complete_result(self):
        stages=[]
        state=dict(overview=[],entities=[],display_policy=dict(reason='test'))
        with patch('dashboard.display_state.display_snapshot',return_value=state) as display:
            with self.assertRaises(InterruptedError):
                numeric_excel.capture(object(),progress=lambda slot,done,payload:stages.append(slot) if done else None,
                    stopped=lambda:bool(stages))
        self.assertEqual(display.call_count,1);self.assertEqual(stages,[0])
