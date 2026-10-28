"""On-demand integration with isolated fake feeds and real cache/Qt lifecycle."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from index_futures_basis.security_model import SecurityQuery,calculate
from index_futures_basis.security_data import SecurityResult,DemoSecurityProvider
from index_futures_basis.sync import Cancelled
from shared_data import DataPaths
from dashboard.native.market_analysis import execute,QueryCancellation,OwnedQueryProvider,safe_error

NOW='2026-10-27 10:00+08:00'


class FakeProvider(DemoSecurityProvider):
    def __init__(self,config):self.calls=[];self.closed=False
    def request(self,operation,**kwargs):
        self.calls.append(operation);return super().request(operation,**kwargs)
    def close(self):self.closed=True


def query():
    return SecurityQuery('510300.SH','1m',('close',),'2026-10-27 09:30','2026-10-27 09:33',True,True,'share','yuan')


class AnalysisTests(unittest.TestCase):
    def test_real_service_own_cache_incremental_and_offline_zero_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shared=DataPaths.for_repo(root/'independent');original=[]
            def factory(config):p=FakeProvider(config);original.append(p);return p
            with patch('dashboard.native.market_analysis.DataPaths.for_repo',side_effect=lambda repo,**kw:DataPaths(repo,Path(kw['data_root']),root/'exports') if kw else shared):
                first=execute(query(),{},root/'profile',now=NOW,provider_factory=factory)
                second=execute(query(),{},root/'profile',now=NOW,provider_factory=factory)
                final=execute(query(),{},root/'profile',now='2026-10-28 10:00+08:00',provider_factory=factory)
                repeated=execute(query(),{},root/'profile',now='2026-10-28 10:00+08:00',provider_factory=factory)
                offline=execute(query(),{},root/'profile',now=NOW,mode='offline',provider_factory=lambda _:self.fail('offline SDK'))
            self.assertEqual(len(first.frame),3)
            self.assertAlmostEqual(first.summary['metrics']['twap'],first.frame.close.mean())
            self.assertGreater(first.metadata['requests'],0)
            # Today's selected range refreshes once per explicit query. Once
            # finalized on the next day, the same complete range makes no calls.
            self.assertEqual(second.metadata['requests'],1);self.assertEqual(final.metadata['requests'],1)
            self.assertEqual(repeated.metadata['requests'],0);self.assertEqual(offline.metadata['requests'],0)
            self.assertTrue(all(p.closed for p in original));self.assertFalse(shared.root.exists())
            self.assertEqual(first.summary['metrics'],offline.summary['metrics'])

    def test_cancel_before_query_is_not_cleared_and_error_does_not_leak_driver(self):
        cancel=QueryCancellation();cancel.set();cancel.clear()
        self.assertTrue(cancel.is_set())
        with self.assertRaises(Cancelled):execute(query(),{},Path('.'),cancel=cancel)
        detail=safe_error(RuntimeError('password=do-not-export; ErrorCode=-40522017'),'history')
        self.assertEqual(detail['error_code'],-40522017);self.assertNotIn('password',str(detail))
        provider=OwnedQueryProvider({});provider.close()
        with self.assertRaises(Cancelled):provider._start()

    def test_cancel_closes_only_owned_reader_and_waits_for_writer(self):
        entered=threading.Event();closed=threading.Event();out=[]
        class Slow(FakeProvider):
            last_operation='info'
            def request(self,operation,**kwargs):
                entered.set();closed.wait(4);raise RuntimeError('secret=never-shared')
            def close(self):closed.set();super().close()
        with tempfile.TemporaryDirectory() as tmp:
            cancel=QueryCancellation()
            def run():
                try:execute(query(),{},Path(tmp),cancel=cancel,provider_factory=Slow,now=NOW)
                except Exception as exc:out.append(type(exc))
            worker=threading.Thread(target=run);worker.start()
            self.assertTrue(entered.wait(3));start=time.monotonic();cancel.set();worker.join(3)
            self.assertFalse(worker.is_alive());self.assertLess(time.monotonic()-start,2)
            self.assertEqual(out,[Cancelled]);self.assertTrue(closed.is_set())

    def test_native_daily_uses_continuous_actual_mapping_and_no_network(self):
        from tests.test_overview_percentiles import metadata
        from dashboard.marketdata.overview_daily import publish_day
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);day='2026-10-26'
            publish_day({},root,day,{'IF2611.CFE':dict(symbol='IF2611.CFE',trade_date=day,is_final=True,
                source_at=day+'T15:00:00+08:00',close=4100,source='fixture')})
            q=SecurityQuery('IF00','1d',('close',),day,day)
            with patch('dashboard.marketdata.contract_reference.latest_contracts',return_value=metadata()),patch('requests.sessions.Session.request',side_effect=AssertionError('no network')):
                result=execute(q,{},root,now=NOW,provider_factory=lambda _:self.fail('no SDK'))
            self.assertEqual(result.frame.close.iloc[0],4100)
            self.assertEqual(result.metadata['contract_mapping'][0]['actual_code'],'IF2611.CFE')
            self.assertEqual(result.metadata['requests'],0)

    def test_old_requested_window_reads_standard_final_daily_prices(self):
        from tests.test_numeric_model import fixture
        from tests.test_overview_percentiles import metadata
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=fixture(root/'history')
            before={p.relative_to(store.root):p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
            q=SecurityQuery('IC2610','1d',('close','oi'),'2026-09-01','2026-09-03')
            with patch('dashboard.marketdata.contract_reference.latest_contracts',return_value=metadata()):
                result=execute(q,dict(history_roots=[str(store.root)]),root,now=NOW)
            self.assertEqual(len(result.frame),3);self.assertEqual(result.frame.close.notna().sum(),3)
            self.assertEqual(result.frame.oi.notna().sum(),0)
            self.assertEqual(result.metadata['missing_cells'],3)
            self.assertEqual(before,{p.relative_to(store.root):p.read_bytes() for p in store.root.rglob('*') if p.is_file()})


class AnalysisUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dashboard.native.bootstrap import configure_qt
        configure_qt()
        from PySide6.QtWidgets import QApplication
        from dashboard.native.app import configure_style
        cls.app=QApplication.instance() or QApplication([]);configure_style(cls.app)

    def pump(self,predicate=lambda:False,seconds=2):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            self.app.processEvents()
            if predicate():return
            time.sleep(.005)

    def page(self,runner):
        from dashboard.native.market_analysis_view import MarketAnalysisPage
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        page=MarketAnalysisPage(SimpleNamespace(config={},local_root=Path(tmp.name)),runner=runner)
        self.addCleanup(page.close);return page

    def test_manual_query_hand_metrics_units_recalculation_and_clear(self):
        calls=[]
        def runner(q,*_,**__):
            calls.append(q)
            frame=pd.DataFrame(dict(time=['2026-10-27T09:31:00+08:00','2026-10-27T09:32:00+08:00','2026-10-27T09:33:00+08:00'],
                close=[10.,12.,float('nan')],volume=[100.,200.,0.],amt=[1000.,2400.,999.]))
            return SecurityResult(q,frame,calculate(q,frame),dict(source='fixture',actual_end=frame.time.iloc[-1]))
        page=self.page(runner);page.show();page.resize(860,620)
        self.assertFalse(calls);page.code.setText('510300.SH');page.vwap.setChecked(True)
        page.query();self.pump(lambda:not page.busy)
        self.assertEqual(len(calls),1);self.assertEqual(page.metrics['twap'][0].text(),'11.0000')
        self.assertEqual(page.metrics['vwap'][0].text(),'—')
        page.volume_unit.setCurrentIndex(page.volume_unit.findData('share'));page.amount_unit.setCurrentIndex(page.amount_unit.findData('yuan'))
        self.assertEqual(len(calls),1);self.assertEqual(page.metrics['vwap'][0].text(),'11.3333')
        page.fields['open'].setChecked(True)
        self.assertIsNone(page.result);self.assertEqual(page.metrics['twap'][0].text(),'—')
        self.assertIn('重新查询',page.note.text());self.assertEqual(len(calls),1)
        page.code.setText('000300.SH');self.assertFalse(page.vwap.isEnabled())
        self.assertIsNone(page.result);self.assertEqual(page.metrics['twap'][0].text(),'—')
        self.assertEqual(page.raw.rowCount(),0)
        self.pump(seconds=.05);self.assertEqual(page.scroll.horizontalScrollBar().maximum(),0)

    def test_busy_inputs_frozen_cancel_never_applies_result_and_readonly(self):
        entered=threading.Event()
        def runner(q,*_,cancel,**__):
            entered.set();cancel.wait(3);raise Cancelled('cancelled')
        page=self.page(runner);page.code.setText('510300.SH');page.set_readonly();page.query()
        self.assertTrue(entered.wait(2));self.assertFalse(page.code.isEnabled());page.stop()
        self.pump(lambda:not page.busy)
        self.assertFalse(page.busy);self.assertIsNone(page.result);self.assertTrue(page.code.isEnabled())
        self.assertFalse(page.mode.isEnabled());self.assertEqual(page.source_active,None)
        self.assertIn('取消',page.note.text())


if __name__=='__main__':unittest.main()
