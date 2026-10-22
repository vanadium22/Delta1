"""Frozen synthetic source bars shared by Excel and local Qt acceptance.

Prices and observations are generated here. Every indicator value is calculated
by the production calculate/dashboard_cards functions; no result is hard coded.
The synthetic bars use the repository's known 2026 exchange calendar.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from dashboard.marketdata.dividends import DividendBook
from dashboard.native.instruments import UNDERLYINGS

OBSERVED_AT = pd.Timestamp('2026-10-22T10:30:00+08:00')
MONTHS = (('2611', '2026-11-20'), ('2612', '2026-12-18'),
          ('2703', '2027-03-19'), ('2706', '2027-06-18'))
ROOTS = ('IF', 'IH', 'IC', 'IM')


class FrozenIndicatorModel:
    def __init__(self, local_root):
        self.local_root = Path(local_root)
        self.config = dict(history_roots=[], realtime_root='', dividend_root='',
                           reference_file=None, history_maintenance_enabled=False)
        self.realtime_verified = False
        self.contract_sync = {'message': '冻结合成输入；未访问接口'}
        self.live_rows = pd.DataFrame()
        self.live = {}
        self.metadata = {root + month + '.CFE': dict(listing_date='2026-01-01', expiry_date=expiry)
                         for root in ROOTS for month, expiry in MONTHS}
        from dashboard.native.intraday import previous_day
        sessions=[];day=previous_day(OBSERVED_AT)
        for _ in range(35):
            sessions.append(pd.Timestamp(str(day)+' 15:00',tz='Asia/Shanghai'))
            day=previous_day(pd.Timestamp(str(day)+' 10:00',tz='Asia/Shanghai'))
        self.calendar = pd.DatetimeIndex(list(reversed(sessions))).tz_convert('UTC')
        self.daily = {}; self.minutes = {}
        axis = np.arange(len(self.calendar), dtype=float)
        mapping = {}
        for root_index, root in enumerate(ROOTS):
            spot = UNDERLYINGS[root][0]
            base = (4000, 2700, 6000, 6500)[root_index]
            closes = base + axis * (1 + .2 * root_index) + np.sin(axis / 3) * 2
            self.daily[spot] = self._daily(closes, 50000 + axis * 20, np.nan)
            self.minutes[spot] = self._minutes(closes, root_index)
            for month_index, (month, expiry) in enumerate(MONTHS):
                symbol = root + month + '.CFE'
                basis = -9 - month_index * 6 + np.sin(axis / 2 + root_index) * 4 + axis * .12
                oi = 2000 + axis * (2 + month_index) + (3500 if month_index == (root_index + 1) % 4 else 0)
                volume = 1000 + axis * 3 + month_index * 30
                self.daily[symbol] = self._daily(closes + basis, volume, oi)
                self.minutes[symbol] = self._minutes(closes + basis, root_index + month_index + 1)
                mapping[symbol] = dict(points=float(2 + month_index), expiry=expiry, alias=symbol)
        self.dividends = DividendBook(reason='', version='frozen-dividend-scenario-v1',
            info=dict(mapping=mapping, snapshot_date='2026-10-21', mapping_anchor='2026-10-21',
                      mapping_policy='冻结合成固定分红情景', inherited=False))
        self.versions = {'synthetic': 'frozen-indicators-2026-10-22-v1'}
        self.indicator_context = dict(metadata=self.metadata, daily=self.daily,
            calendar=self.calendar, versions=self.versions, reference_version='frozen-reference-v1',
            dividend_version=self.dividends.version)
        self.research_engine = SimpleNamespace(history_key=('frozen-v1',), card_metric_cache={},
            observation_cache={}, model=self, daily=self.daily, calendar=self.calendar)
        self.snapshot_calls = []

    def _daily(self, closes, volume, oi):
        return pd.DataFrame(dict(open=closes - .7, high=closes + 2, low=closes - 2,
            close=closes, prev_close=np.r_[closes[0] - 1, closes[:-1]], volume=volume,
            open_interest=oi, turnover=np.asarray(closes) * volume * 200,
            is_final=True, source='synthetic_complete_history'), index=self.calendar)

    def _minutes(self, daily_closes, phase):
        # Six complete synthetic sessions plus the observed morning allow both
        # daily OHLC proxy and continuous-minute guards to run on real inputs.
        frames = []
        for offset, day in enumerate(list(self.calendar[-6:]) + [OBSERVED_AT]):
            local = day.tz_convert('Asia/Shanghai').normalize()
            morning = pd.date_range(local + pd.Timedelta(hours=9, minutes=31), periods=120, freq='min')
            afternoon = pd.date_range(local + pd.Timedelta(hours=13, minutes=1), periods=120, freq='min')
            stamps = morning.append(afternoon)
            if day == OBSERVED_AT:
                stamps = stamps[stamps <= OBSERVED_AT]
            axis = np.arange(len(stamps), dtype=float)
            last = float(daily_closes[-6 + min(offset, 5)])
            close = last - .6 + axis * .004 + np.sin(axis / 9 + phase) * .3
            frames.append(pd.DataFrame(dict(event_time=stamps.tz_convert('UTC'),
                open=close - .05, high=close + .1, low=close - .1, close=close,
                prev_close=last - 1, volume=10 + axis % 7,
                open_interest=3000 + axis, turnover=close * (10 + axis % 7) * 200,
                session_id=['am' if t.hour < 12 else 'pm' for t in stamps],
                trade_date=[t.date() for t in stamps])))
        return pd.concat(frames, ignore_index=True)

    def snapshot(self, request):
        from dashboard.native.nonregression import calculate
        from dashboard.native.card_data import dashboard_cards, selections
        self.snapshot_calls.append(deepcopy(request))
        now = pd.Timestamp(request.get('as_of') or OBSERVED_AT)
        calendar = self.calendar[self.calendar <= now]
        daily = {symbol: frame.loc[frame.index <= now] for symbol, frame in self.daily.items()}
        minutes = {symbol: frame.loc[frame.event_time <= now] for symbol, frame in self.minutes.items()}
        left = request.get('left') or 'IF2612.CFE'
        category = request.get('category', 'basis')
        right = request.get('right') or (UNDERLYINGS[left[:2]][0] if category == 'basis' else 'IF2703.CFE')
        price = request.get('price_input', 'basis')
        metrics = [] if request.get('cards') else calculate(left, right, category, price, daily, minutes,
            self.metadata, self.dividends, calendar, self.live, now, participation=request.get('participation'))
        state = dict(as_of=now.isoformat(), product=left[:2], frequency='1d', demo=False,
            versions=self.versions, quotes=[dict(symbol=s,**q) for s,q in self.live.items()], metrics=metrics, coverage=[], contracts=sorted(self.metadata),
            active_contracts=sorted(self.metadata), left=left, right=right, category=category,
            price_input=price, pair_error=None, errors=[], dividend_info=self.dividends.info,
            dividend_reason='', dividend_mode=self.dividends.mode, dividend_version=self.dividends.version)
        if request.get('cards'):
            selection = selections(request, sorted(self.metadata), sorted(self.metadata), left,
                                   self.metadata, now)
            state.update(dashboard_cards(self.research_engine, state, request, selection, daily, calendar,
                self.metadata, self.dividends, self.live, now, lambda symbol: minutes.get(symbol, pd.DataFrame())))
        return state

    def enable_live(self, at=OBSERVED_AT, delta=0.):
        """One frozen synchronous synthetic quote batch, without a collector."""
        at=pd.Timestamp(at)
        self.live={s:dict(close=float(f.close.iloc[-1])+delta, high=float(f.close.iloc[-1])+abs(delta)+2,
            low=float(f.close.iloc[-1])-abs(delta)-2, open=float(f.close.iloc[-1])-.7,
            volume=350.,volume_total=350.,open_interest=float(f.open_interest.iloc[-1]) if s.endswith('.CFE') else None,
            source_event_time=at.isoformat(),observed_at=at.isoformat(),run_id='frozen-live-v1')
            for s,f in self.daily.items()}

    def close(self):
        pass
