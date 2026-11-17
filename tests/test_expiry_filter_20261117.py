"""The configurable expiry filter reaches history, charts, settings and caches."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from dashboard.marketdata.overview_basis import annual_min_days, calculate
from dashboard.marketdata.overview_daily import requests
from dashboard.marketdata.overview_display_cache import preserve, scope
from dashboard.marketdata.overview_dividends import DerivedCache
from dashboard.marketdata.overview_percentiles import prepare, evaluate, requirements, dated_slots
from dashboard.marketdata.indicator_analysis import selection, values
from dashboard.native.market_overview import MarketOverviewEngine, futures_values
from dashboard.native.model import NativeModel
from dashboard.native.term_curve import points
from dashboard.native.continuous import slot_map
from tests.test_market_overview import ZERO_DIVIDENDS, observation
from tests.test_overview_percentiles import metadata, daily_data, SPOTS
import tests.test_overview_ddb_refresh as settings_tests
import tests.test_indicator_analysis as indicator_tests


class ExpiryCalculationTests(unittest.TestCase):
    def test_default_includes_one_to_five_days_and_never_divides_by_zero(self):
        self.assertEqual(annual_min_days({}),1)
        for days in (-1,0,1,2,3,4,5):
            with self.subTest(days=days):
                result=calculate(3990,4000,0,days)
                self.assertEqual(result['points'],-10)
                if days>=1:self.assertAlmostEqual(result['annual_pct'],100*-10/4000*365/days)
                else:self.assertIsNone(result['annual_pct'])
                strict=calculate(3990,4000,0,days,min_annual_days=5)
                self.assertEqual(strict['annual_pct'] is not None,days>=5)

    def test_invalid_config_rejected_and_legacy_profiles_gain_default_without_rewrite(self):
        for bad in (0,-1,3651,True,1.5,'1',None):
            with self.subTest(value=bad),self.assertRaises(ValueError):
                annual_min_days({'overview_min_annual_days':bad})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'native.json';raw=b'{"history_roots":[],"product":"IC","frequency":"1m"}'
            path.write_bytes(raw);model=NativeModel(tmp)
            self.assertEqual(model.config['overview_min_annual_days'],1);self.assertEqual(path.read_bytes(),raw)
            candidate=dict(model.config,overview_min_annual_days=5);model.save_config(candidate)
            self.assertEqual(NativeModel(tmp).config['overview_min_annual_days'],5)
            with self.assertRaises(ValueError):model.save_config(dict(candidate,overview_min_annual_days=0))
            self.assertEqual(NativeModel(tmp).config['overview_min_annual_days'],5)

    def test_newly_eligible_history_enters_percentiles_and_real_gaps_still_block(self):
        meta=metadata();data=daily_data(meta);day='2026-10-27'
        loose=prepare('IF',0,meta,data,day,dividends=ZERO_DIVIDENDS)
        strict=prepare('IF',0,meta,data,day,dividends=ZERO_DIVIDENDS,min_annual_days=5)
        more=[r for r in loose['rows'] if r['days'] is not None and 1<=r['days']<5]
        self.assertTrue(more)
        for h in (loose,strict):self.assertEqual(evaluate(h,0,'IF2611.CFE')['windows']['20']['percentile'],50)
        self.assertGreater(evaluate(loose,0,'IF2611.CFE')['windows']['60']['samples'],
                           evaluate(strict,0,'IF2611.CFE')['windows']['60']['samples'])
        missing=more[-1];data[missing['symbol']]=data[missing['symbol']][data[missing['symbol']].trade_date.ne(missing['day'])]
        incomplete=evaluate(prepare('IF',0,meta,data,day,dividends=ZERO_DIVIDENDS),0,'IF2611.CFE')
        self.assertIsNone(incomplete['windows']['20']['percentile'])
        self.assertIn(missing['day'],[r['day'] for r in incomplete['windows']['20']['missing']])
        self.assertEqual(evaluate(prepare('IF',0,meta,data,day,dividends=ZERO_DIVIDENDS,min_annual_days=5),0,'IF2611.CFE')['windows']['20']['percentile'],50)

    def test_history_maintenance_requests_follow_the_same_filter(self):
        meta=metadata();day='2026-10-27'
        needed=lambda n:{(r['symbol'],r['day']) for r in requirements(meta,day,min_annual_days=n)['rows']}
        loose,strict=needed(1),needed(5);extra=loose-strict;self.assertTrue(extra)
        with tempfile.TemporaryDirectory() as tmp:
            def jobs(n):
                return {(s,j['day']) for j in requests({'overview_min_annual_days':n},tmp,day,meta,reference_data={}) for s in j['symbols']}
            self.assertTrue(extra<=jobs(1));self.assertFalse(extra&jobs(5))
        unknown=dated_slots({},'IF',0,[day],min_annual_days=1)[0]
        self.assertEqual(unknown['reason'],'mapping_missing');self.assertFalse(unknown['excluded'])

    def test_current_values_and_term_curve_share_inclusive_boundary(self):
        now=pd.Timestamp('2026-11-19T10:00:05+08:00');symbol='IF2611.CFE'
        live={symbol:observation(3990,at=now),'000300.SH':observation(4000,at=now)}
        meta={symbol:dict(expiry_date='2026-11-20')}
        for minimum,valid in ((1,True),(2,False),(5,False)):
            row=dict(symbol=symbol,root='IF',slot=0)
            futures_values(row,live,{},meta,now,dividends=ZERO_DIVIDENDS,min_annual_days=minimum)
            self.assertEqual(row['annual_pct'] is not None,valid)
            self.assertEqual(bool(points([row])),valid)
            self.assertIn(f'T<{minimum}',row['basis_reason'])
        for expiry in ('2026-11-19','2026-11-18'):
            row=dict(symbol=symbol,root='IF',slot=0)
            futures_values(row,live,{}, {symbol:dict(expiry_date=expiry)},now,dividends=ZERO_DIVIDENDS)
            self.assertIsNone(row['annual_pct']);self.assertEqual(points([row]),[])

    def test_indicator_all_channels_use_the_configured_boundary(self):
        day='2026-11-19';meta=metadata();mapping=slot_map(meta,'IF',day)[0]
        prices={s:3990 for s in mapping.values()};prices['000300.SH']=4000
        loose=values(day,selection(),mapping,meta,prices,ZERO_DIVIDENDS,current=True)
        strict=values(day,selection(),mapping,meta,prices,ZERO_DIVIDENDS,current=True,min_annual_days=5)
        for key in ('raw','adjusted','annual'):
            self.assertIsNotNone(loose[key]['value']);self.assertFalse(loose[key]['excluded'])
            self.assertIsNone(strict[key]['value']);self.assertEqual(strict[key]['reason'],'T_LT_5')
        # Calendar legs also obey the configured filter, even with a valid gap.
        for slot,days in ((1,1),(2,3),(3,5)):
            meta[mapping[f'IF0{slot}.CFE']]['expiry_date']=str(date.fromisoformat(day)+timedelta(days=days))
        loose=values(day,selection(),mapping,meta,prices,ZERO_DIVIDENDS,current=True)
        strict=values(day,selection(),mapping,meta,prices,ZERO_DIVIDENDS,current=True,min_annual_days=5)
        for key in ('calendar_03_02','calendar_02_01'):
            self.assertIsNotNone(loose[key]['value']);self.assertTrue(strict[key]['excluded'])

    def test_derived_and_saved_display_caches_do_not_cross_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=DerivedCache(tmp,writable=True)
            self.assertIsNotNone(cache.calculate('IF2611.CFE','2026-11-19',3990,4000,0,1)['annual_pct'])
            self.assertIsNone(cache.calculate('IF2611.CFE','2026-11-19',3990,4000,0,1,min_annual_days=5)['annual_pct'])
            self.assertEqual(cache.hits,0);cache.flush()
            reader=DerivedCache(tmp)
            self.assertIsNotNone(reader.calculate('IF2611.CFE','2026-11-19',3990,4000,0,1)['annual_pct'])
            self.assertEqual(reader.hits,1)
            self.assertNotEqual(scope({}),scope({'overview_min_annual_days':5}))
            self.assertEqual(scope({}),scope({'overview_min_annual_days':1}))

    def test_overview_engine_recalculates_after_setting_changes_in_same_session(self):
        day='2026-11-19';now=pd.Timestamp(day+'T10:00:05+08:00');meta=metadata();data=daily_data(meta,day=day)
        live={s:observation(4000,at=now) for root,spot in SPOTS.items() for s in [spot,*slot_map(meta,root,day)[0].values()]}
        repo=Mock();repo.freeze.return_value={};repo.symbols.return_value={}
        repo.read_window.side_effect=lambda s,*a,**k:data.get(s,pd.DataFrame())
        model=SimpleNamespace(config={'overview_min_annual_days':5},configure_repository=lambda _:repo,
                              _live=lambda *a:deepcopy(live),live_rows=pd.DataFrame())
        ref=SimpleNamespace(data={},version='expiry-fixture');engine=MarketOverviewEngine(model)
        with patch('dashboard.native.market_overview.ReferenceBook',return_value=ref),\
             patch('dashboard.native.market_overview.latest_contracts',return_value=meta),\
             patch('dashboard.native.market_overview.load_dividends',return_value=ZERO_DIVIDENDS):
            strict=engine.snapshot(now=now)['market_overview']
            model.config['overview_min_annual_days']=1
            loose=engine.snapshot(now=now)['market_overview']
            model.config['overview_min_annual_days']=5
            strict_again=engine.snapshot(now=now)['market_overview']
        for value,eligible in ((strict,False),(loose,True),(strict_again,False)):
            near=[r for r in value['futures'] if r['slot']==0];self.assertEqual(len(near),4)
            for row in near:
                self.assertEqual(row['days'],1);self.assertEqual(row['annual_pct'] is not None,eligible)
                self.assertEqual(row['percentile_20'] is not None,eligible)
                self.assertEqual(row['percentile_60'] is not None,eligible)
                self.assertEqual(bool(points([row])),eligible)

    def test_indicator_engine_invalidates_cached_statistics_when_filter_changes(self):
        helper=indicator_tests.IndicatorReaderTests();helper.setUp();self.addCleanup(helper.doCleanups)
        first=helper.snapshot();helper.model.config['overview_min_annual_days']=5
        strict=helper.snapshot();self.assertFalse(strict['cache_hit']);self.assertNotEqual(first['version'],strict['version'])
        self.assertGreater(first['series']['annual']['statistics']['samples'],strict['series']['annual']['statistics']['samples'])
        helper.model.config['overview_min_annual_days']=1
        again=helper.snapshot();self.assertTrue(again['cache_hit']);self.assertEqual(first['version'],again['version'])

    def test_same_filter_can_keep_valid_near_expiry_point_but_changed_filter_cannot_revive_it(self):
        now=pd.Timestamp('2026-11-19T10:00:05+08:00')
        row=dict(symbol='IF2611.CFE',root='IF',slot=0,expiry='2026-11-20',days=1,price=3990,
                 basis_points=-10,annual_pct=-91.25,basis_source_at=now.isoformat(),
                 basis_future_source_at=now.isoformat(),basis_spot_source_at=now.isoformat())
        def payload(value):return dict(futures=[value],indices=[],etfs=[],index_details={},etf_groups={})
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(config={},local_root=Path(tmp),overview_write_cache=True)
            preserve(model,payload(deepcopy(row)),now)
            missing=dict(row,basis_points=None,annual_pct=None)
            loose=payload(missing);preserve(model,loose,now+pd.Timedelta(seconds=1))
            self.assertTrue(points(loose['futures'])[0]['saved'])
            model.config['overview_min_annual_days']=5
            strict=payload(dict(row,basis_points=None,annual_pct=None))
            preserve(model,strict,now+pd.Timedelta(seconds=2))
            self.assertNotIn('basis_display',strict['futures'][0]);self.assertEqual(points(strict['futures']),[])


class ExpirySettingsTests(unittest.TestCase):
    def fixture(self):
        from dashboard.native.inline_settings import InlineSettings
        helper=settings_tests.SettingsLayoutTests();window,pipeline=helper.fixture();self.addCleanup(helper.doCleanups)
        widget=InlineSettings(pipeline);self.addCleanup(widget.deleteLater)
        return window,pipeline,widget

    def test_default_visible_without_expanding_paths_and_saved_value_survives_restart(self):
        _,pipeline,widget=self.fixture();field=widget.fields['overview_min_annual_days']
        self.assertEqual(field.text(),'1');self.assertFalse(widget.body.isVisible())
        self.assertFalse(widget.body.isAncestorOf(field))
        field.setText('5');widget.save_expiry_filter()
        self.assertEqual(NativeModel(pipeline.model.local_root).config['overview_min_annual_days'],5)
        self.assertIn('T<5',widget.notice.text());self.assertIn('T=5',widget.notice.text())

    def test_saving_filter_during_collection_preserves_other_config_and_does_not_start_network(self):
        window,pipeline,widget=self.fixture()
        pipeline.collection.running.return_value=True
        pipeline.model.config.update(history_roots=[],history_connection_file='old-profile',custom_setting='keep')
        widget.fields['overview_min_annual_days'].setText('2')
        with patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            widget.save_expiry_filter()
        self.assertEqual(pipeline.model.config['overview_min_annual_days'],2)
        self.assertEqual(pipeline.model.config['history_connection_file'],'old-profile')
        self.assertEqual(pipeline.model.config['custom_setting'],'keep');window.refresh.assert_called_once()
        pipeline.collection.stop.assert_not_called();pipeline.collection.start.assert_not_called()

    def test_invalid_input_or_active_calculation_does_not_write(self):
        window,pipeline,widget=self.fixture();field=widget.fields['overview_min_annual_days']
        for bad in ('','0','-1','1.5','3651'):
            field.setText(bad);widget.save_expiry_filter();pipeline.model.save_config.assert_not_called()
        field.setText('1');window.busy=True;widget.save_expiry_filter()
        pipeline.model.save_config.assert_not_called()

    def test_indicator_parameter_change_redraws_immediately(self):
        from dashboard.native.indicator_analysis_view import IndicatorAnalysisPage
        with tempfile.TemporaryDirectory() as tmp:
            page=IndicatorAnalysisPage(SimpleNamespace(local_root=Path(tmp),config={}))
            self.addCleanup(page.deleteLater)
            result=indicator_tests.preview();result['min_annual_days']=1
            page.render(result)
            changed=deepcopy(result);changed['min_annual_days']=5
            with patch.object(page,'redraw',wraps=page.redraw) as draw:page.render(changed)
            draw.assert_called_once()
            self.assertIn('T<5',page.charts['annual'].footer.toolTip())


if __name__=='__main__':unittest.main()
