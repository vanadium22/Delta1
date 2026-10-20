"""Opt-in native Excel verification of the shipped compact template."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from dashboard.numeric_snapshot import save_snapshot
from dashboard.numeric_view import add_view
from tests.test_numeric_view import fixture

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('RUN_EXCEL_COM')=='1','requires desktop Excel')
class CompactExcelTests(unittest.TestCase):
    def test_selectors_then_same_visible_book_updates_without_losing_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);feed_file=folder/'feed.json';out=folder/'compact_synthetic.xlsx'
            feed=fixture()
            for r in feed['sheets']['分位与样本']:
                if r[1]=='IM03.CFE':r[4]=None
            def publish():
                feed['generated_at']=datetime.now(timezone.utc).isoformat()
                add_view(feed);save_snapshot(feed,feed_file)
                return feed['generated_at']
            first=publish()
            process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                str(ROOT/'dashboard/excel_numeric/live.ps1'),'-FeedFile',str(feed_file),'-Output',str(out)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            run_file=None
            def wait(stamp):
                nonlocal run_file
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    for p in ([run_file] if run_file else (ROOT/'dashboard/runtime/numeric_live').glob('*/run.json')):
                        try:
                            r=json.loads(p.read_text(encoding='utf8'))
                            if Path(r['output'])==out:
                                run_file=p
                                if r.get('state')=='running' and r.get('feed_generated_at')==stamp:
                                    return r
                        except (ValueError,KeyError,OSError):
                            pass
                    if process.poll() is not None:
                        self.fail(process.communicate()[1].decode(errors='replace'))
                    time.sleep(.1)
                self.fail('compact workbook did not finish the expected feed')
            try:
                wait(first)
                script=folder/'select.ps1'
                script.write_text('''param($Inspect,$RunFile)
$ErrorActionPreference='Stop'
& $Inspect -RunFile $RunFile | Out-Null
$run=Get-Content -LiteralPath $RunFile -Raw -Encoding UTF8 | ConvertFrom-Json
$native=[NumericInspect]::Window([long]$run.hwnd,[uint32]$run.excel_pid)
$app=$native.Application
$book=@($app.Workbooks | Where-Object { $_.FullName -eq $run.output })[0]
$view=$book.Worksheets.Item('概览');$metrics=$book.Worksheets.Item('指标')
$cases=@()
foreach($slot in @(0,1,2,3)){
  $view.Range('E3').Value2=[double]$slot;$metrics.Range('E3').Value2=[double]$slot
  [void]$app.Calculate()
  $chartValues=$view.ChartObjects(1).Chart.SeriesCollection(1).Values
  $cases+=@{slot=$slot;contract=$view.Range('E6').Value2;future=$view.Range('B8').Value2;
    stress=$view.Range('H10').Value2;zero=$view.Range('B15').Text;
    efficiency=$metrics.Range('D28').Value2;chart0=$chartValues.GetValue($chartValues.GetLowerBound(0));
    chart_count=$chartValues.Length;plot_hidden=(-not $view.ChartObjects(1).Chart.PlotVisibleOnly);
    last_chart_source=$book.Worksheets.Item('卡片数据').Range('AA10').Text}
}
[void]$metrics.Activate();[void]$metrics.Range('D28').Select();$book.Windows.Item(1).ScrollRow=10
$cases | ConvertTo-Json -Compress
''',encoding='utf-8-sig')
                raw=subprocess.run(['powershell.exe','-NoProfile','-File',str(script),'-Inspect',
                    str(ROOT/'dashboard/excel_numeric/inspect.ps1'),'-RunFile',str(run_file)],
                    check=True,capture_output=True,timeout=20,creationflags=0x08000000)
                cases=json.loads(raw.stdout.decode('utf-8-sig'))
                (ROOT/'.deps/numeric_ui/selector-cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf8')
                for slot,item in enumerate(cases):
                    self.assertEqual(item['future'],4100.+slot*10)
                    self.assertEqual(item['efficiency'],21.+slot)
                    self.assertEqual(item['zero'],'0%')
                    self.assertEqual(item['chart0'],0.)
                    self.assertEqual(item['chart_count'],4);self.assertTrue(item['plot_hidden'])
                    if slot==3:self.assertEqual(item['last_chart_source'],'#N/A')
                    if slot in (0,3): self.assertEqual(item['stress'],'')
                from dashboard.numeric_diagnose import sample
                before=sample(run_file);self.assertTrue(before['overview_match_feed'])
                self.assertTrue(before['window']['visible'])
                selected=next(r for r in feed['sheets']['数字看板'] if r[1]=='IF03.CFE')
                selected[3]=5100.;selected[11]=46315.45
                metric=next(r for r in feed['sheets']['研究指标'] if r[1]=='IF03.CFE' and r[3]=='B10')
                metric[5]=-.7
                stamp=publish();wait(stamp)
                after=sample(run_file)
                self.assertTrue(after['overview_match_feed'],after)
                self.assertEqual(after['window']['view']['future'],5100.)
                self.assertEqual(after['window']['view']['metric_efficiency'],-.7)
                self.assertNotEqual(before['window']['view']['source'],after['window']['view']['source'])
                for key in ('full_name','hwnd','excel_pid','active_sheet','selection','scroll_row','scroll_column'):
                    self.assertEqual(before['window'][key],after['window'][key],key)
                baseline=wait(stamp)
                same=publish();stable=wait(same)
                self.assertEqual(baseline['saves'],stable['saves'])
                evidence=ROOT/'.deps/numeric_ui'
                (evidence/'compact-native.json').write_text(json.dumps(dict(cases=cases,before=before,after=after),ensure_ascii=False,indent=2),encoding='utf8')
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


if __name__=='__main__':
    unittest.main()
