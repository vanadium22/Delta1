from datetime import datetime
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch
import pandas as pd
from dashboard.session_clock import session_policy, SessionStop
from dashboard.display_state import cached_pair_time, display_snapshot, latest_saved_pair
from dashboard.numeric_excel import workbook_payload
from dashboard.numeric_snapshot import freeze_state


class SessionTests(unittest.TestCase):
    def test_boundaries_calendar_and_unknown_year_fail_closed(self):
        for clock, expected in [('09:28:59',False),('09:29:00',True),('15:00:59',True),('15:01:00',False)]:
            self.assertEqual(session_policy(datetime.fromisoformat('2026-10-19T'+clock+'+08:00'))['allowed'],expected)
        for day in ('2026-10-18','2026-10-01','2030-10-21'):
            with patch('requests.Session',side_effect=AssertionError('clock must be offline')):
                self.assertFalse(session_policy(datetime.fromisoformat(day+'T10:00:00+08:00'))['allowed'])

    def test_collector_stops_at_boundary_and_offline_probe_never_constructs_client(self):
        stop=SessionStop(threading.Event(),policy=lambda:dict(allowed=False))
        self.assertTrue(stop.wait(0));self.assertTrue(stop.is_set())
        from dashboard.session_guard import probe_realtime
        from dashboard.native.collection import CollectionJob
        client=Mock()
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=False,reason='盘后')):
            self.assertTrue(probe_realtime({},client)['offline'])
            job=CollectionJob('.');job.start('unused',['IF2611.CFE'],set(),client_factory=client)
            self.assertFalse(job.running());client.assert_not_called()

    def test_saved_pairs_reject_stale_source_mixed_times_and_future(self):
        now=pd.Timestamp('2026-10-19T18:00:00+08:00')
        q=dict(close=4200.,source_event_time='2026-10-19T15:00:00+08:00',observed_at='2026-10-19T15:00:02+08:00')
        self.assertIsNotNone(cached_pair_time(q,q,now))
        self.assertIsNone(cached_pair_time(q,{**q,'source_event_time':'2026-10-19T14:58:00+08:00'},now))
        self.assertIsNone(cached_pair_time(q,q,pd.Timestamp('2026-10-19T09:00:00+08:00')))
        self.assertIsNone(cached_pair_time({**q,'close':0},q,now))

    def test_later_stale_poll_does_not_erase_last_valid_cache(self):
        rows=[]
        for received,source in [('2026-10-19T15:00:02+08:00','2026-10-19T15:00:00+08:00'),('2026-10-19T15:11:00+08:00','2026-10-19T15:00:00+08:00')]:
            for symbol in ('IF2611.CFE','000300.SH'):
                rows.append(dict(instrument_id=symbol,close=4200.,observed_at=pd.Timestamp(received),source_event_time=source))
        saved=latest_saved_pair(SimpleNamespace(live_rows=pd.DataFrame(rows)),'IF2611.CFE','000300.SH',pd.Timestamp('2026-10-19T18:00:00+08:00'))
        self.assertEqual(saved[2],pd.Timestamp('2026-10-19T15:00:00+08:00'))
        self.assertEqual(saved[0]['observed_at'],pd.Timestamp('2026-10-19T15:00:02+08:00'))


class DisplayTests(unittest.TestCase):
    def fixture(self, live=False):
        dates=pd.date_range('2026-09-10T07:00:00Z',periods=25,freq='B')
        refs={f'IF{m}.CFE':dict(listing_date='2026-09-01',expiry_date=d) for m,d in [('2611','2026-11-20'),('2612','2026-12-18'),('2703','2027-03-19'),('2706','2027-06-18')]}
        daily={s:pd.DataFrame(dict(close=[4100.]*25),index=dates) for s in refs}
        daily['000300.SH']=pd.DataFrame(dict(close=[4200.]*25),index=dates)
        q=dict(close=4150.,source_event_time='2026-10-19T15:00:00+08:00',observed_at='2026-10-19T15:00:02+08:00') if live else {}
        card=dict(symbol='IF2611.CFE',root='IF',alias='IF00.CFE',name='IF',expiry='2026-11-20',spot_symbol='000300.SH',quote=q,spot={**q,'close':4200.} if live else {},
            aligned=False,quality=dict(usable=False,status='陈旧'),reason='陈旧',current={},days=32,dividend=2.,historical={},chart={})
        state=dict(as_of='2026-10-19T10:00:00Z',versions={},dividend_version='test',dividend_mode='fixed_snapshot',selection=dict(overview_slot=0),overview=[card],
            entities=[dict(left='IF2611.CFE',right='000300.SH',title='IF',metrics=[dict(id='A02.annual',title='年化',unit='%',formula='F-S+D',value=None,current=None,reason='')])])
        model=SimpleNamespace(config={},research_engine=SimpleNamespace(daily=daily,calendar=dates),snapshot=Mock(return_value=state))
        book=SimpleNamespace(mode='fixed_snapshot',version='test',points=lambda s,d:2.)
        return model,refs,book

    def run_display(self,model,refs,book,now='2026-10-19T18:00:00+08:00',saved=None):
        with patch('dashboard.display_state.ReferenceBook'),patch('dashboard.display_state.latest_contracts',return_value=refs),patch('dashboard.display_state.DividendBook.load',return_value=book),patch('dashboard.display_state.daily_saved_pairs',return_value=saved or {}):
            return display_snapshot(model,dict(cards=True,category='basis',distribution_input='annual'),now=now)

    def test_after_close_uses_coherent_cache_without_changing_raw_snapshot(self):
        model,refs,book=self.fixture(live=True)
        state=self.run_display(model,refs,book)
        card=state['overview'][0]
        self.assertEqual(card['display_kind'],'保存行情回看');self.assertEqual(card['current']['points'],-48.)
        self.assertFalse(card['quality']['usable']);self.assertEqual(model.snapshot.return_value['overview'][0]['current'],{})
        self.assertEqual(state['entities'][0]['metrics'][0]['display_kind'],'保存行情回看')

    def test_daily_calculation_cache_survives_missing_sqlite_tail(self):
        model,refs,book=self.fixture(live=True)
        q=model.snapshot.return_value['overview'][0]['quote'].copy()
        s={**q,'close':4200.}
        model.snapshot.return_value['overview'][0].update(quote={},spot={})
        state=self.run_display(model,refs,book,saved={'IF2611.CFE':(q,s,pd.Timestamp(q['source_event_time']))})
        self.assertEqual(state['overview'][0]['display_kind'],'保存行情回看')
        self.assertEqual(state['overview'][0]['current']['points'],-48.)

    def test_history_uses_original_day_T_and_latest_prices_and_preserves_zero(self):
        model,refs,book=self.fixture()
        state=self.run_display(model,refs,book)
        card=state['overview'][0]
        self.assertEqual(card['display_kind'],'历史收盘')
        expected=(pd.Timestamp('2026-11-20').date()-model.research_engine.calendar[-1].date()).days
        self.assertEqual(card['days'],expected);self.assertEqual(card['current']['points'],-98.)
        payload=freeze_state(state)
        payload['snapshots'][0]['overview'][0]['chart']['rows'][0]['percentile']=0.
        feed=workbook_payload(payload)
        self.assertEqual(feed['sheets']['分位与样本'][0][4],0.)
        self.assertEqual(feed['sheets']['数字看板'][0][9],card['current']['annual_pct']/100)
        self.assertTrue(feed['sheets']['研究指标'])


if __name__=='__main__':unittest.main()
