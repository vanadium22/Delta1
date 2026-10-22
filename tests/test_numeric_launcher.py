"""Run the shipped CMD launcher against a hidden, offline PowerShell probe.

Only the two machine-specific existence-check paths are redirected into the
test repository. The CMD selection logic and argument forwarding run unchanged;
the probe never starts Python, Excel, a collector, or a configuration wizard.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'dashboard/start_numeric_excel.cmd'
COMPANY = r'D:\conda\envs\swhy_delta1\python.exe'
LOCAL = r'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe'
PROBE = r'''param([string]$Python,[string]$Output,[string]$LocalRoot,
    [string]$Snapshot,[switch]$ReadOnlyCache,[switch]$Once,[switch]$Hidden,
    [switch]$NoPrompt,[int]$FixtureExit=0)
$ErrorActionPreference='Stop'
$record=@{python=$Python;output=$Output;local_root=$LocalRoot;snapshot=$Snapshot;
    read_only=[bool]$ReadOnlyCache;once=[bool]$Once;hidden=[bool]$Hidden;
    no_prompt=[bool]$NoPrompt;cwd=$PWD.Path}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'invocation.json'),
    ($record | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
exit $FixtureExit
'''


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'),
                     'requires Windows CMD and Windows PowerShell')
class NumericLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = LAUNCHER.read_text(encoding='utf8')
        # Guard the isolation boundary if the production launcher changes.
        for path in (COMPANY, LOCAL):
            if cls.source.count(path) != 2:
                raise AssertionError('Expected one existence check and assignment: ' + path)
        cls.run_root = ROOT / '.deps/numeric_launcher_regression' / uuid.uuid4().hex
        cls.run_root.mkdir(parents=True)
        cls.evidence = dict(source=str(LAUNCHER),
            source_sha256=hashlib.sha256(LAUNCHER.read_bytes()).hexdigest(),
            started_at=datetime.now(timezone.utc).isoformat(),
            hidden_children=True, real_python_or_excel_started=False, cases=[])

    @classmethod
    def tearDownClass(cls):
        cls.evidence['finished_at'] = datetime.now(timezone.utc).isoformat()
        (cls.run_root / 'verification.json').write_text(
            json.dumps(cls.evidence, ensure_ascii=False, indent=2), encoding='utf8')

    def run_launcher(self, available=(), *, override=None, arguments=(), exit_code=0):
        repo = self.run_root / (self._testMethodName + ' repo space 中文 & A')
        live = repo / 'dashboard/excel_numeric/live.ps1'
        live.parent.mkdir(parents=True)
        live.write_text(PROBE, encoding='utf-8-sig')
        isolated = self.source.replace(COMPANY, r'company env\python.exe').replace(
            LOCAL, r'local env\python.exe')
        launcher = repo / 'dashboard/start_numeric_excel.cmd'
        launcher.write_text(isolated, encoding='utf8')
        paths = dict(company=repo / 'company env/python.exe',
                     dedicated=repo / '.venvs/numeric_excel/Scripts/python.exe',
                     generic=repo / '.venv/Scripts/python.exe',
                     local=repo / 'local env/python.exe')
        for kind in available:
            paths[kind].parent.mkdir(parents=True, exist_ok=True)
            paths[kind].write_bytes(b'existence-check-only; never executed')
        caller = repo / 'caller space 中文 & B'
        caller.mkdir()
        environment = os.environ.copy()
        environment.pop('SWHY_DELTA1_PYTHON', None)
        environment['DASHBOARD_PYTHON'] = 'inherited value must not decide selection'
        if override is not None:
            environment['SWHY_DELTA1_PYTHON'] = override
        args = [str(a) for a in arguments]
        if exit_code:
            args += ['-FixtureExit', str(exit_code)]
        # CMD needs its own outer /s /c quotes, not POSIX shell escaping.
        # Every argument is test-owned and quoted, including paths with '&'.
        self.assertTrue(all('"' not in arg and '%' not in arg for arg in args))
        tail = ''.join(' "' + arg + '"' for arg in args)
        comspec = environment.get('COMSPEC', r'C:\Windows\System32\cmd.exe')
        command = '"' + comspec + '" /d /s /c ""' + str(launcher) + '"' + tail + '"'
        result = subprocess.run(command, cwd=caller, env=environment,
            input=b'\r\n', capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        invocation = live.with_name('invocation.json')
        self.assertTrue(invocation.is_file(), result.stderr.decode(errors='replace'))
        record = json.loads(invocation.read_text(encoding='utf8'))
        self.evidence['cases'].append(dict(case=self._testMethodName,
            available=list(available), override=override, returncode=result.returncode,
            invocation=record))
        self.assertEqual(result.returncode, exit_code, result.stderr.decode(errors='replace'))
        self.assertEqual(Path(record['cwd']), repo)
        return record, paths

    def test_explicit_override_precedes_every_environment_even_when_missing(self):
        explicit = str(self.run_root / 'explicit space 中文 & preferred/python.exe')
        record, _ = self.run_launcher(('company', 'dedicated', 'generic', 'local'),
                                      override=explicit)
        self.assertEqual(record['python'], explicit)

    def test_company_precedes_repository_and_local_environments(self):
        record, _ = self.run_launcher(('company', 'dedicated', 'generic', 'local'))
        self.assertEqual(record['python'], r'company env\python.exe')

    def test_dedicated_repository_precedes_generic_and_local(self):
        record, paths = self.run_launcher(('dedicated', 'generic', 'local'))
        self.assertEqual(Path(record['python']), paths['dedicated'])

    def test_generic_repository_precedes_local(self):
        record, paths = self.run_launcher(('generic', 'local'))
        self.assertEqual(Path(record['python']), paths['generic'])

    def test_known_local_environment_precedes_path(self):
        record, _ = self.run_launcher(('local',))
        self.assertEqual(record['python'], r'local env\python.exe')

    def test_path_fallback_when_no_known_environment_exists(self):
        record, _ = self.run_launcher()
        self.assertEqual(record['python'], 'python')

    def test_quoted_paths_and_switches_reach_powershell_unchanged(self):
        folder = self.run_root / 'argument space 中文 & C'
        output = str(folder / '结果 快照 & 1.xlsx')
        settings = str(folder / '隔离 设置 & 2')
        snapshot = str(folder / '冻结 输入 & 3.json')
        record, _ = self.run_launcher(('local',), arguments=(
            '-Output', output, '-LocalRoot', settings, '-Snapshot', snapshot,
            '-ReadOnlyCache', '-Once', '-Hidden', '-NoPrompt'))
        self.assertEqual(record['python'], r'local env\python.exe')
        self.assertEqual((record['output'], record['local_root'], record['snapshot']),
                         (output, settings, snapshot))
        self.assertTrue(all(record[k] for k in ('read_only', 'once', 'hidden', 'no_prompt')))

    def test_child_failure_exit_code_survives_pause_and_popd(self):
        record, _ = self.run_launcher(('local',), exit_code=23)
        self.assertEqual(record['python'], r'local env\python.exe')


if __name__ == '__main__':
    unittest.main()
