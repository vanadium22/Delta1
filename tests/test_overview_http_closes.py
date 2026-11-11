"""HTTP previous-close provenance, calendar/contract boundaries and DDB routing."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import pandas as pd

from dashboard.marketdata import overview_daily as daily
from dashboard.marketdata import overview_http_closes as http
from dashboard.marketdata import history_maintenance as hm
from dashboard.marketdata.overview_percentiles import prepare,evaluate
from tests.test_market_overview import ZERO_DIVIDENDS
from tests.test_overview_percentiles import metadata,daily_data
from tests.test_overview_data import close_row

DAY='2026-11-10'
NOW=pd.Timestamp('2026-11-11T10:00:03+08:00')
FUTURE='IF2611.CFE'
SPOT='000300.SH'


def quote(symbol,**changes):
    return dict(securityId=symbol,tradeDate='20261111',quoteTimestamp=100002,
        yesterdayClosePrice=4000.,latestPrice=4010.,openingPrice=4005.,highPrice=4015.,lowPrice=3995.,
        closingPrice=4020.,preSettlementPrice=3988.,openInterest=12345.,**changes)


def record(symbols=(FUTURE,SPOT),*,clock=NOW,**changes):
    data={s:quote(s) for s in symbols}
    return dict(status='success',symbols=list(symbols),requested_symbols=list(symbols),
        received_at=clock.isoformat(),response=dict(data=data),**changes)


def reference_file(root,meta):
    path=Path(root)/'reference.json'
    path.write_text(json.dumps(dict(schema_version='cn_index_reference_v1',aliases=[],contracts=[
        dict(instrument_id=s,known_at='2026-01-01T00:00:00Z',**r) for s,r in meta.items()])),encoding='utf8')
    return path


class HttpPreviousCloseTests(unittest.TestCase):
    def test_valid_previous_closes_are_dated_archived_and_do_not_copy_current_oi_or_ohlc(self):
        source=record();before=deepcopy(source)
        with tempfile.TemporaryDirectory() as tmp:
            result=http.ingest(source,{},tmp,metadata(),now=NOW)
            self.assertEqual(result['inserted'],2);self.assertEqual(result['target'],DAY)
            rows=daily.read_day({},tmp,DAY)['rows']
            for symbol,row in rows.items():
                self.assertEqual(row['close'],4000.);self.assertEqual(row['source_trade_date'],'2026-11-11')
                self.assertEqual(row['source_security_id'],symbol);self.assertTrue(row['is_final'])
                for field in ('oi','open','high','low','volume','amount'):self.assertIsNone(row[field])
                raw=row['raw_response'];content=(Path(raw['root'])/raw['path']).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(),raw['sha256'])
                self.assertEqual(row['source_at'],DAY+'T15:00:00+08:00')
            self.assertEqual(source,before)

    def test_missing_or_conflicting_source_dates_never_use_receipt_or_mapping_date(self):
        for changes in (dict(tradeDate=None),dict(tradeDate='2026-11-10'),dict(tradeDate='2026-11-12'),
                        dict(tradeDate='20261111',tradingDay='2026-11-10'),dict(tradeDate='2026-02-30'),
                        dict(tradeDate=True),dict(tradeDate='2026-11-11 00:00:00')):
            with self.subTest(changes=changes),tempfile.TemporaryDirectory() as tmp:
                source=record((FUTURE,));source['response']['data'][FUTURE].update(changes)
                source['symbol_mapping']={FUTURE:dict(trading_date='2026-11-11')}
                result=http.ingest(source,{},tmp,metadata(),now=NOW)
                self.assertEqual(result['inserted'],0);self.assertEqual(len(result['rejected']),1)
                self.assertEqual(daily.read_day({},tmp,DAY),{})

    def test_supported_explicit_date_fields_and_numeric_formats(self):
        for field in http.DATE_FIELDS:
            for day in ('2026-11-11','20261111',20261111):
                with self.subTest(field=field,day=day),tempfile.TemporaryDirectory() as tmp:
                    source=record((SPOT,));q=source['response']['data'][SPOT]
                    q.pop('tradeDate');q[field]=day
                    self.assertEqual(http.ingest(source,{},tmp,{},now=NOW)['inserted'],1)

    def test_previous_price_must_be_valid_and_is_never_settlement_or_latest_price(self):
        for bad in (None,0,-1,True,'4000',float('nan'),1e12):
            with self.subTest(price=bad),tempfile.TemporaryDirectory() as tmp:
                source=record((SPOT,));source['response']['data'][SPOT]['yesterdayClosePrice']=bad
                result=http.ingest(source,{},tmp,{},now=NOW)
                self.assertEqual(result['inserted'],0)
                self.assertEqual(result['rejected'][0]['reason'],'previous_close_invalid')

    def test_previous_close_does_not_require_a_valid_current_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=record((FUTURE,));source['response']['data'][FUTURE]['latestPrice']=0
            self.assertEqual(http.ingest(source,{},tmp,metadata(),now=NOW)['inserted'],1)

    def test_future_source_clock_and_stale_or_naive_receipts_are_rejected(self):
        for received,source_time in ((NOW-pd.Timedelta(days=1),100002),(NOW+pd.Timedelta(seconds=5),100002),
                                    (NOW,100010),(NOW,246000),(NOW,None)):
            with self.subTest(received=received,source_time=source_time),tempfile.TemporaryDirectory() as tmp:
                source=record((SPOT,),clock=received);source['response']['data'][SPOT]['quoteTimestamp']=source_time
                self.assertEqual(http.ingest(source,{},tmp,{},now=NOW)['inserted'],0)
        with tempfile.TemporaryDirectory() as tmp:
            source=record((SPOT,));source['received_at']='2026-11-11T10:00:03'
            self.assertEqual(http.ingest(source,{},tmp,{},now=NOW)['inserted'],0)

    def test_actual_identity_and_both_listing_days_are_required(self):
        for symbol,bad_id in (('IF00.CFE','IF00.CFE'),('IF2611.CFE','IF2612.CFE'),('IF2610.CFE','IF2610.CFE')):
            with self.subTest(symbol=symbol),tempfile.TemporaryDirectory() as tmp:
                source=record((symbol,));source['response']['data'][symbol]['securityId']=bad_id
                result=http.ingest(source,{},tmp,metadata(),now=NOW)
                self.assertEqual(result['inserted'],0);self.assertTrue(result['rejected'])
        with tempfile.TemporaryDirectory() as tmp:
            meta=metadata();meta[FUTURE]['listing_date']='2026-11-11'
            result=http.ingest(record((FUTURE,)),{},tmp,meta,now=NOW)
            self.assertEqual(result['inserted'],0)

    def test_alias_fanout_keeps_the_original_actual_response_as_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=record((FUTURE,));source['source_response']=deepcopy(source['response'])
            source['response']['data']={'IF00.CFE':source['response']['data'][FUTURE]}
            source['symbols']=['IF00.CFE'];source['symbol_mapping']={'IF00.CFE':dict(source_symbol=FUTURE)}
            result=http.ingest(source,{},tmp,metadata(),now=NOW)
            self.assertEqual(result['inserted'],1);self.assertNotIn('IF00.CFE',daily.read_day({},tmp,DAY)['rows'])

    def test_partial_quotes_are_isolated_without_dropping_the_good_leg(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=record();source['status']='partial';source['response']['data'][FUTURE].pop('tradeDate')
            result=http.ingest(source,{},tmp,metadata(),now=NOW)
            self.assertEqual(result['inserted'],1);self.assertEqual(set(daily.read_day({},tmp,DAY)['rows']),{SPOT})

    def test_existing_close_and_repeated_http_values_never_create_progress_or_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily.publish_day({},tmp,DAY,{SPOT:close_row(SPOT,DAY,4100.)})
            first=http.ingest(record(),{},tmp,metadata(),now=NOW)
            self.assertEqual(first['inserted'],1);self.assertEqual(daily.read_day({},tmp,DAY)['rows'][SPOT]['close'],4100.)
            path=Path(tmp)/'overview_daily/days'/f'{DAY}.json';before=path.read_bytes()
            archives=list((Path(tmp)/'overview_daily/archive').glob('*.json'))
            second=http.ingest(record(),{},tmp,metadata(),now=NOW)
            self.assertEqual(second['inserted'],0);self.assertEqual(second['already_present'],2)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(list((Path(tmp)/'overview_daily/archive').glob('*.json')),archives)
            jobs=daily.requests({},tmp,DAY,metadata(),reference_data={})
            future=next(j for j in jobs if j['day']==DAY and j['asset']=='future')
            self.assertIn(FUTURE,future['symbols']);self.assertTrue(future['requires_oi'])

    def test_calendar_uses_previous_trading_day_across_weekend_and_national_holiday(self):
        for current,previous in (('2026-11-09','2026-11-06'),('2026-10-08','2026-09-30')):
            clock=pd.Timestamp(current+'T10:00:03+08:00')
            with self.subTest(current=current),tempfile.TemporaryDirectory() as tmp:
                source=record((SPOT,),clock=clock);source['response']['data'][SPOT]['tradeDate']=current
                result=http.ingest(source,{},tmp,{},now=clock)
                self.assertEqual(result['target'],previous);self.assertEqual(result['inserted'],1)
                self.assertIn(SPOT,daily.read_day({},tmp,previous)['rows'])

    def test_weekend_and_wrong_target_do_not_backdate_latest_previous_close(self):
        for clock,target in ((NOW.replace(hour=16),'2026-11-11'),(pd.Timestamp('2026-11-14T10:00:03+08:00'),'2026-11-13'),
                             (NOW,'2026-11-09')):
            with self.subTest(clock=clock,target=target),tempfile.TemporaryDirectory() as tmp:
                result=http.ingest(record(clock=clock),{},tmp,metadata(),now=clock,target=target)
                self.assertEqual(result['status'],'not_applicable');self.assertEqual(result['inserted'],0)

    def test_after_close_previous_close_is_still_yesterday_and_never_todays_close(self):
        clock=NOW.replace(hour=16)
        with tempfile.TemporaryDirectory() as tmp:
            source=record(clock=clock)
            value=http.ingest(source,{},tmp,metadata(),now=clock)
            self.assertEqual(value['inserted'],2);self.assertEqual(value['target'],DAY)
            self.assertEqual(daily.read_day({},tmp,'2026-11-11'),{})

    def test_twenty_and_sixty_percentiles_recover_and_older_holes_remain_explicit(self):
        meta=metadata();prices=daily_data(meta,day='2026-11-11')
        for symbol in (FUTURE,SPOT):prices[symbol]=prices[symbol][prices[symbol].trade_date.ne(DAY)]
        before=evaluate(prepare('IF',0,meta,prices,'2026-11-11',dividends=ZERO_DIVIDENDS),0,FUTURE)
        self.assertIsNone(before['windows']['20']['percentile']);self.assertIsNone(before['windows']['60']['percentile'])
        with tempfile.TemporaryDirectory() as tmp:
            http.ingest(record(),{},tmp,meta,now=NOW)
            for symbol,row in daily.read_day({},tmp,DAY)['rows'].items():
                prices[symbol]=daily.merge_daily(prices[symbol],[dict(row,open_interest=row['oi'])])
        after=evaluate(prepare('IF',0,meta,prices,'2026-11-11',dividends=ZERO_DIVIDENDS),0,FUTURE)
        for length in ('20','60'):
            self.assertTrue(after['windows'][length]['complete']);self.assertEqual(after['windows'][length]['percentile'],50.)
        prices[FUTURE]=prices[FUTURE][prices[FUTURE].trade_date.ne('2026-11-09')]
        still_missing=evaluate(prepare('IF',0,meta,prices,'2026-11-11',dividends=ZERO_DIVIDENDS),0,FUTURE)
        self.assertIsNone(still_missing['windows']['60']['percentile'])
        self.assertIn('2026-11-09',[r['day'] for r in still_missing['windows']['60']['missing']])

    def test_cancel_and_daily_writer_conflict_leave_existing_prices_intact(self):
        from dashboard.marketdata.bars import _writer_lock
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(http.ingest(record(),{},tmp,metadata(),now=NOW,stop=lambda:True)['inserted'],0)
            with _writer_lock(Path(tmp)/'overview_daily/publication'):
                value=http.ingest(record(),{},tmp,metadata(),now=NOW)
            self.assertEqual(value['status'],'publication_failed');self.assertEqual(daily.read_day({},tmp,DAY),{})


class HttpRoutingTests(unittest.TestCase):
    def test_one_bounded_request_only_for_absent_latest_prices_not_oi_or_older_holes(self):
        client=Mock();client.fetch.return_value=record((FUTURE,))
        factory=Mock(return_value=client)
        with tempfile.TemporaryDirectory() as tmp:
            daily.publish_day({},tmp,DAY,{SPOT:close_row(SPOT,DAY)})
            jobs=[dict(day=DAY,asset='future',symbols=[FUTURE],requires_oi=True),
                  dict(day=DAY,asset='index',symbols=[SPOT]),dict(day='2026-11-09',asset='future',symbols=['IF2612.CFE'])]
            first=http.collect({},tmp,DAY,metadata(),jobs=jobs,now=NOW,client_factory=factory)
            self.assertEqual(first['inserted'],1);client.fetch.assert_called_once_with([FUTURE])
            factory.assert_called_once_with(connect_timeout=1,read_timeout=2);client.close.assert_called_once()
            second=http.collect({},tmp,DAY,metadata(),jobs=jobs,now=NOW,client_factory=factory)
            self.assertEqual(second['status'],'not_needed');self.assertEqual(factory.call_count,1)

    def test_failure_exposes_only_error_type_and_never_changes_vpn(self):
        factory=Mock(side_effect=ConnectionError('PRIVATE_PASSWORD'))
        jobs=[dict(day=DAY,asset='index',symbols=[SPOT])]
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.marketdata.ddb_vpn.ensure_connected') as vpn:
            value=http.collect({},tmp,DAY,{},jobs=jobs,now=NOW,client_factory=factory)
        self.assertEqual(value['status'],'unavailable');self.assertNotIn('PRIVATE_PASSWORD',json.dumps(value));vpn.assert_not_called()

    def run_maintenance(self,*,missing_date=False,older_gap=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        ref=reference_file(root,metadata());config=dict(reference_file=str(ref),history_roots=[str(root/'history')])
        events=[];source=record((SPOT,))
        if missing_date:source['response']['data'][SPOT].pop('tradeDate')
        class Client:
            def __init__(self,**kw):events.append('http_open')
            def fetch(self,symbols):events.append('http_fetch');return deepcopy(source)
            def close(self):events.append('http_close')
        def jobs(config,local_root,target,meta):
            result=[]
            if SPOT not in daily.read_day(config,local_root,DAY).get('rows',{}):
                result.append(dict(day=DAY,asset='index',symbols=[SPOT]))
            if older_gap:result.append(dict(day='2026-11-09',asset='future',symbols=[FUTURE]))
            return result
        remote=Mock()
        def direct(path):events.append('ddb_open');return remote
        def fill(client,config,local_root,target,meta,**kw):
            asked=jobs(config,local_root,target,meta)
            events.append(('ddb_jobs',asked))
            return dict(status='complete',inserted=sum(len(j['symbols']) for j in asked),pending_rows=0,pending_batches=0)
        with ExitStack() as stack:
            stack.enter_context(patch('dashboard.marketdata.repository.MarketDataRepository'))
            stack.enter_context(patch.object(daily,'seed_local',return_value=0))
            stack.enter_context(patch.object(daily,'requests',side_effect=jobs))
            stack.enter_context(patch('index_strategy.instant_dld.client.MarketDataClient',Client))
            filled=stack.enter_context(patch.object(daily,'fill',side_effect=fill))
            credential=stack.enter_context(patch('index_strategy.history.credentials.load_config',side_effect=AssertionError('credentials not needed')))
            vpn=stack.enter_context(patch('dashboard.marketdata.ddb_vpn.ensure_connected',side_effect=AssertionError('VPN not needed')))
            result=hm._run_overview_cycle(root,config,budget=45,stop_file=None,direct_factory=direct,lifetime=None,
                vpn_mode='manual',include_completed_today=True,now=NOW)
        return result,events,filled,credential,vpn

    def test_verified_http_closes_can_complete_before_loading_ddb_credentials_or_sdk(self):
        value,events,fill,credential,vpn=self.run_maintenance()
        self.assertEqual(value['state'],'complete');self.assertEqual(value['http_previous_close']['inserted'],1)
        self.assertEqual(value['ddb_connection']['stage'],'not_needed')
        self.assertEqual(events,['http_open','http_fetch','http_close'])
        fill.assert_not_called();credential.assert_not_called();vpn.assert_not_called()

    def test_ddb_receives_only_the_replanned_older_gap_after_http_has_closed(self):
        value,events,fill,credential,vpn=self.run_maintenance(older_gap=True)
        self.assertEqual(value['state'],'complete');self.assertEqual(value['overview_daily']['seeded_http'],1)
        self.assertEqual(events[:4],['http_open','http_fetch','http_close','ddb_open'])
        self.assertEqual(events[4][1],[dict(day='2026-11-09',asset='future',symbols=[FUTURE])])
        credential.assert_not_called();vpn.assert_not_called()

    def test_undated_http_does_not_erase_a_real_gap_before_ddb(self):
        value,events,fill,_,_=self.run_maintenance(missing_date=True)
        self.assertEqual(value['http_previous_close']['inserted'],0)
        self.assertEqual(value['http_previous_close']['rejected'][0]['reason'],'source_trade_date_missing')
        self.assertEqual(events[4][1],[dict(day=DAY,asset='index',symbols=[SPOT])]);fill.assert_called_once()

    def test_safe_status_strips_raw_responses_credentials_and_nested_unknown_fields(self):
        value=http.safe_status(dict(status='saved',inserted=1,password='PRIVATE_PASSWORD',response='PRIVATE_BODY',
            rejected=[dict(symbol=FUTURE,reason='source_trade_date_missing',error='PRIVATE_EXCEPTION')]))
        self.assertNotIn('PRIVATE_',json.dumps(value));self.assertEqual(value['inserted'],1)

    def test_app_reports_include_safe_http_evidence_from_all_three_paths(self):
        from dashboard.overview_check import app_reports
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'sessions/run/status.json';path.parent.mkdir(parents=True)
            safe=dict(schema='overview-http-previous-close-v1',target=DAY,status='saved',inserted=2,password='PRIVATE_PASSWORD')
            path.write_text(json.dumps(dict(schema='app-update-evidence-v1',local_root=str(root),
                history=dict(http_previous_close=safe),collection=dict(http_previous_close=safe),
                overview_runtime=dict(latest_snapshot=dict(http_previous_close=safe)))),encoding='utf8')
            result=app_reports(root,root/'sessions')['matching_profile'][0]
        self.assertNotIn('PRIVATE_',json.dumps(result))
        for entry in (result['history_update'],result['collection'],result['overview_runtime']):
            self.assertEqual(entry['http_previous_close']['inserted'],2)

    def test_off_session_snapshot_reuses_its_one_http_response_for_previous_closes(self):
        from dashboard.native.latest_snapshot import collect
        clock=NOW.replace(hour=9);source=record(clock=clock)
        for q in source['response']['data'].values():q['quoteTimestamp']=90002
        client=Mock();client.fetch.return_value=source
        with tempfile.TemporaryDirectory() as tmp:
            ref=reference_file(tmp,metadata())
            result=collect(dict(reference_file=str(ref)),tmp,now=clock,client_factory=lambda **kw:client)
            self.assertEqual(result['http_previous_close']['inserted'],2)
            self.assertEqual(set(daily.read_day({},tmp,DAY)['rows']),{FUTURE,SPOT})
            self.assertFalse((Path(tmp)/'live/quotes.sqlite3').exists())
        self.assertEqual(client.fetch.call_count,1);client.close.assert_called_once()

    def test_live_collector_uses_actual_keys_and_publishes_without_extra_http(self):
        from dashboard.native.collection import CollectionJob,RollingResolver
        from index_strategy.instant_dld.collector import collect as real_collect
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ref=reference_file(root,metadata());meta=metadata()
            indices=set(http.ROOTS.values())
            active=[s for s,r in meta.items() if r['listing_date']<='2026-11-11'<=r['expiry_date']]
            config=dict(reference_file=str(ref),history_roots=[str(root/'history')])
            resolver=RollingResolver(indices,ref,root/'reference-cache',now=lambda:NOW.to_pydatetime(),
                synchronizer=lambda *a,**k:dict(reference_file=str(ref),active_contracts=active))
            class Client:
                url='https://fixture.invalid';verify=True;timeout=(1,2)
                def __init__(self,**kw):self.session=SimpleNamespace(trust_env=False);self.calls=0;self.closed=False
                def fetch(self,symbols):self.calls+=1;return record(symbols)
                def close(self):self.closed=True
            client=Client()
            def bounded(*args,**kw):kw.update(interval=.01,max_polls=1);return real_collect(*args,**kw)
            original_ingest=http.ingest
            def dated_ingest(*args,**kw):return original_ingest(*args,now=NOW,**kw)
            with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True)),\
                 patch('dashboard.native.collection.RollingResolver',return_value=resolver),\
                 patch('dashboard.native.collection.collect',side_effect=bounded),patch.object(http,'ingest',side_effect=dated_ingest):
                job=CollectionJob(root);job.start(root/'quotes',sorted(indices),indices,auto_roll=True,once=True,
                    config=config,client_factory=lambda **kw:client)
                job.worker.join(8)
            self.assertFalse(job.running());self.assertEqual(client.calls,1);self.assertTrue(client.closed)
            rows=daily.read_day({},root,DAY)['rows']
            self.assertEqual(len(rows),20);self.assertFalse(any('00.CFE' in s for s in rows))
            self.assertEqual(job.state()['http_previous_close']['inserted'],20)

    def test_running_page_invalidates_cached_missing_percentiles_after_http_publication(self):
        from dashboard.native.market_overview import MarketOverviewEngine
        from tests.test_market_overview import observation
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
                before=engine.snapshot(now=NOW)['market_overview']
                old=next(r for r in before['futures'] if r['symbol']==FUTURE)
                self.assertIsNone(old['percentile_20']);self.assertIsNone(old['percentile_60'])
                http.ingest(record(),{},root,meta,now=NOW)
                after=engine.snapshot(now=NOW)['market_overview']
            new=next(r for r in after['futures'] if r['symbol']==FUTURE)
            self.assertEqual(new['percentile_20'],50.);self.assertEqual(new['percentile_60'],50.)


if __name__=='__main__':unittest.main()
