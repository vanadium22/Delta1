"""Synthetic, opt-in handshake test against one real, owned Excel workbook."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dashboard.numeric_snapshot import save_snapshot
from dashboard.research_workspace import evaluate
from dashboard.native.nonregression import calculate
from tests.test_intraday_workspace import fixture
from tests.test_numeric_view import fixture as view_fixture

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('RUN_EXCEL_COM')=='1','requires desktop Excel')
class WorkspaceExcelTests(unittest.TestCase):
    def test_same_book_selection_roundtrip_source_time_and_stale_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);feed_file=folder/'feed.json';out=folder/'workspace_synthetic.xlsx'
            f=fixture();metadata={f['left']:dict(listing_date='2026-04-17',expiry_date='2026-12-18')}
            def snapshot(request):
                case={**f,'price_input':request['price_input']}
                return {'metrics':calculate(**case)}
            model=SimpleNamespace(config={},local_root=folder,snapshot=snapshot)
            feed=view_fixture()
            def publish(selection=None):
                with patch('dashboard.marketdata.contract_reference.latest_contracts',return_value=metadata):
                    feed['workspace']=evaluate(model,selection,f['as_of'])
                feed['generated_at']=datetime.now(timezone.utc).isoformat()
                save_snapshot(feed,feed_file)
            publish()
            process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                str(ROOT/'dashboard/excel_numeric/live.ps1'),'-FeedFile',str(feed_file),'-Output',str(out)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            run_file=None
            def wait(check,description):
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        self.fail(process.communicate()[1].decode(errors='replace'))
                    try:
                        result=check()
                        if result:return result
                    except (ValueError,KeyError,OSError):pass
                    time.sleep(.25)
                self.fail(description+' '+(run_file.read_text(encoding='utf8') if run_file else ''))
            def find_run():
                for p in (ROOT/'dashboard/runtime/numeric_live').glob('*/run.json'):
                    r=json.loads(p.read_text(encoding='utf8'))
                    if Path(r['output'])==out:return p
            script=folder/'interact.ps1'
            script.write_text('''param($Inspect,$RunFile,$Mode)
$ErrorActionPreference='Stop'
& $Inspect -RunFile $RunFile | Out-Null
$run=Get-Content -LiteralPath $RunFile -Raw -Encoding UTF8 | ConvertFrom-Json
$native=[NumericInspect]::Window([long]$run.hwnd,[uint32]$run.excel_pid)
$app=$native.Application
$book=@($app.Workbooks | Where-Object {$_.FullName -eq $run.output})[0]
$s=$book.Worksheets.Item('组合对比')
if($Mode -eq 'future'){
 [void]$s.Activate();$s.Range('D7').Formula='期货价'
 [void]$s.Range('E22').Select();$book.Windows.Item(1).ScrollRow=20
}
if($Mode -eq 'daily'){$s.Range('E7').Formula='日终'}
@{book=$book.FullName;hwnd=$app.Hwnd;value=$s.Range('G7').Value2;source=$s.Range('N7').Value2;
 status=$s.Range('P7').Value2;selection=$app.Selection.Address();scroll=$book.Windows.Item(1).ScrollRow;
 input=$s.Range('D7').Value2;group=$s.Range('B3').Value2;validation=$s.Range('B7').Validation.Type;
 pending=$s.Range('A17').Value2} | ConvertTo-Json -Compress
''',encoding='utf-8-sig')
            def inspect(mode='read'):
                result=subprocess.run(['powershell.exe','-NoProfile','-File',str(script),'-Inspect',
                    str(ROOT/'dashboard/excel_numeric/inspect.ps1'),'-RunFile',str(run_file),'-Mode',mode],
                    capture_output=True,check=True,timeout=20,creationflags=0x08000000)
                return json.loads(result.stdout.decode('utf-8-sig'))
            def selection():
                return json.loads((run_file.parent/'selection.json').read_text(encoding='utf8'))
            def current(expected):
                result=inspect()
                return result if result['value']==expected else None
            try:
                run_file=wait(find_run,'run not found')
                first=wait(selection,'selection not emitted')
                publish(first)
                expected=feed['workspace']['comparisons'][0][0]
                initial=wait(lambda:current(expected),'first workspace not written')
                self.assertEqual(initial['group'],'全部')
                self.assertEqual(initial['validation'],3)
                inspect('future')
                second=wait(lambda:(v if (v:=selection())['request_id']!=first['request_id'] else None),'changed selection not emitted')
                self.assertEqual(second['rows'][0]['input'],'期货价')
                # Re-publish the preceding request: it must never refill this selection.
                publish(first);time.sleep(1.2)
                pending=inspect();self.assertIsNone(pending['value'])
                publish(second)
                future=wait(lambda:current(4050.),'future selection not computed')
                self.assertEqual(future['selection'],'$E$22');self.assertEqual(future['scroll'],20)
                f['live'][f['left']]['close']=4060.
                f['live'][f['left']]['source_event_time']='2026-10-20T10:00:03+08:00'
                f['live'][f['left']]['observed_at']=f['as_of']+__import__('pandas').Timedelta(seconds=3)
                f['as_of']+=__import__('pandas').Timedelta(seconds=3)
                publish(second)
                changed=wait(lambda:current(4060.),'new live input not written')
                self.assertGreater(changed['source'],future['source'])
                self.assertEqual(changed['hwnd'],initial['hwnd']);self.assertEqual(changed['book'],initial['book'])
                publish(second);time.sleep(1.2)
                unchanged=inspect()
                self.assertEqual(changed['source'],unchanged['source']);self.assertEqual(changed['value'],unchanged['value'])
                inspect('daily')
                third=wait(lambda:(v if (v:=selection())['request_id']!=second['request_id'] else None),'daily choice not emitted')
                publish(third)
                daily=wait(lambda:current(4025.),'daily result not restored')
                self.assertIsNone(daily['source']);self.assertEqual(daily['status'],'日终参考')
                save_snapshot(dict(initial=initial,pending=pending,future=future,changed=changed,unchanged=unchanged,daily=daily),
                              ROOT/'.deps/numeric_realtime/workspace-com.json')
            finally:
                if run_file:(run_file.parent/'stop').write_text('stop')
                try:process.communicate(timeout=30)
                except subprocess.TimeoutExpired:process.terminate();process.communicate(timeout=10)
                deadline=time.monotonic()+10
                while out.exists():
                    try:out.unlink()
                    except PermissionError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
