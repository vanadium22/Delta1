import unittest
from dashboard.percentile_audit import independent_value,independent_rank


class AuditTests(unittest.TestCase):
    def test_zero_is_a_real_tail_and_not_missing(self):
        self.assertEqual(independent_rank([1.,2.,3.],-1.),0.)
        self.assertIsNone(independent_rank([None,2.],-1.))
        self.assertIsNone(independent_rank([1.,2.],None))

    def test_ties_and_percentage_units(self):
        self.assertEqual(independent_rank([0.,0.,1.,2.],0.),25.)
        self.assertAlmostEqual(independent_value(4000.,4000.,40.,365),1.)

    def test_t_below_five_and_missing_dividends_stay_missing(self):
        self.assertIsNone(independent_value(4000.,4000.,20.,4))
        self.assertIsNone(independent_value(4000.,4000.,None,10))
        self.assertEqual(independent_value(4000.,4000.,0.,5),0.)

    def test_stale_quote_can_have_zero_historical_rank_without_a_live_value(self):
        import pandas as pd
        from types import SimpleNamespace
        from dashboard.native.card_data import overview_card
        cal=pd.date_range('2026-09-01 07:00',periods=21,freq='B',tz='UTC')
        now=cal[-1]+pd.Timedelta(days=1)
        f=pd.DataFrame(dict(points=[1.]*20+[-1.],basis=[1.]*20+[-1.],annual=[1.]*20+[-1.],T=[30.]*21),index=cal)
        book=SimpleNamespace(points=lambda *_:0.,info={},reason='')
        q=dict(close=4000.,received_at=cal[-1].isoformat(),source_event_time=cal[-1].isoformat())
        card=overview_card('IF2612.CFE',{},cal,{'IF2612.CFE':{'expiry_date':'2026-12-18'}},book,
            {'IF2612.CFE':q,'000300.SH':q},now,'annual',(f,{'alias':'IF03.CFE'}))
        self.assertIsNone(card['current']['annual_pct'])
        self.assertEqual(card['chart']['kind'],'历史')
        self.assertEqual(card['chart']['time'],cal[-1].isoformat())
        self.assertEqual(card['chart']['rows'][0]['n'],20)
        self.assertEqual(card['chart']['rows'][0]['percentile'],0.)


if __name__=='__main__':unittest.main()
