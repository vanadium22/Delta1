"""Historical reference pools cannot fabricate an intraday observation."""
import unittest

import pandas as pd

from dashboard.indicator_catalog import find_variant
from dashboard.indicator_selection import entity
from dashboard.indicator_workspace import result_contract
from dashboard.native.intraday import consecutive_days
from dashboard.native.nonregression import calculate
from tests.test_intraday_workspace import fixture


class IntradayReferenceGuardTests(unittest.TestCase):
    def source(self):
        values=fixture();values['price_input']='future'
        self.assertTrue(consecutive_days(list(values['calendar'][-20:].tz_convert('Asia/Shanghai').date),values['as_of'],20))
        return values

    def contract(self,row,values):
        return result_contract(row,find_variant(family_id=row['id'],input_id='future',category='basis'),
            entity('basis',values['left'],metadata=values['metadata']),{},
            {'daily':values['data']},{'timing':'盘中优先'},values['as_of'])

    def test_complete_prior_history_without_quotes_retains_daily_reference_only(self):
        values=self.source();values['live']={}
        rows={row['id']:row for row in calculate(**values)}
        for code in ('A03.mean','A03.std'):
            self.assertIsNotNone(rows[code]['value'])
            self.assertIsNone(rows[code]['current'])
            self.assertIsNone(rows[code]['current_time'])
            self.assertIsNone(rows[code]['current_n'])
            self.assertEqual(self.contract(rows[code],values)['data_status'],'daily_reference')

    def test_complete_prior_history_with_stale_quotes_cannot_be_intraday(self):
        values=self.source()
        for quote in values['live'].values():
            quote['source_event_time']=values['as_of']-pd.Timedelta(seconds=40)
        rows={row['id']:row for row in calculate(**values)}
        for code in ('A03.mean','A03.std'):
            self.assertIsNotNone(rows[code]['value'])
            self.assertIsNone(rows[code]['current'])
            self.assertIsNone(rows[code]['current_time'])
            self.assertIsNone(rows[code]['current_n'])
            self.assertEqual(self.contract(rows[code],values)['data_status'],'daily_reference')

    def test_current_references_require_fresh_source_and_publish_its_time_and_n(self):
        values=self.source();rows={row['id']:row for row in calculate(**values)}
        sample=values['data'][values['left']].close.tail(20)
        for code,expected in (('A03.mean',sample.mean()),('A03.std',sample.std(ddof=1))):
            self.assertAlmostEqual(rows[code]['current'],expected)
            self.assertEqual(pd.Timestamp(rows[code]['current_time']),pd.Timestamp(values['live'][values['left']]['source_event_time']))
            self.assertEqual(rows[code]['current_n'],20)
            self.assertEqual(rows[code]['current_reference_end'],sample.index[-1].isoformat())
            self.assertEqual(self.contract(rows[code],values)['data_status'],'intraday_estimate')

    def test_fresh_quote_without_previous_session_does_not_publish_references(self):
        values=self.source();values['calendar']=values['calendar'][:-1]
        values['data']={symbol:frame.reindex(values['calendar']) for symbol,frame in values['data'].items()}
        rows={row['id']:row for row in calculate(**values)}
        for code in ('A03.mean','A03.std'):
            self.assertIsNone(rows[code]['current'])
            self.assertIsNone(rows[code]['current_time'])


if __name__=='__main__':unittest.main()
