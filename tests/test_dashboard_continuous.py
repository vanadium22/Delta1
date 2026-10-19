"""Continuous-slot history must keep an auditable mapping and dividend version."""
import unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd

from dashboard.native.continuous import slot_map,slot_history
from dashboard.native.card_data import distributions,selections
from dashboard.marketdata.dividends import DividendBook
from dashboard.native.indicator_help import explain_metric


class ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.metadata={f'IF{m}.CFE':dict(listing_date=listing,expiry_date=expiry) for m,listing,expiry in (
            ('2609','2026-01-19','2026-09-18'),('2610','2026-08-24','2026-10-16'),
            ('2611','2026-09-21','2026-11-20'),('2612','2026-04-20','2026-12-18'),
            ('2703','2026-07-20','2027-03-19'))}
        self.calendar=pd.DatetimeIndex(['2026-09-18T07:00Z','2026-09-21T07:00Z'])
        self.daily={s:pd.DataFrame({'close':[3900.,4000.]},index=self.calendar) for s in self.metadata}
        self.daily['000300.SH']=pd.DataFrame({'close':[4000.,4000.]},index=self.calendar)
        self.book=DividendBook(reason='',version='one',info={'mapping':{'IF2610.CFE':dict(alias='IF00.CFE',points=20.,expiry='2026-10-16')}})
        self.now=pd.Timestamp('2026-10-16T10:00+08:00')

    def history(self,book=None,current='IF2610.CFE'):
        return slot_history('IF',0,self.daily,self.calendar,self.metadata,book or self.book,current,self.now)

    def test_expiry_day_and_next_listing_have_explicit_unique_mappings(self):
        self.assertEqual(slot_map(self.metadata,'IF','2026-09-18')[0]['IF00.CFE'],'IF2609.CFE')
        self.assertEqual(slot_map(self.metadata,'IF','2026-09-21')[0]['IF00.CFE'],'IF2610.CFE')
        self.assertEqual(slot_map(self.metadata,'IF','2026-09-20T18:00Z')[0]['IF00.CFE'],'IF2610.CFE')
        broken={s:r for s,r in self.metadata.items() if s!='IF2611.CFE'}
        self.assertFalse(slot_map(broken,'IF','2026-09-21')[0])
        duplicate={**self.metadata,'IF9999.CFE':self.metadata['IF2610.CFE']}
        self.assertFalse(slot_map(duplicate,'IF','2026-09-21')[0])

    def test_fixed_scenario_d_is_consistent_across_roll_and_versioned(self):
        frame,info=self.history()
        self.assertEqual(list(frame.symbol),['IF2609.CFE','IF2610.CFE'])
        self.assertEqual(list(frame.D),[20.,20.])
        self.assertEqual(list(frame.points),[-80.,20.])
        self.assertTrue(np.isnan(frame.annual.iloc[0]))
        self.assertAlmostEqual(frame.annual.iloc[1],50*365/(100*25))
        self.assertEqual(info['mappings'][0]['days'],0)
        self.assertEqual(info['mode'],'continuous_fixed_scenario')
        self.book.version='two';self.assertNotEqual(info['version'],self.history()[1]['version'])

    def test_new_contract_cannot_inherit_dividend_but_existing_contract_can_change_slot(self):
        frame,_=self.history(current='IF2611.CFE');self.assertTrue(frame.basis.isna().all())
        self.book.info['mapping']['IF2610.CFE']['alias']='IF01.CFE'
        frame,_=self.history();self.assertTrue((frame.D==20.).all())

    def test_daily_remaining_matches_each_contract_date_and_missing_is_not_zero(self):
        book=SimpleNamespace(mode='daily_remaining',version='daily1',info={},points=lambda s,d:3. if (s,str(d))==('IF2609.CFE','2026-09-18') else None)
        frame,info=self.history(book)
        self.assertEqual(frame.D.iloc[0],3.);self.assertTrue(np.isnan(frame.D.iloc[1]))
        self.assertTrue(np.isnan(frame.basis.iloc[1]));self.assertEqual(info['mode'],'continuous_daily_dividends')

    def test_missing_mapping_and_missing_price_are_explicit_gaps(self):
        self.daily['IF2609.CFE'].iloc[0,0]=np.nan
        frame,_=self.history();self.assertTrue(np.isnan(frame.basis.iloc[0]));self.assertIn('缺数',frame.reason.iloc[0])
        del self.metadata['IF2611.CFE']
        frame,info=self.history();self.assertTrue(pd.isna(frame.symbol.iloc[1]));self.assertIn('唯一',frame.reason.iloc[1])
        self.assertIsNone(info['mappings'][1]['symbol'])

    def test_annual_known_ineligible_days_are_filtered_but_unknown_mapping_is_not(self):
        cal=pd.date_range('2026-08-01 07:00',periods=22,freq='B',tz='UTC')
        s=pd.Series(np.arange(22,dtype=float),index=cal);eligibility=pd.Series(True,index=cal)
        s.iloc[-4]=np.nan;eligibility.iloc[-4]=False
        r=distributions(s,cal,cal[-1],21.,eligibility=eligibility)[0]
        self.assertTrue(r['complete']);self.assertEqual(r['n'],19);self.assertEqual(r['percentile'],100.)
        eligibility.iloc[-4]=True
        self.assertFalse(distributions(s,cal,cal[-1],21.,eligibility=eligibility)[0]['complete'])

    def test_slot_selection_preserves_concrete_contract_names(self):
        contracts=list(self.metadata)
        result=selections({'overview_slot':3},contracts,contracts,'IF2612.CFE',self.metadata,self.now)
        self.assertEqual(result['overview_symbols'][0],'IF2703.CFE');self.assertEqual(result['overview_slot'],3)
        self.assertEqual(result['overview_symbols'][1],'IH') # missing root references stay unavailable

    def test_structured_help_covers_all_visible_families(self):
        from dashboard.native.card_data import FAMILIES
        for family,title,code in FAMILIES:
            r=dict(id=code,title=title,unit='bp',scope='完整历史日线',formula='原公式',meaning='原解释')
            info=explain_metric(r)
            for key in ('formula','variables','window','reading','boundaries'):self.assertTrue(info[key],(code,key))
        info=explain_metric(dict(id='B10',title='',unit='',scope='',formula='',meaning=''),'basis','annual')
        self.assertIn('xₜ − xₜ₋₅',info['formula']);self.assertIn('过零',''.join(info['reading']))


if __name__=='__main__':unittest.main()
