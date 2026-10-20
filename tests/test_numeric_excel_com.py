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
