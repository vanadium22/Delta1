"""Exercise the actual Windows launcher; stderr must never terminate its child."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Windows PowerShell required')
class AppLauncherTests(unittest.TestCase):
    def fixture(self,preflight_code=0,app_code=0):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)/"中文 space' $literal";dashboard=root/'dashboard';native=dashboard/'native'
        native.mkdir(parents=True)
        source=Path(__file__).resolve().parents[1]/'dashboard'
        for name in ('start_app.ps1','app_python.ps1'):shutil.copyfile(source/name,dashboard/name)
        (dashboard/'__init__.py').touch();(native/'__init__.py').touch()
        (dashboard/'app_check.py').write_text(
            'import sys\nprint("benign preflight warning",file=sys.stderr,flush=True)\n'
            f'raise SystemExit({preflight_code})\n',encoding='utf8')
        (native/'editions_current.py').write_text(
            'import faulthandler,json,sys,time\nfrom pathlib import Path\n'
            'root=Path.cwd()\n(root/"started").write_text("yes")\n'
            'for i in range(5):\n'
            ' print("collector warning "+str(i),file=sys.stderr,flush=True)\n'
            ' print("normal output "+str(i),flush=True)\n'
            ' time.sleep(.05)\n'
            '(root/"completed.json").write_text(json.dumps(dict(argv=sys.argv[1:],fault_handler=faulthandler.is_enabled())))\n'
            f'raise SystemExit({app_code})\n',encoding='utf8')
        return root,dashboard

    def launch(self,dashboard,*arguments):
        env=os.environ.copy();env['SWHY_DELTA1_PYTHON']=sys.executable
        env.pop('PYTHONPATH',None)
        result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-WindowStyle','Hidden',
            '-ExecutionPolicy','Bypass','-File',str(dashboard/'start_app.ps1'),'-Edition','presentation',*arguments],
            env=env,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        runs=list((dashboard/'runtime/app_startup').glob('run-*'))
        self.assertEqual(len(runs),1,result.stderr.decode(errors='replace'))
        report=json.loads((runs[0]/'launcher.json').read_text(encoding='utf-8-sig'))
        return result,runs[0],report

    def test_stderr_does_not_stop_child_and_paths_round_trip(self):
        root,dashboard=self.fixture()
        # Includes whitespace, shell metacharacters and a trailing backslash.
        value=str(root/'配置 path $name')+'\\'
        result,run,report=self.launch(dashboard,'--local-root',value)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        finished=json.loads((root/'completed.json').read_text())
        self.assertEqual(finished['argv'],['--edition','presentation','--local-root',value])
        self.assertTrue(finished['fault_handler'])
        self.assertEqual(report['phase'],'app_exited');self.assertEqual(report['exit_code'],0)
        self.assertIn('benign preflight warning',(run/'preflight.stderr.log').read_text())
        self.assertIn('collector warning 4',next(run.glob('app-*.stderr.log')).read_text())
        self.assertFalse((run/'launcher-error.log').exists())

    def test_preflight_failure_prevents_app_and_preserves_exit_code(self):
        root,dashboard=self.fixture(preflight_code=7)
        result,run,report=self.launch(dashboard)
        self.assertEqual(result.returncode,7);self.assertFalse((root/'started').exists())
        self.assertEqual(report['phase'],'preflight_failed');self.assertEqual(report['exit_code'],7)

    def test_real_child_failure_is_logged_and_not_restarted(self):
        root,dashboard=self.fixture(app_code=23)
        result,run,report=self.launch(dashboard)
        self.assertEqual(result.returncode,23);self.assertTrue((root/'completed.json').is_file())
        self.assertEqual(json.loads((root/'completed.json').read_text())['argv'],['--edition','presentation'])
        self.assertEqual(report['phase'],'app_exited');self.assertEqual(report['exit_code'],23)


if __name__=='__main__':unittest.main()
