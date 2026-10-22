"""Opt-in background Excel controls: never display or attach to user windows."""
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid

from dashboard.indicator_workspace import evaluate
from dashboard.indicator_ui import ui_controls
from dashboard.numeric_snapshot import save_snapshot
from dashboard.numeric_view import add_research_view
from tests.indicator_frozen_fixture import FrozenIndicatorModel, OBSERVED_AT

ROOT=Path(__file__).resolve().parents[1]
NAMES={'basis':'期现','calendar':'同品种跨期','cross':'跨品种'}
def input_label(input_id,page='basis'):
    return next(item['label'] for item in ui_controls(page)['inputs'] if item['input_id']==input_id)
def family_title(family_id,page='basis'):
    return next(item['label'] for item in ui_controls(page)['families'] if item['family_id']==family_id)


@unittest.skipUnless(os.environ.get('RUN_EXCEL_COM')=='1','requires desktop Excel; always hidden')
class ExcelUiControlsTests(unittest.TestCase):
    def test_pair_intraday_controls_values_evidence_and_fallback(self):
        from tests.pair_intraday_fixture import FrozenPairIntradayModel
        from dashboard.numeric_excel import excel_time
        evidence_root=ROOT/'.deps/pair_intraday/excel'
        folder=evidence_root/('com_'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
        models={}
        def model_for(scenario):
            if scenario not in models:models[scenario]=FrozenPairIntradayModel(folder/scenario,scenario=scenario)
            return models[scenario]
        active_model=model_for('valid')
        def publish(request):
            result=evaluate(active_model,request,OBSERVED_AT)
            feed=add_research_view(dict(ready=True),result);save_snapshot(feed,folder/'feed.json');return feed
        publish(dict(active_page='cross',request_id='initial',pages={
            'cross':dict(variant_id='B09::fixed::v1',timing='日终')}))
        # Include every diagnostic row and its n/source time in this focused probe.
        probe=(ROOT/'tests/excel_ui_probe.ps1').read_text(encoding='utf-8-sig')
        probe=probe.replace('@(1,2,3,9,11)','@(1,2,3,4,6,9,11)').replace('$r -le 80','$r -le 300')
        (folder/'probe.ps1').write_text(probe,encoding='utf-8-sig')
        stdout=(folder/'stdout.log').open('wb');stderr=(folder/'stderr.log').open('wb')
        process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(folder/'probe.ps1'),'-Root',str(ROOT),'-Work',str(folder)],stdout=stdout,stderr=stderr,creationflags=0x08000000)
        records=[];results=[];counter=0;identity=None;started=time.monotonic()
        def command(page=None,edits=()):
            nonlocal counter,identity
            counter+=1;save_snapshot(dict(id=str(counter),page=page,edits=list(edits)),folder/'command.json')
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                if (folder/'error.txt').exists():self.fail((folder/'error.txt').read_text())
                try:
                    response=json.loads((folder/f'response_{counter}.json').read_text(encoding='utf8'))
                    self.assertFalse(response['visible']);self.assertEqual(response['chart_count'],1)
                    observed=(response['hwnd'],response['full_name'])
                    if identity is None:identity=observed
                    self.assertEqual(identity,observed);records.append(response);return response
                except (OSError,ValueError):pass
                if process.poll() is not None:self.fail((folder/'stderr.log').read_text(errors='replace'))
                time.sleep(.1)
            self.fail('Hidden intraday workbook did not answer')
        cases=[(p,f,x,'valid','盘中优先') for p in ('calendar','cross')
               for f,x in (('B09','fixed'),('B11','future'),('B11','basis'),('B11','annual'))]
        cases += [(p,f,x,'zero','盘中优先') for p in ('calendar','cross') for f,x in (('B09','fixed'),('B11','future'))]
        cases += [('cross',f,x,s,'盘中优先') for s in ('missing_history','reconnect','missing_leg','stale')
                  for f,x in (('B09','fixed'),('B11','future'))]
        cases += [('cross',f,x,'valid','日终') for f,x in (('B09','fixed'),('B11','future'))]
        try:
            initial=command();publish(initial['request']);command()
            for page,family,input_id,scenario,timing in cases:
                active_model=model_for(scenario);name=NAMES[page]
                edits=[dict(sheet=name,cell='B3',value=family_title(family,page)),
                       dict(sheet=name,cell='E3',value='固定口径' if input_id=='fixed' else input_label(input_id,page)),
                       dict(sheet=name,cell='B4',value=timing)]
                pending=command(name,edits);self.assertEqual(pending['pages'][name]['rows'],[])
                feed=publish(pending['request']);done=command();view=done['pages'][name]
                expected=feed['research']['excel_pages'][page];shared=feed['research']['pages'][page]['entities']
                self.assertEqual(len(view['rows']),6 if page=='cross' else 4)
                for actual,source in zip(view['rows'],expected['summary']):
                    self.assertEqual(actual[0],source[0]);self.assertEqual(actual[2],source[2]);self.assertEqual(actual[4:],source[4:])
                    if source[1] is None:self.assertIsNone(actual[1])
                    else:self.assertAlmostEqual(actual[1],source[1],places=9)
                    if source[3]:self.assertAlmostEqual(actual[3],excel_time(source[3]),places=8)
                self.assertEqual(len(view['details']),len(expected['details']))
                self.assertTrue(view['details'][0][0].startswith('【主指标】'))
                self.assertEqual(len(view['notes']),len(expected['detail_notes']))
                for note,source in zip(view['notes'],expected['detail_notes']):
                    if source:self.assertEqual(note['text'],source);self.assertFalse(note['visible'])
                    else:self.assertIsNone(note)
                for actual,source in zip(view['details'],expected['details']):
                    self.assertEqual(actual[0],source[0]);self.assertEqual(actual[2:],[source[i] for i in (2,3,5,8,10)])
                    if isinstance(source[1],(int,float)):self.assertAlmostEqual(actual[1],source[1],places=9)
                    else:self.assertEqual(actual[1],source[1])
                branch='B09.same_time' if family=='B09' else 'B11.sample'
                current_available=scenario in ('valid','zero') or (scenario=='reconnect' and family=='B09')
                expected_primary=branch if timing=='盘中优先' and current_available else family
                self.assertTrue(all(e['primary']['id']==expected_primary for e in shared))
                self.assertTrue(all(e['primary']['unit']=='倍' for e in shared))
                if expected_primary==branch:
                    self.assertIn('同刻累计' if family=='B09' else '采集段',view['status'])
                    self.assertTrue(all(e['primary']['data_status']=='intraday_estimate' for e in shared))
                    self.assertTrue(all(e['primary'].get('pair_intraday') for e in shared))
                    self.assertTrue(any(n and 'pair_intraday' in n['text'] and 'pair_metadata' in n['text'] for n in view['notes']))
                    if scenario=='zero':self.assertTrue(all(e['primary']['value']==0. for e in shared))
                else:
                    self.assertTrue(all(e['primary']['data_status'] in ('daily_reference','old_history') for e in shared))
                save_snapshot(feed,folder/(f'{page}_{family}_{input_id}_{scenario}_{timing}.json'))
                results.append(dict(page=page,family=family,input=input_id,scenario=scenario,timing=timing,
                    primary_ids=[e['primary']['id'] for e in shared],values=[e['primary']['value'] for e in shared],
                    n=[e['primary']['n'] for e in shared],states=[e['primary']['data_status'] for e in shared],
                    detail_rows=len(view['details']),evidence=[e['primary'].get('pair_intraday') for e in shared]))
            result=dict(passed=True,seconds=round(time.monotonic()-started,2),checks=len(records),cases=results,
                        workbook=str(folder/'verified.xlsx'),hidden=True)
            save_snapshot(result,folder/'evidence.json');save_snapshot(dict(passed=True,folder=str(folder),checks=len(records),cases=len(results)),evidence_root/'latest_com.json')
        finally:
            (folder/'stop').write_text('stop')
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
            stdout.close();stderr.close()

    def test_real_chinese_controls_migration_stale_results_and_paging(self):
        evidence_root=ROOT/'.deps/pair_reconstruction/excel'
        folder=evidence_root/('com_'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        model=FrozenIndicatorModel(folder/'settings')
        selection=dict(active_page='basis',request_id='initial',pages={
            'basis':dict(variant_id='A03.mean::basis::v1',timing='日终',limit=100),
            'calendar':dict(variant_id='A03.mean::basis::v1',timing='日终'),
            'cross':dict(variant_id='A03.mean::basis::v1',timing='日终')})
        def publish(request):
            result=evaluate(model,request,OBSERVED_AT)
            feed=add_research_view(dict(ready=True),result)
            save_snapshot(feed,folder/'feed.json')
            return feed
        publish(selection)
        stdout=(folder/'stdout.log').open('wb');stderr=(folder/'stderr.log').open('wb')
        process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(ROOT/'tests/excel_ui_probe.ps1'),'-Root',str(ROOT),'-Work',str(folder)],
            stdout=stdout,stderr=stderr,creationflags=0x08000000)
        records=[];counter=0;identity=None
        def command(page=None,edits=()):
            nonlocal counter,identity
            counter+=1
            save_snapshot(dict(id=str(counter),page=page,edits=list(edits)),folder/'command.json')
            until=time.monotonic()+35
            while time.monotonic()<until:
                if (folder/'error.txt').exists():self.fail((folder/'error.txt').read_text(encoding='utf8'))
                try:
                    r=json.loads((folder/f'response_{counter}.json').read_text(encoding='utf8'))
                    if r['id']==str(counter):
                        self.assertFalse(r['visible']);self.assertEqual(r['chart_count'],1)
                        observed=(r['hwnd'],r['full_name'])
                        if identity is None:identity=observed
                        self.assertEqual(identity,observed)
                        records.append(r);return r
                except (OSError,ValueError):pass
                if process.poll() is not None:self.fail((folder/'stderr.log').read_text(errors='replace'))
                time.sleep(.1)
            self.fail('Hidden owned workbook did not answer')
        def change(page,edits):
            name=NAMES[page];pending=command(name,edits)
            self.assertEqual(pending['pages'][name]['rows'],[])
            feed=publish(pending['request']);done=command()
            expected=feed['research']['excel_pages'][page]['summary'];actual=done['pages'][name]['rows']
            self.assertEqual(len(actual),len(expected))
            for a,e in zip(actual,expected):
                self.assertEqual(a[0],e[0]);self.assertEqual(a[2],e[2]);self.assertEqual(a[4:],e[4:])
                if e[1] is None:self.assertIsNone(a[1])
                else:self.assertAlmostEqual(a[1],e[1],places=9)
                if e[3]:
                    from dashboard.numeric_excel import excel_time
                    self.assertAlmostEqual(a[3],excel_time(e[3]),places=8)
            self.assertEqual(done['pages'][name]['nav'],"'"+name+"详情'!A1")
            details=feed['research']['excel_pages'][page]['details']
            for actual,source in zip(done['pages'][name]['details'],details):
                self.assertEqual(actual[0],source[0]);self.assertEqual(actual[2:], [source[2],source[8],source[10]])
                if isinstance(source[1],(int,float)):self.assertAlmostEqual(actual[1],source[1],places=9)
                else:self.assertEqual(actual[1],source[1])
            return done,feed
        def edit(page,cell,value,detail=False):return dict(sheet=NAMES[page]+('详情' if detail else ''),cell=cell,value=value)
        try:
            start=command();self.assertEqual(start['pages']['期现']['limit'],24)
            publish(start['request']);command()
            for page in NAMES:
                for input_id in ('future','basis','annual'):
                    done,feed=change(page,[edit(page,'B3',family_title('A03.mean',page)),edit(page,'E3',input_label(input_id,page))])
                    self.assertEqual(done['request']['pages'][page]['variant_id'],f'A03.mean::{input_id}::v1')
                    self.assertEqual(len(done['pages'][NAMES[page]]['rows']),6 if page=='cross' else 4)
                    if page!='basis':
                        self.assertTrue(done['pages'][NAMES[page]]['construction'])
                        self.assertTrue(done['pages'][NAMES[page]]['meaning'])
                        self.assertTrue(done['pages'][NAMES[page]]['limitations'])
            # Rapid control changes: the intermediate response must not repopulate a new title.
            old=command('期现',[edit('basis','E3',input_label('future'))]);stale=publish(old['request'])
            newer=command('期现',[edit('basis','E3',input_label('annual'))]);self.assertEqual(newer['pages']['期现']['rows'],[])
            rejected=command();self.assertEqual(rejected['pages']['期现']['rows'],[])
            publish(newer['request']);command()
            done,_=change('basis',[edit('basis','B3','A03.std::future::v1')])
            self.assertEqual(done['pages']['期现']['input'],input_label('future'))
            self.assertEqual(done['request']['pages']['basis']['family_id'],'A03.std')
            done,_=change('basis',[edit('basis','E3','更多口径'),edit('basis','B7',input_label('log_basis'),True)])
            self.assertEqual(done['request']['pages']['basis']['variant_id'],'A03.std::log_basis::v1')
            # The former close label migrates to a real log-price ratio, not a point spread.
            done,_=change('cross',[edit('cross','E3','期货收盘价 close')])
            self.assertEqual(done['request']['pages']['cross']['input'],'future')
            self.assertEqual(done['pages']['跨品种']['input'],input_label('future','cross'))
            self.assertEqual(len(done['pages']['跨品种']['rows']),6)
            for family in ('B03','B07','B09','B11'):
                edits=[edit('cross','B3',family_title(family,'cross'))]
                if family!='B09':edits.append(edit('cross','E3',input_label('future','cross')))
                done,feed=change('cross',edits)
                details=done['pages']['跨品种']['details']
                self.assertTrue(any(row[0].startswith('【主指标】') for row in details))
                self.assertTrue(any(row[0].startswith('【辅助解释】') for row in details))
                self.assertIn('contract-pair-v3',details[0][3])
            done,_=change('cross',[edit('cross','B3',family_title('B12','cross')),edit('cross','E5',0,True)])
            self.assertEqual(done['pages']['跨品种']['input'],'固定口径');self.assertEqual(done['pages']['跨品种']['p'],0)
            done,_=change('cross',[edit('cross','E5',None,True)])
            self.assertIsNone(done['pages']['跨品种']['p'])
            done,_=change('basis',[edit('basis','E3',input_label('basis')),edit('basis','E4','全部合约'),edit('basis','B5',4,True)])
            done,_=change('basis',[edit('basis','H4',4,True)])
            self.assertEqual(done['request']['pages']['basis']['offset'],4)
            done,_=change('basis',[edit('basis','E4','默认代表')])
            self.assertEqual(done['request']['pages']['basis']['offset'],0);self.assertEqual(len(done['pages']['期现']['rows']),4)
            self.assertIsNone(done['pages']['期现']['old_row'])
            done,_=change('basis',[edit('basis','B3',family_title('B07')),edit('basis','E3',input_label('future'))])
            self.assertEqual(done['pages']['期现']['input_validation'],input_label('future'))
            done,_=change('basis',[edit('basis','E3',input_label('annual'))])
            self.assertEqual(done['pages']['期现']['rows'],[]);self.assertIn('不适用',done['pages']['期现']['status'])
            save_snapshot(dict(passed=True,checks=records,workbook=str(folder/'verified.xlsx')),folder/'evidence.json')
            (evidence_root/'latest_com.json').write_text(json.dumps(dict(folder=str(folder),checks=len(records),passed=True),ensure_ascii=False),encoding='utf8')
        finally:
            (folder/'stop').write_text('stop',encoding='utf8')
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
            stdout.close();stderr.close()


if __name__=='__main__':unittest.main()
