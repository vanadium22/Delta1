import copy
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
import numpy as np
import pandas as pd

from dashboard.native.nonregression import calculate, FIELDS
from dashboard.native.intraday import previous_day, expected_minutes, same_time_volume
from dashboard.marketdata.dividends import DividendBook
from dashboard.research_workspace import validate, group, evaluate
from tests.test_dashboard_nonregression import quote
from index_strategy.instant_dld.quotes import normalize_quote


def fixture(price=4050, total=500, now='2026-10-20T10:00:00+08:00'):
    now=pd.Timestamp(now)
    days=[];day=previous_day(now)
    for _ in range(26):
        days.append(pd.Timestamp(str(day)+' 15:00',tz='Asia/Shanghai'))
        day=previous_day(pd.Timestamp(str(day)+' 10:00',tz='Asia/Shanghai'))
    t=pd.DatetimeIndex(list(reversed(days))).tz_convert('UTC')
    f=pd.DataFrame({c:1. for c in FIELDS},index=t)
    f['close']=4000+np.arange(26);f['volume']=1000;f['open_interest']=5000
    f['high']=f.close+10;f['low']=f.close-10
    s=f.copy();s['close']=4100
    live={}
    for symbol,p in [('IF2612.CFE',price),('000300.SH',4100)]:
        q=normalize_quote(symbol,{**quote(total),'latestPrice':p,'highPrice':4100,'lowPrice':3900},now.isoformat())
        q['observed_at']=now;live[symbol]=q
    book=DividendBook(reason='',info={'mapping':{'IF2612.CFE':{'points':5,'expiry':'2026-12-18'}}})
    return dict(left='IF2612.CFE',right='000300.SH',category='basis',price_input='annual',
        data={'IF2612.CFE':f,'000300.SH':s},minute_data={},metadata={'IF2612.CFE':{'expiry_date':'2026-12-18'}},
        dividends=book,calendar=t,live=live,as_of=now)


class IntradayTests(unittest.TestCase):
    def test_chosen_calendar_legs_use_current_difference(self):
        f=fixture();f['category']='calendar';f['right']='IF2703.CFE'
        f['data'][f['right']]=f['data'][f['left']]+10
        f['metadata'][f['right']]={'expiry_date':'2027-03-19'}
        f['live'][f['right']]={**f['live'][f['left']],'close':4070.}
        f['price_input']='future'
        r={m['id']:m for m in calculate(**f)}
        self.assertEqual(r['X']['current'],-20.)
        self.assertEqual(r['X']['value'],-10.)

    def test_workspace_applies_timing_and_does_not_fill_missing_live_from_daily(self):
        f=fixture();metrics=calculate(**f)
        next(m for m in metrics if m['id']=='B10')['current']=None
        model=SimpleNamespace(config={},local_root='.',snapshot=Mock(return_value={'metrics':metrics}))
        metadata={f['left']:{'listing_date':'2026-04-17','expiry_date':'2026-12-18'}}
        spec={'category':'期现','left':f['left'],'right':'','input':'年化','timing':'盘中优先','date':''}
        with patch('dashboard.marketdata.contract_reference.latest_contracts',return_value=metadata):
            value=evaluate(model,{'rows':[spec],'request_id':'first','group':'位置与趋势'},f['as_of'])
            self.assertEqual(value['request_id'],'first')
            self.assertEqual(value['selection']['rows'][0]['right'],f['right'])
            self.assertIsNone(value['comparisons'][0][2])
            self.assertTrue(all(row[0]=='位置与趋势' for row in value['details']))
            x=next(m for m in metrics if m['id']=='X');saved=x['current'];x['current']=None
            daily_fallback=evaluate(model,{'rows':[spec]},f['as_of'])
            self.assertEqual(daily_fallback['comparisons'][0][-1],'日终参考')
            self.assertIsNone(daily_fallback['comparisons'][0][4])
            x['current']=saved
            spec['timing']='日终'
            value=evaluate(model,{'rows':[spec]},f['as_of'])
            self.assertIsNotNone(value['comparisons'][0][2])
            self.assertTrue(all(row[3] is None for row in value['details']))
            next(m for m in metrics if m['id']=='B10')['time']='2026-10-15T07:00:00+00:00'
            self.assertIsNone(evaluate(model,{'rows':[spec]},f['as_of'])['comparisons'][0][2])
            spec.update(timing='历史日',date='2026-10-16')
            evaluate(model,{'rows':[spec]},f['as_of'])
            self.assertEqual(model.snapshot.call_args[0][0]['as_of'],'2026-10-16T15:01:00+08:00')

    def test_live_changes_do_not_change_completed_history(self):
        before=fixture();after=fixture(price=4060)
        a={r['id']:r for r in calculate(**before)};b={r['id']:r for r in calculate(**after)}
        for code in a:
            self.assertEqual(a[code]['history'],b[code]['history'])
            self.assertEqual(a[code]['value'],b[code]['value'])
        for code in ['X','B10','A03.z','A03.percentile','A03.change5']:
            self.assertIsNotNone(a[code]['current'])
        for code in ['X','B10','A03.z','A03.change5']:
            self.assertNotEqual(a[code]['current'],b[code]['current'])
        self.assertAlmostEqual(a['B04.Q.intraday']['current'],.1)
        self.assertEqual(a['B04.Q']['current'],None)
        self.assertIsNone(a['B09.same_time']['current'])

    def test_stale_or_unsynchronized_inputs_cannot_be_live(self):
        f=fixture()
        f['live']['000300.SH']['source_event_time']='2026-10-20T09:59:20+08:00'
        r={r['id']:r for r in calculate(**f)}
        self.assertIsNone(r['B10']['current']);self.assertIsNotNone(r['B10']['value'])
        # Turnover is independent of the index leg.
        self.assertAlmostEqual(r['B04.Q.intraday']['current'],.1)
        f['as_of']+=pd.Timedelta(minutes=2)
        r={r['id']:r for r in calculate(**f)}
        self.assertIsNone(r['B04.Q.intraday']['current'])

    def test_zero_volume_valid_invalid_live_oi_remains_missing(self):
        r={r['id']:r for r in calculate(**fixture(total=0))}
        self.assertEqual(r['B04.Q.intraday']['current'],0.)
        self.assertIsNone(r['B04.doi']['current'])
        self.assertIsNone(r['B04.K']['current'])

    def test_missing_yesterday_is_not_another_prior_day(self):
        f=fixture()
        f['calendar']=f['calendar'][:-1]
        f['data']={k:v.iloc[:-1] for k,v in f['data'].items()}
        r={r['id']:r for r in calculate(**f)}
        self.assertIsNone(r['B10']['current'])
        self.assertIsNone(r['B04.Q.intraday']['current'])

    def test_missing_whole_session_inside_window_is_not_bridged(self):
        f=fixture()
        f['calendar']=f['calendar'].delete(-3)
        f['data']={k:v.reindex(f['calendar']) for k,v in f['data'].items()}
        r={r['id']:r for r in calculate(**f)}
        self.assertIsNone(r['B10']['current'])
        self.assertIsNone(r['A03.z']['current'])
        self.assertIsNotNone(r['X']['current'])

    def test_sample_range_reset_and_same_clock_volume(self):
        from dashboard.native.intraday import observations
        f=fixture()
        minutes=[]
        for d in f['calendar']:
            day=d.tz_convert('Asia/Shanghai').date()
            for i,t in enumerate(expected_minutes(day)):
                minutes.append(dict(event_time=t,close=4000+i*.1,volume=2.,
                                    trade_date=str(day),session_id='am' if i<120 else 'pm'))
        raw=pd.DataFrame(minutes);spot=raw.copy();spot['close']=4100
        f['minute_data']={f['left']:raw,f['right']:spot}
        samples=[]
        for i in range(2):
            for symbol,q in f['live'].items():
                at=f['as_of']+pd.Timedelta(seconds=i*3)
                samples.append({**q,'instrument_id':symbol,'run_id':'one','poll':i,'batch':0,
                                'observed_at':at,'source_event_time':at,
                                'close':q['close']+(i if symbol==f['left'] else 0)})
        def run(samples,now):
            rows=calculate(**f)
            observations(rows,pd.DataFrame(samples),f['left'],f['right'],'basis','annual',
                         f['data'],f['minute_data'],f['metadata'],f['dividends'],now)
            return {r['id']:r for r in rows}
        r=run(samples,f['as_of']+pd.Timedelta(seconds=3))
        self.assertGreater(r['B11.sample']['current'],0)
        self.assertEqual(r['B11.sample']['current_scope'],'采集区间')
        self.assertAlmostEqual(r['B09.same_time']['current'],500/60)
        self.assertEqual(r['B09.same_time']['current_time'],f['as_of'].isoformat())
        # A reconnect cannot include extremes from an earlier run.
        for sample in samples[-2:]:sample['run_id']='two'
        self.assertIsNone(run(samples,f['as_of']+pd.Timedelta(seconds=3))['B11.sample']['current'])
        self.assertNotIn('B11.sample',run(samples,f['as_of']+pd.Timedelta(minutes=1)))

    def test_calendar_holiday_and_off_hours(self):
        self.assertEqual(str(previous_day('2026-10-08T10:00+08:00')),'2026-09-30')
        f=fixture()
        f['as_of']=pd.Timestamp('2026-10-20T15:01+08:00')
        r={r['id']:r for r in calculate(**f)}
        self.assertIsNone(r['B10']['current'])

    def test_same_time_denominator_excludes_afternoon_and_requires_all_20_days(self):
        f=fixture()
        days=[t.tz_convert('Asia/Shanghai').date() for t in f['calendar'][-20:]]
        records=[]
        for day in days:
            for t in expected_minutes(day):
                am=t.tz_convert('Asia/Shanghai').hour<12
                records.append(dict(event_time=t,volume=2 if am else 1000,close=4000,trade_date=day,session_id='am' if am else 'pm'))
        raw=pd.DataFrame(records)
        self.assertEqual(same_time_volume(raw,days,f['as_of']),60.)
        self.assertIsNone(same_time_volume(raw.iloc[1:],days,f['as_of']))
        self.assertIsNone(same_time_volume(raw,days[1:],f['as_of']))
        f['minute_data']['IF2612.CFE']=raw
        r={r['id']:r for r in calculate(**f)}
        self.assertAlmostEqual(r['B09.same_time']['current'],500/60)
        self.assertEqual(r['B09.same_time']['current_n'],20)

    def test_future_amplitude_is_provisional_and_keeps_daily_value(self):
        f=fixture();f['price_input']='future'
        r={r['id']:r for r in calculate(**f)}
        self.assertGreater(r['B11']['current'],r['B11']['value'])
        self.assertIn('非最终',r['B11']['current_reason'])

    def test_watchlist_prevents_wrong_underlying_and_unscaled_cross_points(self):
        ids={'IF2611.CFE':{},'IF2612.CFE':{},'IH2612.CFE':{}}
        row=dict(category='期现',left='IF2611.CFE',right='000016.SH',input='年化',timing='盘中优先',date='')
        self.assertEqual(validate(row,ids,pd.Timestamp('2026-10-20').date())[1],'期现需对应指数')
        row.update(category='跨指数',right='IH2612.CFE',input='期货价')
        self.assertIsNotNone(validate(row,ids,pd.Timestamp('2026-10-20').date())[1])
        row.update(input='年化')
        self.assertIsNone(validate(row,ids,pd.Timestamp('2026-10-20').date())[1])
        self.assertEqual(group('B04.Q.intraday'),'成交与活跃')
        self.assertEqual(group('B04.doi'),'持仓与结构')


if __name__=='__main__':unittest.main()
