"""Company time-only HTTP samples need archived live-session corroboration."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

import pandas as pd

from dashboard.marketdata import overview_daily as daily
from dashboard.marketdata import overview_http_closes as http
from dashboard.marketdata import history_maintenance as hm
from dashboard.marketdata import ddb_vpn as vpn
from dashboard.marketdata.overview_percentiles import prepare,evaluate
from tests.test_overview_http_closes import DAY,NOW,FUTURE,SPOT,record,reference_file
from tests.test_overview_percentiles import metadata,daily_data
from tests.test_market_overview import ZERO_DIVIDENDS,observation


def packet(at=NOW,*,price=4001.,previous=4000.):
    result=record(clock=at)
    for quote in result['response']['data'].values():
        quote.pop('tradeDate');quote.update(latestPrice=price,yesterdayClosePrice=previous,
            quoteTimestamp=int((at-pd.Timedelta(seconds=1)).strftime('%H%M%S')),createTime=0,updateTime=0)
    return result


def ingest(root,value,*,config=None,meta=None):
    return http.ingest(value,config or {},root,meta or metadata(),now=pd.Timestamp(value['received_at']))


class SessionEvidenceTests(unittest.TestCase):
    def test_two_real_changes_save_close_with_two_hashed_witnesses_and_an_inferred_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=ingest(tmp,packet())
            self.assertEqual(first['inserted'],0)
            self.assertEqual({r['reason'] for r in first['rejected']},{'live_session_evidence_pending'})
            second=ingest(tmp,packet(NOW+pd.Timedelta(seconds=3),price=4002.))
            self.assertEqual(second['inserted'],2);self.assertEqual(second['session_inferred_rows'],2)
            for row in daily.read_day({},tmp,DAY)['rows'].values():
                self.assertEqual(row['close'],4000.);self.assertIsNone(row['oi'])
                self.assertEqual(row['source_date_basis'],'corroborated_live_session')
                proof=row['date_evidence'];self.assertFalse(proof['exchange_date_certified'])
                self.assertFalse(proof['source_trade_date_explicit']);self.assertEqual(proof['witness_count'],2)
                for witness in proof['witnesses']:
                    raw=witness['raw_response'];content=(Path(raw['root'])/raw['path']).read_bytes()
                    self.assertEqual(hashlib.sha256(content).hexdigest(),raw['sha256'])

    def test_service_update_metadata_or_a_moving_clock_without_market_change_is_insufficient(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingest(tmp,packet());second=packet(NOW+pd.Timedelta(seconds=3))
            for q in second['response']['data'].values():q.update(createTime=1794366000000,updateTime=1794366003000)
            value=ingest(tmp,second)
            self.assertEqual(value['inserted'],0)
            self.assertEqual({r['reason'] for r in value['rejected']},{'market_values_not_advanced'})

    def test_frozen_reversed_and_wrong_rate_source_clocks_do_not_prove_today(self):
        for seconds,source,reason in ((3,100002,'live_session_clock_not_advanced'),
                                     (3,100001,'live_session_clock_reversed'),(20,100005,'live_session_clock_rate_mismatch')):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as tmp:
                ingest(tmp,packet());second=packet(NOW+pd.Timedelta(seconds=seconds),price=4002.)
                for q in second['response']['data'].values():q['quoteTimestamp']=source
                value=ingest(tmp,second)
                self.assertEqual(value['inserted'],0);self.assertEqual({r['reason'] for r in value['rejected']},{reason})

    def test_preopen_lunch_postclose_and_old_quotes_never_infer_a_daily_date(self):
        for clock in ('09:00:03','12:10:03','15:20:03'):
            at=pd.Timestamp('2026-11-11T'+clock+'+08:00')
            with self.subTest(clock=clock),tempfile.TemporaryDirectory() as tmp:
                ingest(tmp,packet(at));value=ingest(tmp,packet(at+pd.Timedelta(seconds=3),price=4002.))
                self.assertEqual(value['inserted'],0);self.assertEqual(daily.read_day({},tmp,DAY),{})
                self.assertEqual({r['reason'] for r in value['rejected']},{'live_session_required'})
        with tempfile.TemporaryDirectory() as tmp:
            source=packet()
            for q in source['response']['data'].values():q['quoteTimestamp']=95900
            self.assertEqual({r['reason'] for r in ingest(tmp,source)['rejected']},{'quote_not_fresh_for_session'})

    def test_explicit_old_or_conflicting_dates_are_not_overridden_by_corroboration(self):
        for fields in (dict(tradeDate='2026-11-10'),dict(tradeDate='2026-11-11',tradingDay='2026-11-10')):
            with self.subTest(fields=fields),tempfile.TemporaryDirectory() as tmp:
                ingest(tmp,packet());second=packet(NOW+pd.Timedelta(seconds=3),price=4002.)
                for q in second['response']['data'].values():q.update(fields)
                self.assertEqual(ingest(tmp,second)['inserted'],0)

    def test_new_day_and_afternoon_require_new_witnesses(self):
        for at in (NOW+pd.Timedelta(days=1),NOW.replace(hour=13)):
            with self.subTest(at=at),tempfile.TemporaryDirectory() as tmp:
                ingest(tmp,packet());second=ingest(tmp,packet(at,price=4002.))
                self.assertEqual(second['inserted'],0)
                self.assertEqual({r['reason'] for r in second['rejected']},{'live_session_evidence_pending'})
                third=ingest(tmp,packet(at+pd.Timedelta(seconds=3),price=4003.))
                self.assertEqual(third['inserted'],2)

    def test_expired_proof_and_corrupt_session_file_restart_with_one_unproven_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingest(tmp,packet());at=NOW+pd.Timedelta(seconds=121)
            self.assertEqual(ingest(tmp,packet(at,price=4002.))['inserted'],0)
            path=Path(tmp)/'overview_daily/http_previous_close/session_evidence.json';path.write_text('broken',encoding='utf8')
            value=ingest(tmp,packet(at+pd.Timedelta(seconds=3),price=4003.))
            self.assertEqual(value['inserted'],0)
            self.assertEqual({r['reason'] for r in value['rejected']},{'live_session_evidence_pending'})

    def test_corrupted_first_raw_witness_cannot_authorize_a_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingest(tmp,packet())
            book=json.loads((Path(tmp)/'overview_daily/http_previous_close/session_evidence.json').read_text())
            reference=book['quotes'][SPOT]['raw_response'];(Path(reference['root'])/reference['path']).write_bytes(b'changed')
            result=ingest(tmp,packet(NOW+pd.Timedelta(seconds=3),price=4002.))
            self.assertEqual(result['inserted'],0)
            self.assertEqual({r['reason'] for r in result['rejected']},{'prior_session_witness_unavailable'})
            self.assertEqual(ingest(tmp,packet(NOW+pd.Timedelta(seconds=6),price=4003.))['inserted'],2)

    def test_changed_previous_close_needs_two_new_stable_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingest(tmp,packet())
            value=ingest(tmp,packet(NOW+pd.Timedelta(seconds=3),price=4002.,previous=3999.))
            self.assertEqual(value['inserted'],0)
            self.assertEqual({r['reason'] for r in value['rejected']},{'previous_close_changed_during_session'})
            self.assertEqual(ingest(tmp,packet(NOW+pd.Timedelta(seconds=6),price=4003.,previous=3999.))['inserted'],2)
            self.assertEqual(daily.read_day({},tmp,DAY)['rows'][FUTURE]['close'],3999.)

    def test_bad_identity_is_isolated_even_after_first_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingest(tmp,packet());second=packet(NOW+pd.Timedelta(seconds=3),price=4002.)
            second['response']['data'][FUTURE]['securityId']='IF2612.CFE'
            result=ingest(tmp,second)
            self.assertEqual(result['inserted'],1);self.assertEqual(set(daily.read_day({},tmp,DAY)['rows']),{SPOT})

    def test_explicit_only_override_and_missing_current_trade_do_not_infer_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=dict(overview_http_session_evidence_enabled=False)
            value=ingest(tmp,packet(),config=config)
            self.assertEqual({r['reason'] for r in value['rejected']},{'source_trade_date_missing'})
            self.assertFalse((Path(tmp)/'overview_daily/http_previous_close/session_evidence.json').exists())
        with tempfile.TemporaryDirectory() as tmp:
            value=packet()
            for q in value['response']['data'].values():q['latestPrice']=0
            self.assertEqual(ingest(tmp,value)['inserted'],0)
            self.assertEqual(daily.read_day({},tmp,DAY),{})

    def test_witnessed_closes_restore_both_windows_with_visible_date_provenance(self):
        meta=metadata();prices=daily_data(meta,day='2026-11-11')
        for symbol in (FUTURE,SPOT):prices[symbol]=prices[symbol][prices[symbol].trade_date.ne(DAY)]
        with tempfile.TemporaryDirectory() as tmp:
            ingest(tmp,packet());ingest(tmp,packet(NOW+pd.Timedelta(seconds=3),price=4002.))
            for symbol,row in daily.read_day({},tmp,DAY)['rows'].items():
                prices[symbol]=daily.merge_daily(prices[symbol],[dict(row,open_interest=row['oi'])])
        output=evaluate(prepare('IF',0,meta,prices,'2026-11-11',dividends=ZERO_DIVIDENDS),0,FUTURE)
        for window in output['windows'].values():
            self.assertEqual(window['percentile'],50.);self.assertEqual(window['http_session_inferred_dates'],[DAY])
            self.assertEqual(window['http_session_inferred_count'],1);self.assertIn('日期推定',window['reason'])


class SessionRoutingTests(unittest.TestCase):
    def test_maintenance_waits_for_two_bounded_requests_before_publishing(self):
        client=Mock();client.fetch.side_effect=[packet(),packet(NOW+pd.Timedelta(seconds=3),price=4002.)]
        pause=Mock(return_value=True)
        jobs=[dict(day=DAY,asset='future',symbols=[FUTURE]),dict(day=DAY,asset='index',symbols=[SPOT])]
        with tempfile.TemporaryDirectory() as tmp:
            value=http.collect({},tmp,DAY,metadata(),jobs=jobs,now=NOW,client_factory=lambda **kw:client,pause=pause)
        self.assertEqual(value['inserted'],2);self.assertEqual(value['session_inferred_rows'],2)
        self.assertEqual(value['network_requests'],2);pause.assert_called_once();self.assertEqual(client.fetch.call_count,2)
        client.close.assert_called_once()

    def test_fixed_snapshot_has_two_attempt_limit_and_stop_does_not_fetch_again(self):
        jobs=[dict(day=DAY,asset='index',symbols=[SPOT])]
        client=Mock();client.fetch.side_effect=lambda symbols:packet()
        with tempfile.TemporaryDirectory() as tmp:
            value=http.collect({},tmp,DAY,metadata(),jobs=jobs,now=NOW,client_factory=lambda **kw:client,pause=lambda *a:True)
        self.assertEqual(value['inserted'],0);self.assertEqual(client.fetch.call_count,2)
        stopped=threading.Event();client.reset_mock()
        def cancel(*args):stopped.set();return False
        with tempfile.TemporaryDirectory() as tmp:
            value=http.collect({},tmp,DAY,metadata(),jobs=jobs,now=NOW,client_factory=lambda **kw:client,
                pause=cancel,stop=stopped.is_set)
        self.assertEqual(value['status'],'cancelled');self.assertEqual(client.fetch.call_count,1)

    def test_auto_ddb_remains_enabled_and_reuses_a_manually_connected_tunnel_after_http(self):
        original_collect=http.collect;events=[];observations=[packet(),packet(NOW+pd.Timedelta(seconds=3),price=4002.)]
        class Client:
            def __init__(self,**kwargs):pass
            def fetch(self,symbols):events.append('http');return deepcopy(observations.pop(0))
            def close(self):events.append('http_closed')
        def collect(*args,**kwargs):return original_collect(*args,**kwargs,pause=lambda *a:True)
        def jobs(config,root,target,meta):
            saved=daily.read_day(config,root,target).get('rows',{})
            result=[dict(day=DAY,asset='future',symbols=[FUTURE],requires_oi=True)]
            if SPOT not in saved:result.append(dict(day=DAY,asset='index',symbols=[SPOT]))
            result.append(dict(day='2026-11-09',asset='future',symbols=[FUTURE]))
            return result
        def fill(client,config,root,target,meta,**kwargs):
            pending=jobs(config,root,target,meta)
            self.assertEqual({j['asset'] for j in pending},{'future'})
            self.assertIsNone(daily.read_day(config,root,DAY)['rows'][FUTURE]['oi'])
            return dict(status='complete',pending_rows=0,inserted=2)
        client=Mock()
        def direct(path):events.append('ddb');return client
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);ref=reference_file(root,metadata());config=dict(reference_file=str(ref),history_roots=[str(root/'history')])
            stack.enter_context(patch('dashboard.marketdata.repository.MarketDataRepository'))
            stack.enter_context(patch.object(daily,'seed_local',return_value=0))
            stack.enter_context(patch.object(daily,'requests',side_effect=jobs))
            stack.enter_context(patch.object(daily,'fill',side_effect=fill))
            stack.enter_context(patch.object(http,'collect',side_effect=collect))
            stack.enter_context(patch('index_strategy.instant_dld.client.MarketDataClient',Client))
            stack.enter_context(patch('index_strategy.history.credentials.load_config',return_value=dict(host='old.invalid',port=8903,
                username='PRIVATE_USER',password='PRIVATE_PASSWORD',enable_ssl=True)))
            reachable=stack.enter_context(patch.object(vpn,'reachable',return_value=True))
            login=stack.enter_context(patch.object(vpn,'invoke',side_effect=AssertionError('existing tunnel must be reused')))
            result=hm._run_overview_cycle(root,config,budget=45,stop_file=None,direct_factory=direct,lifetime=None,
                vpn_mode='auto',include_completed_today=True,now=NOW)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['http_previous_close']['inserted'],2)
        self.assertEqual(result['ddb_vpn']['mode'],'existing_tunnel');login.assert_not_called()
        reachable.assert_called_once_with('192.168.198.77',8904,True)
        self.assertEqual(events,['http','http','http_closed','ddb']);client.close.assert_called_once()
        self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_same_page_recalculates_after_witnessed_close_publication(self):
        from types import SimpleNamespace
        from dashboard.native.market_overview import MarketOverviewEngine
        meta=metadata();prices=daily_data(meta,day='2026-11-11')
        for symbol in (FUTURE,SPOT):prices[symbol]=prices[symbol][prices[symbol].trade_date.ne(DAY)]
        repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={}
        repo.read_window.side_effect=lambda symbol,*a,**kw:prices.get(symbol,pd.DataFrame())
        live={s:observation(4000.,4000.,NOW) for s in set(meta)|set(http.ROOTS.values())}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ref=reference_file(root,meta)
            model=SimpleNamespace(local_root=root,config=dict(reference_file=str(ref)),configure_repository=lambda _:repo,
                _live=lambda *a:live,live_rows=pd.DataFrame())
            engine=MarketOverviewEngine(model)
            with patch('dashboard.native.market_overview.load_dividends',return_value=ZERO_DIVIDENDS):
                old=next(r for r in engine.snapshot(now=NOW)['market_overview']['futures'] if r['symbol']==FUTURE)
                self.assertIsNone(old['percentile_60'])
                ingest(tmp,packet());ingest(tmp,packet(NOW+pd.Timedelta(seconds=3),price=4002.))
                new=next(r for r in engine.snapshot(now=NOW)['market_overview']['futures'] if r['symbol']==FUTURE)
            self.assertEqual(new['percentile_20'],50.);self.assertEqual(new['percentile_60'],50.)
            self.assertIn('日期推定',new['continuous_percentiles']['windows']['60']['reason'])

    def test_safe_summary_never_exports_raw_witness_payload(self):
        value=http.safe_status(dict(session_inferred_rows=2,date_evidence=[dict(symbol=SPOT,basis='corroborated_live_session',
            witness_count=2,exchange_date_certified=False,response_body='PRIVATE_BODY',password='PRIVATE_PASSWORD')]))
        self.assertNotIn('PRIVATE_',json.dumps(value));self.assertEqual(value['session_inferred_rows'],2)

    def test_safe_app_report_retains_reused_vpn_mode_and_specific_failure_code(self):
        from dashboard.overview_check import app_reports
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sessions/run/status.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(schema='app-update-evidence-v1',local_root=tmp,history=dict(
                updated_at=NOW.isoformat(),error_code='login',ddb_vpn=dict(state='connected',mode='existing_tunnel',
                tcp_verified=True,password='PRIVATE_PASSWORD')))),encoding='utf8')
            value=app_reports(tmp,Path(tmp)/'sessions')['matching_profile'][0]['history_update']
        self.assertEqual(value['error_code'],'login');self.assertEqual(value['ddb_vpn']['mode'],'existing_tunnel')
        self.assertNotIn('PRIVATE_',json.dumps(value))


if __name__=='__main__':unittest.main()
