"""Frozen two-contract counterexamples; no repositories, collectors, or windows."""
import copy
import math
import unittest

import numpy as np
import pandas as pd

from dashboard.marketdata.dividends import DividendBook
from dashboard.native.nonregression import calculate, single
from dashboard.native.intraday import expected_minutes
from dashboard.native.pair_metrics import (PAIR_FORMULA_VERSION, pair_value, pair_series,
    pair_quantities, ratio_for_day, pair_minute_frame, pair_daily, pair_ohlc_statistics)
from tests.test_indicator_formula_redesign import pair_fixture


def source(category='calendar', price='future'):
    f = pair_fixture(category)
    f['price_input'] = price
    f['dividends'] = DividendBook(reason='', info={'mapping': {
        f['left']: {'points': 5., 'expiry': f['metadata'][f['left']]['expiry_date']},
        f['right']: {'points': 9., 'expiry': f['metadata'][f['right']]['expiry_date']},
    }})
    return f


def rows(f):
    return {row['id']: row for row in calculate(**f)}


def legs(f):
    symbols = {f['left']: '000300.SH', f['right']: '000300.SH' if f['category']=='calendar' else '000905.SH'}
    return [single(f['data'][symbol],f['data'][symbols[symbol]],symbol,
                   f['metadata'][symbol]['expiry_date'],f['dividends'],f['calendar']) for symbol in (f['left'],f['right'])]


def set_minutes(f, fn, *, all_days=False):
    """fn(day offset, minute offset) returns synchronous prices and volumes."""
    records = {f['left']: [], f['right']: []}
    selected = f['calendar'] if all_days else f['calendar'][-1:]
    for day_no, stamp in enumerate(selected):
        day = stamp.tz_convert('Asia/Shanghai').date()
        for i, at in enumerate(expected_minutes(day)):
            fa, fb, va, vb = fn(day_no,i)
            for symbol, close, volume in ((f['left'],fa,va),(f['right'],fb,vb)):
                records[symbol].append(dict(event_time=at,close=close,volume=volume,trade_date=day,
                                            session_id='am' if i<120 else 'pm'))
    f['minute_data'] = {symbol: pd.DataFrame(values) for symbol,values in records.items()}


class PairInputTests(unittest.TestCase):
    def test_calendar_annual_is_interval_carry_not_difference_of_leg_annuals(self):
        inputs = dict(future_a=4000.,future_b=4100.,spot_a=4050.,spot_b=4050.,dividend_a=10.,dividend_b=20.,days_a=30,days_b=90)
        value = pair_value('calendar','annual',**inputs)
        self.assertAlmostEqual(value,100*(4120/4010-1)*365/60)
        old = 36500*((4000-4050+10)/(4050*30)-(4100-4050+20)/(4050*90))
        self.assertNotAlmostEqual(value,old)
        self.assertAlmostEqual(pair_value('calendar','raw_annual',**inputs),100*(4100/4000-1)*365/60)
        self.assertAlmostEqual(pair_value('calendar','log_annual',**inputs),100*math.log(4100/4000)*365/60)
        self.assertAlmostEqual(pair_value('calendar','log_basis',**inputs),10000*math.log(4000/4100))
        result=rows(source('calendar','log_basis'))
        self.assertEqual(result['B11.A.tr']['unit'],'bp')
        self.assertEqual(result['B11.A.baseline']['unit'],'bp')
        self.assertEqual(result['B11.pair.tr']['unit'],'对数bp')

    def test_cross_close_is_log_price_ratio_and_preserves_reversal(self):
        a=pair_value('cross','future',future_a=4000,future_b=6000)
        b=pair_value('cross','future',future_a=6000,future_b=4000)
        self.assertAlmostEqual(a,10000*math.log(2/3))
        self.assertAlmostEqual(a,-b)
        self.assertEqual(pair_value('cross','future',future_a=4000,future_b=4000),0.)

    def test_missing_invalid_reversed_expiry_and_near_expiry_fail_closed(self):
        base=dict(future_a=4000,future_b=4010,spot_a=4000,dividend_a=0,dividend_b=0,days_a=30,days_b=90)
        for key in ('annual','raw_annual','log_annual'):
            self.assertIsNone(pair_value('calendar',key,**{**base,'days_a':4}))
            self.assertIsNone(pair_value('calendar',key,**{**base,'days_b':None}))
        self.assertIsNone(pair_value('calendar','future',**{**base,'days_a':90,'days_b':30}))
        self.assertIsNone(pair_value('calendar','future',**{**base,'future_b':None}))
        self.assertIsNone(pair_value('cross','future',future_a=0,future_b=4000))
        self.assertIsNone(pair_value('cross','future',future_a=True,future_b=4000))
        self.assertIsNone(pair_value('calendar','basis',**{**base,'dividend_b':None}))
        self.assertEqual(pair_value('calendar','basis',**{**base,'future_b':4000}),0.)

    def test_vector_and_scalar_formulas_agree_for_every_input_and_category(self):
        for category in ('calendar','cross'):
            f=source(category);a,b=legs(f)
            for price in ('future','basis','annual','raw_basis','log_basis','raw_annual','log_annual'):
                actual=pair_series(a,b,category,price)
                for at in (a.index[0],a.index[-1]):
                    expected=pair_value(category,price,future_a=a.at[at,'close'],future_b=b.at[at,'close'],
                        spot_a=a.at[at,'S'],spot_b=b.at[at,'S'],dividend_a=a.at[at,'D'],dividend_b=b.at[at,'D'],
                        days_a=a.at[at,'T'],days_b=b.at[at,'T'])
                    self.assertAlmostEqual(actual.at[at],expected,(category,price))

    def test_production_statistics_and_intraday_share_pair_input(self):
        for category,price in (('calendar','annual'),('calendar','log_basis'),('cross','future'),('cross','annual')):
            f=source(category,price);a,b=legs(f);x=pair_series(a,b,category,price);result=rows(f)
            prior=x.iloc[-21:-1]
            self.assertAlmostEqual(result['A03.mean']['value'],prior.mean())
            self.assertAlmostEqual(result['A03.std']['value'],prior.std(ddof=1))
            self.assertAlmostEqual(result['A03.z']['value'],(x.iloc[-1]-prior.mean())/prior.std(ddof=1))
            now=f['as_of'].tz_convert('Asia/Shanghai').date()
            qa,qb=(f['live'][symbol] for symbol in (f['left'],f['right']))
            expected=pair_value(category,price,future_a=qa['close'],future_b=qb['close'],spot_a=4100,
                spot_b=4100 if category=='calendar' else 7020,dividend_a=5,dividend_b=9,
                days_a=(pd.Timestamp(f['metadata'][f['left']]['expiry_date']).date()-now).days,
                days_b=(pd.Timestamp(f['metadata'][f['right']]['expiry_date']).date()-now).days)
            self.assertAlmostEqual(result['X']['current'],expected)
            self.assertEqual(result['X']['formula_version'],PAIR_FORMULA_VERSION)
            self.assertEqual(result['pair.legacy_input']['role'],'auxiliary')

    def test_fixed_carry_and_generic_annual_share_near_expiry_guard(self):
        f=source('calendar','annual')
        f['metadata'][f['left']]['expiry_date']='2026-10-22'
        f['dividends']=DividendBook(reason='',info={'mapping':{
            f['left']:{'points':5.,'expiry':'2026-10-22'},
            f['right']:{'points':9.,'expiry':f['metadata'][f['right']]['expiry_date']}}})
        result=rows(f)
        for code in ('X','A05','A05.log_carry'):
            self.assertIsNone(result[code]['current'],code)
            self.assertTrue(result[code]['last_valid'],code)
            self.assertIsNone(result[code]['history'][-1]['value'],code)
        self.assertIsNotNone(result['A05.legacy_carry']['current'])
        self.assertIsNotNone(result['A05.legacy_log_carry']['current'])


class PairCapacityTests(unittest.TestCase):
    def test_flat_pair_with_different_leg_oi_weights_has_zero_pair_drift(self):
        f=source();a,b=(f['data'][s] for s in (f['left'],f['right']))
        changes=np.resize([1.,2.,3.,4.,5.],len(a)-1)
        a['close']=4000+np.r_[0,np.cumsum(changes)];b['close']=a.close+100
        da=np.resize([1.,1.,1.,1.,6.],len(a)-1);db=np.resize([6.,1.,1.,1.,1.],len(a)-1)
        a['open_interest']=5000+np.r_[0,np.cumsum(da)];b['open_interest']=4000+np.r_[0,np.cumsum(db)]
        result=rows(f)
        self.assertEqual(result['B03']['value'],0.)
        self.assertAlmostEqual(result['B03.legacy_difference']['value'],2.)
        self.assertEqual(result['B03.legacy_difference']['role'],'auxiliary')
        a['open_interest']=5000;b['open_interest']=4000
        empty=rows(f)['B03']
        self.assertIsNone(empty['value'])
        self.assertEqual(empty['pair_metadata']['historical']['weight_sum'],0.)

    def test_both_legs_active_pair_activity_rises_despite_zero_legacy_ratio(self):
        f=source();a,b=(f['data'][s] for s in (f['left'],f['right']))
        a['volume']=100.;b['volume']=100.
        a.iloc[-1,a.columns.get_loc('volume')]=400.;b.iloc[-1,b.columns.get_loc('volume')]=400.
        result=rows(f)
        self.assertEqual(result['B09']['value'],4.)
        self.assertEqual(result['B09.legacy_log_ratio']['value'],0.)
        self.assertEqual(result['B09']['unit'],'倍')

    def test_cross_ratio_uses_previous_prices_and_same_ratio_for_oi_delta(self):
        f=source('cross');a,b=legs(f)
        a['close']=4000.;b['close']=6000.
        a.iloc[-1,a.columns.get_loc('close')]=8000.
        a['oi_valid']=100.;b['oi_valid']=300.
        a.iloc[-1,a.columns.get_loc('oi_valid')]=110.;b.iloc[-1,b.columns.get_loc('oi_valid')]=320.
        a['doi']=a.oi_valid.diff();b['doi']=b.oi_valid.diff()
        q=pair_quantities(a,b,'cross',f['left'],f['right'])
        self.assertEqual(q.h.iloc[-1],1.)
        self.assertEqual(q.doi.iloc[-1],10.)
        a.iloc[-2,a.columns.get_loc('close')]=np.nan
        self.assertTrue(pd.isna(pair_quantities(a,b,'cross',f['left'],f['right']).volume.iloc[-1]))
        a,b=legs(f)
        a=a.drop(a.index[-2]);b=b.drop(b.index[-2])
        self.assertTrue(pd.isna(pair_quantities(a,b,'cross',f['left'],f['right']).h.iloc[-1]))

    def test_oi_growth_freezes_current_lagged_ratio_at_both_endpoints(self):
        f=source('cross');a,b=legs(f)
        a['close']=np.linspace(3000,6000,len(a));b['close']=6000.
        a['oi_valid']=1000+np.arange(len(a))*10;b['oi_valid']=1200+np.arange(len(a))*50
        a['doi']=a.oi_valid.diff();b['doi']=b.oi_valid.diff()
        q=pair_quantities(a,b,'cross',f['left'],f['right']);h=q.h.iloc[-1]
        expected=100*math.log(min(a.oi_valid.iloc[-1],b.oi_valid.iloc[-1]/h)/min(a.oi_valid.iloc[-6],b.oi_valid.iloc[-6]/h))
        self.assertAlmostEqual(q.growth.iloc[-1],expected)
        a.iloc[-3,a.columns.get_loc('oi_valid')]=np.nan
        self.assertTrue(pd.isna(pair_quantities(a,b,'cross',f['left'],f['right']).growth.iloc[-1]))

    def test_zero_capacity_is_valid_missing_leg_is_not_zero(self):
        f=source();a,b=legs(f);a['volume']=0.
        q=pair_quantities(a,b,'calendar',f['left'],f['right'])
        self.assertEqual(q.volume.iloc[-1],0.)
        b.iloc[-1,b.columns.get_loc('volume')]=np.nan
        self.assertTrue(pd.isna(pair_quantities(a,b,'calendar',f['left'],f['right']).volume.iloc[-1]))

    def test_current_capacity_uses_last_completed_close_and_zero_p(self):
        f=source('cross');f['participation']=0.
        result=rows(f);a,b=legs(f)
        h=ratio_for_day(a,b,'cross',f['left'],f['right'],f['as_of'])
        self.assertAlmostEqual(result['B12.h']['current'],h)
        self.assertEqual(result['B12.A_p']['current'],0.)
        self.assertEqual(result['B12.B_p']['value'],0.)
        self.assertNotAlmostEqual(result['B12.h']['current'],result['B12.legacy_h']['current'])
        self.assertEqual(result['B08']['n'],6)
        self.assertAlmostEqual(result['B12.A']['pair_metadata']['current']['effective_h'],h)
        self.assertAlmostEqual(result['A09.h']['pair_metadata']['current']['effective_h'],result['A09.h']['current'])
        self.assertAlmostEqual(result['B12.legacy_h']['pair_metadata']['current']['effective_h'],result['B12.legacy_h']['current'])
        self.assertNotEqual(result['B12.A']['pair_metadata']['historical']['time'],result['B12.A']['pair_metadata']['current']['time'])
        self.assertIsNone(ratio_for_day(a.iloc[:-1],b.iloc[:-1],'cross',f['left'],f['right'],f['as_of']))

    def test_intraday_joint_oi_and_unavailable_joint_metrics_never_use_old_values(self):
        f=source();a,b=legs(f)
        for symbol,frame,inc in ((f['left'],a,20),(f['right'],b,10)):
            f['live'][symbol]['open_interest']=float(frame.oi_valid.iloc[-1]+inc)
        result=rows(f)
        expected=min(a.oi_valid.iloc[-1]+20,b.oi_valid.iloc[-1]+10)-min(a.oi_valid.iloc[-1],b.oi_valid.iloc[-1])
        self.assertEqual(result['B04.doi']['current'],expected)
        for code in ('B03','B07','B08','B09','B11','B09.same_time','B11.sample'):
            self.assertFalse(result[code]['current_supported'],code)
            self.assertIsNone(result[code]['current'],code)


class PairMinuteTests(unittest.TestCase):
    def test_pair_ohlc_uses_synchronous_values_not_leg_high_minus_high(self):
        f=source();f['live']={}
        def values(day,i):
            return (110. if i==0 else 100.,105. if i==1 else 90.,2.,1.)
        set_minutes(f,values)
        result=rows(f)
        self.assertEqual(result['B07.pair.high']['value'],20.)
        self.assertNotEqual(result['B07.pair.high']['value'],110-105)
        self.assertEqual(result['B07.pair.low']['value'],-5.)
        self.assertAlmostEqual(result['B07']['value'],(2*10-20+5)/25)
        self.assertEqual(result['B02.weight_sum']['value'],240.)
        self.assertAlmostEqual(result['B02.center']['value'],(20-5+238*10)/240)

    def test_missing_minute_or_mismatched_session_cannot_make_pair_ohlc(self):
        f=source();f['live']={};set_minutes(f,lambda day,i:(4000.+i,3900.+i,1.,1.))
        f['minute_data'][f['right']]=f['minute_data'][f['right']].drop(index=100)
        self.assertIsNone(rows(f)['B07']['value'])
        set_minutes(f,lambda day,i:(4000.+i,3900.+i,1.,1.))
        f['minute_data'][f['right']].loc[100,'session_id']='other'
        self.assertIsNone(rows(f)['B07']['value'])

    def test_common_leg_motion_can_leave_zero_pair_stress_while_legs_are_active(self):
        f=source();f['live']={}
        n=len(f['calendar'])
        def values(day,i):
            wave=math.sin(2*math.pi*i/239)
            fa=4000+50*wave
            return fa,fa+(0 if day==n-1 else 2*wave),10.,10.
        set_minutes(f,values,all_days=True)
        result=rows(f)
        self.assertAlmostEqual(result['B11']['value'],0.,places=10)
        self.assertGreater(result['B11.max']['value'],0.)
        self.assertEqual(result['B11']['unit'],'倍')

    def test_price_ohlc_remains_valid_when_matched_weight_is_missing(self):
        f=source();f['live']={};set_minutes(f,lambda day,i:(4000.+i,3900.+i/2,np.nan,1.))
        result=rows(f)
        self.assertEqual(result['B07']['value'],1.)
        self.assertIsNone(result['B02.center']['value'])

    def test_prefix_replay_does_not_change_past_pair_results(self):
        f=source('cross','future');f['live']={}
        full=rows(f)
        prefix=copy.deepcopy(f);prefix['calendar']=f['calendar'][:-3]
        prefix['data']={s:df.reindex(prefix['calendar']) for s,df in f['data'].items()}
        before=rows(prefix);cutoff=prefix['calendar'][-1]
        for code in ('X','A03.mean','A03.std','A03.z','B03','B04.Q','B08','B09','B10','B12.A'):
            expected=[p for p in full[code]['history'] if pd.Timestamp(p['time'])<=cutoff]
            self.assertEqual(before[code]['history'],expected,code)


if __name__ == '__main__':
    unittest.main()
