"""Regression for the 13:23 company feedback, using offline fixtures only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import pandas as pd

from dashboard.marketdata.overview_market_sizes import build,etf_assets,futures_notionals
from dashboard.marketdata.overview_display_cache import preserve
from dashboard.marketdata.overview_reference import publish
from dashboard.native.equity_collection import EquitySampler
from tests.test_market_overview import NOW,observation,ZERO_DIVIDENDS
from tests.test_overview_details import reference,equity_snapshot
from tests.test_realtime_store import quote


def contracts(root='IF'):
    return [dict(symbol=root+month+'.CFE',root=root,slot=i) for i,month in enumerate(('2611','2612','2703','2706'))]


def daily_history(rows,day='2026-10-23',missing=()):
    return {r['symbol']:pd.DataFrame([dict(trade_date=day,is_final=True,close=4000-10*r['slot'],
        open_interest=None if r['slot'] in missing else (r['slot']+1)*100)]) for r in rows}


class MarketSizeTests(unittest.TestCase):
    def test_whole_same_date_etf_universe_is_top_three_plus_other_and_sums_exactly(self):
        result=etf_assets(reference(),'IF','2026-10-26')
        self.assertEqual(result['total_cny'],1000e8);self.assertEqual(len(result['rows']),4)
        self.assertEqual(result['rows'][-1]['amount_cny'],100e8)
        self.assertAlmostEqual(sum(r['share_pct'] for r in result['rows']),100)
        self.assertEqual(sum(r['amount_cny'] for r in result['rows']),result['total_cny'])
        bad=reference();bad['etfs']['IF']['complete']=False
        self.assertIsNone(etf_assets(bad,'IF','2026-10-26')['total_cny'])

    def test_nominal_uses_oi_price_and_product_multiplier_not_volume_or_margin(self):
        for root,multiplier in (('IF',300),('IH',300),('IC',200),('IM',200)):
            rows=contracts(root);history=daily_history(rows)
            result=futures_notionals(root,rows,history,{},NOW,{},'2026-10-23','2026-10-23')
            expected=sum((i+1)*100*(4000-10*i)*multiplier for i in range(4))
            self.assertEqual(result['total_cny'],expected);self.assertEqual(result['status'],'complete')
            self.assertEqual(result['rows'][0]['amount_cny'],100*4000*multiplier)
            self.assertTrue(all(r['price_at']==r['oi_at'] for r in result['rows']))

    def test_live_oi_is_synchronized_and_falls_back_to_coherent_completed_day(self):
        rows=contracts();history=daily_history(rows)
        live={r['symbol']:dict(observation(4050,4000),open_interest=1000,volume_total=999999) for r in rows}
        current=futures_notionals('IF',rows,history,live,NOW,{},'2026-10-23','2026-10-23')
        self.assertEqual(current['basis'],'current_http');self.assertEqual(current['total_cny'],4*4050*1000*300)
        live[rows[-1]['symbol']]['source_event_time']=(NOW-pd.Timedelta(seconds=4)).isoformat()
        saved=futures_notionals('IF',rows,history,live,NOW,{},'2026-10-23','2026-10-23')
        self.assertEqual(saved['basis'],'completed_daily');self.assertEqual(saved['as_of'],'2026-10-23')

    def test_missing_oi_has_known_partial_total_without_fabricating_a_complete_pie(self):
        rows=contracts();history=daily_history(rows,missing=(3,))
        result=futures_notionals('IF',rows,history,{},NOW,{},'2026-10-23','2026-10-23')
        self.assertIsNone(result['total_cny']);self.assertEqual(result['covered'],3);self.assertEqual(result['status'],'partial')
        self.assertAlmostEqual(sum(r['share_pct'] for r in result['rows']),100)
        groups=build(reference(),rows,history,{},NOW,{},'2026-10-23')
        self.assertIsNone(groups['IF']['futures_to_etf']);self.assertTrue(groups['IF']['same_day'])

    def test_real_zero_daily_oi_is_zero_but_http_zero_remains_unverified(self):
        rows=contracts();history=daily_history(rows)
        for frame in history.values():frame['open_interest']=0
        live={r['symbol']:dict(observation(),open_interest=None,open_interest_raw=0) for r in rows}
        result=futures_notionals('IF',rows,history,live,NOW,{},'2026-10-23','2026-10-23')
        self.assertEqual(result['total_cny'],0);self.assertEqual(result['status'],'complete')
        self.assertEqual(result['basis'],'completed_daily');self.assertTrue(all(r['share_pct']==0 for r in result['rows']))

    def test_duplicate_slots_and_invalid_multiplier_never_create_false_totals(self):
        rows=contracts();bad=deepcopy(rows);bad[-1]['slot']=2
        self.assertIsNone(futures_notionals('IF',bad,daily_history(rows),{},NOW,{},'2026-10-23','2026-10-23')['total_cny'])
        result=futures_notionals('IF',rows,daily_history(rows),{},NOW,{rows[0]['symbol']:dict(multiplier=0)},'2026-10-23','2026-10-23')
        self.assertEqual(result['covered'],3);self.assertIsNone(result['total_cny'])


class SamplingTests(unittest.TestCase):
    def test_default_larger_batches_prioritize_failed_codes_and_keep_five_minute_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=reference();value['indices']['IF']['rows']=[dict(symbol=f'{600000+i:06}.SH',weight_pct=100/650) for i in range(650)]
            failed='600649.SH';path=Path(tmp)/'overview_equities/latest.json';path.parent.mkdir()
            path.write_text(json.dumps(dict(schema='overview-equities-v1',snapshot_id='old',quotes={failed:observation()},failed_symbols=[failed])),encoding='utf8')
            waits=[];asks=[];sampler=EquitySampler(tmp,{},lambda:dict(allowed=True),Mock(),pause=lambda seconds:waits.append(seconds) or False)
            class Client:
                def fetch(self,symbols):
                    asks.append(symbols)
                    return dict(status='success',received_at=NOW.isoformat(),response=dict(data={s:{**quote(10,100,100005),'securityId':s} for s in symbols}))
            from dashboard.marketdata.equity_observations import EquityObservationStore
            with EquityObservationStore(Path(tmp)/'observations',archive_enabled=False) as store:result=sampler.cycle(Client(),store,dict(data=value,version='fixture'),1)
            self.assertEqual([len(r) for r in asks],[300,300,51]);self.assertIn(failed,asks[0])
            self.assertEqual(result['round_target_seconds'],300);self.assertEqual(waits,[15.,15.]);self.assertEqual(result['pending_count'],0)

    def test_truncated_large_response_retries_missing_next_round_with_smaller_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=reference();value['indices']['IF']['rows']=[dict(symbol=f'{600000+i:06}.SH',weight_pct=100/350) for i in range(350)]
            asks=[];sampler=EquitySampler(tmp,{},lambda:dict(allowed=True),Mock(),pause=lambda _:False)
            class Client:
                def fetch(self,symbols):
                    asks.append(list(symbols));received=symbols[:100]
                    return dict(status='success',received_at=NOW.isoformat(),response=dict(data={s:{**quote(10,100,100005),'securityId':s} for s in received}))
            from dashboard.marketdata.equity_observations import EquityObservationStore
            with EquityObservationStore(Path(tmp)/'observations',archive_enabled=False) as store:
                first=sampler.cycle(Client(),store,dict(data=value,version='fixture'),1);split=len(asks)
                second=sampler.cycle(Client(),store,dict(data=value,version='fixture'),2)
            self.assertEqual(first['next_batch_size'],100);self.assertGreater(first['pending_count'],0)
            self.assertLessEqual(max(len(r) for r in asks[split:]),100);self.assertEqual(second['pending_count'],0)
            missing=set(first['failed_symbols']);self.assertTrue(set(asks[split][1:]) & missing)

    def test_equity_generation_is_frozen_before_later_publication_during_calculation(self):
        from dashboard.native.market_overview import MarketOverviewEngine
        from tests.test_overview_percentiles import metadata
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);publish(root/'overview_reference/latest.json',reference())
            path=root/'overview_equities/latest.json';path.parent.mkdir();path.write_text(json.dumps(equity_snapshot()),encoding='utf8')
            repo=SimpleNamespace(freeze=lambda:{},symbols=lambda _:{},read_window=lambda *a,**k:pd.DataFrame())
            model=SimpleNamespace(local_root=root,config={},live_rows=pd.DataFrame(),configure_repository=lambda _:repo)
            def live(instruments,now):
                late=equity_snapshot();late.update(snapshot_id='later',finished_at=(NOW+pd.Timedelta(seconds=1)).isoformat());path.write_text(json.dumps(late),encoding='utf8')
                return {s:observation(104,100) for s in instruments}
            model._live=live
            book=SimpleNamespace(data=dict(contracts=[dict(instrument_id=s,**r,known_at='2026-01-01T00:00:00+08:00') for s,r in metadata().items()]),version='fixture')
            with patch('dashboard.native.market_overview.ReferenceBook',return_value=book),patch('dashboard.native.market_overview.load_dividends',return_value=ZERO_DIVIDENDS):
                result=MarketOverviewEngine(model).snapshot(now=NOW)
            self.assertEqual(result['market_overview']['index_details']['IF']['covered'],3)
            self.assertTrue(result['market_overview']['index_details']['IF']['inputs']['snapshot_valid'])
            self.assertEqual(json.loads(path.read_text())['snapshot_id'],'later')


class RequiredPositionTests(unittest.TestCase):
    def test_existing_price_with_missing_oi_still_requests_completed_future_position(self):
        from dashboard.marketdata.overview_daily import requests,publish_day
        from tests.test_overview_data import close_row
        symbol='IF2611.CFE';meta={symbol:dict(listing_date='2026-09-01',expiry_date='2026-11-20')}
        with tempfile.TemporaryDirectory() as tmp:
            publish_day({},tmp,'2026-10-23',{symbol:close_row(symbol,'2026-10-23',oi=None)})
            jobs=requests({},tmp,'2026-10-23',meta,reference_data={})
            needed=[j for j in jobs if j['asset']=='future' and j['day']=='2026-10-23']
            self.assertEqual(needed[0]['symbols'],[symbol]);self.assertTrue(needed[0]['requires_oi'])
            publish_day({},tmp,'2026-10-23',{symbol:close_row(symbol,'2026-10-23',oi=0)})
            jobs=requests({},tmp,'2026-10-23',meta,reference_data={})
            self.assertFalse(any(j['asset']=='future' and j['day']=='2026-10-23' for j in jobs))

    def test_local_price_only_is_not_misclassified_as_an_available_position(self):
        from dashboard.marketdata.overview_daily import local_copy_plan
        job=dict(day='2026-10-23',asset='future',symbols=['IF2611.CFE'],requires_oi=True)
        price=pd.DataFrame([dict(trade_date='2026-10-23',is_final=True,close=4000.)])
        first=local_copy_plan([job],{'IF2611.CFE':price});self.assertEqual(first['local_copy_rows'],0)
        price['open_interest']=100
        second=local_copy_plan([job],{'IF2611.CFE':price});self.assertEqual(second['local_copy_rows'],1)

    def test_side_cache_with_valid_oi_replaces_incomplete_standard_row_as_one_coherent_row(self):
        from dashboard.marketdata.overview_daily import merge_daily
        frame=pd.DataFrame([dict(trade_date='2026-10-23',is_final=True,close=4000,open_interest=None,source='old')])
        updated=merge_daily(frame,[dict(trade_date='2026-10-23',is_final=True,close=4001,open_interest=10,source='complete')])
        self.assertEqual(updated.iloc[0]['close'],4001);self.assertEqual(updated.iloc[0]['open_interest'],10)
        self.assertEqual(updated.iloc[0]['source'],'complete')

    def test_seed_does_not_republish_price_only_as_position_progress(self):
        from dashboard.marketdata.overview_daily import seed_local,publish_day
        from tests.test_overview_data import close_row
        job=dict(day='2026-10-23',asset='future',symbols=['IF2611.CFE'],requires_oi=True)
        repo=SimpleNamespace(read_window=lambda *a,**k:pd.DataFrame([dict(trade_date='2026-10-23',is_final=True,close=4000.)]))
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.marketdata.overview_daily.requests',return_value=[job]):
            publish_day({},tmp,'2026-10-23',{'IF2611.CFE':close_row('IF2611.CFE','2026-10-23',oi=None)})
            before={p:p.read_bytes() for p in Path(tmp).rglob('*.json')}
            self.assertEqual(seed_local(repo,{}, {},tmp,'2026-10-23',{}),0)
            self.assertTrue(all(p.read_bytes()==content for p,content in before.items()))


class RetainedBasisTests(unittest.TestCase):
    def data(self):
        from tests.test_market_overview_ui import state
        row=deepcopy(state()['market_overview']['futures'][0]);row['basis_change_previous']=1.5
        return dict(indices=[],etfs=[],futures=[row],index_details={},etf_groups={})

    def test_missing_new_pair_keeps_priced_bundle_and_percentiles_but_not_as_live_computation(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True)
            first=self.data();preserve(model,first,NOW);prior=first['futures'][0]
            second=self.data();row=second['futures'][0]
            row.update(price=4001.,basis_points=None,annual_pct=None,dividend_points=None,percentile_20=None,percentile_60=None,basis_reason='两腿时间差超限')
            for w in row['continuous_percentiles']['windows'].values():w['percentile']=None
            preserve(model,second,NOW+pd.Timedelta(seconds=1));display=row['basis_display']
            self.assertIsNone(row['annual_pct']);self.assertIsNone(row['dividend_points']);self.assertEqual(row['price'],4001.)
            self.assertEqual(display['annual_pct'],prior['annual_pct']);self.assertEqual(display['basis_change_previous'],1.5)
            self.assertEqual(display['basis_source_at'],prior['basis_source_at']);self.assertTrue(display['saved'])
            from dashboard.native.futures_overview_view import FuturesCard
            from tests.test_market_overview_ui import APP
            card=FuturesCard(None)
            try:
                card.render(row,0);self.assertEqual(card.price.text(),'4,001.00');self.assertNotEqual(card.annual_value.text(),'—')
                self.assertIn('基差沿用',card.dividend_note.text());self.assertNotIn('缺',card.rank_value.text())
            finally:card.close();card.deleteLater();APP.processEvents()

    def test_kept_bundle_survives_restart_then_new_valid_result_replaces_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True);data=self.data();preserve(model,data,NOW)
            missing=self.data();missing['futures'][0].update(basis_points=None,annual_pct=None)
            reader=SimpleNamespace(local_root=Path(tmp),config={});preserve(reader,missing,NOW+pd.Timedelta(seconds=2))
            self.assertTrue(missing['futures'][0]['basis_display']['saved'])
            current=self.data();current['futures'][0].update(basis_points=1.2,annual_pct=.5)
            preserve(model,current,NOW+pd.Timedelta(seconds=3));self.assertNotIn('basis_display',current['futures'][0])
            different=self.data();different['futures'][0].update(slot=1,basis_points=None,annual_pct=None)
            preserve(model,different,NOW+pd.Timedelta(seconds=4));self.assertNotIn('basis_display',different['futures'][0])

    def test_t_below_five_remains_excluded_when_new_result_is_calculable(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True);preserve(model,self.data(),NOW)
            current=self.data();row=current['futures'][0];row.update(days=4,annual_pct=None,percentile_20=None,percentile_60=None)
            for w in row['continuous_percentiles']['windows'].values():w['percentile']=None
            preserve(model,current,NOW+pd.Timedelta(seconds=1));self.assertNotIn('basis_display',row);self.assertIsNone(row['annual_pct'])

    def test_slot_change_with_missing_price_does_not_reuse_another_slots_percentiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True);preserve(model,self.data(),NOW)
            current=self.data();row=current['futures'][0]
            row.update(slot=1,price=None,basis_points=None,annual_pct=None,continuous_percentiles={})
            preserve(model,current,NOW+pd.Timedelta(seconds=1));row=current['futures'][0]
            self.assertEqual(row['slot'],1);self.assertIsNotNone(row['price']);self.assertNotIn('basis_display',row)
            self.assertEqual(row['continuous_percentiles'],{})

    def test_new_expiry_reference_cannot_reuse_an_annual_with_old_T(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True);preserve(model,self.data(),NOW)
            current=self.data();current['futures'][0].update(expiry='2026-11-19',basis_points=None,annual_pct=None)
            preserve(model,current,NOW+pd.Timedelta(seconds=1));self.assertNotIn('basis_display',current['futures'][0])


class ViewportTests(unittest.TestCase):
    def test_click_all_four_indices_through_transformed_viewport_and_summary(self):
        from tests.test_market_overview_ui import OverviewUiTests,pump
        from PySide6.QtCore import QPointF,Qt
        from PySide6.QtTest import QTest
        from dashboard.native.instruments import UNDERLYINGS
        case=OverviewUiTests();w=case.window()
        def click(page,card):
            local=card.mapTo(page.body,card.rect().center())
            pos=page.scroll.mapFromScene(page.scroll.proxy.mapToScene(QPointF(local)))
            self.assertTrue(page.scroll.viewport().rect().contains(pos))
            QTest.mouseClick(page.scroll.viewport(),Qt.MouseButton.LeftButton,pos=pos);pump(.04)
        try:
            for width,height in ((1920,1080),(1536,864)):
                w.resize(width,height);pump(.08);page=w.quotes.views['indices']
                for root,(symbol,_,_) in UNDERLYINGS.items():
                    w.pages.setCurrentWidget(page);pump(.04);click(page,page.cards[symbol]);self.assertEqual(page.selected_root,root)
                    w.pages.setCurrentIndex(0);pump(.04);click(w.quotes,w.quotes.index_cards[symbol]);self.assertEqual(w.pages.currentIndex(),1)
                    self.assertEqual(page.selected_root,root)
        finally:case.doCleanups()

    def test_summary_font_is_larger_at_medium_and_capacity_pies_fit_without_scroll(self):
        from tests.test_market_overview_ui import OverviewUiTests,pump
        case=OverviewUiTests();w=case.window()
        try:
            w.resize(1920,1080);pump(.1)
            area=w.quotes.scroll;card=w.quotes.products['IF'].futures[0]
            self.assertGreater(card.annual_value.font().pixelSize()*area.display_scale,18)
            self.assertEqual(area.verticalScrollBar().maximum(),0)
            page=w.quotes.views['etfs'];w.pages.setCurrentWidget(page);pump(.1)
            self.assertEqual(page.scroll.verticalScrollBar().maximum(),0)
            self.assertIn('规模对比',page.capacity.title.text())
        finally:case.doCleanups()


if __name__=='__main__':unittest.main()
