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
                self.assertEqual(cell(out,'D7'),2345.)
                self.assertIsNone(cell(out,'E7'))
                self.assertEqual(cell(out,'J7'),0.)
                with zipfile.ZipFile(out) as z:
                    self.assertFalse(any(n.startswith('xl/charts/') for n in z.namelist()))
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=10)


if __name__=='__main__':unittest.main()
