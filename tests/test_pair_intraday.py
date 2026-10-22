"""Contract-pair intraday counterexamples using only frozen synthetic inputs."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair_intraday_fixture import FrozenPairIntradayModel, OBSERVED_AT
from dashboard.native.intraday import expected_minutes, observations
from dashboard.native.pair_intraday import PAIR_INTRADAY_VERSION, update_pair_intraday
from dashboard.native.pair_metrics import MULTIPLIERS, pair_value, quote_value


LEFT, CALENDAR, CROSS = 'IF2612.CFE', 'IF2703.CFE', 'IC2612.CFE'
INPUTS = ('future','basis','annual','raw_basis','log_basis','raw_annual','log_annual')


def compute(model, category='calendar', price='future', now=OBSERVED_AT, *, rows=None,
            samples=True, live=False):
    rows = [] if rows is None else rows
    update_pair_intraday(rows, left=LEFT, right=CALENDAR if category=='calendar' else CROSS,
        category=category, price=price, data=model.daily, minute_data=model.minutes,
        metadata=model.metadata, dividends=model.dividends, now=now,
        samples=model.live_rows if samples else None, live=model.live if live else None)
    return {r['id']:r for r in rows}


class PairIntradayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = FrozenPairIntradayModel('.deps/pair_intraday/synthetic')

    def model(self):
        return deepcopy(self.frozen)

    def test_all_seven_pair_inputs_share_scalar_current_math(self):
        for category,right in (('calendar',CALENDAR),('cross',CROSS)):
            for price in INPUTS:
                with self.subTest(category=category,price=price):
                    result=compute(self.frozen,category,price)
                    row=result['B11.sample'];info=row['pair_intraday']
                    values=[]
                    for _,batch in self.frozen.live_rows.groupby('poll'):
                        quotes={q['instrument_id']:q for q in batch.to_dict('records')}
                        values.append(quote_value(category,price,LEFT,right,quotes,self.frozen.metadata,
                                                  self.frozen.dividends,OBSERVED_AT.date()))
                    self.assertAlmostEqual(info['numerator'],max(values)-min(values))
                    self.assertAlmostEqual(row['current'],info['numerator']/info['denominator'])
                    self.assertEqual(info['baseline_n'],20)
                    self.assertEqual(row['current_n'],4)
                    self.assertEqual(row['formula_version'],PAIR_INTRADAY_VERSION)
                    self.assertEqual(row['current_history'][-1]['value'],row['current'])
                    self.assertLess(pd.Timestamp(row['current_history_cutoff']),OBSERVED_AT.normalize())

    def test_cumulative_matching_is_not_sum_of_minute_matching(self):
        model=self.model()
        for symbol,pattern in ((LEFT,(10.,0.)),(CALENDAR,(0.,10.))):
            model.minutes[symbol]['volume']=np.resize(pattern,len(model.minutes[symbol]))
        row=compute(model)['B09.same_time'];info=row['pair_intraday']
        self.assertEqual(info['denominator'],300.)
        self.assertEqual(info['minute_count'],60)
        self.assertAlmostEqual(row['current'],min(model.live[LEFT]['volume_total'],model.live[CALENDAR]['volume_total'])/300.)

    def test_cross_uses_each_previous_daily_price_and_never_today(self):
        model=self.model();days=model.calendar[-21:]
        model.daily[LEFT].loc[days,'close']=np.arange(21)+100.
        model.daily[CROSS].loc[days,'close']=100.
        for symbol in (LEFT,CROSS):model.minutes[symbol]['volume']=10.
        row=compute(model,'cross')['B09.same_time'];info=row['pair_intraday']
        ratios=(np.arange(21)+100.)*300/100/200
        self.assertAlmostEqual(info['effective_h'],ratios[-1])
        self.assertAlmostEqual(info['denominator'],np.median(600./ratios[:-1]))
        baseline=row['current']
        # An incomplete same-day close must not affect h_today or any denominator.
        current=OBSERVED_AT.tz_convert('UTC')
        for symbol in (LEFT,CROSS):
            model.daily[symbol].loc[current]=model.daily[symbol].iloc[-1]
            model.daily[symbol].loc[current,'close']=1e9 if symbol==LEFT else 1.
            model.daily[symbol].loc[current,'is_final']=False
        self.assertEqual(compute(model,'cross')['B09.same_time']['current'],baseline)

    def test_calendar_requires_no_daily_prices_cross_requires_21(self):
        model=self.model();model.daily={}
        self.assertIsNotNone(compute(model)['B09.same_time']['current'])
        self.assertIsNone(compute(model,'cross')['B09.same_time']['current'])
        model=self.model();model.daily[CROSS]=model.daily[CROSS].drop(model.calendar[-21])
        self.assertIsNone(compute(model,'cross')['B09.same_time']['current'])

    def test_ratio_source_metadata_uses_actual_daily_row_times(self):
        model=self.model()
        for symbol,seconds in ((LEFT,-60),(CROSS,30)):
            frame=model.daily[symbol]
            model.daily[symbol]=frame.rename(index={frame.index[-1]:frame.index[-1]+pd.Timedelta(seconds=seconds)})
        info=compute(model,'cross')['B09.same_time']['pair_intraday']
        self.assertEqual(info['ratio_source_times'][LEFT],model.daily[LEFT].index[-1].isoformat())
        self.assertEqual(info['ratio_source_times'][CROSS],model.daily[CROSS].index[-1].isoformat())
        self.assertEqual(info['ratio_source_time'],model.daily[CROSS].index[-1].isoformat())

    def test_malformed_history_date_and_same_time_revision_fail_closed(self):
        model=self.model();frame=model.minutes[CALENDAR]
        frame.loc[frame.event_time.eq(expected_minutes(model.calendar[-1].date())[9]),'trade_date']='bad-date'
        result=compute(model)
        self.assertIsNone(result['B09.same_time']['current'])
        self.assertIsNone(result['B11.sample']['current'])
        model=self.model();revision=model.live_rows.loc[model.live_rows.poll.eq(3)].copy()
        revision['poll']=4
        revision.loc[revision.instrument_id.eq(CALENDAR),'close']+=1.
        revision.loc[revision.instrument_id.eq(CALENDAR),'volume_total']+=1.
        model.live_rows=pd.concat([model.live_rows,revision],ignore_index=True)
        result=compute(model)
        self.assertIsNone(result['B09.same_time']['current'])
        self.assertIsNone(result['B11.sample']['current'])

    def test_zero_current_volume_and_range_are_real_values(self):
        model=FrozenPairIntradayModel('.deps/pair_intraday/synthetic','zero')
        for category in ('calendar','cross'):
            result=compute(model,category)
            for code in ('B09.same_time','B11.sample'):
                self.assertEqual(result[code]['current'],0.)
                self.assertEqual(result[code]['pair_intraday']['numerator'],0.)
                self.assertTrue(result[code]['current_history'])

    def test_zero_baseline_is_unavailable_not_infinity(self):
        model=self.model()
        for symbol in (LEFT,CALENDAR):model.minutes[symbol]['volume']=0.
        row=compute(model)['B09.same_time']
        self.assertIsNone(row['current']);self.assertEqual(row['pair_intraday']['denominator'],0.)
        for symbol,value in ((LEFT,4000.),(CALENDAR,3990.)):
            model.minutes[symbol]['close']=value
        row=compute(model)['B11.sample']
        self.assertIsNone(row['current']);self.assertEqual(row['pair_intraday']['denominator'],0.)

    def test_minute_missing_duplicate_wrong_session_or_nonfinal_rejects(self):
        for failure in ('missing','duplicate','session','both_session','nonfinal','negative_volume'):
            with self.subTest(failure=failure):
                model=self.model();frame=model.minutes[CALENDAR]
                index=frame.index[frame.event_time.eq(expected_minutes(model.calendar[-1].date())[9])][0]
                if failure=='missing':model.minutes[CALENDAR]=frame.drop(index)
                elif failure=='duplicate':model.minutes[CALENDAR]=pd.concat([frame,frame.loc[[index]]])
                elif failure in ('session','both_session'):
                    frame.loc[index,'session_id']='pm'
                    if failure=='both_session':model.minutes[LEFT].loc[index,'session_id']='pm'
                elif failure=='nonfinal':frame.loc[index,'is_final']=False
                else:frame.loc[index,'volume']=-1.
                result=compute(model)
                self.assertIsNone(result['B09.same_time']['current'])
                if failure!='negative_volume':self.assertIsNone(result['B11.sample']['current'])

    def test_tr_needs_21_full_sessions_not_20_or_only_morning(self):
        for stamp in (expected_minutes(self.frozen.calendar[-21].date())[0],
                      expected_minutes(self.frozen.calendar[-1].date())[-1]):
            model=self.model();frame=model.minutes[CALENDAR]
            model.minutes[CALENDAR]=frame.loc[frame.event_time.ne(stamp)]
            result=compute(model)
            self.assertIsNone(result['B11.sample']['current'])
            self.assertIsNotNone(result['B09.same_time']['current'])

    def test_b11_tr_is_pair_path_not_difference_of_leg_extremes(self):
        model=self.model()
        for symbol in (LEFT,CALENDAR):
            frame=model.minutes[symbol]
            frame['close']=4000. if symbol==LEFT else 3990.
            # Synchronized pair range 20; each leg range 10.
            for day in model.calendar:
                idx=expected_minutes(day.date())
                frame.loc[frame.event_time.eq(idx[0]),'close']+=10. if symbol==LEFT else 0.
                frame.loc[frame.event_time.eq(idx[1]),'close']+=10. if symbol==CALENDAR else 0.
        row=compute(model)['B11.sample']
        self.assertEqual(row['pair_intraday']['denominator'],20.)

    def test_boundary_exact_previous_three_seconds_and_never_future(self):
        for seconds,valid,approx in ((0,True,False),(-3,True,True),(-4,False,False),(1,False,False)):
            with self.subTest(seconds=seconds):
                model=self.model();model.live_rows=model.live_rows.loc[model.live_rows.poll.eq(3)].copy()
                model.live_rows['source_event_time']=OBSERVED_AT+pd.Timedelta(seconds=seconds)
                model.live_rows['observed_at']=OBSERVED_AT
                row=compute(model)['B09.same_time']
                self.assertEqual(row['current'] is not None,valid)
                if valid:self.assertEqual(row['pair_intraday']['approximation'],approx)

    def test_boundary_point_ages_even_with_fresher_later_samples(self):
        model=self.model()
        extra=model.live_rows.loc[model.live_rows.poll.eq(3)].copy()
        extra['poll']=4;extra['source_event_time']=OBSERVED_AT+pd.Timedelta(seconds=50)
        extra['observed_at']=extra.source_event_time
        # Fill continuous five-second observations so the old boundary remains
        # in the same segment; it still cannot be published fifty seconds later.
        batches=[model.live_rows]
        for seconds in range(5,51,5):
            q=extra.copy();q['poll']=3+seconds;q['source_event_time']=OBSERVED_AT+pd.Timedelta(seconds=seconds);q['observed_at']=q.source_event_time;batches.append(q)
        model.live_rows=pd.concat(batches,ignore_index=True)
        row=compute(model,now=OBSERVED_AT+pd.Timedelta(seconds=50))['B09.same_time']
        self.assertIsNone(row['current'])

    def test_invalid_intermediate_batch_breaks_range_instead_of_skipping(self):
        model=self.model()
        model.live_rows=model.live_rows.loc[~(model.live_rows.poll.eq(1)&model.live_rows.instrument_id.eq(CALENDAR))]
        row=compute(model)['B11.sample']
        self.assertEqual(row['current_n'],2)
        self.assertEqual(len(row['current_history']),1)
        self.assertEqual(pd.Timestamp(row['pair_intraday']['segment_start']),OBSERVED_AT-pd.Timedelta(seconds=5))

    def test_latest_poll_without_both_legs_is_a_barrier_but_other_chunks_are_not(self):
        model=self.model()
        drop=model.live_rows.poll.eq(3)&model.live_rows.instrument_id.isin([LEFT,CALENDAR])
        model.live_rows=model.live_rows.loc[~drop]
        result=compute(model)
        self.assertIsNone(result['B09.same_time']['current'])
        self.assertIsNone(result['B11.sample']['current'])
        model=self.model()
        unrelated=~model.live_rows.instrument_id.isin([LEFT,CALENDAR])
        model.live_rows.loc[unrelated,'batch']=2
        result=compute(model)
        self.assertEqual(result['B11.sample']['current_n'],4)
        self.assertIsNotNone(result['B09.same_time']['current'])
        # Never assemble a synthetic single HTTP observation from two chunks.
        model.live_rows.loc[model.live_rows.instrument_id.eq(CALENDAR),'batch']=3
        result=compute(model)
        self.assertIsNone(result['B11.sample']['current'])

    def test_latest_missing_all_required_spots_does_not_continue_previous_range(self):
        model=self.model()
        drop=model.live_rows.poll.eq(3)&~model.live_rows.instrument_id.str.endswith('.CFE')
        model.live_rows=model.live_rows.loc[~drop]
        result=compute(model,'cross','basis')
        self.assertIsNotNone(result['B09.same_time']['current'])
        self.assertIsNone(result['B11.sample']['current'])
        self.assertEqual(result['B11.sample']['current_n'],0)

    def test_latest_missing_invalid_misaligned_or_future_input_clears_segment(self):
        for failure in ('missing','nan','mismatch','future','receipt_before_source'):
            with self.subTest(failure=failure):
                model=self.model();mask=model.live_rows.poll.eq(3)&model.live_rows.instrument_id.eq(CALENDAR)
                if failure=='missing':model.live_rows=model.live_rows.loc[~mask]
                elif failure=='nan':model.live_rows.loc[mask,'close']=np.nan
                elif failure=='mismatch':model.live_rows.loc[mask,'source_event_time']=OBSERVED_AT-pd.Timedelta(seconds=1)
                elif failure=='future':model.live_rows.loc[mask,'source_event_time']=OBSERVED_AT+pd.Timedelta(seconds=1)
                else:model.live_rows.loc[mask,'observed_at']=OBSERVED_AT-pd.Timedelta(seconds=1)
                result=compute(model)
                self.assertIsNone(result['B11.sample']['current'])
                self.assertEqual(result['B11.sample']['current_n'],0)
                self.assertIsNone(result['B09.same_time']['current'])

    def test_reconnect_gap_and_quality_reset_start_new_segment(self):
        for failure in ('run','gap','quality','lunch','day'):
            with self.subTest(failure=failure):
                model=self.model();latest=model.live_rows.poll.eq(3)
                if failure=='run':model.live_rows.loc[latest,'run_id']='new'
                elif failure=='quality':model.live_rows.loc[latest,'quality_flags']=16
                else:
                    old=model.live_rows.loc[~latest].copy()
                    delta={'gap':pd.Timedelta(seconds=60),'lunch':pd.Timedelta(hours=2),'day':pd.Timedelta(days=1)}[failure]
                    old['source_event_time']=old.source_event_time-delta;old['observed_at']=old.observed_at-delta
                    model.live_rows=pd.concat([old,model.live_rows.loc[latest]],ignore_index=True)
                result=compute(model)
                self.assertIsNone(result['B11.sample']['current'])
                self.assertEqual(result['B11.sample']['current_n'],1)
                self.assertIsNotNone(result['B09.same_time']['current'])

    def test_stale_and_lunch_do_not_reuse_last_valid_value(self):
        for now in (OBSERVED_AT+pd.Timedelta(seconds=31),OBSERVED_AT.replace(hour=12)):
            result=compute(self.frozen,now=now)
            self.assertIsNone(result['B11.sample']['current'])
            self.assertIsNone(result['B09.same_time']['current'])

    def test_future_receipts_are_excluded_by_prefix_replay(self):
        model=self.model();prefix=model.live_rows.loc[model.live_rows.poll.lt(3)].copy()
        asof=OBSERVED_AT-pd.Timedelta(seconds=5)
        first=compute(model,now=asof)
        model.live_rows=prefix
        second=compute(model,now=asof)
        self.assertEqual(first,second)

    def test_future_bar_duplicates_do_not_change_past_reference_pool(self):
        model=self.model();before=compute(model,'cross')
        for symbol in (LEFT,CROSS):
            future=model.minutes[symbol].iloc[[-1,-1]].copy()
            future['event_time']=OBSERVED_AT.tz_convert('UTC')+pd.Timedelta(days=1)
            model.minutes[symbol]=pd.concat([model.minutes[symbol],future],ignore_index=True)
            future_daily=model.daily[symbol].iloc[[-1,-1]].copy()
            future_daily.index=pd.DatetimeIndex([OBSERVED_AT.tz_convert('UTC')+pd.Timedelta(days=1)]*2)
            model.daily[symbol]=pd.concat([model.daily[symbol],future_daily])
        self.assertEqual(before,compute(model,'cross'))

    def test_volume_does_not_depend_on_spot_or_annual_validity(self):
        model=self.model();model.live_rows=model.live_rows.loc[model.live_rows.instrument_id.str.endswith('.CFE')]
        model.metadata[LEFT]['expiry_date']='2026-10-23'
        result=compute(model,'cross','annual')
        self.assertIsNotNone(result['B09.same_time']['current'])
        self.assertIsNone(result['B11.sample']['current'])
        self.assertIsNotNone(compute(model,'cross','future')['B11.sample']['current'])

    def test_empty_observations_revalidate_direct_live_point_and_clear_sample(self):
        model=self.model();rows=list(compute(model,samples=False,live=True).values())
        model.live_rows=pd.DataFrame()
        observations(rows,model.live_rows,LEFT,CALENDAR,'calendar','future',model.daily,model.minutes,
                     model.metadata,model.dividends,OBSERVED_AT)
        self.assertIsNotNone(next(r for r in rows if r['id']=='B09.same_time')['current'])
        observations(rows,model.live_rows,LEFT,CALENDAR,'calendar','future',model.daily,model.minutes,
                     model.metadata,model.dividends,OBSERVED_AT+pd.Timedelta(seconds=31))
        self.assertTrue(all(r['current'] is None for r in rows))

    def test_old_cached_values_and_history_are_not_written_or_reused(self):
        model=self.model();before={s:f.copy(deep=True) for s,f in model.minutes.items()}
        rows=[dict(id='B09',value=42.,history=[dict(time='daily',value=42.)],current=None),
              dict(id='B11',value=17.,history=[dict(time='daily',value=17.)],current=None)]
        frozen=deepcopy(rows);result=compute(model,rows=rows)
        self.assertEqual(rows[:2],frozen)
        for symbol in before:pd.testing.assert_frame_equal(model.minutes[symbol],before[symbol])
        model.live_rows=model.live_rows.loc[~(model.live_rows.poll.eq(3)&model.live_rows.instrument_id.eq(CALENDAR))]
        updated=compute(model,rows=rows)
        self.assertIsNone(updated['B09.same_time']['current'])
        self.assertIsNone(updated['B11.sample']['current'])
        self.assertEqual(updated['B11.sample']['current_history'],[])

    def test_full_calculate_preserves_daily_primaries_and_new_child_version(self):
        model=self.model()
        result=model.snapshot(dict(left=LEFT,right=CROSS,category='cross',price_input='future'))
        rows={r['id']:r for r in result['metrics']}
        for code in ('B09','B11'):
            self.assertIsNotNone(rows[code]['value'])
            self.assertIsNone(rows[code]['current'])
            self.assertEqual(rows[code]['formula_version'],'contract-pair-v3')
        for code in ('B09.same_time','B11.sample'):
            self.assertIsNotNone(rows[code]['current'])
            self.assertEqual(rows[code]['history'],[])
            self.assertEqual(rows[code]['formula_version'],PAIR_INTRADAY_VERSION)


if __name__ == '__main__':
    unittest.main()
