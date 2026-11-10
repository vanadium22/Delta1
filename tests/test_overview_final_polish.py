"""Company display robustness, dated AUM, durable batches and fit-to-page UI."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import zipfile

import pandas as pd

from dashboard.marketdata.overview_aum import start_day
from dashboard.marketdata.overview_contributions import contributions
from dashboard.marketdata.overview_display_cache import preserve
from dashboard.marketdata.overview_etf_history import read_aum_history,series_for,size_changes
from dashboard.marketdata.overview_reference import available_sections,ranking,validate
from dashboard.marketdata.wind_terminal_worker import refresh
from dashboard.native.equity_collection import EquitySampler
from tests.test_market_overview import NOW,observation
from tests.test_overview_data import FakeWind,response
from tests.test_overview_details import reference,equity_snapshot
from tests.test_realtime_store import quote


class HistoryWind(FakeWind):
    def wsd(self,codes,field,start,end,options):
        if field=='netasset_total' and start!=end:
            self.calls.append(('WSD_HISTORY',field,options))
            value=response([field.upper()],[[480e8,None,500e8]],[codes])
            value.Times=[datetime(2026,10,d) for d in (21,22,23)]
            return value
        return super().wsd(codes,field,start,end,options)


class AumDownloadTests(unittest.TestCase):
    def request(self):return dict(day='2026-10-23',fetched_at=NOW.isoformat(),old=reference(),config={},stage='nav')

    def test_three_calendar_months_clamps_short_months(self):
        self.assertEqual(start_day('2026-11-10'),'2026-08-10')
        self.assertEqual(start_day('2026-05-31'),'2026-02-28')

    def test_existing_field_real_dates_missing_cells_and_no_realtime_subscription(self):
        sdk=HistoryWind();value=validate(refresh(sdk,self.request())['data'])
        history=value['etf_aum_history'];self.assertEqual(history['requested_start'],'2026-07-23')
        self.assertEqual(len(history['rows']),3)
        self.assertEqual([p['as_of'] for p in history['rows']['510301.SH']['points']],['2026-10-21','2026-10-23'])
        self.assertEqual([p['aum_cny'] for p in history['rows']['510301.SH']['points']],[480e8,500e8])
        calls=[r for r in sdk.calls if r[0]=='WSD_HISTORY'];self.assertEqual(len(calls),3)
        self.assertTrue(all('Fill=Blank' in r[2] and 'unit=1' in r[2] for r in calls))
        selected=ranking(value,'IF',today='2026-10-26')[0];local=read_aum_history({},'not-present',value)
        first=selected[0];first['aum_series']=series_for('IF',first,local)
        change=size_changes('IF',[first],local)[0]
        self.assertEqual(change['aum_change_cny'],20e8);self.assertEqual(change['aum_previous_date'],'2026-10-21')

    def test_one_bad_code_preserves_its_old_history_and_other_codes_update(self):
        request=self.request();prior=refresh(HistoryWind(),request)['data'];request['old']=prior
        sdk=HistoryWind();method=sdk.wsd
        def broken(codes,field,start,end,options):
            value=method(codes,field,start,end,options)
            if codes=='510302.SH' and start!=end:value.Times[-1]=datetime(2026,10,24)
            return value
        sdk.wsd=broken;value=validate(refresh(sdk,request)['data'])
        self.assertEqual(value['etf_aum_history']['rows']['510302.SH'],prior['etf_aum_history']['rows']['510302.SH'])
        self.assertTrue(value['etf_aum_history']['rows']['510301.SH']['points']);self.assertTrue(value['errors'])

    def test_bad_optional_history_is_isolated_from_other_history_and_quotes(self):
        value=refresh(HistoryWind(),self.request())['data']
        value['etf_aum_history']['rows']['510302.SH']['points'][0]['aum_cny']=0
        with self.assertRaises(ValueError):validate(value)
        readable,issues=available_sections(value)
        self.assertIn('IF',readable['indices']);self.assertEqual(len(readable['etf_aum_history']['rows']),2)
        self.assertTrue(any(r['scope']=='etf_aum_history.510302.SH' for r in issues))

    def test_daily_job_is_due_when_nav_is_current_but_aum_is_absent_and_is_bounded(self):
        from dashboard.marketdata.overview_reference import publish
        from dashboard.native.overview_reference_job import ReferenceJob
        value=reference();selected=ranking(value,'IF',today='2026-10-26')[0]
        value['etf_nav']=dict(schema='etf-nav-v1',rows={r['symbol']:dict(symbol=r['symbol'],as_of='2026-10-23',nav_cny=4,close_cny=4,source='fixture') for r in selected})
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.native.overview_reference_job.repair_needs',return_value=[]),patch('subprocess.Popen') as spawn:
            spawn.return_value.poll.return_value=0;publish(Path(tmp)/'overview_reference/latest.json',value)
            job=ReferenceJob(tmp);job.tick({},enabled=True,now=NOW.to_pydatetime())
            self.assertEqual(spawn.call_args.args[0][-1],'nav')
            job.tick({},enabled=True,now=NOW.to_pydatetime());self.assertEqual(spawn.call_count,1)


class RollingAndDisplayTests(unittest.TestCase):
    def test_daily_jobs_default_to_headlines_while_full_stock_mode_remains_explicit(self):
        from dashboard.marketdata.overview_daily import requests
        with tempfile.TemporaryDirectory() as tmp:
            ordinary=requests({},tmp,'2026-10-26',{},reference_data=reference())
            full=requests(dict(overview_stock_daily_enabled=True),tmp,'2026-10-26',{},reference_data=reference())
        self.assertFalse(any(r['asset']=='stock' for r in ordinary));self.assertTrue(any(r['asset']=='etf' for r in ordinary))
        self.assertTrue(any(r['asset']=='stock' for r in full))

    def test_partial_industry_renormalizes_basket_only_and_keeps_original_index_weights(self):
        group=reference()['indices']['IF'];group['rows'][1]['industry']='电子'
        snap=equity_snapshot();del snap['quotes']['600002.SH']
        group['rows'][2]['weight_pct']=None;group['weights_complete']=False
        detail=contributions(group,snap,dict(symbol='000300.SH'),NOW,'2026-10-23','v1')
        sector=next(r for r in detail['industries'] if r['name']=='电子')
        self.assertAlmostEqual(sector['change_pct'],10);self.assertAlmostEqual(sector['contribution_points'],5)
        self.assertEqual(detail['weighted_covered'],1);self.assertEqual(detail['covered'],2)
        self.assertEqual(detail['coverage_pct'],50);self.assertTrue(detail['partial'])
        self.assertEqual(detail['leaders'][0]['name'],'电子')

    def test_rolling_uses_a_separate_six_minute_budget_and_rejects_future_quotes(self):
        snap=equity_snapshot();snap.update(mode='rolling',quote_max_age_seconds=360)
        for q in snap['quotes'].values():q['source_event_time']=(NOW-pd.Timedelta(seconds=240)).isoformat();q['observed_at']=NOW.isoformat()
        detail=contributions(reference()['indices']['IF'],snap,dict(symbol='000300.SH'),NOW,'2026-10-23','v1')
        self.assertEqual(detail['covered'],3)
        snap['quotes']['600001.SH']['source_event_time']=(NOW+pd.Timedelta(seconds=4)).isoformat()
        self.assertEqual(contributions(reference()['indices']['IF'],snap,dict(symbol='000300.SH'),NOW,'2026-10-23','v1')['covered'],2)

    def test_each_batch_is_published_before_next_request_and_failures_retain_last_quote(self):
        value=reference();value['indices']['IF']['rows']=[dict(symbol=f'{600000+i:06}.SH',weight_pct=100/205) for i in range(205)]
        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            sampler=EquitySampler(tmp,dict(overview_equity_batch_size=100),lambda:dict(allowed=True),Mock(),pause=lambda _:False)
            class Client:
                def fetch(self,symbols):
                    if calls:
                        saved=json.loads((Path(tmp)/'overview_equities/latest.json').read_text());self_outer.assertEqual(saved['batch'],len(calls))
                    calls.append(symbols)
                    return dict(status='success',received_at=NOW.isoformat(),response=dict(data={s:{**quote(10,100,100005),'securityId':s} for s in symbols}))
            self_outer=self
            from dashboard.marketdata.equity_observations import EquityObservationStore
            with EquityObservationStore(Path(tmp)/'observations',archive_enabled=False) as store:
                first=sampler.cycle(Client(),store,dict(data=value,version='v1'),1)
                failing=SimpleNamespace(fetch=Mock(side_effect=OSError('CANARY_RAW_EXCEPTION')))
                second=sampler.cycle(failing,store,dict(data=value,version='v2'),2)
            self.assertEqual([len(r) for r in calls],[100,100,6]);self.assertEqual(first['quotes'],second['quotes'])
            self.assertEqual(second['batch_count'],3);self.assertNotIn('CANARY',json.dumps(second))

    def test_no_automatic_parquet_keeps_raw_sqlite_and_existing_archive(self):
        from dashboard.marketdata.equity_observations import EquityObservationStore
        from index_strategy.instant_dld.reader import RealtimeReader
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data/old.parquet';path.parent.mkdir();path.write_bytes(b'preserved-original')
            with patch('dashboard.marketdata.equity_observations.publish_parquet',side_effect=AssertionError('unexpected archive')):
                with EquityObservationStore(tmp,archive_enabled=False) as store:
                    store.batch(dict(status='success',poll=1,batch=1,batch_count=1,received_at=NOW.isoformat(),symbols=['600001.SH'],response=dict(data={'600001.SH':{**quote(10,100,100005),'securityId':'600001.SH'}})))
            with RealtimeReader(tmp).connect() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM quotes').fetchone()[0],1)
            self.assertTrue(list(Path(tmp).rglob('*.json')));self.assertEqual(path.read_bytes(),b'preserved-original')

    def display(self):
        detail=contributions(reference()['indices']['IF'],equity_snapshot(),dict(symbol='000300.SH'),NOW,'2026-10-23','v1')
        return dict(indices=[dict(symbol='000300.SH',price=104,source_at=NOW.isoformat(),quality=dict(usable=True))],
            futures=[dict(symbol='IF2611.CFE',price=105,annual_pct=3.,source_at=NOW.isoformat(),quality=dict(usable=True))],etfs=[],
            index_details={'IF':detail},etf_groups={})

    def test_display_sections_survive_restart_no_data_and_read_only_audit_without_advancing_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True)
            original=self.display();preserve(model,original,NOW)
            before={p:p.read_bytes() for p in (Path(tmp)/'overview_display').glob('*.json')};self.assertEqual(len(before),2)  # No ETF section exists in this fixture.
            missing=self.display();missing['index_details']['IF']=dict(covered=0,inputs={'missing_quotes':3});missing['futures'][0]['price']=None
            reader=SimpleNamespace(local_root=Path(tmp),config={})
            preserve(reader,missing,NOW+pd.Timedelta(minutes=1))
            self.assertTrue(missing['index_details']['IF']['display_saved']);self.assertEqual(missing['index_details']['IF']['snapshot_at'],NOW.isoformat())
            self.assertEqual(missing['futures'][0]['annual_pct'],3.);self.assertFalse(missing['futures'][0]['quality']['usable'])
            self.assertEqual(missing['futures'][0]['source_at'],NOW.isoformat());self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))

    def test_partial_new_results_win_and_old_basis_does_not_attach_to_new_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True);preserve(model,self.display(),NOW)
            new=self.display();new['index_details']['IF']['covered']=1;new['futures'][0].update(price=106,annual_pct=None)
            preserve(model,new,NOW+pd.Timedelta(seconds=3))
            self.assertEqual(new['index_details']['IF']['covered'],1);self.assertFalse(new['index_details']['IF'].get('display_saved',False))
            self.assertIsNone(new['futures'][0]['annual_pct'])
            other=SimpleNamespace(local_root=Path(tmp),config={'realtime_root':'different-source'})
            new['futures'][0]['price']=None;preserve(other,new,NOW+pd.Timedelta(seconds=4));self.assertIsNone(new['futures'][0]['price'])


class PagePolishTests(unittest.TestCase):
    def test_display_preference_is_separate_from_native_configuration(self):
        from tests.test_market_overview_ui import OverviewUiTests,pump
        case=OverviewUiTests();w=case.window()
        try:
            config=Path(w.model.local_root)/'native.json';config.write_bytes(b'{"preserved":true}');before=config.read_bytes()
            w.page_scale.setCurrentIndex(w.page_scale.findData('small'));pump(.05)
            self.assertEqual(json.loads((Path(w.model.local_root)/'overview_ui.json').read_text())['page_scale'],'small')
            self.assertEqual(config.read_bytes(),before)
        finally:case.doCleanups()

    def test_medium_and_small_fit_1080p_pages_and_large_can_scroll(self):
        from tests.test_market_overview_ui import APP,state,pump
        from dashboard.native.editions_current import PresentationWindow,freeze_window
        with tempfile.TemporaryDirectory() as tmp:
            class Frozen(PresentationWindow):frozen_payload=freeze_window(state())
            w=Frozen(SimpleNamespace(local_root=Path(tmp),config={},close=Mock()));w.show();pump(.1)
            try:
                for width,height in ((1920,1080),(1536,864)):
                    w.resize(width,height)
                    for mode in ('medium','small'):
                        w.page_scale.setCurrentIndex(w.page_scale.findData(mode));pump(.05)
                        for i,page in enumerate((w.quotes,*w.quotes.views.values())):
                            w.pages.setCurrentIndex(i);pump(.1)
                            self.assertEqual(page.scroll.verticalScrollBar().maximum(),0,(width,mode,i))
                            self.assertEqual(page.scroll.horizontalScrollBar().maximum(),0)
                w.page_scale.setCurrentIndex(w.page_scale.findData('large'));w.pages.setCurrentIndex(0);pump(.1)
                self.assertGreater(w.quotes.scroll.verticalScrollBar().maximum(),0)
            finally:w.close();w.deleteLater();pump(.1)

    def test_basket_bar_uses_percentage_even_when_index_base_is_missing_and_zero_is_visible(self):
        from tests.test_market_overview_ui import APP,pump
        from dashboard.native.overview_pages import IndexOverviewPage
        snap=equity_snapshot();snap['quotes'].pop('000300.SH')
        detail=contributions(reference()['indices']['IF'],snap,dict(symbol='000300.SH'),NOW,'2026-10-23','v1')
        page=IndexOverviewPage()
        try:
            page.details={'IF':detail};page.show_detail()
            self.assertIsNone(detail['industries'][0]['contribution_points'])
            self.assertAlmostEqual(page.industries.cellWidget(0,3).value,10.)
        finally:page.close();page.deleteLater();APP.processEvents()

    def test_volume_bar_and_legend_use_slot_colors_when_rows_are_not_in_slot_order(self):
        from tests.test_market_overview_ui import APP,pump
        from dashboard.native.futures_overview_view import VolumeDistribution,COLORS
        from PySide6.QtGui import QColor
        widget=VolumeDistribution();widget.resize(600,90)
        widget.render([dict(slot=2,share_pct=90),dict(slot=0,share_pct=10)],'');widget.show();pump(.05)
        try:
            image=widget.grab().toImage()
            self.assertEqual(image.pixelColor(10,25).name(),QColor(COLORS[2]).name())
            self.assertEqual(image.pixelColor(5,65).name(),QColor(COLORS[2]).name())
            self.assertEqual(image.pixelColor(550,20).name(),QColor(COLORS[0]).name())
            self.assertIn('季月 90.0%',widget.toolTip());self.assertIn('当月 10.0%',widget.toolTip())
        finally:widget.close();widget.deleteLater();APP.processEvents()


class OneClickTests(unittest.TestCase):
    def test_one_click_orders_open_sample_close_diagnostics_and_safe_json_pack(self):
        script=Path(__file__).resolve().parents[1]/'dashboard/company_retest.ps1'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profile';profile.mkdir();(profile/'native.json').write_text('{"secret":"CANARY_NEVER_EXPORT"}')
            (root/'dashboard').mkdir()
            for name in ('collect_company_return.ps1','collect_company_return.cmd'):(root/'dashboard'/name).write_bytes((script.parent/name).read_bytes())
            quote_path=lambda p:str(p).replace("'","''")
            code=r'''
. '__SCRIPT__'
$script:events=@();$script:head='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';$script:diagnoses=0;$script:prompts=0
function Invoke-DeltaGit { param([string[]]$GitArguments)
    $script:events+=('git:'+($GitArguments -join ' '))
    switch ($GitArguments[0]) { 'branch' { return 'codex/company-apps' } 'rev-parse' { return $script:head } default { return 'ok' } }
}
function Read-Host { param([string]$Prompt)
    $script:prompts++
    if ($script:prompts -eq 3) { @{phase='closed';shutdown=@{complete=$true}} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath '__ROOT__/app_run.json' -Encoding UTF8 }
    return ''
}
function Open-DeltaPresentation { param($Repository,$Profile) $script:events+='open'; '{}' | Set-Content -LiteralPath '__ROOT__/app_run.json' }
function Start-Sleep { param($Seconds) throw 'Test should not sleep or run real sampling' }
function Invoke-DeltaDiagnosis { param($Repository,$Profile,$Reports)
    $script:diagnoses++;$script:events+=('diagnose:'+ $script:diagnoses);$at=(Get-Date).ToString('o')
    $dir=Join-Path $Reports ('diagnosis-'+$script:diagnoses);New-Item -ItemType Directory -Path $dir | Out-Null
    @{at=$at;commit=$script:head;local_root=$Profile} | ConvertTo-Json | Set-Content (Join-Path $dir 'diagnosis.json') -Encoding UTF8
    @{ok=$true} | ConvertTo-Json | Set-Content (Join-Path $dir 'preflight.json') -Encoding UTF8
    $closed=$script:diagnoses -eq 2
    @{diagnostic_profile=@{local_root=$Profile};app_reports=@{matching_profile=@(@{report_path='__ROOT__/app_run.json';observed_at=$at;
        collection_worker_running=(-not $closed);closing=$closed;phase=$(if($closed){'closed'}else{'collecting'});shutdown=@{complete=$closed}})}} |
        ConvertTo-Json -Depth 8 | Set-Content (Join-Path $dir 'overview.json') -Encoding UTF8
}
$result=Invoke-CompanyRetest -Repository '__ROOT__' -Profile '__PROFILE__' -Seconds 0
@{code=$result;events=$script:events;prompts=$script:prompts} | ConvertTo-Json -Depth 5 | Set-Content '__ROOT__/test_result.json' -Encoding UTF8
'''.replace('__SCRIPT__',quote_path(script)).replace('__ROOT__',quote_path(root)).replace('__PROFILE__',quote_path(profile))
            task=root/'run.ps1';task.write_text(code,encoding='utf-8-sig')
            run=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(task)],capture_output=True,timeout=45)
            self.assertEqual(run.returncode,0,run.stderr.decode('utf8',errors='replace'))
            result=json.loads((root/'test_result.json').read_text(encoding='utf-8-sig'));self.assertEqual(result['code'],0)
            self.assertEqual(result['events'][-3:],['open','diagnose:1','diagnose:2']);self.assertEqual(result['prompts'],3)
            packages=list(root.rglob('*_safe_*.zip'));self.assertEqual(len(packages),1)
            with zipfile.ZipFile(packages[0]) as package:
                files=[n for n in package.namelist() if not n.endswith('/')];self.assertTrue(all(n.endswith('.json') for n in files))
                self.assertTrue(json.loads(package.read(next(n for n in files if n.endswith('return_manifest.json'))))['Complete'])
                self.assertTrue(all(b'CANARY_NEVER_EXPORT' not in package.read(n) for n in files))


if __name__=='__main__':unittest.main()
