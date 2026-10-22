"""Opt-in real Excel acceptance using the same frozen bars as both Qt editions."""
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import pandas as pd
from dashboard.indicator_workspace import evaluate
from dashboard.numeric_snapshot import save_snapshot
from dashboard.numeric_view import add_research_view
from tests.indicator_frozen_fixture import FrozenIndicatorModel,OBSERVED_AT
from tests.test_numeric_view import fixture as view_fixture

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('RUN_EXCEL_COM')=='1','requires desktop Excel')
class WorkspaceExcelTests(unittest.TestCase):
    def test_three_pages_same_visible_book_selection_time_values_and_stale_request(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder=Path(tmp);feed_file=folder/'feed.json';out=folder/'indicator_synthetic.xlsx'
            model=FrozenIndicatorModel(folder);now=OBSERVED_AT
            feed=view_fixture();published={}
            def publish(selection=None):
                nonlocal feed
                research=evaluate(model,selection or dict(active_page='cross',pages={'cross':dict(timing='日终')}),now)
                add_research_view(feed,research)
                feed['generated_at']=datetime.now(timezone.utc).isoformat();feed['ready']=True
                save_snapshot(feed,feed_file)
                published[research.get('request_id')]=research
                return research
            publish()
            # A previous calculation cache must never emit a choice request.
            feed['ready']=False;save_snapshot(feed,feed_file)
            process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                str(ROOT/'dashboard/excel_numeric/live.ps1'),'-FeedFile',str(feed_file),'-Output',str(out)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            run_file=None
            def wait(check,description):
                deadline=time.monotonic()+55
                while time.monotonic()<deadline:
                    if process.poll() is not None:self.fail(process.communicate()[1].decode(errors='replace'))
                    try:
                        result=check()
                        if result:return result
                    except (ValueError,KeyError,OSError):pass
                    time.sleep(.2)
                self.fail(description+' '+(run_file.read_text(encoding='utf8') if run_file else ''))
            def find_run():
                for p in (ROOT/'dashboard/runtime/numeric_live').glob('*/run.json'):
                    try:
                        if Path(json.loads(p.read_text(encoding='utf8'))['output'])==out:return p
                    except (ValueError,KeyError):pass
            script=folder/'interact.ps1'
            script.write_text('''param($Inspect,$RunFile,$Mode)
$ErrorActionPreference='Stop'
& $Inspect -RunFile $RunFile | Out-Null
$run=Get-Content -LiteralPath $RunFile -Raw -Encoding UTF8 | ConvertFrom-Json
$native=[NumericInspect]::Window([long]$run.hwnd,[uint32]$run.excel_pid)
$app=$native.Application
$book=@($app.Workbooks | Where-Object {$_.FullName -eq $run.output})[0]
if($Mode -in @('basis','calendar','cross')){$name=if($Mode -eq 'calendar'){'同品种跨期'}elseif($Mode -eq 'cross'){'跨品种'}else{'期现'};[void]$book.Worksheets.Item($name).Activate()}
$s=$book.ActiveSheet
if($Mode -eq 'future'){$s.Range('B3').Formula='A03.mean::future::v1';$s.Range('B4').Formula='日终';[void]$s.Range('H20').Select();$book.Windows.Item(1).ScrollRow=18}
if($Mode -eq 'live'){$s.Range('B3').Formula='A03.mean::future::v1';$s.Range('B4').Formula='盘中优先'}
if($Mode -eq 'daily'){$s.Range('B4').Formula='日终'}
if($Mode -eq 'all'){$s.Range('E3').Formula='all';$s.Range('N4').Formula='24';$s.Range('H4').Formula='all'}
if($Mode -eq 'capacity'){$s.Range('B3').Formula='B12::fixed::v1';$s.Range('E3').Formula='representatives';$s.Range('B4').Formula='日终';$s.Range('B8').Value2=[double]0.1}
$names=@();foreach($sheet in $book.Worksheets){if($sheet.Visible -eq -1){$names+=,$sheet.Name}}
@{book=$book.FullName;hwnd=$book.Windows.Item(1).Hwnd;visible=[bool]$app.Visible;sheet=$s.Name;
 value=$s.Range('H13').Value2;unit=$s.Range('I13').Value2;source=$s.Range('J13').Value2;
 cutoff=$s.Range('K13').Value2;n=$s.Range('L13').Value2;state=$s.Range('N13').Value2;
 variant=$s.Range('B3').Value2;scope=$s.Range('E3').Value2;timing=$s.Range('B4').Value2;
 selection=$app.Selection.Address();scroll=$book.Windows.Item(1).ScrollRow;names=$names;
 entity=$s.Range('G13').Value2;entity6=$s.Range('G18').Value2;entity16=$s.Range('G28').Value2;
 pending=$s.Range('A9').Value2;validation=$s.Range('B3').Validation.Type;p=$s.Range('B8').Value2;
 p_value=$s.Range('B285').Value2} | ConvertTo-Json -Compress
''',encoding='utf-8-sig')
            def inspect(mode='read'):
                result=subprocess.run(['powershell.exe','-NoProfile','-File',str(script),'-Inspect',
                    str(ROOT/'dashboard/excel_numeric/inspect.ps1'),'-RunFile',str(run_file),'-Mode',mode],
                    capture_output=True,check=True,timeout=25,creationflags=0x08000000)
                return json.loads(result.stdout.decode('utf-8-sig'))
            def selection(after=None):
                value=json.loads((run_file.parent/'selection.json').read_text(encoding='utf8'))
                return value if value.get('request_id')!=after else None
            def rendered(expected):
                value=inspect()
                save_snapshot(dict(expected=expected,observed=value),ROOT/'.deps/metric_implementation/excel_latest_check.json')
                equal=(math.isclose(value['value'],expected,rel_tol=1e-12,abs_tol=1e-9)
                       if isinstance(value.get('value'),(int,float)) and isinstance(expected,(int,float))
                       else value.get('value')==expected)
                return value if equal else None
            evidence=[]
            try:
                run_file=wait(find_run,'run not found')
                time.sleep(1.)
                self.assertFalse((run_file.parent/'selection.json').exists())
                publish()  # Fresh preferences retain the saved cross page.
                first=wait(selection,'selection not emitted');research=publish(first)
                self.assertEqual(first['active_page'],'cross')
                expected=research['pages']['cross']['entities'][0]['primary']
                initial=wait(lambda:rendered(expected['value']),'first result not written')
                self.assertTrue(initial['visible']);self.assertEqual(initial['validation'],3)
                self.assertEqual(initial['names'],['期现','同品种跨期','跨品种','来源与状态','概览'])
                self.assertEqual(initial['unit'],expected['unit']);self.assertEqual(initial['n'],expected['n'])
                evidence.append(initial)
                inspect('basis');first_basis=wait(lambda:selection(first['request_id']),'basis choice not emitted')
                research=publish(first_basis);expected=research['pages']['basis']['entities'][0]['primary']
                wait(lambda:rendered(expected['value']),'basis result not written');first=first_basis
                inspect('future');second=wait(lambda:selection(first['request_id']),'variant request not emitted')
                publish(first);time.sleep(1.1)
                pending=inspect();self.assertIsNone(pending['value']);evidence.append(pending)
                research=publish(second);expected=research['pages']['basis']['entities'][0]['primary']
                future=wait(lambda:rendered(expected['value']),'independent future variant not written')
                self.assertEqual(future['selection'],'$H$20');self.assertEqual(future['scroll'],18)
                self.assertEqual(future['hwnd'],initial['hwnd']);self.assertEqual(future['book'],initial['book']);evidence.append(future)
                # Historical and live estimates have distinct samples/source times.
                model.enable_live(now,2.);inspect('live')
                third=wait(lambda:selection(second['request_id']),'live request not emitted')
                research=publish(third);expected=research['pages']['basis']['entities'][0]['primary']
                live=wait(lambda:rendered(expected['value']),'live result not written');evidence.append(live)
                now+=pd.Timedelta(seconds=3);model.enable_live(now,4.)
                research=publish(third);expected=research['pages']['basis']['entities'][0]['primary']
                changed=wait(lambda:(v if (v:=inspect())['source']!=live['source'] else None),'new source time not written')
                self.assertAlmostEqual(changed['value'],expected['value'],places=8);evidence.append(changed)
                publish(third);time.sleep(.8);same=inspect()
                self.assertEqual((same['value'],same['source']),(changed['value'],changed['source']))
                previous=third
                for mode,count in (('calendar',4),('cross',6)):
                    inspect(mode);chosen=wait(lambda:selection(previous['request_id']),'page request not emitted')
                    research=publish(chosen);expected=research['pages'][mode]['entities'][0]['primary']
                    viewed=wait(lambda:rendered(expected['value']),'page result not written')
                    self.assertEqual(len(research['pages'][mode]['entities']),count)
                    if count==6:self.assertTrue(viewed['entity6'])
                    self.assertEqual(viewed['hwnd'],initial['hwnd']);evidence.append(viewed);previous=chosen
                inspect('all');chosen=wait(lambda:selection(previous['request_id']),'expanded request not emitted')
                research=publish(chosen);expected=research['pages']['cross']['entities'][0]['primary']
                expanded=wait(lambda:rendered(expected['value']),'expanded result not written')
                self.assertEqual(research['pages']['cross']['total'],96)
                self.assertEqual(len(research['pages']['cross']['entities']),24);self.assertTrue(expanded['entity16']);evidence.append(expanded)
                inspect('capacity');capacity_choice=wait(lambda:selection(chosen['request_id']),'participation request not emitted')
                self.assertAlmostEqual(capacity_choice['pages']['cross']['participation'],.1)
                research=publish(capacity_choice);expected=research['pages']['cross']['entities'][0]['primary']
                capacity=wait(lambda:rendered(expected['value']),'explicit participation result not written')
                self.assertAlmostEqual(capacity['p'],.1)
                first_metrics=research['pages']['cross']['entities'][0]['metrics']
                participation=next(m for m in first_metrics if m['id']=='B12.p')
                self.assertEqual(participation['value'],.1);evidence.append(capacity)
                save_snapshot(dict(checks=evidence,contract=research),ROOT/'.deps/metric_implementation/excel_contract.json')
            finally:
                if run_file:(run_file.parent/'stop').write_text('stop')
                try:process.communicate(timeout=30)
                except subprocess.TimeoutExpired:process.terminate();process.communicate(timeout=10)


if __name__=='__main__':unittest.main()
