"""Company October 29: durable shutdown, actual NAV and honest input evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import pandas as pd

from dashboard.marketdata.equity_observations import EquityObservationStore
from dashboard.marketdata.overview_reference import closing_nav, publish
from dashboard.marketdata.overview_audit import collect
from dashboard.overview_check import sample, app_reports
from index_strategy.instant_dld.reader import RealtimeReader
from index_strategy.instant_dld.realtime_store import publish_parquet, WriterLock, WriterBusyError
from tests.test_realtime_store import quote
from tests.test_market_overview import ZERO_DIVIDENDS, observation
from tests.test_overview_details import reference


NOW=pd.Timestamp('2026-10-29T11:05:20+08:00')


def populate(store, count=205, polls=1):
    store.next_archive=time.monotonic()+3600
    symbols=[str(600000+i)+'.SH' for i in range(count)]
    for poll in range(1,polls+1):
        for offset in range(0,count,100):
            selected=symbols[offset:offset+100]
            store.batch(dict(received_at=NOW.isoformat(),symbols=selected,status='success',poll=poll,batch=offset//100+1,
                batch_count=(count+99)//100,response=dict(data={s:quote(total=poll*1000,source=110520) for s in selected})))
    return symbols


class ArchiveShutdownTests(unittest.TestCase):
    def test_bounded_parallel_files_keep_original_reader_format_and_writer_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            progress=[];store=EquityObservationStore(tmp,progress=progress.append)
            symbols=populate(store,polls=3)
            active=peak=0;lock=threading.Lock()
            def write(*args,**kwargs):
                nonlocal active,peak
                with lock:active+=1;peak=max(peak,active)
                try:
                    with self.assertRaises(WriterBusyError):WriterLock(Path(tmp))
                    time.sleep(.005)
                    return publish_parquet(*args,**kwargs)
                finally:
                    with lock:active-=1
            with patch('dashboard.marketdata.equity_observations.publish_parquet',side_effect=write):store.close()
            self.assertGreater(peak,1);self.assertLessEqual(peak,4);self.assertEqual(active,0)
            self.assertEqual(progress[-1]['status'],'complete');self.assertEqual(progress[-1]['symbols_finished'],205)
            self.assertEqual(progress[-1]['rows_published'],615)
            reader=RealtimeReader(tmp)
            with reader.connect() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM quotes').fetchone()[0],615)
                self.assertEqual(con.execute('SELECT SUM(rows) FROM parquet_parts').fetchone()[0],615)
            for symbol in symbols[::17]:self.assertEqual(len(reader.read_parquet_day(symbol,'2026-10-29')),3)
            released=WriterLock(Path(tmp))
            released.close()

    def test_archive_failure_drains_owned_writers_and_replays_from_durable_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EquityObservationStore(tmp);populate(store)
            active=0;lock=threading.Lock()
            def failed(table,directory,prefix,**kwargs):
                nonlocal active
                with lock:active+=1
                try:
                    if '600000.SH' in str(directory):raise OSError('synthetic disk failure')
                    time.sleep(.01)
                    return publish_parquet(table,directory,prefix,**kwargs)
                finally:
                    with lock:active-=1
            with patch('dashboard.marketdata.equity_observations.publish_parquet',side_effect=failed):
                with self.assertRaises(OSError):store.close()
            self.assertEqual(active,0)
            before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(tmp).rglob('*.parquet')}
            reader=RealtimeReader(tmp)
            with reader.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM quotes').fetchone()[0],205)
            EquityObservationStore(tmp).close()
            for p,sha in before.items():self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),sha)
            with reader.connect() as con:self.assertEqual(con.execute('SELECT SUM(rows) FROM parquet_parts').fetchone()[0],205)
            self.assertEqual(len(reader.read_parquet_day('600000.SH','2026-10-29')),1)

    def test_shutdown_reports_archive_progress_and_final_drained_state(self):
        from tests.test_app_pipeline import PipelineTests
        fixture=PipelineTests();window,pipeline=fixture.fixture()
        try:
            pipeline.collection.state.return_value=dict(equities=dict(status='draining',archive=dict(status='archiving',symbols_finished=64,symbols_total=205)))
            window.busy=True;pipeline.stop()
            self.assertIn('页面计算',pipeline.shutdown_state()['waiting'])
            self.assertIn('64/205',pipeline.shutdown_message())
            self.assertFalse(pipeline.shutdown_state()['complete'])
            window.busy=False;pipeline.finish_shutdown()
            result=json.loads(pipeline.report_path.read_text(encoding='utf8'))
            self.assertTrue(result['shutdown']['complete']);self.assertFalse(result['shutdown']['waiting'])
            self.assertEqual(result['phase'],'closed')
        finally:
            pipeline.timer.stop();fixture.doCleanups()


class CompanyEvidenceTests(unittest.TestCase):
    def full_reference(self):
        value=reference();value['fetched_at']='2026-10-29T10:11:02+08:00';value['indices']={}
        offset=0
        for root,size,spot in (('IF',300,'000300.SH'),('IH',50,'000016.SH'),('IC',500,'000905.SH'),('IM',1000,'000852.SH')):
            rows=[dict(symbol=str(600000+offset+i)+'.SH',weight_pct=100/size,industry='电子') for i in range(size)]
            rows[0]['weight_pct']=None
            value['indices'][root]=dict(index_id=spot,as_of='2026-10-28',source='synthetic company boundary',
                membership_complete=True,membership_as_of='2026-10-28',weights_complete=False,rows=rows)
            offset+=size
        return value

    def audit(self,root,value,*,replace_later=False,cutoff=None):
        publish(Path(root)/'overview_reference/latest.json',value)
        quotes={'600000.SH':observation(100,99,NOW)}
        path=Path(root)/'overview_equities/latest.json';path.parent.mkdir()
        snapshot=dict(schema='overview-equities-v1',snapshot_id='first',reference_version='synthetic',finished_at=(cutoff or NOW).isoformat(),quotes=quotes)
        path.write_text(json.dumps(snapshot),encoding='utf8')
        def delayed(*args,**kwargs):
            if replace_later:path.write_text(json.dumps(dict(snapshot,snapshot_id='later',finished_at=(NOW+pd.Timedelta(seconds=3)).isoformat())),encoding='utf8')
            return {},dict(rows=[]),[]
        with patch('dashboard.marketdata.overview_audit.inspect_history',return_value=(None,{},dict(inventory=[]))),\
                patch('dashboard.marketdata.overview_audit.daily_inputs',side_effect=delayed),\
                patch('dashboard.marketdata.overview_audit.calculation_preview',return_value={}),\
                patch('dashboard.marketdata.overview_audit.requests',return_value=[]),\
                patch('dashboard.marketdata.overview_basis.load_dividends',return_value=ZERO_DIVIDENDS):
            result=collect({},root,now=NOW)
        return result

    def test_complete_membership_is_known_even_if_weights_are_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self.audit(tmp,self.full_reference(),replace_later=True)
        self.assertTrue(result['ddb']['all_four_equity_universes_known'])
        self.assertTrue(result['constituent_quotes']['all_four_universes_known'])
        self.assertEqual(result['constituent_quotes']['total_missing_count'],1849)
        self.assertEqual(result['summary']['missing_membership_roots'],[])
        self.assertEqual(result['summary']['missing_industry_symbols'],0)
        self.assertEqual(result['constituent_quotes']['quality_evaluation'],'valid')
        self.assertEqual(result['constituent_quotes']['stale_at_snapshot_symbols'],[])

    def test_snapshot_after_audit_start_has_unknown_quality_not_all_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self.audit(tmp,self.full_reference(),cutoff=NOW+pd.Timedelta(seconds=1))
        self.assertEqual(result['constituent_quotes']['quality_evaluation'],'snapshot_after_audit_start')
        self.assertIsNone(result['constituent_quotes']['stale_at_snapshot_symbols'])

    def test_nav_is_present_in_readonly_sample_and_actual_group_card(self):
        from tests.test_app_pipeline import APP
        from dashboard.native.overview_pages import EtfCard
        value=reference();value['fetched_at']='2026-10-29T10:00:00+08:00'
        value['etf_nav']=dict(schema='etf-nav-v1',rows={'510301.SH':dict(symbol='510301.SH',as_of='2026-10-28',nav_cny=4,close_cny=3.992,source='synthetic same-day pair')})
        expected=closing_nav(value,'510301.SH','2026-10-29')
        self.assertAlmostEqual(expected['closing_premium_bp'],-20)
        with tempfile.TemporaryDirectory() as tmp:
            publish(Path(tmp)/'overview_reference/latest.json',value)
            report=sample({},tmp,now=NOW)
        actual=report['etfs']['IF']['closing_nav'][0]
        self.assertEqual(actual['nav_date'],'2026-10-28');self.assertAlmostEqual(actual['closing_premium_bp'],-20)
        card=EtfCard(None)
        try:
            card.render(dict(symbol='510301.SH',name='Synthetic ETF',quality={},**expected),1)
            self.assertIn('盘中折溢价',card.premium.text());self.assertIn('-20.0',card.closing_premium.text())
            self.assertIn('2026-10-28',card.closing_premium.text());self.assertIn('待接入',card.iopv.text())
        finally:card.close();card.deleteLater();APP.processEvents()

    def test_exported_shutdown_and_archive_evidence_omit_unknown_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run/status.json';path.parent.mkdir()
            path.write_text(json.dumps(dict(schema='app-update-evidence-v1',local_root=tmp,shutdown=dict(requested=True,complete=True,waiting=[],elapsed_seconds=2,password='CANARY'),
                collection=dict(equities=dict(status='stopped',password='CANARY',archive=dict(status='complete',symbols_total=1800,symbols_finished=1800,secret='CANARY'))))),encoding='utf8')
            value=app_reports(tmp,tmp)
        row=value['matching_profile'][0]
        self.assertTrue(row['shutdown']['complete']);self.assertEqual(row['collection']['equities']['archive']['symbols_finished'],1800)
        self.assertNotIn('CANARY',json.dumps(value))


if __name__=='__main__':unittest.main()
