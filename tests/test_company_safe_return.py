"""Exercise the actual offline PowerShell packer against isolated fake reports."""
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


SCRIPT=Path(__file__).resolve().parents[1]/'dashboard/collect_company_return.ps1'


@unittest.skipUnless(os.name=='nt','Company wrapper uses Windows PowerShell')
class SafeReturnTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.dashboard=self.root/'dashboard';self.dashboard.mkdir()
        self.script=self.dashboard/SCRIPT.name;shutil.copyfile(SCRIPT,self.script)
        self.report=self.root/'retest';self.report.mkdir();self.profile=self.root/'profile'
        self.started=datetime.now(timezone.utc)-timedelta(hours=1)
        self.at=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        self.write(self.report/'git.json',dict(Commit='a'*40,StartedAt=self.started.isoformat()))
        self.write(self.report/'drive_y.json',dict(Mapped=True))

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf8')

    def diagnosis(self,name,*,closed=False,run='run-1/status.json',base=None,commit=None,stage=None,profile=None):
        folder=(base or self.report)/name
        self.write(folder/'diagnosis.json',dict(at=self.at,commit=commit or 'a'*40,
            local_root=str(profile or self.profile),wind_stage=stage))
        self.write(folder/'preflight.json',dict(ok=True))
        if stage:self.write(folder/'wind.json',dict(ok=True))
        else:
            self.write(folder/'overview.json',dict(diagnostic_profile=dict(local_root=str(profile or self.profile)),
                app_reports=dict(matching_profile=[dict(report_path=run,observed_at=self.at,
                    collection_worker_running=not closed,closing=closed,phase='closed' if closed else 'collecting',
                    shutdown=dict(complete=closed))])))
        return folder

    def pack(self,mode='runtime'):
        env=dict(os.environ);env['TEMP']=str(self.root);env['TMP']=str(self.root)
        result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
            '-File',str(self.script),'-ReportDirectory',str(self.report),'-LocalRoot',str(self.profile),'-RunMode',mode],
            capture_output=True,env=env,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        archives=list(self.root.glob('retest_safe_*.zip'));self.assertEqual(len(archives),1)
        with zipfile.ZipFile(archives[0]) as archive:
            files=[n for n in archive.namelist() if not n.endswith('/')]
            self.assertTrue(all(n.endswith('.json') for n in files))
            self.assertFalse(any('native.json' in n or '.log' in n or '.xlsx' in n for n in files))
            values={n:json.loads(archive.read(n).decode('utf-8-sig')) for n in files}
        return next(v for n,v in values.items() if n.endswith('/return_manifest.json')),values

    def test_complete_explicit_runtime_reports_and_no_private_files(self):
        first=self.diagnosis('diagnosis-open');self.diagnosis('diagnosis-closed',closed=True)
        self.write(self.report/'native.json',dict(password='CANARY_SECRET'))
        (first/'overview.stderr.log').write_text('CANARY_RAW_ERROR')
        manifest,values=self.pack()
        self.assertTrue(manifest['Complete']);self.assertEqual(manifest['MissingReports'],[])
        self.assertEqual(len(values),9);self.assertNotIn('CANARY',json.dumps(values))

    def test_metadata_only_package_is_created_with_explicit_missing_evidence(self):
        manifest,values=self.pack()
        self.assertFalse(manifest['Complete']);self.assertEqual(len(values),3)
        self.assertIn('Overview report absent',manifest['MissingReports'])
        self.assertIn('same-run open and completed shutdown reports absent',manifest['MissingReports'])

    def test_two_different_app_runs_cannot_pass_shutdown_acceptance(self):
        self.diagnosis('diagnosis-open');self.diagnosis('diagnosis-closed',closed=True,run='different/status.json')
        manifest,_=self.pack()
        self.assertFalse(manifest['Complete']);self.assertEqual(len(manifest['MissingReports']),1)

    def test_other_commit_or_other_profile_cannot_pass(self):
        self.diagnosis('diagnosis-open',commit='b'*40)
        self.diagnosis('diagnosis-closed',closed=True,profile=self.root/'other-profile')
        manifest,_=self.pack()
        self.assertFalse(manifest['Complete'])
        self.assertTrue(any('commit mismatch' in s for s in manifest['MissingReports']))
        self.assertTrue(any('profile mismatch' in s for s in manifest['MissingReports']))

    def test_legacy_reports_are_recovered_by_recorded_time_despite_old_directory_clock(self):
        legacy=self.dashboard/'runtime/app_startup'
        first=self.diagnosis('diagnosis-legacy-open',base=legacy)
        self.diagnosis('diagnosis-legacy-closed',closed=True,base=legacy)
        old=self.diagnosis('diagnosis-obsolete',base=legacy)
        self.write(old/'diagnosis.json',dict(at=(self.started-timedelta(days=1)).isoformat(),commit='a'*40))
        env=dict(os.environ,DELTA_FIXTURE_DIR=str(first))
        changed=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
            "(Get-Item -LiteralPath $env:DELTA_FIXTURE_DIR).CreationTime=[datetime]'2020-01-01'"],
            env=env,capture_output=True,timeout=20)
        self.assertEqual(changed.returncode,0)
        manifest,values=self.pack()
        self.assertTrue(manifest['Complete']);self.assertEqual(len(manifest['DiagnosisReports']),2)
        self.assertFalse(any('obsolete' in n for n in values))

    def test_full_mode_requires_all_stages_as_well_as_same_run_shutdown(self):
        for name in ('dividend_before','dividend_share','dividend_import','dividend_after','etf_local','etf_capabilities'):
            self.write(self.report/(name+'.json'),dict(ok=True))
        for stage in ('Connect','Indices','ETFs','Nav'):self.diagnosis('diagnosis-'+stage,stage=stage)
        self.diagnosis('diagnosis-open');self.diagnosis('diagnosis-closed',closed=True)
        manifest,_=self.pack('full')
        self.assertTrue(manifest['Complete']);self.assertEqual(manifest['RunMode'],'full')


if __name__=='__main__':unittest.main()
