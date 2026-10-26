"""End-to-end cache semantics with fake Wind/HTTP/DDB transports, no VPN."""
from copy import deepcopy
from datetime import datetime
import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import pandas as pd

from dashboard.marketdata import overview_daily as daily
from dashboard.marketdata.overview_reference import validate,publish,ranking
from dashboard.marketdata.overview_sessions import latest_completed_session
from dashboard.marketdata.overview_weights import roll,closed_snapshot
from dashboard.marketdata.wind_terminal_worker import refresh as wind_refresh,ROOTS
from dashboard.marketdata.overview_windpy import refresh as terminal_refresh,setup
from dashboard.marketdata.overview_contributions import contributions
from dashboard.native.latest_snapshot import collect,load
from dashboard.native.market_overview import quote_card,futures_values,MarketOverviewEngine
from tests.test_market_overview import NOW,frame,observation
from tests.test_overview_details import reference
from tests.test_realtime_store import quote


CLOSE=pd.Timestamp('2026-10-26T16:00:00+08:00')


def response(fields,columns,codes=None):
    return SimpleNamespace(ErrorCode=0,Fields=fields,Data=columns,Codes=codes or [])


class FakeWind:
    def __init__(self,*,incomplete=False,missing_scale=False):
        self.calls=[];self.incomplete=incomplete;self.missing_scale=missing_scale
    def start(self,**kw):return SimpleNamespace(ErrorCode=0)
    def stop(self):pass
    def wset(self,kind,options):
        self.calls.append(('WSET',kind,options))
        if kind=='indexconstituent':
            count=next(n for code,n in {'000300.SH':300,'000016.SH':50,'000905.SH':500,'000852.SH':1000}.items() if code in options)
            return response(['wind_code','sec_name','i_weight','date'],
                [[f'{600001+i:06}.SH' for i in range(count)],['成分'+str(i) for i in range(count)],[100/count]*count,[datetime(2026,10,23)]*count])
        return response(['wind_code','sec_name'],[['510301.SH','510302.SH','510303.SH','510304.SH'],['普通ETF'+str(i) for i in range(4)]])
    def wss(self,codes,field,options):
        self.calls.append(('WSS',field,options));codes=codes.split(',')
        values={'industry_sw':lambda s:'电子','close':lambda s:100,
            'fund_trackindexcode':lambda s:None if self.incomplete and s=='510304.SH' else '000300.SH',
            'fund_trackindex':lambda s:None if self.incomplete and s=='510304.SH' else '沪深300指数',
            'netasset_total':lambda s:None if self.missing_scale and s=='510304.SH' else
                {'510301.SH':100e8,'510302.SH':300e8,'510303.SH':200e8,'510304.SH':100e8}[s]}
        return response([field.upper()],[[values[field](s) for s in codes]],codes)
    def wsd(self,codes,field,start,end,options):
        values=self.wss(codes,field,options)
        self.calls[-1]=('WSD',field,options)
        result=response([field.upper()],[[v] for v in values.Data[0]],codes.split(','))
        result.Times=[datetime.fromisoformat(start)]
        return result


class WindTerminalTests(unittest.TestCase):
    def request(self):return dict(day='2026-10-23',fetched_at=NOW.isoformat(),old={},config={})

    def test_terminal_returns_full_same_benchmark_size_ranking_and_stock_anchors(self):
        sdk=FakeWind();value=wind_refresh(sdk,self.request());data=validate(value['data'])
        ranked,meta=ranking(data,'IF',today='2026-10-26')
        self.assertEqual([r['symbol'] for r in ranked],['510302.SH','510303.SH','510301.SH'])
        self.assertEqual(meta['universe_count'],4);self.assertAlmostEqual(ranked[0]['aum_share_pct'],300/7)
        self.assertEqual(data['indices']['IF']['rows'][0]['anchor_close'],100)
        self.assertEqual(data['indices']['IF']['rows'][0]['industry'],'电子')
        self.assertEqual({c[0] for c in sdk.calls},{'WSET','WSS','WSD'})

    def test_missing_universe_mapping_or_scale_never_produces_fake_top_three(self):
        for sdk in (FakeWind(incomplete=True),FakeWind(missing_scale=True)):
            value=wind_refresh(sdk,self.request())['data']
            self.assertEqual(ranking(value,'IF',today='2026-10-26')[0],[])
            self.assertTrue(value['indices']);self.assertTrue(value['errors'])

    def test_truncated_index_and_wrong_dated_assets_are_withheld(self):
        sdk=FakeWind();original=sdk.wset
        def truncated(kind,options):
            if kind=='indexconstituent':return response(['wind_code','sec_name','i_weight','date'],
                [['600001.SH','600002.SH'],['甲','乙'],[50,50],[datetime(2026,10,23)]*2])
            return original(kind,options)
        sdk.wset=truncated;data=wind_refresh(sdk,self.request())['data']
        self.assertFalse(data['indices']);self.assertTrue(any('样本数' in s for s in data['errors']))
        sdk=FakeWind();original_daily=sdk.wsd
        def wrong_date(codes,field,*args):
            value=original_daily(codes,field,*args)
            if field=='netasset_total':value.Times=[datetime(2026,10,22)]
            return value
        sdk.wsd=wrong_date;data=wind_refresh(sdk,self.request())['data']
        self.assertEqual(ranking(data,'IF',today='2026-10-26')[0],[])

    def test_known_industry_is_reused_and_invalid_reference_preserves_old(self):
        request=self.request();request['old']=dict(industries={'600001.SH':dict(industry='已知行业')})
        sdk=FakeWind();value=wind_refresh(sdk,request)['data']
        self.assertEqual(value['indices']['IF']['rows'][0]['industry'],'已知行业')
        for op,field,options in sdk.calls:
            self.assertNotIn(op,('WSQ','WSI'))
        with self.assertRaises(InterruptedError):wind_refresh(FakeWind(),self.request(),lambda:True)

    def test_bridge_preserves_user_site_and_missing_module_never_connects(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'WindPy.py').write_text('raise AssertionError("setup must not import WindPy")',encoding='utf8')
            with patch.dict(os.environ,{'PYTHONPATH':tmp}):
                result=setup(dict(overview_wind_python=sys.executable),tmp)
            self.assertTrue(result['module_available']);self.assertTrue(result['user_site_enabled'])
            self.assertFalse(result['connection_attempted'])
        finished=SimpleNamespace(returncode=0,stdout=json.dumps(dict(ok=True,data=reference(),diagnostics={})))
        with patch('subprocess.run',return_value=finished) as run:
            terminal_refresh({'overview_wind_python':sys.executable},'.',{},now=NOW.to_pydatetime())
            self.assertNotIn('-s',run.call_args.args[0]);self.assertIn('2026-10-23',run.call_args.kwargs['input'])

    def test_real_hidden_stdlib_worker_with_fake_terminal_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            code='from datetime import datetime\nfrom types import SimpleNamespace\n'+inspect.getsource(response)+'\n'+inspect.getsource(FakeWind)+'\nw=FakeWind()\n'
            Path(tmp,'WindPy.py').write_text(code,encoding='utf8')
            with patch.dict(os.environ,{'PYTHONPATH':tmp}):
                result=terminal_refresh(dict(overview_wind_python=sys.executable),tmp,{},now=NOW.to_pydatetime())
            self.assertTrue(result['ok']);self.assertEqual(result['diagnostics']['provider'],'WindPy')
            self.assertTrue(result['diagnostics']['user_site_enabled']);self.assertEqual(len(result['data']['indices']),4)


def close_row(symbol,day,price=100,**kwargs):
    return dict(symbol=symbol,trade_date=day,source_at=day+'T15:00:00+08:00',is_final=True,
        source='DDB test catalog',open=price,high=price+1,low=price-1,close=price,volume=1000,
        amount=100000,units={},**kwargs)


def write_day(root,day,rows,stamp='2026-10-26T15:50:00+08:00'):
    path=Path(root)/'overview_daily/days'/(day+'.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(dict(schema='overview-daily-v1',trade_date=day,fetched_at=stamp,rows=rows)),encoding='utf8')


class DatedDataTests(unittest.TestCase):
    def test_calendar_includes_today_only_after_completed_close_and_handles_weekends(self):
        for stamp,expected in [('2026-10-26T09:00:00+08:00','2026-10-23'),('2026-10-26T15:09:59+08:00','2026-10-23'),
            ('2026-10-26T15:10:00+08:00','2026-10-26'),('2026-10-25T20:00:00+08:00','2026-10-23'),
            ('2026-10-08T08:00:00+08:00','2026-09-30')]:
            self.assertEqual(latest_completed_session(datetime.fromisoformat(stamp)),expected)

    def test_ddb_batch_uses_verified_daily_route_and_keeps_raw_native_units(self):
        for asset,symbol,multiple in [('etf','510300.SH',100),('stock','600001.SH',100),('index','000300.SH',1),('future','IF2611.CFE',1)]:
            with self.subTest(asset=asset),tempfile.TemporaryDirectory() as tmp:
                session=Mock();session.run.side_effect=[1,pd.DataFrame([dict(symbol=symbol,trade_date=pd.Timestamp('2026-10-23'),
                    open=100.,high=102.,low=99.,close=101.,volume=10.,amount=2.,oi=10.)])]
                client=SimpleNamespace(session=session,bind=Mock())
                rows=daily.fetch_batch(client,dict(asset=asset,symbols=[symbol],day='2026-10-23'),tmp)
                self.assertEqual(rows[symbol]['volume'],10*multiple)
                self.assertEqual(rows[symbol]['amount'],20000 if asset=='future' else 2000)
                raw=pd.read_parquet(next(Path(tmp).glob('*.parquet')))
                self.assertEqual(raw.iloc[0].volume,10)
                self.assertIn('overviewCodes',session.upload.call_args.args[0])
                self.assertNotIn(symbol,str(session.run.call_args.args[0]))

    def test_bad_dates_duplicates_and_partial_rows_cannot_be_published_as_complete(self):
        for values,count in [([close_row('510300.SH','2026-10-22')],1),([close_row('510300.SH','2026-10-23')]*2,2)]:
            client=SimpleNamespace(bind=Mock(),session=Mock())
            client.session.run.side_effect=[count,pd.DataFrame(values)]
            with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):
                daily.fetch_batch(client,dict(asset='etf',symbols=['510300.SH'],day='2026-10-23'),tmp)
                self.assertEqual(list(Path(tmp).glob('*')),[])

    def test_side_cache_fill_resumes_only_missing_days_and_instruments(self):
        value=reference();metadata={'IF2611.CFE':dict(listing_date='2026-09-01',expiry_date='2026-11-20')}
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'reference_load',return_value=dict(data=value)):
            first=daily.requests({},tmp,'2026-10-26',metadata)
            self.assertTrue(any(j['asset']=='etf' for j in first));self.assertTrue(any(j['asset']=='stock' for j in first))
            asked=[]
            def fetch(client,job,root):
                asked.append((job['day'],tuple(job['symbols'])))
                return {s:close_row(s,job['day']) for s in job['symbols']}
            result=daily.fill(Mock(),{},tmp,'2026-10-26',metadata,fetcher=fetch)
            self.assertEqual(result['status'],'complete');self.assertGreater(result['inserted'],0)
            self.assertEqual(daily.requests({},tmp,'2026-10-26',metadata),[])
            count=len(asked);daily.fill(Mock(),{},tmp,'2026-10-26',metadata,fetcher=fetch)
            self.assertEqual(len(asked),count)

    def test_cache_keeps_archives_and_exact_previous_session_not_last_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            day='2026-10-26';symbol='510300.SH'
            daily.publish_day({},tmp,day,{symbol:close_row(symbol,day,110)})
            self.assertIsNone(daily.quote_rows({},tmp,day)[symbol]['prev_close'])
            daily.publish_day({},tmp,'2026-10-22',{symbol:close_row(symbol,'2026-10-22',90)})
            self.assertIsNone(daily.quote_rows({},tmp,day)[symbol]['prev_close'])
            daily.publish_day({},tmp,'2026-10-23',{symbol:close_row(symbol,'2026-10-23',100)})
            self.assertEqual(daily.quote_rows({},tmp,day)[symbol]['prev_close'],100)
            daily.publish_day({},tmp,day,{symbol:close_row(symbol,day,111)})
            self.assertEqual(len(list((Path(tmp)/'overview_daily/archive').glob('*'))),1)

    def test_full_universe_weight_roll_has_explicit_assumption_and_never_renormalises_missing(self):
        group=reference()['indices']['IF'];group['as_of']='2026-10-22'
        for member in group['rows']:member.update(anchor_close=100,anchor_date='2026-10-22')
        with tempfile.TemporaryDirectory() as tmp:
            rows={m['symbol']:close_row(m['symbol'],'2026-10-23',p) for m,p in zip(group['rows'],[110,100,90])}
            write_day(tmp,'2026-10-23',rows)
            rolled=roll(group,{},tmp,'2026-10-23')
            self.assertAlmostEqual(rolled['rows'][0]['weight_pct'],100*55/103)
            self.assertEqual(rolled['official_as_of'],'2026-10-22');self.assertIn('未认证公司行动',rolled['weight_reason'])
            self.assertEqual(group['as_of'],'2026-10-22')
            rows.pop('600003.SH');write_day(tmp,'2026-10-23',rows)
            self.assertEqual(roll(group,{},tmp,'2026-10-23'),group)

    def test_factor_change_blocks_rolling_and_closed_contribution_uses_its_own_day(self):
        group=reference()['indices']['IF']
        with tempfile.TemporaryDirectory() as tmp:
            for day,prices in [('2026-10-23',[100,100,100,100]),('2026-10-26',[110,95,100,104])]:
                codes=['600001.SH','600002.SH','600003.SH','000300.SH']
                write_day(tmp,day,{s:close_row(s,day,p) for s,p in zip(codes,prices)})
            snapshot=closed_snapshot({},tmp,'2026-10-26','v1')
            value=contributions(group,snapshot,dict(symbol='000300.SH'),CLOSE,'2026-10-23','v1')
            self.assertEqual(value['covered'],3);self.assertAlmostEqual(value['contribution_points'],3.5)
            self.assertEqual(value['source_at'],'2026-10-26T15:00:00+08:00')
            self.assertEqual(value['snapshot_at'],'2026-10-26T15:50:00+08:00')
            group['as_of']='2026-10-22'
            for day,factor in [('2026-10-22',1),('2026-10-23',2)]:
                write_day(tmp,day,{m['symbol']:close_row(m['symbol'],day,100,adjustment_factor=factor) for m in group['rows']})
            self.assertEqual(roll(group,{},tmp,'2026-10-23'),group)

    def test_closed_basis_and_percentile_exclude_pricing_day_and_do_not_change_realtime(self):
        from dashboard.indicator_v6.sources import dates_between
        days=dates_between('2026-09-01','2026-10-26')[-21:];s='IF2611.CFE'
        data={s:frame(days,lambda _:4000),'000300.SH':frame(days,lambda _:4000)}
        data[s]['event_time']=data[s].event_time.dt.tz_convert('UTC')
        row=quote_card(s,'沪深300','IF',{},data,CLOSE,'2026-10-23')
        spot=quote_card('000300.SH','沪深300','IF',{},data,CLOSE,'2026-10-23')
        futures_values(row,{},data,{s:dict(expiry_date='2026-11-20')},CLOSE,spot)
        self.assertEqual(row['basis_points'],0);self.assertEqual(row['percentile'],50)
        self.assertEqual(row['days'],25);self.assertEqual(row['percentile_end'],'2026-10-23')
        self.assertEqual(row['basis_kind'],'completed_daily');self.assertFalse(row['quality']['usable'])
        preopen=pd.Timestamp('2026-10-27T08:00:00+08:00')
        futures_values(row,{},data,{s:dict(expiry_date='2026-11-20')},preopen,spot)
        self.assertEqual(row['days'],25)
        row['display_kind']='observation'
        futures_values(row,{},data,{s:dict(expiry_date='2026-11-20')},CLOSE,spot)
        self.assertIsNone(row['basis_points'])

    def test_verified_completed_close_precedes_same_day_inferred_http_clock(self):
        symbol='510300.SH';data={symbol:frame(['2026-10-23','2026-10-26'],lambda i:100+i*10)}
        live={symbol:observation(111,100,pd.Timestamp('2026-10-26T15:00:03+08:00'),observation_mode='off_session_snapshot')}
        row=quote_card(symbol,'ETF','IF',live,data,CLOSE,'2026-10-23')
        self.assertEqual(row['price'],110);self.assertEqual(row['display_kind'],'completed_daily')

    def test_engine_closed_cache_quotes_work_without_todays_realtime_or_registered_etf_bars(self):
        repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={};repo.read_window.return_value=pd.DataFrame()
        with tempfile.TemporaryDirectory() as tmp:
            for day,price in [('2026-10-23',100),('2026-10-26',110)]:
                write_day(tmp,day,{s:close_row(s,day,price) for s in ('000300.SH','510300.SH')})
            model=SimpleNamespace(local_root=Path(tmp),config={},_live=lambda *args:{},configure_repository=lambda _:repo,live_rows=pd.DataFrame())
            value=MarketOverviewEngine(model).snapshot(now=CLOSE)['market_overview']
            self.assertEqual(value['indices'][0]['price'],110);self.assertEqual(value['indices'][0]['change_pct'],10)
            self.assertEqual(value['etfs'][0]['price'],110);self.assertFalse(value['indices'][0]['quality']['usable'])


class OffHoursTests(unittest.TestCase):
    def test_snapshot_keeps_prior_source_date_and_uses_separate_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            at='2026-10-26T08:00:00+08:00';q=quote(1000,4,150000);q['securityId']='510300.SH'
            client=Mock();client.fetch.return_value=dict(status='success',received_at=at,response=dict(data={'510300.SH':q}))
            value=collect({},tmp,now=pd.Timestamp(at),client_factory=lambda **kw:client)
            saved=load(tmp)['quotes']['510300.SH']
            self.assertEqual(saved['source_event_time'],'2026-10-23T15:00:00+08:00')
            self.assertEqual(saved['observed_at'],at);self.assertEqual(value['status'],'snapshot_received')
            self.assertFalse((Path(tmp)/'live/quotes.sqlite3').exists())
            later='2026-10-26T16:00:00+08:00';client.fetch.return_value['received_at']=later
            collect({},tmp,now=pd.Timestamp(later),client_factory=lambda **kw:client)
            self.assertEqual(load(tmp)['quotes']['510300.SH']['source_event_time'],saved['source_event_time'])
            self.assertIn('保留原源日期',load(tmp)['quotes']['510300.SH']['source_date_basis'])

    def test_explicit_trading_date_is_used_but_failed_response_does_not_repaint_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=quote(1000,4,150000);q.update(securityId='510300.SH',tradeDate='20261026')
            client=Mock();client.fetch.return_value=dict(status='success',received_at=CLOSE.isoformat(),response=dict(data={'510300.SH':q}))
            collect({},tmp,now=CLOSE,client_factory=lambda **kw:client)
            before=(Path(tmp)/'overview_snapshots/latest.json').read_bytes()
            self.assertEqual(load(tmp)['quotes']['510300.SH']['source_event_time'],'2026-10-26T15:00:00+08:00')
            client.fetch.return_value=dict(status='connection_error',received_at=CLOSE.isoformat())
            self.assertEqual(collect({},tmp,now=CLOSE,client_factory=lambda **kw:client)['status'],'unavailable')
            self.assertEqual((Path(tmp)/'overview_snapshots/latest.json').read_bytes(),before)
            client.fetch.return_value=dict(status='success',received_at=CLOSE.isoformat(),response=dict(data={}))
            self.assertEqual(collect({},tmp,now=CLOSE,client_factory=lambda **kw:client)['status'],'no_valid_quotes')
            self.assertEqual((Path(tmp)/'overview_snapshots/latest.json').read_bytes(),before)

    def test_new_explicit_source_date_overrides_identical_old_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=quote(1000,4,150000);q.update(securityId='510300.SH')
            client=Mock();client.fetch.return_value=dict(status='success',received_at='2026-10-26T08:00:00+08:00',response=dict(data={'510300.SH':q}))
            collect({},tmp,now=pd.Timestamp('2026-10-26T08:00:00+08:00'),client_factory=lambda **kw:client)
            q['tradeDate']='20261026';client.fetch.return_value['received_at']=CLOSE.isoformat()
            collect({},tmp,now=CLOSE,client_factory=lambda **kw:client)
            self.assertEqual(load(tmp)['quotes']['510300.SH']['source_event_time'],'2026-10-26T15:00:00+08:00')


if __name__=='__main__':unittest.main()
