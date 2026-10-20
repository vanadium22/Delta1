import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.numeric_excel import HEADERS
from dashboard.numeric_view import add_view, METRICS, PRODUCTS, short_reason


def fixture():
    sheets = {name: [] for name in HEADERS}
    for slot in range(4):
        for p, product in enumerate(PRODUCTS):
            alias = f'{product}{slot:02d}.CFE'
            contract = product + ('2611','2612','2703','2706')[slot] + '.CFE'
            sheets['数字看板'].append([product,alias,contract,4100.+slot*10+p*100,4200.,0.,31.,-100.,-238.,-.12,'保存行情回看',46315.4375,contract,'合成测试'])
            for window in ('20交易日','3个月','6个月','12个月'):
                sheets['分位与样本'].append([product,alias,contract,window,0. if p == 0 else .2+p*.1,20,0,0,-12.,'%',46315.4375,46311.625,'有效'])
            for i, (code, title, unit) in enumerate(METRICS):
                missing = slot in (0,3) and code in ('B09','B11')
                sheets['研究指标'].append([product,alias,contract,code,title,None if missing else float(i+p+slot),unit,
                    '缺少数据' if missing else '历史',None if missing else 46311.625,'样本不足、数据缺失或分母无效' if missing else '', '测试公式'])
    return add_view(dict(schema_version=1, generated_at='2026-10-20T02:30:00Z',ready=True,mode='只读缓存',headers=HEADERS,sheets=sheets))


class ViewTests(unittest.TestCase):
    def test_original_results_unchanged_and_selected_rows_match(self):
        feed = fixture()
        original = copy.deepcopy(feed['sheets']['研究指标'])
        add_view(feed)
        self.assertEqual(original,feed['sheets']['研究指标'])
        self.assertEqual(len(feed['sheets']['指标数据']),100)
        for slot in range(4):
            for p in range(4):
                row = feed['sheets']['卡片数据'][slot*4+p]
                self.assertEqual(row[3],4100.+slot*10+p*100)
                self.assertEqual(row[22],46315.4375)
                self.assertEqual(row[23],46311.625)
        self.assertEqual(feed['sheets']['卡片数据'][0][13],0.)
        self.assertIsNone(feed['sheets']['卡片数据'][0][8])
        self.assertNotEqual(feed['sheets']['卡片数据'][4][8],None)

    def test_missing_current_is_not_zero_and_original_reason_is_not_guessed(self):
        feed=fixture()
        row=feed['sheets']['研究指标'][0]
        row[5]=None;row[9]='样本不足、数据缺失或分母无效'
        self.assertEqual(short_reason(row),'样本/分母')
        row[5]=0.
        self.assertEqual(short_reason(row),'历史')
        for r in feed['sheets']['研究指标']:
            if r[1]=='IF00.CFE' and r[3]=='B10':
                r[8]=46310.625
        add_view(feed)
        self.assertEqual(feed['sheets']['卡片数据'][0][23],46310.625)

    def test_helper_row_widths_match_declared_headers(self):
        feed=fixture()
        self.assertEqual(len(feed['headers']['卡片数据']),len(feed['sheets']['卡片数据'][0]))
        self.assertEqual(len(feed['headers']['指标数据']),len(feed['sheets']['指标数据'][0]))


class StartupTests(unittest.TestCase):
    def test_history_batch_cooldown_waits_then_advances_and_can_cancel(self):
        import time
        from dashboard.numeric_startup import history
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{}')
            calls=[]
            def cycle(*args,**kwargs):
                calls.append(time.time())
                return dict(state='partial',inserted=1,next_retry=time.time()+.05) if len(calls)==1 else dict(state='complete')
            result=history(root,root/'result.json',root/'stop',cycle=cycle)
            self.assertEqual(result['state'],'complete');self.assertEqual(len(calls),2)
            self.assertGreaterEqual(calls[1]-calls[0],.05)
            calls.clear()
            with patch('dashboard.numeric_startup.time.sleep',side_effect=lambda _: (root/'stop').touch()):
                result=history(root,root/'result.json',root/'stop',cycle=cycle)
            self.assertEqual(result['state'],'stopped');self.assertEqual(len(calls),1)

    def test_direct_network_failure_does_not_rewrite_existing_credentials(self):
        from dashboard.marketdata.history_maintenance import open_direct
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'connection.json'
            path.write_text('{"host":"fixture.invalid","port":1,"username":"fixture","password":"test-only"}')
            before=path.read_bytes()
            with patch('socket.create_connection',side_effect=TimeoutError('blocked')):
                with self.assertRaises(ConnectionError):open_direct(path)
            self.assertEqual(path.read_bytes(),before)

    def test_summary_is_offline_and_does_not_activate_data(self):
        from dashboard.numeric_startup import summary
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{"history_roots":[]}')
            before=(root/'native.json').read_bytes()
            with patch('requests.Session',side_effect=AssertionError('no network')):
                result=summary(root)
            self.assertEqual(result['history_dates'],{'1d':None,'1m':None})
            self.assertEqual((root/'native.json').read_bytes(),before)

    def test_missing_credentials_never_starts_network_and_keeps_config(self):
        from dashboard.numeric_startup import history
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'native.json'
            config.write_text(json.dumps(dict(history_connection_file=str(root/'missing.json'))))
            before=config.read_bytes()
            with patch('dashboard.marketdata.history_maintenance.open_direct',side_effect=AssertionError('no network')):
                result=history(root,root/'result.json',root/'stop')
            self.assertEqual(result['state'],'waiting_credentials')
            self.assertEqual(config.read_bytes(),before)

    def test_cancel_and_partial_stop_before_next_network_stage(self):
        from dashboard.numeric_startup import history
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{}')
            calls=[]
            def cycle(*args,**kw):
                calls.append(kw)
                return dict(state='partial',inserted=0)
            result=history(root,root/'result.json',root/'stop',cycle=cycle)
            self.assertEqual(len(calls),1)
            (root/'stop').touch()
            result=history(root,root/'result.json',root/'stop',cycle=cycle)
            self.assertEqual(result['state'],'stopped');self.assertEqual(len(calls),1)


if __name__=='__main__':
    unittest.main()
