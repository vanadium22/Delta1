"""Dated exchange listings, automatic rollover, failure isolation and audit history."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from dashboard.marketdata.contract_reference import parse_parameters, synchronize, latest_contracts
from dashboard.marketdata.repository import ReferenceBook
from dashboard.marketdata.dividends import make_contract_scenario, DividendBook
from dashboard.native.collection import RollingResolver, CollectionJob
from dashboard.native.continuous import slot_map
from index_strategy.instant_dld.service import write_json


ROOTS=('IF','IH','IC','IM')
DATES={'2610':('2026-08-24','2026-10-16'), '2611':('2026-09-21','2026-11-20'),
       '2612':('2026-04-20','2026-12-18'), '2703':('2026-07-20','2027-03-19'),
       '2706':('2026-10-19','2027-06-18'), '2701':('2026-11-23','2027-01-15')}


def xml(day='2026-10-19',months=('2611','2612','2703','2706'),omit=()):
    rows=[]
    for root in ROOTS:
        for month in months:
            code=root+month
            if code in omit:continue
            listing,expiry=DATES[month]
            fields=dict(INSTRUMENT_ID=code,PRODUCT_ID=root,OPEN_DATE=listing.replace('-',''),
                        END_TRADING_DAY=expiry.replace('-',''),TRADING_DAY=day.replace('-',''))
            rows.append('<INDEX>'+''.join(f'<{k}>{v}</{k}>' for k,v in fields.items())+'</INDEX>')
    return ('<tradeproperty>'+''.join(rows)+'</tradeproperty>').encode()


class RolloverTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.base=self.root/'original.json';self.cache=self.root/'cache'
        rows=[]
        for root in ROOTS:
            for month in ('2610','2611','2612','2703'):
                listing,expiry=DATES[month]
                rows.append(dict(instrument_id=root+month+'.CFE',listing_date=listing,expiry_date=expiry,known_at='2026-10-15T00:00Z'))
        write_json(self.base,dict(schema_version='cn_index_reference_v1',contracts=rows,aliases=[]))
        self.original=self.base.read_bytes()
        self.fetch=Mock(return_value=(xml(),date(2026,10,19),'http://exchange.test/parameters.xml'))
        self.now=pd.Timestamp('2026-10-19T10:00+08:00')

    def sync(self,**kwargs):
        return synchronize(self.base,self.cache,now=kwargs.pop('now',self.now),fetcher=self.fetch,quote_checker=kwargs.pop('quote_checker',None),**kwargs)

    def test_new_contracts_are_discovered_and_original_history_is_preserved(self):
        state=self.sync()
        self.assertTrue(state['complete']);self.assertEqual(len(state['active_contracts']),16)
        self.assertEqual(set(state['changed']),{p+'2706.CFE' for p in ROOTS})
        self.assertEqual(self.original,self.base.read_bytes())
        book=ReferenceBook(state['reference_file']);meta=latest_contracts(book.data)
        self.assertEqual(len(meta),20)
        self.assertEqual(slot_map(meta,'IF','2026-10-16')[0]['IF00.CFE'],'IF2610.CFE')
        self.assertEqual(slot_map(meta,'IF',self.now)[0],dict(zip(
            [f'IF0{i}.CFE' for i in range(4)],['IF2611.CFE','IF2612.CFE','IF2703.CFE','IF2706.CFE'])))
        self.assertIsNone(book.contract('IF2706.CFE','2026-10-19T01:00Z'))
        self.assertTrue(Path(state['raw_path']).is_file())
        self.assertTrue(list((self.cache/'versions').glob('*.json')))

    def test_success_is_daily_cached_and_next_date_requeries(self):
        self.sync();before=(self.cache/'current.json').read_bytes()
        self.sync(now=self.now+pd.Timedelta(hours=1));self.assertEqual(self.fetch.call_count,1)
        self.fetch.return_value=(xml('2026-10-20'),date(2026,10,20),'http://exchange.test/next.xml')
        self.sync(now=self.now+pd.Timedelta(days=1));self.assertEqual(self.fetch.call_count,2)
        self.assertEqual(before,(self.cache/'current.json').read_bytes())

    def test_timeout_retries_after_backoff_without_expired_contracts(self):
        self.fetch.side_effect=requests.Timeout('offline')
        state=self.sync()
        self.assertFalse(state['complete']);self.assertEqual(len(state['active_contracts']),12)
        self.assertNotIn('IF2610.CFE',state['active_contracts'])
        self.sync(now=self.now+pd.Timedelta(seconds=30));self.assertEqual(self.fetch.call_count,1)
        self.fetch.side_effect=None
        state=self.sync(now=self.now+pd.Timedelta(minutes=5));self.assertTrue(state['complete'])

    def test_invalid_xml_keeps_last_valid_reference(self):
        self.sync();before=(self.cache/'current.json').read_bytes()
        self.fetch.return_value=(b'<html>bad gateway</html>',date(2026,10,19),'http://exchange.test')
        state=self.sync(force=True)
        self.assertIn('error',state);self.assertEqual(before,(self.cache/'current.json').read_bytes())

    def test_incomplete_product_does_not_block_other_products(self):
        self.fetch.return_value=(xml(omit=('IH2706',)),date(2026,10,19),'http://exchange.test')
        state=self.sync()
        self.assertEqual(state['incomplete_products'],['IH'])
        self.assertIn('IF2706.CFE',state['active_contracts'])
        resolver=RollingResolver(['000300.SH'],self.base,self.cache,now=lambda:self.now,
                                 synchronizer=lambda *a,**kw:state)
        resolved,errors=resolver.resolve_many(['IF03.CFE','IH03.CFE','000300.SH'])
        self.assertEqual(resolved['IF03.CFE']['source_symbol'],'IF2706.CFE')
        self.assertIn('000300.SH',resolved);self.assertIn('IH03.CFE',errors)

    def test_wrong_trade_day_or_expiry_month_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_parameters(xml(),date(2026,10,20),self.now.isoformat(),'url')
        broken=xml().replace(b'<END_TRADING_DAY>20270618',b'<END_TRADING_DAY>20270319')
        with self.assertRaises(ValueError):
            parse_parameters(broken,date(2026,10,19),self.now.isoformat(),'url')

    def test_resolver_rolls_without_restarting_and_never_subscribes_expired(self):
        before=pd.Timestamp('2026-10-16T14:59+08:00')
        self.fetch.return_value=(xml('2026-10-16',('2610','2611','2612','2703')),date(2026,10,16),'url')
        clock=[before]
        resolver=RollingResolver(['000300.SH'],self.base,self.cache,now=lambda:clock[0],
            synchronizer=lambda ref,directory,**kw:synchronize(ref,directory,fetcher=self.fetch,quote_checker=None,**kw))
        first,_=resolver.resolve_many(['IF00.CFE','IF03.CFE'])
        self.assertEqual(first['IF00.CFE']['source_symbol'],'IF2610.CFE')
        clock[0]=self.now;self.fetch.return_value=(xml(),date(2026,10,19),'url')
        second,errors=resolver.resolve_many(['IF00.CFE','IF03.CFE','IF2610.CFE'])
        self.assertEqual(second['IF00.CFE']['source_symbol'],'IF2611.CFE')
        self.assertEqual(second['IF03.CFE']['source_symbol'],'IF2706.CFE')
        self.assertIn('IF2610.CFE',errors)
        self.assertIsNone(second['IF03.CFE']['trading_date'])

    def test_next_month_also_discovers_nonquarter_month(self):
        self.sync()
        self.fetch.return_value=(xml('2026-11-23',('2612','2701','2703','2706')),date(2026,11,23),'url')
        state=self.sync(now=pd.Timestamp('2026-11-23T10:00+08:00'))
        meta=latest_contracts(ReferenceBook(state['reference_file']).data)
        self.assertEqual(slot_map(meta,'IF','2026-11-23')[0]['IF01.CFE'],'IF2701.CFE')
        self.assertNotIn('IF2611.CFE',state['active_contracts'])

    def test_manual_retry_bypasses_failed_backoff(self):
        self.fetch.side_effect=requests.Timeout('offline');self.sync()
        self.fetch.side_effect=None
        self.assertTrue(self.sync(force=True)['complete']);self.assertEqual(self.fetch.call_count,2)

    def test_old_official_file_never_certifies_today(self):
        self.fetch.return_value=(xml('2026-10-16',('2610','2611','2612','2703')),date(2026,10,16),'url')
        state=self.sync()
        self.assertFalse(state['complete']);self.assertEqual(len(state['active_contracts']),12)

    def test_quote_outage_does_not_discard_official_listing_and_is_retried(self):
        checker=Mock(side_effect=lambda symbols:dict(status='timeout',verified=[],missing=symbols))
        state=self.sync(quote_checker=checker)
        self.assertEqual(len(state['active_contracts']),16)
        self.assertIn('IF2706.CFE',state['quote_verification']['missing'])
        self.sync(now=self.now+pd.Timedelta(seconds=30),quote_checker=checker)
        self.assertEqual(checker.call_count,1)
        self.sync(now=self.now+pd.Timedelta(minutes=5),quote_checker=checker)
        self.assertEqual(checker.call_count,2)

    def test_quote_identity_mismatch_is_not_verified(self):
        from dashboard.marketdata.contract_reference import check_quotes
        client=Mock()
        client.fetch.return_value=dict(status='success',response={'data':{
            'IF2706.CFE':dict(securityId='IF2703.CFE',latestPrice=4000.),
            'IH2706.CFE':dict(securityId='IH2706.CFE',latestPrice=2500.),
            'IC2706.CFE':dict(securityId='IC2706.CFE',latestPrice=0.)}})
        with patch('index_strategy.instant_dld.client.MarketDataClient',return_value=client):
            result=check_quotes(['IF2706.CFE','IH2706.CFE','IC2706.CFE'])
        self.assertEqual(result['verified'],['IH2706.CFE']);client.close.assert_called_once()



class DividendRolloverTests(unittest.TestCase):
    def setUp(self):
        self.metadata={p+m+'.CFE':dict(listing_date=listing,expiry_date=expiry)
            for p in ROOTS for m,(listing,expiry) in DATES.items()}
        self.snapshot=dict(date='2026-09-18',content_hash='source1',rows=[
            dict(alias=p+'03.CFE',source_contract=p+'2703.CFE',points=float(i+10))
            for i,p in enumerate(ROOTS)])
        self.day=pd.Timestamp('2026-10-19T10:00+08:00')

    def scenario(self):return make_contract_scenario(self.snapshot,self.metadata,self.day)

    def test_2706_inherits_2703_per_product_without_changing_source(self):
        result=self.scenario()
        for p in ROOTS:
            new=result['mapping'][p+'2706.CFE'];old=result['mapping'][p+'2703.CFE']
            self.assertEqual(new['points'],old['points'])
            self.assertEqual(new['inherited_from'],p+'2703.CFE')
            self.assertEqual(new['expiry'],'2027-06-18')
        self.assertEqual(len(self.snapshot['rows']),4)

    def test_real_new_contract_value_including_zero_replaces_estimate(self):
        previous=self.scenario()
        self.snapshot['rows'].append(dict(alias='IF03.CFE',source_contract='IF2706.CFE',points=0.))
        new=self.scenario()
        self.assertEqual(new['mapping']['IF2706.CFE']['points'],0.)
        self.assertNotIn('inherited_from',new['mapping']['IF2706.CFE'])
        self.assertNotEqual(new['version'],previous['version'])

    def test_contract_identity_wins_over_outdated_slot_label(self):
        self.snapshot['rows'][0]['alias']='IF00.CFE'
        result=self.scenario()
        self.assertEqual(result['mapping']['IF2703.CFE']['points'],10.)
        self.assertNotIn('IF2611.CFE',result['mapping'])

    def test_never_backfills_from_later_maturity_or_other_product(self):
        self.snapshot['rows']=[self.snapshot['rows'][0]]
        result=self.scenario()
        self.assertNotIn('IF2612.CFE',result['mapping'])
        self.assertNotIn('IH2706.CFE',result['mapping'])

    def test_predecessor_can_be_expired_but_estimate_keeps_target_expiry(self):
        self.snapshot['rows'].append(dict(alias='IF01.CFE',source_contract='IF2610.CFE',points=2.5))
        result=self.scenario()
        self.assertEqual(result['mapping']['IF2611.CFE']['points'],2.5)
        self.assertEqual(result['mapping']['IF2611.CFE']['inherited_from'],'IF2610.CFE')
        book=DividendBook(reason='',info=result)
        self.assertEqual(book.points('IF2611.CFE',self.day),2.5)
        self.assertIsNone(book.points('IF2610.CFE',self.day))

    def test_conflicting_concrete_values_are_rejected(self):
        self.snapshot['rows'].append(dict(alias='IF02.CFE',source_contract='IF2703.CFE',points=99.))
        with self.assertRaisesRegex(ValueError,'冲突'):self.scenario()

    def test_new_contract_without_history_stays_missing_without_numeric_warnings(self):
        import warnings
        from dashboard.native.nonregression import single,FIELDS
        calendar=pd.date_range('2026-10-12',periods=3,tz='UTC')
        empty=pd.DataFrame(columns=FIELDS,index=calendar)
        with warnings.catch_warnings():
            warnings.simplefilter('error',RuntimeWarning)
            result=single(empty,empty,'IF2706.CFE','2027-06-18',DividendBook(reason='',info=self.scenario()),calendar)
        self.assertTrue(result['close'].isna().all())
        self.assertTrue(result['trbp'].isna().all())


if __name__=='__main__':unittest.main()
