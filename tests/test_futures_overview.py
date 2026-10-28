"""Presentation derivatives keep v6 units, concrete identities and strict clocks."""
import unittest

import pandas as pd

from dashboard.native.futures_overview import details
from dashboard.native.market_overview import quote_card
from tests.test_market_overview import NOW, observation,futures_values


def fixture():
    live={'000300.SH':observation(4024,4000)}
    items=[('2611','2026-11-20',4008,62),('2612','2026-12-18',3990,25),
           ('2703','2027-03-19',3946,10),('2706','2027-06-18',3920,3)]
    for month,_,price,volume in items:
        live['IF'+month+'.CFE']={**observation(price,3981.6),'volume_total':volume}
    return live,items


def calculate(live,items,observations=None):
    rows=[];metadata={'IF'+month+'.CFE':dict(expiry_date=expiry) for month,expiry,_,_ in items}
    spot=quote_card('000300.SH','沪深300','IF',live,{},NOW,'2026-10-23')
    for slot,(month,_,_,_) in enumerate(items):
        symbol='IF'+month+'.CFE';row=quote_card(symbol,'沪深300','IF',live,{},NOW,'2026-10-23');row['slot']=slot
        futures_values(row,live,{},metadata,NOW);rows.append(row)
    result=details(rows,[spot],live,pd.DataFrame() if observations is None else observations,NOW)
    return result['IF'],rows


class FuturesOverviewTests(unittest.TestCase):
    def test_spread_previous_change_and_full_volume_distribution(self):
        live,items=fixture();group,rows=calculate(live,items)
        self.assertAlmostEqual(group['basis_change_previous'],2.4)
        self.assertEqual(group['calendar_points'],18)
        self.assertEqual([r['share_pct'] for r in group['distribution']],[62,25,10,3])
        self.assertEqual([r['days'] for r in rows],[25,53,144,235])
        self.assertTrue(all(r['percentile'] is None for r in rows))
        self.assertTrue(all(r['annual_pct'] is not None for r in rows))

    def test_five_minute_change_uses_paired_historical_observations(self):
        live,items=fixture();at=NOW-pd.Timedelta(minutes=5)
        frame=pd.DataFrame([dict(observation(4008.8,3981.6,at),instrument_id='IF2611.CFE'),
                            dict(observation(4024,4000,at),instrument_id='000300.SH')])
        group,_=calculate(live,items,frame)
        self.assertAlmostEqual(group['basis_change_5m'],-.8)
        frame.loc[1,'source_event_time']=(at-pd.Timedelta(seconds=4)).isoformat()
        group,_=calculate(live,items,frame);self.assertIsNone(group['basis_change_5m'])

    def test_missing_previous_close_does_not_remove_current_price_or_calendar(self):
        live,items=fixture();live['IF2611.CFE']['prev_close']=None
        group,rows=calculate(live,items)
        self.assertIsNone(group['basis_change_previous']);self.assertEqual(group['calendar_points'],18)
        self.assertEqual(rows[0]['price'],4008);self.assertEqual(rows[0]['basis_points'],-16)

    def test_partial_or_unsynchronised_quotes_do_not_make_complete_volume_shares(self):
        live,items=fixture();live['IF2706.CFE']['source_event_time']=(NOW-pd.Timedelta(seconds=31)).isoformat()
        group,rows=calculate(live,items)
        self.assertEqual(group['distribution'],[]);self.assertEqual(group['calendar_points'],18)
        self.assertIsNone(rows[-1]['annual_pct'])
        live,items=fixture()
        live['IF2611.CFE']['source_event_time']=(NOW-pd.Timedelta(seconds=3)).isoformat()
        live['IF2612.CFE']['source_event_time']=(NOW+pd.Timedelta(seconds=3)).isoformat()
        group,rows=calculate(live,items)
        self.assertIsNotNone(rows[0]['basis_points']);self.assertIsNotNone(rows[1]['basis_points'])
        self.assertIsNone(group['calendar_points']);self.assertEqual(group['distribution'],[])

    def test_valid_zero_previous_change_and_zero_total_volume(self):
        live,items=fixture()
        for symbol,q in live.items():q['prev_close']=q['close'];q['volume_total']=0
        group,_=calculate(live,items)
        self.assertEqual(group['basis_change_previous'],0)
        self.assertEqual(group['distribution'],[]);self.assertIn('合计为0',group['distribution_reason'])


if __name__=='__main__':unittest.main()
