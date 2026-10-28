"""October 28 overview policy, lifecycle and incomplete company reference cases."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import pandas as pd

from dashboard.marketdata.dividends import DividendBook
from dashboard.marketdata.overview_basis import calculate,load_dividends
from dashboard.marketdata.overview_percentiles import prepare,evaluate
from dashboard.marketdata.overview_reference import validate,publish,ranking,load
from dashboard.marketdata.overview_contributions import contributions
from dashboard.marketdata.overview_windpy import refresh as terminal_refresh
from dashboard.marketdata.wind_terminal_worker import refresh
from dashboard.native.overview_details import enrich
from dashboard.native.overview_reference_job import ReferenceJob
from dashboard.native.collection import CollectionJob
from tests.test_overview_data import FakeWind
from tests.test_overview_percentiles import metadata,daily_data,DAY,NOW
from tests.test_market_overview import ZERO_DIVIDENDS,actual_futures_values,observation
from tests.test_overview_details import reference,equity_snapshot


class OverviewRevisionTests(unittest.TestCase):
    def test_excel_arithmetic_valid_zero_and_missing_dividend(self):
        value=calculate(990,1000,2,30)
        self.assertEqual(value['points'],-8)
        self.assertAlmostEqual(value['annual_pct'],-8/1000*365/30*100)
        self.assertEqual(calculate(1000,1000,0,30)['annual_pct'],0)
        self.assertIsNone(calculate(1000,1000,None,30)['annual_pct'])
        self.assertIsNone(calculate(1000,1000,0,0)['annual_pct'])
        for future,spot,dividend in ((0,1000,0),(-1,1000,0),(1000,0,0),(1000,1000,-1),(1000,1000,True)):
            self.assertIsNone(calculate(future,spot,dividend,30)['annual_pct'])
        live={'IF2611.CFE':observation(990,at=NOW),'000300.SH':observation(1000,at=NOW)}
        row=dict(symbol='IF2611.CFE',root='IF')
        actual_futures_values(row,live,{},metadata(),NOW)
        self.assertEqual(row['raw_basis_points'],-10);self.assertIsNone(row['annual_pct'])

    def test_dividend_inherits_only_earlier_same_product_and_zero_wins(self):
        meta=metadata()
        records=[dict(contract_id=symbol,points=value,effective_from='2026-09-18T00:00:00+08:00',
            source_business_date='2026-09-18',file_sha256='fixture',revision=symbol)
            for symbol,value in [('IF2610.CFE',2),('IF2612.CFE',0)]]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.xlsx';path.write_bytes(b'explicit mocked workbook')
            with patch('dashboard.marketdata.overview_dividends.local_sources',return_value=[path]), \
                 patch('dashboard.marketdata.overview_dividends.records_from_file',return_value=records):
                book=load_dividends(dict(dividend_root=str(path)),meta,DAY)
        self.assertEqual(book.points('IF2611.CFE',DAY),2)
        self.assertEqual(book.info['mapping']['IF2611.CFE']['inherited_from'],'IF2610.CFE')
        self.assertEqual(book.points('IF2703.CFE',DAY),0)
        self.assertIsNone(book.points('IF2608.CFE','2026-07-30'))
        self.assertIsNone(book.points('IH2611.CFE',DAY))

    def test_slot_history_uses_same_simple_dividend_formula_without_filling_missing_days(self):
        meta=metadata();data=daily_data(meta)
        book=SimpleNamespace(points=lambda s,d:2.,version='explicit-fixed-D',info={})
        history=prepare('IF',3,meta,data,DAY,dividends=book)
        row=history['rows'][-1]
        self.assertAlmostEqual(row['annual_pct'],2/4000*365/row['days']*100)
        self.assertEqual(evaluate(history,1000,history['current_symbol'])['windows']['60']['percentile'],100)
        missing_day=row['day'];book.points=lambda s,d:None if d==missing_day else 2.
        history=prepare('IF',3,meta,data,DAY,dividends=book)
        result=evaluate(history,1000,history['current_symbol'])
        self.assertIsNone(result['windows']['20']['percentile'])
        self.assertEqual(result['windows']['20']['missing'][0]['reason'],'dividend_missing')
        self.assertEqual(result['windows']['20']['samples'],19)

    def test_company_mixed_dates_and_missing_weights_keep_members_and_classification(self):
        sdk=FakeWind();original=sdk.wset
        def mixed(kind,options):
            value=original(kind,options)
            if kind=='indexconstituent':
                i=value.Fields.index('date');w=value.Fields.index('i_weight')
                if '000016.SH' in options:value.Data[i]=[datetime(2026,9,30)]*50
                else:value.Data[w][0]=None;value.Data[i][0]=datetime(2026,9,30)
            return value
        sdk.wset=mixed
        result=refresh(sdk,dict(day='2026-10-23',fetched_at=NOW.isoformat(),old={},config={},stage='indices'))
        data=validate(result['data'])
        self.assertEqual([len(data['indices'][r]['rows']) for r in ('IF','IH','IC','IM')],[300,50,500,1000])
        self.assertTrue(all(all(m['industry'] for m in g['rows']) for g in data['indices'].values()))
        self.assertFalse(data['indices']['IF']['weights_complete']);self.assertIsNone(data['indices']['IF']['rows'][0]['weight_pct'])
        self.assertEqual(data['indices']['IH']['as_of'],'2026-09-30')
        snapshot=equity_snapshot();snapshot['reference_version']='v'
        detail=contributions(data['indices']['IF'],snapshot,dict(symbol='000300.SH'),NOW,'2026-10-23','v')
        self.assertEqual(detail['expected'],300);self.assertIsNone(detail['contribution_points'])
        self.assertIsNone(detail['coverage_pct']);self.assertFalse(detail['leaders'])

    def test_dated_nav_premium_is_separate_from_live_iopv(self):
        request=dict(day='2026-10-23',fetched_at=NOW.isoformat(),old={},config={},stage='etfs')
        result=refresh(FakeWind(),request);data=validate(result['data'])
        self.assertEqual(len(data['etf_nav']['rows']),3)
        first=next(iter(data['etf_nav']['rows']));data['etf_nav']['rows'][first]['close_cny']=101
        state=dict(indices=[],etfs=[dict(symbol=first,root='IF',quality=dict(usable=False),iopv_id=None,
            iopv=None,premium_bp=None,series=[])],previous_session='2026-10-23')
        model=SimpleNamespace(config={},live_rows=pd.DataFrame())
        enrich(model,state,dict(data=data,version='fixture',due=False,error=None),NOW)
        self.assertAlmostEqual(state['etfs'][0]['closing_premium_bp'],100)
        self.assertIsNone(state['etfs'][0]['premium_bp']);self.assertIsNone(state['etfs'][0]['iopv'])
        self.assertEqual(state['etfs'][0]['nav_date'],'2026-10-23')
        bad=deepcopy(data);bad['etf_nav']['rows'][first]['as_of']='2027-01-01'
        with self.assertRaises(ValueError):validate(bad)

    def test_nav_task_does_not_repeat_weekly_universe_or_refresh_weekly_review_date(self):
        old=refresh(FakeWind(),dict(day='2026-10-23',fetched_at=NOW.isoformat(),old={},config={},stage='etfs'))['data']
        sdk=FakeWind();value=refresh(sdk,dict(day='2026-10-26',fetched_at='2026-10-27T10:00:00+08:00',old=old,config={},stage='nav'))['data']
        self.assertEqual({kind for kind,_,_ in sdk.calls},{'WSD'})
        self.assertEqual({field for _,field,_ in sdk.calls},{'nav','close'})
        self.assertEqual(value['reference_reviewed_at'],old['reference_reviewed_at'])
        self.assertTrue(all(r['as_of']=='2026-10-26' for r in value['etf_nav']['rows'].values()))

    def test_daily_nav_attempt_is_bounded_independently_from_weekly_attempt(self):
        value=reference();value['errors']=['weights pending']
        with tempfile.TemporaryDirectory() as tmp,patch('subprocess.Popen',side_effect=OSError('fixture')) as spawn:
            path=Path(tmp)/'overview_reference/latest.json';publish(path,value)
            job=ReferenceJob(tmp);job.tick({},enabled=True,now=NOW.to_pydatetime(),force=True)
            job.tick({},enabled=True,now=NOW.to_pydatetime());job.tick({},enabled=True,now=NOW.to_pydatetime())
            self.assertEqual(spawn.call_count,2);self.assertEqual(job.state()['status'],'nav_attempted_today')
            self.assertEqual(json.loads((path.parent/'nav-attempt.json').read_text())['day'],'2026-10-26')
            self.assertTrue((path.parent/'attempt.json').exists())
            # An unpublished post-close NAV may become available the next
            # morning: the target stays the same, but the local check day changes.
            later=NOW+pd.Timedelta(days=1)
            from dashboard.marketdata.overview_sessions import latest_completed_session
            with patch('dashboard.marketdata.overview_sessions.latest_completed_session',return_value='2026-10-26'):
                job.tick({},enabled=True,now=later.to_pydatetime())
            self.assertEqual(spawn.call_count,3)

    def test_bad_dividend_workbook_does_not_fail_quote_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'broken.xlsx';path.write_bytes(b'not a zip')
            book=load_dividends(dict(overview_dividend_file=str(path)),metadata(),DAY)
            self.assertTrue(book.reason);self.assertIsNone(book.points('IF2611.CFE',DAY))
            from dashboard.native.market_overview import MarketOverviewEngine
            live={'000300.SH':observation(1000,at=NOW),'IF2611.CFE':observation(990,at=NOW)}
            repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={};repo.read_window.return_value=pd.DataFrame()
            model=SimpleNamespace(config=dict(overview_dividend_file=str(path)),configure_repository=lambda _:repo,
                _live=lambda *a:live,live_rows=pd.DataFrame())
            with patch('dashboard.native.market_overview.ReferenceBook',return_value=SimpleNamespace(data={},version='fixture')),\
                 patch('dashboard.native.market_overview.latest_contracts',return_value=metadata()):
                result=MarketOverviewEngine(model).snapshot(now=NOW)['market_overview']
            self.assertEqual(result['indices'][0]['price'],1000);self.assertTrue(result['dividend_reason'])
            future=next(r for r in result['futures'] if r['symbol']=='IF2611.CFE')
            self.assertEqual(future['price'],990);self.assertEqual(future['raw_basis_points'],-10);self.assertIsNone(future['annual_pct'])

    def test_stop_cancels_only_owned_blocking_wind_reader_and_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sdk=root/'sdk';sdk.mkdir();stop=root/'stop';marker=root/'entered'
            (sdk/'WindPy.py').write_text('import time\nfrom pathlib import Path\nclass Wind:\n'
                ' def start(self,**kw):\n  Path('+repr(str(marker))+').touch()\n  time.sleep(20)\n'
                ' def isconnected(self):return True\n def stop(self):pass\nw=Wind()\n',encoding='utf8')
            old=root/'latest.json';old.write_text('preserve snapshot',encoding='utf8');before=old.read_bytes()
            def cancel():
                deadline=time.monotonic()+4
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
                stop.touch()
            thread=threading.Thread(target=cancel,daemon=True);thread.start();started=time.monotonic()
            with patch.dict(os.environ,{'PYTHONPATH':str(sdk)}),self.assertRaises(InterruptedError):
                terminal_refresh(dict(overview_wind_python=sys.executable),root,{},now=NOW.to_pydatetime(),stop_file=stop)
            thread.join(1);self.assertLess(time.monotonic()-started,3)
            self.assertEqual(old.read_bytes(),before)

    def test_headline_schedule_and_equity_stop_are_independent(self):
        from tests.test_app_collection import FakeClient
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True)),\
             patch('dashboard.native.collection.collect') as collect:
            factory=Mock(return_value=FakeClient());job=CollectionJob(tmp)
            job.start(Path(tmp)/'quotes',['000300.SH'],{'000300.SH'},client_factory=factory,config={});job.worker.join(3)
            self.assertFalse(job.running());self.assertEqual(collect.call_args.kwargs['interval'],3)
            self.assertEqual(factory.call_args.kwargs,dict(connect_timeout=1,read_timeout=2))
            job.equities=Mock();job.stop();job.equities.stop.assert_called_once()

    def test_live_editions_do_not_construct_research_service(self):
        from tests.test_app_pipeline import APP
        from dashboard.native.editions_current import PresentationWindow,DeveloperWindow
        from dashboard.native.model import NativeModel
        for cls in (PresentationWindow,DeveloperWindow):
            with tempfile.TemporaryDirectory() as tmp,patch('dashboard.indicator_v6.service.Service') as service:
                model=NativeModel(tmp);window=cls(model);window.timer.stop()
                self.assertEqual(window.research_pages,{});self.assertEqual(window.pages.count(),1)
                service.assert_not_called();window.close();APP.processEvents()

    def test_no_known_history_gap_starts_realtime_without_waiting_for_wind(self):
        from tests.test_app_pipeline import PipelineTests
        fixture=PipelineTests();window,pipeline=fixture.fixture();pipeline.enabled=True
        try:
            result=dict(quick=dict(known_pending=240,unknown_groups=12600),overview_pending=0,credentials=dict(available=True),preview=None)
            with patch.object(pipeline,'submit',side_effect=lambda work,done:done(result)),\
                 patch.object(pipeline,'request_realtime') as realtime,patch.object(pipeline,'request_history') as history,\
                 patch.object(pipeline,'one_click') as wind:
                pipeline.inspect();realtime.assert_called_once();history.assert_not_called();wind.assert_not_called()
        finally:fixture.doCleanups()

    def test_settings_wait_for_reference_reader_before_changing_paths(self):
        from tests.test_app_pipeline import APP
        from dashboard.native.inline_settings import InlineSettings
        with tempfile.TemporaryDirectory() as tmp:
            pipeline=SimpleNamespace(model=SimpleNamespace(config={},local_root=Path(tmp)),history=SimpleNamespace(process=None),
                collection=SimpleNamespace(running=lambda:False),task=None,window=SimpleNamespace(busy=False),
                overview_reference=SimpleNamespace(running=lambda:True),readonly=Mock())
            settings=InlineSettings(pipeline)
            self.assertFalse(settings.idle());pipeline.readonly.assert_called_once();settings.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
