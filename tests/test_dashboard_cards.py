"""Card aggregation must retain financial and temporal boundaries."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pandas as pd

from dashboard.native.card_data import distributions,group_metrics,selections,overview_card,dashboard_cards
from dashboard.marketdata.dividends import DividendBook


class CardDataTests(unittest.TestCase):
    def setUp(self):
        self.calendar=pd.date_range('2026-08-03 07:00',periods=53,freq='B',tz='UTC')
        self.series=pd.Series(np.arange(-52.,1.),index=self.calendar)

    def test_distribution_excludes_current_and_never_shortens_missing_window(self):
        rows=distributions(self.series,self.calendar,self.calendar[-1],0.,listing='2026-07-01')
        self.assertTrue(rows[0]['complete']);self.assertEqual(rows[0]['n'],20)
        self.assertEqual(rows[0]['percentile'],100.)
        self.assertAlmostEqual(rows[0]['p50'],-10.5)
        self.assertFalse(rows[1]['complete'])
        damaged=self.series.copy();damaged.iloc[-4]=np.nan
        self.assertFalse(distributions(damaged,self.calendar,self.calendar[-1],0.)[0]['complete'])
        constant=distributions(self.series*0,self.calendar,self.calendar[-1],0.)[0]
        self.assertTrue(constant['complete']);self.assertEqual(constant['percentile'],50.)

    def test_continuous_partial_window_exposes_missing_dates_without_filling(self):
        damaged=self.series.copy();damaged.iloc[-4]=np.nan
        row=distributions(damaged,self.calendar,self.calendar[-1],0.,allow_partial=True)[0]
        self.assertFalse(row['complete']);self.assertTrue(row['available'])
        self.assertEqual(row['n'],19);self.assertEqual(row['missing'],1)
        self.assertEqual(row['percentile'],100.)
        self.assertEqual(row['missing_dates'],[str(self.calendar[-4].date())])
        self.assertFalse(distributions(damaged.iloc[-3:],self.calendar[-3:],self.calendar[-1],0.,allow_partial=True)[0]['available'])

    def test_natural_month_requires_listing_and_negative_crossing_is_valid(self):
        cal=pd.date_range('2026-01-01 07:00',periods=210,freq='B',tz='UTC')
        series=pd.Series(np.linspace(-50,50,len(cal)),index=cal)
        row=distributions(series,cal,cal[-1],0.,listing='2026-01-01')[1]
        self.assertTrue(row['complete']);self.assertEqual(row['percentile'],0)
        self.assertFalse(distributions(series,cal,cal[-1],0.,listing='2026-09-01')[1]['complete'])

    def test_annual_excludes_ineligible_days_without_padding(self):
        expiry=self.calendar[-1].tz_convert('Asia/Shanghai').date().isoformat()
        rows=distributions(self.series,self.calendar,self.calendar[-1],0.,listing='2026-01-01',expiry=expiry,annual=True)
        self.assertFalse(rows[0]['complete']);self.assertLess(rows[0]['n'],20)

    def test_selection_is_fixed_month_for_every_root_and_preserves_missing_legs(self):
        contracts=[p+m+'.CFE' for p in ('IF','IH','IC','IM') for m in ('2609','2610','2612','2703')]
        selection=selections({'category':'calendar','research_month':'2610','far_month':'2612','overview_month':'2609'},contracts,contracts[1:],'IF2612.CFE')
        self.assertEqual(selection['pairs'][2],('IC','IC2610.CFE','IC2612.CFE'))
        self.assertEqual(selection['overview_symbols'][0],'IF2609.CFE')
        cross=selections({'category':'cross','cross_pair':'IM/IC'},contracts,contracts,'IF2612.CFE')
        self.assertEqual(cross['pairs'],[('IM − IC','IM2612.CFE','IC2612.CFE')])

    def test_fixed_contract_percentile_is_not_hidden_by_overview_distribution(self):
        metrics=[{'id':x} for x in ('A01.points','A01.bp','A02.annual','A02.convergence','A03.z','A03.percentile','A03.change5','B02.center','B02.gap','C01','A08')]
        entities=[dict(title='IF',left='IF2612.CFE',right='000300.SH',metrics=metrics)]
        basis=group_metrics(entities,'basis','basis');ids={g['id'] for g in basis}
        self.assertFalse(ids&{'A01','A02.annual','C01','A08'})
        self.assertIn('A03.percentile',ids)
        self.assertIn('A02.convergence',ids);self.assertIn('A03.z',ids)
        self.assertEqual(len(next(g for g in basis if g['id']=='B02')['entities'][0]['metrics']),2)
        self.assertIn('A03.percentile',{g['id'] for g in group_metrics(entities,'cross','basis')})

    def test_stale_quote_cannot_become_current_basis_or_relabel_history(self):
        cal=self.calendar
        daily={'IF2612.CFE':pd.DataFrame({'close':np.arange(3900.,3953.),'volume':100.,'open_interest':500.},index=cal),
               '000300.SH':pd.DataFrame({'close':4000.},index=cal)}
        metadata={'IF2612.CFE':{'expiry_date':'2026-12-18','listing_date':'2026-04-17'}}
        book=DividendBook(reason='',version='test',info={'mapping':{'IF2612.CFE':{'points':10.,'expiry':'2026-12-18'}}})
        now=cal[-1]+pd.Timedelta(days=1)
        q={'close':3960.,'volume_total':1000.,'observed_at':cal[-1],'source_event_time':cal[-1]}
        row=overview_card('IF2612.CFE',daily,cal,metadata,book,{'IF2612.CFE':q,'000300.SH':{**q,'close':4000.}},now,'basis')
        self.assertIsNone(row['current']['bp']);self.assertFalse(row['quality']['usable'])
        self.assertEqual(row['chart']['kind'],'历史');self.assertEqual(row['chart']['time'],cal[-1].isoformat())
        self.assertAlmostEqual(row['chart']['value'],10000*(3952-4000+10)/4000)
        old=overview_card('IF2609.CFE',daily,cal,metadata,book,{},now,'basis')
        self.assertIsNone(old['chart']['value']);self.assertIsNone(old['dividend'])

    def test_reference_revision_invalidates_cached_contract_calculations(self):
        from dashboard.native.nonregression import metric
        engine=SimpleNamespace(history_key=('dataset-v1',),card_metric_cache={},model=SimpleNamespace(live_rows=pd.DataFrame()))
        now=pd.Timestamp('2026-10-16T10:00:00+08:00')
        calendar=pd.DatetimeIndex([pd.Timestamp('2026-10-14T15:00:00+08:00')])
        metadata={'IF2612.CFE':dict(listing_date='2026-04-17',expiry_date='2026-12-18',known_at='v1')}
        selection=dict(pairs=[('IF','IF2612.CFE','000300.SH')],overview_symbols=[])
        book=DividendBook(reason='',version='scenario-v1')
        def calculate(*args,**kwargs):
            days=(pd.Timestamp(args[6]['IF2612.CFE']['expiry_date'])-pd.Timestamp('2026-10-14')).days
            return [metric('A02.convergence','test',pd.Series([days],index=calendar),'bp/日','test','test')]
        def snapshot():return dashboard_cards(engine,dict(category='basis',price_input='basis'),{},selection,{},calendar,metadata,book,{},now,lambda _:pd.DataFrame())
        with patch('dashboard.native.nonregression.calculate',side_effect=calculate) as calc:
            self.assertEqual(snapshot()['entities'][0]['metrics'][0]['value'],65)
            snapshot();self.assertEqual(calc.call_count,1)
            metadata['IF2612.CFE']['expiry_date']='2026-12-25'
            self.assertEqual(snapshot()['entities'][0]['metrics'][0]['value'],72)
            self.assertEqual(calc.call_count,2)

    def test_explicit_zero_participation_does_not_reuse_invalid_boolean_cache(self):
        from dashboard.native.nonregression import metric
        engine=SimpleNamespace(history_key=('v1',),card_metric_cache={},model=SimpleNamespace(live_rows=pd.DataFrame()))
        now=pd.Timestamp('2026-10-16T10:00:00+08:00');calendar=pd.DatetimeIndex([now-pd.Timedelta(days=1)])
        metadata={'IF2612.CFE':dict(listing_date='2026-04-17',expiry_date='2026-12-18')}
        selection=dict(pairs=[('IF','IF2612.CFE','000300.SH')],overview_symbols=[])
        def calculation(*args,**kwargs):
            value=0. if kwargs['participation'] is not False else float('nan')
            return [metric('B12.A_p','explicit p',pd.Series([value],index=calendar),'手','p capacity','explicit')]
        def snapshot(p):
            result=dashboard_cards(engine,dict(category='basis',price_input='basis'),{'participation':p},selection,{},calendar,metadata,DividendBook(),{},now,lambda _:pd.DataFrame())
            return result['entities'][0]['metrics'][0]['value']
        with patch('dashboard.native.nonregression.calculate',side_effect=calculation) as calculation_mock:
            self.assertIsNone(snapshot(False));self.assertEqual(snapshot(0),0.)
            self.assertIsNone(snapshot(False));self.assertEqual(calculation_mock.call_count,2)


if __name__=='__main__':unittest.main()
