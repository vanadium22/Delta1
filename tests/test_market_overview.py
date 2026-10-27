"""Market overview correctness with current quotes and no today's history."""
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from dashboard.native.market_overview import (MarketOverviewEngine, quote_card,
    futures_values, previous_session, observed_series)
from dashboard.native.overview_instruments import etfs, quote_registry
from dashboard.marketdata.adapters import read_realtime_observations
from dashboard.marketdata.bars import validate_instruments
from index_strategy.instant_dld.realtime_store import RealtimeStore
from tests.test_realtime_store import quote


NOW = pd.Timestamp('2026-10-26T10:00:05+08:00')


def observation(price=4000, previous=3980, at=NOW, **extra):
    return dict(close=price, prev_close=previous, volume_total=10000, open=3990,
                high=4010, low=3975, source_event_time=at.isoformat(),
                observed_at=at.isoformat(), **extra)


def frame(days, price):
    return pd.DataFrame([dict(event_time=pd.Timestamp(d+'T15:00:00+08:00'), trade_date=d,
                             is_final=True, close=price(i), volume=1000) for i,d in enumerate(days)])


class OverviewTests(unittest.TestCase):
    def test_latest_and_endpoint_previous_close_need_no_today_history(self):
        r=quote_card('000300.SH','沪深300','IF',{'000300.SH':observation()}, {}, NOW, '2026-10-23')
        self.assertEqual(r['price'],4000);self.assertAlmostEqual(r['change_pct'],100*(4000/3980-1))
        self.assertTrue(r['quality']['usable']);self.assertEqual(r['source_at'],NOW.isoformat())
        self.assertIsNone(r['yesterday_close'])

    def test_zero_change_is_valid_and_invalid_previous_does_not_become_zero(self):
        live={'000300.SH':observation(4000,4000)}
        r=quote_card('000300.SH','沪深300','IF',live,{},NOW,'2026-10-23')
        self.assertEqual(r['change_pct'],0)
        live['000300.SH']['prev_close']=0
        r=quote_card('000300.SH','沪深300','IF',live,{},NOW,'2026-10-23')
        self.assertIsNone(r['change_pct']);self.assertEqual(r['price'],4000)

    def test_yesterday_requires_exact_previous_session_and_no_today_bar(self):
        live={'000300.SH':observation(previous=None)}
        daily={'000300.SH':frame(['2026-10-22'],lambda _:3980)}
        r=quote_card('000300.SH','沪深300','IF',live,daily,NOW,'2026-10-23')
        self.assertIsNone(r['change_pct']);self.assertIsNone(r['yesterday_close'])
        daily['000300.SH']=frame(['2026-10-23'],lambda _:3980)
        r=quote_card('000300.SH','沪深300','IF',live,daily,NOW,'2026-10-23')
        self.assertIsNotNone(r['change_pct']);self.assertEqual(r['prev_date'],'2026-10-23')

    def test_fresh_receipt_never_relabels_stale_source_and_future_is_excluded(self):
        q=observation(at=NOW-pd.Timedelta(seconds=31));q['observed_at']=NOW.isoformat()
        r=quote_card('000300.SH','沪深300','IF',{'000300.SH':q},{},NOW,'2026-10-23')
        self.assertFalse(r['quality']['usable']);self.assertEqual(r['price'],4000)
        self.assertEqual(r['source_at'],q['source_event_time'])
        q['source_event_time']=(NOW+pd.Timedelta(minutes=5)).isoformat()
        r=quote_card('000300.SH','沪深300','IF',{'000300.SH':q},{},NOW,'2026-10-23')
        self.assertIsNone(r['price']);self.assertIsNone(r['source_at'])

    def test_market_basis_does_not_silently_publish_old_fixed_contract_rank(self):
        from dashboard.indicator_v6.sources import dates_between
        days=dates_between('2026-09-01','2026-10-23')[-20:]
        s='IF2611.CFE';live={s:observation(4000,3980),'000300.SH':observation(4000,3980)}
        daily={s:frame(days,lambda _:4000),'000300.SH':frame(days,lambda _:4000)}
        row=dict(symbol=s,root='IF');meta={s:dict(expiry_date='2026-11-20')}
        futures_values(row,live,daily,meta,NOW)
        self.assertIsNone(row['percentile']);self.assertEqual(row['basis_points'],0)
        daily[s]=daily[s].drop(index=4)
        futures_values(row,live,daily,meta,NOW)
        self.assertIsNone(row['percentile'])
        self.assertEqual(row['basis_points'],0)

    def test_unsynchronized_future_keeps_price_and_suppresses_basis(self):
        s='IF2611.CFE';live={s:observation(),'000300.SH':observation(at=NOW-pd.Timedelta(seconds=4))}
        row=quote_card(s,'沪深300','IF',live,{},NOW,'2026-10-23')
        futures_values(row,live,{}, {s:dict(expiry_date='2026-11-20')},NOW)
        self.assertEqual(row['price'],4000);self.assertIsNone(row['basis_points'])
        self.assertIn('3秒',row['basis_reason'])

    def test_calendar_weekend_and_holiday(self):
        self.assertEqual(previous_session('2026-10-26'),'2026-10-23')
        self.assertEqual(previous_session('2026-10-08'),'2026-09-30')

    def test_etf_mapping_requires_explicit_matching_underlying(self):
        config={'research_etf_iopv_mapping':{'IF':dict(etf_id='510300.SH',iopv_id='IOPV.510300',underlying_id='000300.SH')}}
        self.assertEqual(etfs(config)[0]['iopv_id'],'IOPV.510300')
        self.assertEqual(len(quote_registry({})),4)
        config['research_etf_iopv_mapping']['IF']['underlying_id']='000905.SH'
        self.assertIsNone(etfs(config)[0]['iopv_id'])

    def test_no_today_history_pipeline_and_independent_iopv_validity(self):
        config=dict(research_etf_iopv_mapping={'IF':dict(etf_id='510300.SH',iopv_id='IOPV.510300',underlying_id='000300.SH')})
        live={'000300.SH':observation(), '510300.SH':observation(4.02,4), 'IOPV.510300':observation(4,4)}
        repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={};repo.read_window.side_effect=ValueError('no history')
        model=SimpleNamespace(config=config, configure_repository=lambda _:repo, _live=lambda *a:live, live_rows=pd.DataFrame())
        e=MarketOverviewEngine(model);result=e.snapshot(now=NOW)['market_overview']
        self.assertEqual(len(result['indices']),4);self.assertEqual(len(result['etfs']),4)
        self.assertEqual(result['indices'][0]['price'],4000)
        self.assertAlmostEqual(result['etfs'][0]['premium_bp'],50)
        live['IOPV.510300']['source_event_time']=(NOW-pd.Timedelta(seconds=31)).isoformat()
        result=e.snapshot(now=NOW)['market_overview']
        self.assertIsNone(result['etfs'][0]['premium_bp']);self.assertEqual(result['etfs'][0]['price'],4.02)
        model.configure_repository=Mock(side_effect=OSError('fixture historical root unavailable'))
        result=e.snapshot(now=NOW)['market_overview']
        self.assertEqual(result['indices'][0]['price'],4000)
        self.assertEqual(result['etfs'][0]['price'],4.02)
        self.assertTrue(any('历史参考不可用' in error for error in result['errors']))

    def test_etf_observations_read_real_sqlite_without_expanding_bar_scope(self):
        with tempfile.TemporaryDirectory() as t:
            with RealtimeStore(Path(t)) as store:
                q=quote(1000,4,100005);q['securityId']='510300.SH'
                store.batch(dict(run_id='fixture',poll=1,batch=1,batch_count=1,status='success',received_at=NOW.isoformat(),
                    symbols=['510300.SH'],response=dict(data={'510300.SH':q})))
            rows,cursor=read_realtime_observations(t,dataset_id='fixture',instruments=quote_registry({}))
            self.assertEqual(rows.iloc[0].instrument_id,'510300.SH');self.assertEqual(rows.iloc[0].close,4)
            self.assertGreater(cursor['sequence'],0)
            with self.assertRaises(ValueError):validate_instruments(quote_registry({}))

    def test_invalid_observation_registry_fails_before_opening_a_store(self):
        for registry in (None, [], {}, {123:dict(asset_type='cn_etf',market_region='CN')},
                         {'510300.SH':dict(asset_type='cn_etf',market_region='US')}):
            with self.subTest(registry=registry), self.assertRaises(ValueError):
                read_realtime_observations('not-opened',dataset_id='fixture',instruments=registry)

    def test_trace_uses_source_time_deduplicates_and_rejects_delayed_receipts(self):
        r=dict(symbol='000300.SH',source_at=NOW.isoformat(),prev_close=4000)
        q=observation();q.update(instrument_id=r['symbol'])
        old={**q,'source_event_time':NOW-pd.Timedelta(seconds=31)}
        observations=pd.DataFrame([q,q,old])
        observations['observed_at']=pd.to_datetime(observations.observed_at,utc=True)
        self.assertEqual(len(observed_series(r,observations,NOW)),1)


if __name__=='__main__':unittest.main()
