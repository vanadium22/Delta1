"""Opt-in Windows Excel integration: two updates in the SAME open workbook."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import zipfile
import xml.etree.ElementTree as ET
from dashboard.numeric_excel import HEADERS
from dashboard.numeric_snapshot import save_snapshot

ROOT=Path(__file__).resolve().parents[1]
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def cell(path, address):
    with zipfile.ZipFile(path) as z:
        sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        v=sheet.find(f'.//s:c[@r="{address}"]/s:v',NS)
        return None if v is None else float(v.text)


@unittest.skipUnless(os.environ.get('RUN_EXCEL_COM')=='1','requires desktop Excel; explicitly opt in')
class ExcelIntegration(unittest.TestCase):
    def test_native_same_window_changes_source_time_but_unchanged_cache_does_not_save_again(self):
        from datetime import datetime, timezone
        import uuid
        from tests.test_numeric_refresh import payload as make_payload, feed as make_feed
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);feed_path=folder/'feed.json';out=folder/('refresh_'+uuid.uuid4().hex+'.xlsx')
            value=make_payload()
            def publish(previous=None):
                value['generated_at']=datetime.now(timezone.utc).isoformat()
                answer=make_feed(value,previous)
                save_snapshot(answer,feed_path)
                return answer
            first=publish()
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'dashboard/excel_numeric/live.ps1'),
                     '-FeedFile',str(feed_path),'-Output',str(out)]
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            run_path=None
            def wait(predicate, timeout=45):
                nonlocal run_path
                end=time.monotonic()+timeout
                while time.monotonic()<end:
                    for p in ([run_path] if run_path else (ROOT/'dashboard/runtime/numeric_live').glob('*/run.json')):
                        try:
                            r=json.loads(p.read_text(encoding='utf8'))
                            if Path(r['output'])==out:
                                run_path=p
                                if predicate(r):return r
                        except (OSError,ValueError,KeyError):pass
                    if process.poll() is not None:self.fail(process.communicate()[1].decode(errors='replace'))
                    time.sleep(.2)
                self.fail('Timed out waiting for live workbook evidence')
            def inspect():
                result=subprocess.run(['powershell.exe','-NoProfile','-File',str(ROOT/'dashboard/excel_numeric/inspect.ps1'),
                    '-RunFile',str(run_path)],capture_output=True,timeout=20,creationflags=0x08000000)
                answer=json.loads(result.stdout.decode('utf-8-sig'))
                self.assertTrue(answer['attached'],answer)
                return answer
            try:
                wait(lambda r:r.get('state')=='running' and r.get('observed',{}).get('cells',[None])[0]==4150.)
                initial=inspect()
                self.assertTrue(initial['visible']);self.assertEqual(initial['cells']['D7'],4150.)
                second=publish(first)
                wait(lambda r:r.get('state')=='running' and r.get('feed_generated_at')==second['generated_at'] and '未观察到' in r.get('observed',{}).get('status',''))
                stable=inspect(); baseline=wait(lambda r:r.get('state')=='running' and r.get('feed_generated_at')==second['generated_at'])
                third=publish(second)
                after=wait(lambda r:r.get('state')=='running' and r.get('feed_generated_at')==third['generated_at'])
                self.assertEqual(after['saves'],baseline['saves'],'clock-only recalculation must not save the workbook again')
                self.assertEqual(stable['cells']['D7'],initial['cells']['D7'])
                self.assertEqual(stable['cells']['L7'],initial['cells']['L7'])
                self.assertIn('未观察到',stable['cells']['A3'])
                card=value['snapshots'][0]['overview'][0]
                card['quote'].update(close=4300.,source_event_time='2026-10-20T09:31:00+08:00')
                card['spot']['source_event_time']='2026-10-20T09:31:00+08:00'
                card['chart']['time']='2026-10-20T09:31:00+08:00'
                fourth=publish(third)
                wait(lambda r:r.get('state')=='running' and r.get('observed',{}).get('cells',[None])[0]==4300.)
                changed=inspect()
                for key in ('full_name','hwnd','excel_pid','selection','scroll_row','scroll_column'):
                    self.assertEqual(changed[key],initial[key],key)
                self.assertEqual(changed['cells']['D7'],4300.)
                self.assertNotEqual(changed['cells']['L7'],initial['cells']['L7'])
                self.assertIn('2026-10-20 09:31:00',changed['cells']['A4'])
                self.assertEqual(cell(out,'D7'),4300.)
                self.assertEqual(cell(out,'L7'),changed['cells']['L7'])
                evidence=ROOT/'.deps/numeric_refresh';evidence.mkdir(parents=True,exist_ok=True)
                screenshot=folder/'capture.ps1'
                screenshot.write_text('''param([long]$WindowHandle,[string]$Destination)
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class TestCapture {
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int left,top,right,bottom; }
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out Rect r);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h,IntPtr dc,uint flags);
}
'@
$rect=[TestCapture+Rect]::new();[void][TestCapture]::GetWindowRect([IntPtr]$WindowHandle,[ref]$rect)
$bitmap=[Drawing.Bitmap]::new($rect.right-$rect.left,$rect.bottom-$rect.top)
$graphics=[Drawing.Graphics]::FromImage($bitmap);$dc=$graphics.GetHdc()
try { [void][TestCapture]::PrintWindow([IntPtr]$WindowHandle,$dc,2) } finally { $graphics.ReleaseHdc($dc) }
$bitmap.Save($Destination,[Drawing.Imaging.ImageFormat]::Png);$graphics.Dispose();$bitmap.Dispose()
''',encoding='utf-8-sig')
                subprocess.run(['powershell.exe','-NoProfile','-File',str(screenshot),'-WindowHandle',str(changed['hwnd']),
                    '-Destination',str(evidence/'synthetic-window.png')],check=True,timeout=15,creationflags=0x08000000)
                # The read-only diagnostic independently attaches to this same window.
                from dashboard.numeric_diagnose import sample
                diagnosis=sample(run_path)
                self.assertTrue(diagnosis['cells_match_feed'],diagnosis)
                (evidence/'native-window-test.json').write_text(json.dumps(dict(initial=initial,stable=stable,changed=changed),
                    ensure_ascii=False,indent=2),encoding='utf8')
                # A separate final fault: the same open workbook gets a new value,
                # but an external read handle prevents replacement on Save. Do not
                # attempt to dismiss Excel's own dialogs in production or this test.
                import ctypes
                from ctypes import wintypes
                user32=ctypes.WinDLL('user32',use_last_error=True)
                user32.IsWindowEnabled.argtypes=[wintypes.HWND]
                card['quote']['close']=4400.
                with out.open('rb'):
                    final=publish(fourth)
                    pending=wait(lambda r:r.get('state')=='saving' and r.get('observed',{}).get('cells',[None])[0]==4400.)
                    self.assertEqual(pending['last_save_at'],diagnosis['run']['last_save_at'])
                    end=time.monotonic()+10
                    while user32.IsWindowEnabled(changed['hwnd']) and time.monotonic()<end:time.sleep(.1)
                    self.assertFalse(user32.IsWindowEnabled(changed['hwnd']))
                    blocked=subprocess.run(['powershell.exe','-NoProfile','-File',str(ROOT/'dashboard/excel_numeric/inspect.ps1'),
                        '-RunFile',str(run_path)],capture_output=True,timeout=15,creationflags=0x08000000)
                    blocked=json.loads(blocked.stdout.decode('utf-8-sig'))
                    self.assertFalse(blocked['attached']);self.assertFalse(blocked['window_enabled'])
                (evidence/'save-dialog-test.json').write_text(json.dumps(dict(pending=pending,window=blocked),ensure_ascii=False,indent=2),encoding='utf8')
                # Only this test-owned process, with only synthetic data, is ended.
                # A human should handle a production dialog; no automatic recovery is claimed.
                import signal
                process.terminate()
                try:os.kill(changed['excel_pid'],signal.SIGTERM)
                except OSError:pass
            finally:
                if run_path:(run_path.parent/'stop').write_text('stop',encoding='utf8')
                try:stdout,stderr=process.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    process.terminate();stdout,stderr=process.communicate(timeout=10)
                    if run_path:
                        r=json.loads(run_path.read_text(encoding='utf8'))
                        if Path(r['output'])==out and r.get('excel_pid'):
                            import signal
                            try:os.kill(r['excel_pid'],signal.SIGTERM)
                            except OSError:pass
                end=time.monotonic()+10
                # Excel also creates randomly named replacement files during a
                # failed Save. Wait for all files in THIS temporary test folder.
                while True:
                    try:
                        for candidate in folder.iterdir():
                            if candidate.is_file():candidate.unlink()
                        break
                    except PermissionError:
                        if time.monotonic()>=end:raise
                        time.sleep(.1)
            self.assertIsNotNone(process.returncode)

    def test_default_launcher_shows_real_window_before_calculation_finishes(self):
        import ctypes
        from ctypes import wintypes
        import uuid
        user32=ctypes.WinDLL('user32',use_last_error=True)
        callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
        user32.IsWindowVisible.argtypes=[wintypes.HWND]
        user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);feed=folder/'feed.json';out=folder/('visibility_'+uuid.uuid4().hex+'.xlsx')
            payload=dict(schema_version=1,generated_at='2026-10-20T01:00:00Z',mode='首次计算中',
                         ready=False,headers=HEADERS,sheets={s:[] for s in HEADERS})
            save_snapshot(payload,feed)
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'dashboard/excel_numeric/live.ps1'),
                     '-FeedFile',str(feed),'-Output',str(out),'-MaxUpdates','1']
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            try:
                visible=[]
                @callback_type
                def inspect_window(hwnd, _):
                    title=ctypes.create_unicode_buffer(1024)
                    user32.GetWindowTextW(hwnd,title,len(title))
                    if out.stem in title.value and user32.IsWindowVisible(hwnd):visible.append(title.value)
                    return True
                end=time.monotonic()+45
                while time.monotonic()<end:
                    user32.EnumWindows(inspect_window,0)
                    if visible:break
                    if process.poll() is not None:self.fail(process.communicate()[1].decode(errors='replace'))
                    time.sleep(.2)
                else:self.fail('default launcher did not show a visible native workbook window')
                self.assertFalse(payload['ready'],'window must appear before calculation finishes')
                payload.update(ready=True,generated_at='2026-10-20T01:00:03Z',mode='已完成')
                payload['sheets']['数字看板']=[['IF','IF00.CFE','SYNTHETIC',1234.,4200.,None,32,None,None,0.,'测试',46000.,'SYNTHETIC','合成验证']]
                save_snapshot(payload,feed)
                stdout,stderr=process.communicate(timeout=40)
                self.assertEqual(process.returncode,0,stderr.decode(errors='replace'))
                self.assert_ready_notices(stdout)
                self.assertEqual(cell(out,'D7'),1234.)
                # Excel can release the file lock just after PowerShell exits.
                end=time.monotonic()+10
                while True:
                    try:out.unlink();break
                    except PermissionError:
                        if time.monotonic()>=end:raise
                        time.sleep(.1)
            finally:
                if process.poll() is None:
                    # Allow the launcher's own finally block to close its Excel.
                    payload.update(ready=True,generated_at='2026-10-20T01:00:06Z')
                    save_snapshot(payload,feed)
                    try:process.communicate(timeout=15)
                    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)

    def assert_ready_notices(self, stdout):
        # Windows PowerShell uses the machine code page when stdout is piped.
        for encoding in ('utf-8', 'gb18030'):
            ready='完整计算结果已就绪'.encode(encoding)
            saved='Excel 首次写入成功'.encode(encoding)
            if ready in stdout:
                self.assertEqual(stdout.count(ready),1)
                self.assertEqual(stdout.count(saved),1)
                self.assertLess(stdout.index(ready),stdout.index(saved))
                return
        self.fail('missing calculation/Excel-save completion notices: '+repr(stdout))

    def test_once_waits_for_complete_feed_after_opening_loading_workbook(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);feed=folder/'feed.json';out=folder/'loading.xlsx'
            payload=dict(schema_version=1,generated_at='2026-10-19T07:00:00Z',mode='首次计算中',
                         ready=False,headers=HEADERS,sheets={s:[] for s in HEADERS})
            save_snapshot(payload,feed)
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'dashboard/excel_numeric/live.ps1'),
                     '-FeedFile',str(feed),'-Output',str(out),'-Hidden','-Once']
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            try:
                end=time.monotonic()+45
                while time.monotonic()<end:
                    if out.exists():break
                    if process.poll() is not None:self.fail(process.communicate()[1].decode(errors='replace'))
                    time.sleep(.2)
                else:self.fail('loading workbook was not opened')
                time.sleep(2)
                self.assertIsNone(process.poll(),'Once exited while the feed was incomplete')
                payload.update(ready=True,generated_at='2026-10-19T07:00:03Z',mode='已完成')
                payload['sheets']['数字看板']=[['IF','IF00.CFE','SYNTHETIC',1234.,4200.,None,32,None,None,0.,'测试',46000.,'SYNTHETIC','合成验证']]
                save_snapshot(payload,feed)
                stdout,stderr=process.communicate(timeout=40)
                self.assertEqual(process.returncode,0,stderr.decode(errors='replace'))
                self.assertIn(b'updates: 1',stdout);self.assertEqual(cell(out,'D7'),1234.)
                self.assert_ready_notices(stdout)
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=10)

    def test_two_updates_clear_missing_and_keep_zero_and_no_charts(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);feed=folder/'feed.json';out=folder/'live.xlsx'
            sheets={s:[] for s in HEADERS}
            sheets['数字看板']=[['IF','IF00.CFE','SYNTHETIC',1234.,4200.,None,32,None,None,0.,'测试',46000.,'SYNTHETIC','合成验证，无公司行情']]
            payload=dict(schema_version=1,generated_at='2026-10-19T07:00:00Z',mode='合成验证',headers=HEADERS,sheets=sheets)
            save_snapshot(payload,feed)
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'dashboard/excel_numeric/live.ps1'),
                     '-FeedFile',str(feed),'-Output',str(out),'-Hidden','-MaxUpdates','2']
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            try:
                end=time.monotonic()+45
                while time.monotonic()<end:
                    try:
                        if cell(out,'D7')==1234.:break
                    except (OSError,zipfile.BadZipFile,KeyError,ET.ParseError):pass
                    if process.poll() is not None:self.fail(process.communicate()[1].decode(errors='replace'))
                    time.sleep(.2)
                else:self.fail('first update was not saved')
                payload['generated_at']='2026-10-19T07:00:03Z'
                sheets['数字看板'][0][3]=2345.
                sheets['数字看板'][0][4]=None
                save_snapshot(payload,feed)
                stdout,stderr=process.communicate(timeout=30)
                self.assertEqual(process.returncode,0,stderr.decode(errors='replace'))
                self.assertIn(b'updates: 2',stdout)
                self.assert_ready_notices(stdout)
                self.assertEqual(cell(out,'D7'),2345.)
                self.assertIsNone(cell(out,'E7'))
                self.assertEqual(cell(out,'J7'),0.)
                with zipfile.ZipFile(out) as z:
                    self.assertFalse(any(n.startswith('xl/charts/') for n in z.namelist()))
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=10)


if __name__=='__main__':unittest.main()
