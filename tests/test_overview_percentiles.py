"""Slot histories spanning delivery months, with calendar/price gaps separated."""
from copy import deepcopy
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import pandas as pd

from dashboard.indicator_v6.sources import SPOTS
from dashboard.marketdata.overview_percentiles import prior_days,requirements,prepare,evaluate,apply,SLOTS
from dashboard.native.continuous import slot_map
from dashboard.native.market_overview import MarketOverviewEngine

DAY='2026-10-27'
NOW=pd.Timestamp(DAY+'T10:00:05+08:00')


def metadata():
    dates=(('2608','2026-06-22','2026-08-21'),('2609','2026-01-19','2026-09-18'),
        ('2610','2026-08-24','2026-10-16'),('2611','2026-09-21','2026-11-20'),
        ('2612','2026-04-20','2026-12-18'),('2703','2026-07-20','2027-03-19'),
        ('2706','2026-10-19','2027-06-18'))
    return {root+month+'.CFE':dict(listing_date=start,expiry_date=end) for root in SPOTS for month,start,end in dates}


def daily_data(meta=None,annual_by_slot=(0,0,0,0),*,day=DAY):
    meta=meta or metadata();days=prior_days(day);values={}
    for root,spot in SPOTS.items():
        values[spot]={d:4000. for d in days}
        for d in days:
            mapped,_=slot_map(meta,root,d)
            for slot in SLOTS:
                symbol=mapped[f'{root}0{slot}.CFE'];t=(pd.Timestamp(meta[symbol]['expiry_date'])-pd.Timestamp(d)).days
                values.setdefault(symbol,{})[d]=4000*math.exp(annual_by_slot[slot]/100*t/365)
    return {s:pd.DataFrame([dict(trade_date=d,is_final=True,event_time=pd.Timestamp(d+'T15:00:00+08:00'),close=p)
        for d,p in by_day.items()]) for s,by_day in values.items()}


class ContinuousPercentileTests(unittest.TestCase):
    def test_unavailable_current_preserves_stale_or_pair_reason_without_inventing_date_mismatch(self):
        meta=metadata();history=prepare('IF',3,meta,daily_data(meta),DAY)
        for reason in ('陈旧/缓存行情','期现源时间不同步','缺少有效行情'):
            row=dict(symbol='IF2706.CFE',annual_pct=None,pricing_day=None,basis_reason=reason)
            apply(row,history)
            self.assertEqual(row['percentile_reason'],reason)
            for window in row['continuous_percentiles']['windows'].values():
                self.assertTrue(window['complete']);self.assertIsNone(window['percentile']);self.assertEqual(window['reason'],reason)
        row.update(annual_pct=0,pricing_day='2026-10-26')
        apply(row,history)
        self.assertIsNone(row['percentile_60']);self.assertIn('定价日不匹配',row['percentile_reason'])

    def test_all_four_annual_windows_cross_contract_rolls_and_keep_actual_identity(self):
        meta=metadata();data=daily_data(meta);current=slot_map(meta,'IF',DAY)[0]
        for slot in SLOTS:
            alias=f'IF0{slot}.CFE';symbol=current[alias]
            history=prepare('IF',slot,meta,data,DAY);value=evaluate(history,0,symbol)
            self.assertEqual(value['alias'],alias);self.assertEqual(value['current_symbol'],symbol)
            for length in (20,60):
                window=value['windows'][str(length)]
                self.assertEqual(window['percentile'],50);self.assertTrue(window['complete'])
                self.assertEqual(window['end'],'2026-10-26');self.assertNotEqual(window['start'],DAY)
                self.assertEqual(window['samples']+window['excluded'],length)
        self.assertEqual(current['IF02.CFE'],'IF2703.CFE');self.assertEqual(current['IF03.CFE'],'IF2706.CFE')
        h=prepare('IF',0,meta,data,DAY)
        self.assertEqual(next(r for r in h['rows'] if r['day']=='2026-10-16')['symbol'],'IF2610.CFE')
        self.assertEqual(next(r for r in h['rows'] if r['day']=='2026-10-19')['symbol'],'IF2611.CFE')

    def test_annual_distribution_is_not_raw_basis_and_each_slot_has_its_own_sample(self):
        meta=metadata();data=daily_data(meta,annual_by_slot=(5,-10,2,-1));mapping=slot_map(meta,'IF',DAY)[0]
        for slot,current,expected in ((0,5.5,100),(1,-11,0),(2,3,100),(3,-2,0)):
            value=evaluate(prepare('IF',slot,meta,data,DAY),current,mapping[f'IF0{slot}.CFE'])
            self.assertEqual(value['windows']['20']['percentile'],expected)
            self.assertEqual(value['windows']['60']['percentile'],expected)

    def test_newly_listed_actual_contract_can_have_complete_60_day_slot_distribution(self):
        meta=metadata();data=daily_data(meta);symbol='IF2706.CFE'
        self.assertLess(len(data[symbol]),20)
        value=evaluate(prepare('IF',3,meta,data,DAY),0,symbol)
        self.assertEqual(value['windows']['60']['samples'],60)
        self.assertEqual(value['windows']['60']['percentile'],50)

    def test_known_t_lt5_is_excluded_but_a_real_missing_close_invalidates_its_window(self):
        meta=metadata();data=daily_data(meta);h=prepare('IF',0,meta,data,DAY)
        excluded=[r for r in h['rows'] if r['excluded']]
        self.assertTrue(excluded)
        for r in excluded:data[r['symbol']]=data[r['symbol']][data[r['symbol']].trade_date.ne(r['day'])]
        value=evaluate(prepare('IF',0,meta,data,DAY),0,'IF2611.CFE')
        self.assertEqual(value['windows']['60']['percentile'],50);self.assertFalse(value['windows']['60']['missing'])
        chosen=next(r for r in reversed(h['rows']) if not r['excluded'])
        data[chosen['symbol']]=data[chosen['symbol']][data[chosen['symbol']].trade_date.ne(chosen['day'])]
        value=evaluate(prepare('IF',0,meta,data,DAY),0,'IF2611.CFE')
        self.assertIsNone(value['windows']['20']['percentile']);self.assertIsNone(value['windows']['60']['percentile'])
        self.assertIn(chosen['day'],[r['day'] for r in value['windows']['20']['missing']])

    def test_missing_historical_mapping_is_not_invented_from_todays_expiry_order(self):
        meta=metadata();data=daily_data(meta);del meta['IF2703.CFE']
        value=evaluate(prepare('IF',0,meta,data,DAY),0,'IF2611.CFE')
        self.assertIsNone(value['windows']['60']['percentile'])
        self.assertTrue(all(r['reason']=='mapping_missing' for r in value['windows']['60']['missing']))
        self.assertTrue(requirements(meta,DAY)['mapping_gaps'])

    def test_current_day_future_prices_wrong_slot_and_old_pricing_day_never_enter_rank(self):
        meta=metadata();data=daily_data(meta);symbol='IF2611.CFE'
        today=pd.DataFrame([dict(trade_date=DAY,is_final=True,close=99999),dict(trade_date='2026-10-28',is_final=True,close=1)])
        data[symbol]=pd.concat([data[symbol],today],ignore_index=True)
        h=prepare('IF',0,meta,data,DAY)
        self.assertEqual(evaluate(h,0,symbol)['windows']['20']['percentile'],50)
        self.assertIsNone(evaluate(h,0,'IF2612.CFE')['windows']['20']['percentile'])
        row=dict(symbol=symbol,annual_pct=0,pricing_day='2026-10-26');apply(row,h)
        self.assertIsNone(row['percentile_20'])
        row['pricing_day']=DAY;apply(row,h);self.assertEqual(row['percentile_60'],50)
        apply(row,None);self.assertNotIn('continuous_percentiles',row)

    def test_engine_loads_expired_contracts_and_displays_all_four_concrete_cards(self):
        meta=metadata();data=daily_data(meta);now=NOW
        mapping={r:slot_map(meta,r,DAY)[0] for r in SPOTS};live={}
        for root,spot in SPOTS.items():
            live[spot]=dict(close=4000.,prev_close=4000.,source_event_time=now.isoformat(),observed_at=now.isoformat())
            for symbol in mapping[root].values():live[symbol]=dict(live[spot])
        reference=Mock();reference.data={};reference.version='fixture'
        repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={}
        repo.read_window.side_effect=lambda symbol,*args,**kwargs:data.get(symbol,pd.DataFrame())
        model=SimpleNamespace(config={},configure_repository=lambda _:repo,_live=lambda *args:deepcopy(live),live_rows=pd.DataFrame())
        with patch('dashboard.native.market_overview.ReferenceBook',return_value=reference),\
             patch('dashboard.native.market_overview.latest_contracts',return_value=meta):
            value=MarketOverviewEngine(model).snapshot(now=now)['market_overview']
        rows=[r for r in value['futures'] if r['root']=='IF']
        self.assertEqual([r['symbol'] for r in rows],list(mapping['IF'].values()))
        for row,slot in zip(rows,SLOTS):
            self.assertEqual(row['continuous_percentiles']['alias'],f'IF0{slot}.CFE')
            self.assertEqual(row['percentile_60'],50)
        loaded={call.args[0] for call in repo.read_window.call_args_list}
        self.assertIn('IF2608.CFE',loaded);self.assertIn('IF2610.CFE',loaded)
        self.assertTrue(all(c.kwargs['count']>=61 for c in repo.read_window.call_args_list))

    def test_unchanged_side_files_are_cached_and_unrelated_stock_rows_not_retained(self):
        from dashboard.marketdata import overview_daily
        from tests.test_overview_data import write_day,close_row
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);day='2026-10-26'
            write_day(root,day,{'000300.SH':close_row('000300.SH',day,4000),
                               '600001.SH':close_row('600001.SH',day,10)})
            repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={};repo.read_window.return_value=pd.DataFrame()
            model=SimpleNamespace(local_root=root,config={},configure_repository=lambda _:repo,_live=lambda *a:{},live_rows=pd.DataFrame())
            engine=MarketOverviewEngine(model)
            with patch.object(overview_daily,'read_day',wraps=overview_daily.read_day) as read:
                engine.snapshot(now=NOW);count=read.call_count
                engine.snapshot(now=NOW);self.assertEqual(read.call_count,count)
                self.assertNotIn('600001.SH',engine.side_cache[day]['value']['rows'])
                write_day(root,day,{'000300.SH':close_row('000300.SH',day,4100)})
                value=engine.snapshot(now=NOW)['market_overview']
                self.assertGreater(read.call_count,count);self.assertEqual(value['indices'][0]['price'],4100)


if __name__=='__main__':unittest.main()
