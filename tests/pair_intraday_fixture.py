"""Synthetic full minute history and HTTP observations, with no I/O or collector.

FrozenPairIntradayModel mirrors FrozenIndicatorModel. Scenarios use real source
inputs, never precomputed indicator results. Default pairs: IF2612/IF2703 or
IF2612/IC2612. All instruments are otherwise available to frontend matrices.
"""
import numpy as np
import pandas as pd

try:
    from tests.indicator_frozen_fixture import FrozenIndicatorModel, OBSERVED_AT
except ModuleNotFoundError:
    from indicator_frozen_fixture import FrozenIndicatorModel, OBSERVED_AT


class FrozenPairIntradayModel(FrozenIndicatorModel):
    def __init__(self, local_root, scenario='valid', at=OBSERVED_AT):
        self.observed_at = pd.Timestamp(at)
        super().__init__(local_root)
        self.versions = {'synthetic': 'frozen-pair-intraday-v1-' + scenario}
        self.indicator_context['versions'] = self.versions
        self.research_engine.history_key = ('frozen-pair-intraday-v1', scenario)
        self.scenario = scenario
        self._samples(scenario)
        if scenario == 'missing_history':
            # Yesterday's missing 09:40 minute breaks both historical pools.
            at = self.calendar[-1].tz_convert('Asia/Shanghai').normalize() + pd.Timedelta(hours=9, minutes=40)
            self.minutes = {s:f.loc[f.event_time.ne(at)].copy() for s,f in self.minutes.items()}

    def _minutes(self, daily_closes, phase):
        from dashboard.native.intraday import expected_minutes
        frames = []
        for offset, day in enumerate(self.calendar):
            index = expected_minutes(day.tz_convert('Asia/Shanghai').date())
            axis = np.arange(len(index), dtype=float)
            close = float(daily_closes[offset]) + np.sin(axis / (11 + phase) + phase) * (0.3 + phase * .08) + axis * .002
            volume = 10. + (axis + phase) % 7
            local = index.tz_convert('Asia/Shanghai')
            frames.append(pd.DataFrame(dict(event_time=index, open=close-.05,high=close+.1,
                low=close-.1,close=close,prev_close=float(daily_closes[max(0,offset-1)]),
                volume=volume,open_interest=3000.+axis,turnover=close*volume*200,
                session_id=['am' if t.hour<12 else 'pm' for t in local],
                trade_date=local.date,is_final=True)))
        return pd.concat(frames,ignore_index=True)

    def _samples(self, scenario):
        if scenario not in ('valid','zero','missing_history','reconnect','missing_leg','stale'):
            raise ValueError('Unknown synthetic scenario: '+scenario)
        now = self.observed_at - (pd.Timedelta(seconds=31) if scenario=='stale' else pd.Timedelta(0))
        records=[]
        for poll, seconds in enumerate((15,10,5,0)):
            at = now-pd.Timedelta(seconds=seconds)
            self.enable_live(at)
            for i,(symbol,q) in enumerate(self.live.items()):
                q['close'] += 0. if scenario=='zero' else poll*(.03+.007*i)
                q['volume_total'] = 0. if scenario=='zero' else 1500.+poll*10+i*3
                q['run_id'] = 'frozen-reconnected' if scenario=='reconnect' and poll==3 else 'frozen-pair-http'
                if scenario=='missing_leg' and poll==3 and symbol.endswith('.CFE') and symbol!='IF2612.CFE':
                    continue
                records.append(dict(instrument_id=symbol,poll=poll,batch=1,quality_flags=0,**q))
        self.live_rows=pd.DataFrame(records)
        self.live_rows['observed_at']=pd.to_datetime(self.live_rows.observed_at,utc=True)
        self.live_rows['source_event_time']=pd.to_datetime(self.live_rows.source_event_time,utc=True)
        final=self.live_rows.loc[self.live_rows.poll.eq(3)]
        self.live={r['instrument_id']:r for r in final.to_dict('records')}

    def snapshot(self, request):
        request=dict(request)
        request.setdefault('as_of',self.observed_at.isoformat())
        state=super().snapshot(request)
        if not request.get('cards'):
            from dashboard.native.intraday import observations
            observations(state['metrics'],self.live_rows,state['left'],state['right'],state['category'],
                state['price_input'],self.daily,self.minutes,self.metadata,self.dividends,
                pd.Timestamp(request['as_of']),self.research_engine.observation_cache)
        return state
