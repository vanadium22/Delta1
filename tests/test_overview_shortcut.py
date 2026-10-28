"""Real Windows shortcut generation in an isolated desktop, without launching UI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt','Windows COM shortcuts')
class OverviewShortcutTests(unittest.TestCase):
    def run_script(self, arguments):
        return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',*arguments],
            capture_output=True,text=True,encoding='utf8',errors='replace',timeout=20,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=ROOT)

    def inspect(self,root,path,*,other=False):
        script=root/'inspect.ps1'
        script.write_text('''param([string]$Path,[switch]$Other)
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$shell=New-Object -ComObject WScript.Shell
$item=$shell.CreateShortcut($Path)
if ($Other) { $item.TargetPath=Join-Path $env:SystemRoot 'System32/notepad.exe';$item.Arguments='';$item.Description='Other application';$item.Save() }
[pscustomobject]@{target=$item.TargetPath;arguments=$item.Arguments;working=$item.WorkingDirectory;icon=$item.IconLocation;description=$item.Description}|ConvertTo-Json -Compress
[void][Runtime.InteropServices.Marshal]::ReleaseComObject($item)
[void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
''',encoding='utf-8-sig')
        result=self.run_script(['-File',str(script),'-Path',str(path),*(['-Other'] if other else [])])
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return json.loads(result.stdout)

    def test_generate_update_preserve_localroot_and_verify_new_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);desktop=root/'桌面 with space';config=root/'配置 with space';config.mkdir()
            args=['-File',str(ROOT/'dashboard/create_desktop_shortcut.ps1'),'-OutputDirectory',str(desktop),'-LocalRoot',str(config),'-NoPause']
            result=self.run_script(args);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            shortcut=desktop/'Delta1 股指看板.lnk';self.assertTrue(shortcut.is_file())
            original=self.inspect(root,shortcut)
            self.assertIn('wscript.exe',original['target'].lower())
            self.assertIn('--theme "public"',original['arguments']);self.assertIn(str(config),original['arguments'])
            self.assertEqual(original['icon'],str(ROOT/'dashboard/assets/company_overview.ico')+',0')
            second=self.run_script(['-File',str(ROOT/'dashboard/create_desktop_shortcut.ps1'),'-OutputDirectory',str(desktop),'-NoPause'])
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertEqual(self.inspect(root,shortcut)['arguments'],original['arguments'])
            self.assertEqual([p.name for p in desktop.glob('*.lnk')],['Delta1 股指看板.lnk'])

    def test_unrelated_existing_shortcut_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);desktop=root/'desktop'
            args=['-File',str(ROOT/'dashboard/create_desktop_shortcut.ps1'),'-OutputDirectory',str(desktop),'-NoPause']
            result=self.run_script(args);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            shortcut=desktop/'Delta1 股指看板.lnk';self.inspect(root,shortcut,other=True)
            before=hashlib.sha256(shortcut.read_bytes()).hexdigest()
            refused=self.run_script(args);self.assertEqual(refused.returncode,2)
            self.assertEqual(hashlib.sha256(shortcut.read_bytes()).hexdigest(),before)

    def test_icon_contains_required_sizes(self):
        with Image.open(ROOT/'dashboard/assets/company_overview.ico') as image:
            self.assertTrue({(16,16),(32,32),(48,48),(256,256)} <= image.ico.sizes())


if __name__=='__main__':unittest.main()
