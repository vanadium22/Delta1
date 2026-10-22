"""Frozen synthetic evidence for original non-regression sub-formulas."""
import copy
import math
import unittest
from datetime import date

import numpy as np
import pandas as pd

from dashboard.marketdata.dividends import DividendBook
from dashboard.native.metric_inputs import INPUTS,input_value,theoretical_cost_band,etf_premium
from dashboard.native.metric_components import minute_events
from dashboard.native.nonregression import calculate,single,minute_series,complete_history_calendar,legacy_percentile,FIELDS
from dashboard.native.indicator_help import explain_metric
from tests.test_intraday_workspace import fixture


def mapping_inputs():
    return dict(financing_rate=.02,dividend_yield=.03,long_cost_bp=4.,short_cost_bp=6.,
                spot_leg_id='explicit_executable_spot',expiry_date='2026-12-18',
                effective_from='2026-10-01',effective_to='2026-12-18',
                known_at='2026-10-19T10:00:00+08:00',version='synthetic-frozen-v1')


def pair_fixture(category='calendar'):
    f=fixture();f['category']=category
    left=f['left'];right='IF2703.CFE' if category=='calendar' else 'IC2612.CFE'
    f['right']=right
    f['metadata'][right]={'expiry_date':'2027-03-19' if category=='calendar' else '2026-12-18'}
    b=f['data'][left].copy();b['close']=b.close*1.7+np.sin(np.arange(len(b)))
    f['data'][right]=b
    f['live'][right]={**f['live'][left],'close':6900.}
    if category=='cross':
        spot=f['data']['000300.SH'].copy();spot['close']=7000+np.arange(len(spot))*.7
        f['data']['000905.SH']=spot
        f['live']['000905.SH']={**f['live']['000300.SH'],'close':7020.}
    return f


class OriginalFormulaTests(unittest.TestCase):
    def test_docx_original_values_are_independent_of_dividends(self):
        f,s,t=4307.8,4317.2549,7
        self.assertAlmostEqual(input_value('raw_basis',f,s),-21.90025907,places=6)
        self.assertAlmostEqual(input_value('log_basis',f,s),10000*math.log(f/s))
        self.assertAlmostEqual(input_value('log_annual',f,s,None,t),-11.4319,places=4)
        self.assertNotEqual(input_value('basis',f,s,5,t),input_value('raw_basis',f,s,None,t))
        self.assertIsNone(input_value('basis',f,s,None,t))
        self.assertIsNone(input_value('annual',f,s,5,4))
        for key in ('raw_annual','log_annual'):
            self.assertIsNone(input_value(key,f,s,None,4))
        self.assertIsNone(input_value('log_basis',-1,s))
        self.assertEqual(input_value('raw_basis',s,s),0.)

    def test_single_missing_object_inputs_fail_closed_without_log_crash(self):
        f=fixture();calendar=f['calendar']
        result=single(pd.DataFrame(columns=FIELDS),pd.DataFrame(columns=FIELDS),f['left'],
                      '2026-12-18',DividendBook(),calendar)
        self.assertTrue(result.log_basis.isna().all())
        f['data'][f['left']].iloc[-1,f['data'][f['left']].columns.get_loc('close')]=0
        result=calculate(**f)
        self.assertTrue(next(r for r in result if r['id']=='A01.log_bp')['last_valid'])

    def test_all_inputs_recalculate_mean_std_z_percentile_change_and_efficiency(self):
        f=fixture();f['live']={}
        for key in INPUTS:
            f['price_input']=key;rows={r['id']:r for r in calculate(**f)}
            a=single(f['data'][f['left']],f['data']['000300.SH'],f['left'],
                     '2026-12-18',f['dividends'],f['calendar'])
            x=a[key];prior=x.iloc[-21:-1]
            self.assertAlmostEqual(rows['A03.mean']['value'],prior.mean())
            self.assertAlmostEqual(rows['A03.std']['value'],prior.std(ddof=1))
            self.assertAlmostEqual(rows['A03.z']['value'],(x.iloc[-1]-prior.mean())/prior.std(ddof=1))
            self.assertAlmostEqual(rows['A03.change5']['value'],x.iloc[-1]-x.iloc[-6])
            self.assertEqual(rows['A03.z']['reference_end'],x.index[-2].isoformat())
            self.assertEqual(rows['A03.z']['n'],20)
            self.assertEqual(rows['B10']['n'],6)
            self.assertEqual(rows['A03.percentile']['value'],100*((prior<x.iloc[-1]).sum()+.5*(prior==x.iloc[-1]).sum())/20)
            self.assertAlmostEqual(rows['B10']['value'],(x.iloc[-1]-x.iloc[-6])/x.diff().abs().tail(5).sum())
            self.assertTrue(rows['A03.z']['variant_id'].endswith(':nonregression-v2'))
            self.assertEqual(explain_metric(rows['A03.mean'],'basis',key)['formula'],rows['A03.mean']['formula'])

    def test_raw_log_live_values_do_not_depend_on_missing_dividend(self):
        f=fixture();f['dividends']=DividendBook();f['price_input']='log_basis'
        rows={r['id']:r for r in calculate(**f)}
        self.assertIsNone(rows['A01.bp']['current'])
        self.assertAlmostEqual(rows['A01.log_bp']['current'],10000*math.log(4050/4100))
        self.assertIsNotNone(rows['A03.z']['current'])
        self.assertEqual(rows['A03.change5']['current_n'],6)
        self.assertEqual(rows['B10']['current_n'],6)
        self.assertEqual(rows['A03.z']['current_reference_end'],f['calendar'][-1].isoformat())

    def test_frozen_prefix_replay_never_uses_future_prices_or_current_quotes(self):
        for key in INPUTS:
            full=fixture();full['price_input']=key;full['live']={}
            prefix=copy.deepcopy(full);prefix['calendar']=full['calendar'][:-3]
            prefix['data']={symbol:frame.reindex(prefix['calendar']) for symbol,frame in full['data'].items()}
            before={r['id']:r for r in calculate(**prefix)}
            after={r['id']:r for r in calculate(**full)}
            cutoff=prefix['calendar'][-1]
            for code,row in before.items():
                expected=[h for h in after[code]['history'] if pd.Timestamp(h['time'])<=cutoff]
                self.assertEqual(row['history'],expected,(key,code))

    def test_original_calendar_carry_and_standardized_spread_own_statistics(self):
        f=pair_fixture();rows={r['id']:r for r in calculate(**f)}
        a,b=(f['data'][s].close for s in (f['left'],f['right']))
        delta=(pd.Timestamp('2027-03-19')-pd.Timestamp('2026-12-18')).days
        carry=100*np.log(b/a)*365/delta
        self.assertAlmostEqual(rows['A05.log_carry']['value'],carry.iloc[-1])
        self.assertAlmostEqual(rows['A05.log_std']['value'],carry.iloc[-21:-1].std(ddof=1))
        self.assertAlmostEqual(rows['A04.raw_bp']['value'],10000*(a.iloc[-1]-b.iloc[-1])/4100)
        self.assertIsNotNone(rows['A05.log_z']['current'])
        self.assertAlmostEqual(rows['A09.one_to_one_pnl5']['value'],300*((a-b).iloc[-1]-(a-b).iloc[-6]))

    def test_pair_volume_oi_migration_share_and_both_legs_explanations(self):
        f=pair_fixture();f['price_input']='future';n=len(f['calendar'])
        a,b=(f['data'][s] for s in (f['left'],f['right']))
        a['open_interest']=5000-np.arange(n)*2.;b['open_interest']=4000+np.arange(n)*3.
        a['volume']=100.;b['volume']=200.
        rows={r['id']:r for r in calculate(**f)}
        den=a.open_interest.iloc[-2]+b.open_interest.iloc[-2]
        self.assertEqual(rows['B05.M']['value'],2.)
        self.assertAlmostEqual(rows['B05.R']['value'],200/den)
        self.assertAlmostEqual(rows['B05.N']['value'],100/den)
        self.assertEqual(rows['B05.doi_near']['value'],-2.)
        self.assertEqual(rows['B05.doi_far']['value'],3.)
        self.assertEqual(rows['B05.denominator']['value'],den)
        self.assertAlmostEqual(rows['B06.volume_share']['value'],2/3)
        self.assertAlmostEqual(rows['B06.oi_share']['value'],b.open_interest.iloc[-2]/den)
        self.assertEqual(rows['B04.B.volume']['value'],200.)
        self.assertEqual(rows['B04.A.previous_oi']['value'],a.open_interest.iloc[-2])
        self.assertEqual(rows['B03.B.positive_weight']['value'],15.)
        self.assertIsNone(rows['B03.A.drift']['value'])
        self.assertAlmostEqual(rows['B03.B.drift']['value'],b.close.diff().iloc[-5:].mean())

    def test_original_cross_g_and_attribution(self):
        f=pair_fixture('cross');f['price_input']='log_basis';rows={r['id']:r for r in calculate(**f)}
        a=f['data'][f['left']].close;b=f['data'][f['right']].close
        sa=f['data']['000300.SH'].close;sb=f['data']['000905.SH'].close
        g=10000*(np.log(a/sa)-np.log(b/sb))
        self.assertAlmostEqual(rows['A06.log_bp']['value'],g.iloc[-1])
        self.assertAlmostEqual(rows['A06.log_z']['value'],(g.iloc[-1]-g.iloc[-21:-1].mean())/g.iloc[-21:-1].std(ddof=1))
        self.assertAlmostEqual(rows['A07.actual']['value'],rows['A07.spot']['value']+rows['A07.basis']['value'])
        self.assertTrue({'B04.A.Q','B04.B.Q','B09.A.baseline','B09.B.rvol','B11.A.tr','B11.B.pressure'}<=set(rows))
        self.assertIsNone(rows['B12.A_p']['value'])
        f['participation']=.02;rows={r['id']:r for r in calculate(**f)}
        self.assertAlmostEqual(rows['B12.A_p']['value'],.02*rows['B12.A']['value'])
        self.assertAlmostEqual(rows['B12.B_p']['current'],rows['B12.A_p']['current']*rows['B12.h']['current'])
        f['participation']=2;rows={r['id']:r for r in calculate(**f)}
        self.assertIsNone(rows['B12.A_p']['value'])

    def test_signed_zero_path_and_intermediate_missing_day(self):
        f=fixture();f['live']={};f['price_input']='raw_basis'
        f['data'][f['left']]['close']=4100.
        rows={r['id']:r for r in calculate(**f)}
        self.assertIsNone(rows['B10']['value']);self.assertEqual(rows['A03.change5']['value'],0.)
        f['data'][f['left']]['close']=np.resize([4090.,4110.,4100.],len(f['calendar']))
        before={r['id']:r for r in calculate(**f)}
        f['data'][f['left']].loc[f['calendar'][-3],'close']=np.nan
        after={r['id']:r for r in calculate(**f)}
        self.assertTrue(after['A03.z']['last_valid']);self.assertTrue(after['B10']['last_valid'])
        self.assertNotEqual(before['B10']['time'],after['B10']['time'])

    def test_legacy_30_less_equal_percentile_stays_separate_from_half_weight(self):
        self.assertEqual(legacy_percentile(pd.Series([1.]*31)).iloc[-1],100.)
        from dashboard.native.nonregression import statistics
        self.assertEqual(statistics(pd.Series([1.]*31))[1].iloc[-1],50.)
        self.assertTrue(legacy_percentile(pd.Series([1.]*30)).isna().all())

    def test_minute_original_log_and_complete_explanation_components(self):
        f=fixture();day=f['calendar'][-1].tz_convert('Asia/Shanghai').date()
        from dashboard.native.intraday import expected_minutes
        times=expected_minutes(day)
        raw=pd.DataFrame(dict(event_time=times,close=4000+np.sin(np.arange(240)),volume=1.,trade_date=str(day),session_id=['am']*120+['pm']*120))
        spot=raw.copy();spot['close']=4100.
        f['minute_data']={f['left']:raw,'000300.SH':spot};f['price_input']='log_basis'
        f['dividends']=DividendBook()
        minute=minute_series(raw,spot,f['left'],'2026-12-18',f['dividends'],'log_basis')
        self.assertAlmostEqual(minute.x.iloc[-1],10000*math.log(raw.close.iloc[-1]/4100))
        rows={r['id']:r for r in calculate(**f)}
        self.assertEqual(rows['B02.n']['value'],240.)
        self.assertEqual(rows['B02.weight_sum']['value'],240.)
        self.assertAlmostEqual(rows['B02.center']['value'],rows['B02.weighted_sum']['value']/240)
        self.assertEqual(rows['B01.open']['value'],minute.x.iloc[0])
        self.assertEqual(rows['A11']['n'],31)
        missing=raw.drop(30);f['minute_data'][f['left']]=missing
        rows={r['id']:r for r in calculate(**f)}
        self.assertIsNone(rows['B02.center']['value'])


class EventAndInputTests(unittest.TestCase):
    def test_directional_calendar_book_prices_and_zero_size_guard(self):
        f=pair_fixture();qa,qb=(f['live'][s] for s in (f['left'],f['right']))
        qa.update(bid_price_1=4049.8,ask_price_1=4050.2)
        qb.update(bid_price_1=4069.8,ask_price_1=4070.2)
        rows={r['id']:r for r in calculate(**f)}
        self.assertAlmostEqual(rows['A14.buy']['current'],-19.6)
        self.assertAlmostEqual(rows['A14.sell']['current'],-20.4)
        qb['bid_volume_1']=0
        self.assertIsNone({r['id']:r for r in calculate(**f)}['A14.buy']['current'])

    def test_event_first_last_peak_duration_confirmation_recovery_and_gap(self):
        t=pd.date_range('2026-10-20T09:31:00+08:00',periods=36,freq='min')
        values=np.r_[np.linspace(-1,1,30),[10.,10.,10.,10.,0.,0.]]
        frame=pd.DataFrame(dict(x=values,volume=1,trade_date=date(2026,10,20),session_id='am'),index=t)
        result=minute_events(frame)
        self.assertEqual(result['confirmed'].iloc[31],0.)
        self.assertEqual(result['confirmed_at'].iloc[32],t[32].timestamp())
        self.assertEqual(result['first'].iloc[-1],t[30].timestamp())
        self.assertEqual(result['last'].iloc[-1],t[33].timestamp())
        self.assertEqual(result['duration'].iloc[-1],4.)
        self.assertGreater(result['peak'].iloc[-1],2.)
        self.assertEqual(result['recovered_at'].iloc[-1],t[34].timestamp())
        self.assertEqual(result['recovered'].iloc[-1],1.)
        self.assertTrue(minute_events(frame.drop(t[32]))['confirmed_at'].dropna().empty)

    def test_cost_band_pure_contract_direction_and_no_defaults(self):
        inputs=mapping_inputs();now='2026-10-20T10:00:00+08:00';original=copy.deepcopy(inputs)
        values,reason=theoretical_cost_band(4050.,4100.,59,inputs,now,expiry='2026-12-18')
        self.assertFalse(reason);self.assertEqual(inputs,original)
        fair=4100*(1+(.02-.03)*59/365)
        self.assertAlmostEqual(values['fair'],fair)
        self.assertAlmostEqual(values['long_space'],-values['deviation']-4)
        self.assertAlmostEqual(values['short_space'],values['deviation']-6)
        for patch in ({'known_at':'2026-10-21T00:00:00+08:00'},{'known_at':'2026-10-19'},
                      {'short_cost_bp':-1.},{'effective_to':'2026-10-19'},{'expiry_date':'2027-03-19'}):
            values,reason=theoretical_cost_band(4050.,4100.,59,{**inputs,**patch},now,expiry='2026-12-18')
            self.assertTrue(reason);self.assertTrue(all(v is None for v in values.values()))
        values,reason=theoretical_cost_band(4050.,4100.,59,None,now,expiry='2026-12-18')
        self.assertTrue(reason)

    def test_cost_and_etf_engine_calculation_real_input_integration(self):
        f=fixture();f['carry_inputs']=mapping_inputs()
        f['etf_mapping']={'etf_id':'ETF','iopv_id':'IOPV','underlying_id':'000300.SH'}
        f['live']['ETF']={**f['live']['000300.SH'],'close':4.1}
        f['live']['IOPV']={**f['live']['000300.SH'],'close':4.0}
        rows={r['id']:r for r in calculate(**f)}
        self.assertIsNotNone(rows['A13.fair']['current'])
        self.assertEqual(rows['A13.fair']['input_versions']['carry']['known_at'],f['carry_inputs']['known_at'])
        self.assertEqual(rows['A13.fair']['input_versions']['carry']['spot_leg_id'],'explicit_executable_spot')
        self.assertEqual(rows['A13']['input_versions']['carry']['effective_from'],'2026-10-01')
        self.assertAlmostEqual(rows['A14.etf']['current'],250.)
        self.assertEqual(set(rows['A14.etf']['source_times']),{'ETF','IOPV'})
        self.assertEqual(rows['A14.etf']['input_versions']['etf_iopv_mapping']['underlying_id'],'000300.SH')
        f['live']['IOPV']['source_event_time']='2026-10-20T09:59:55+08:00'
        self.assertIsNone({r['id']:r for r in calculate(**f)}['A14.etf']['current'])
        f['etf_mapping']['underlying_id']='000905.SH'
        self.assertIsNone(etf_premium(f['etf_mapping'],f['live'],f['as_of'],underlying='000300.SH')[0])

    def test_whole_session_calendar_hole_and_unknown_year_guard(self):
        times=pd.DatetimeIndex(['2026-10-19T15:00+08:00','2026-10-21T15:00+08:00']).tz_convert('UTC')
        complete,reason=complete_history_calendar(times)
        self.assertEqual(len(complete),3);self.assertFalse(reason)
        future=pd.DatetimeIndex(['2028-01-03T15:00+08:00','2028-01-05T15:00+08:00']).tz_convert('UTC')
        complete,reason=complete_history_calendar(future)
        self.assertEqual(len(complete),2);self.assertIn('2028',reason)


if __name__=='__main__':unittest.main()
