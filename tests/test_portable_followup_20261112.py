"""Term-curve retention and portable, credential-free setup behavior."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import pandas as pd

from dashboard.native.bootstrap import configure_qt
configure_qt()
from dashboard.marketdata.overview_display_cache import preserve
from dashboard.marketdata.overview_dividends import DEFAULT_SOURCE,MAPPED_DEFAULT_SOURCE,source_directory
from dashboard.native.overview_charts import ProductCharts
from dashboard.native.futures_overview_view import FuturesOverviewPage
from dashboard.native.term_curve import points
from dashboard import python_environment as pyenv
from dashboard.vpn_profile_settings import prepare as prepare_vpn,metadata as vpn_metadata
from tests.test_market_overview_ui import APP,state
from tests.test_market_overview import NOW


class TermCurveTests(unittest.TestCase):
    def payload(self):
        market=state()['market_overview']
        rows=deepcopy([r for r in market['futures'] if r['root']=='IH'])
        for r in rows:
            r['basis_future_source_at']=(NOW-pd.Timedelta(seconds=8)).isoformat()
            r['basis_spot_source_at']=(NOW-pd.Timedelta(seconds=8)).isoformat()
            r['basis_source_at']=(NOW-pd.Timedelta(seconds=8)).isoformat()
        return market,rows

    def test_both_charts_keep_last_complete_same_contract_then_refresh(self):
        market,rows=self.payload()
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True)
            first=dict(futures=deepcopy(rows),indices=[],etfs=[],index_details={},etf_groups={})
            preserve(model,first,NOW)
            current=deepcopy(rows)
            for r in current:
                r['basis_future_source_at']=NOW.isoformat();r['basis_spot_source_at']=NOW.isoformat();r['basis_source_at']=NOW.isoformat()
            current[1].update(annual_pct=None,basis_points=None)
            current[2].update(annual_pct=None,basis_points=None)
            payload=dict(futures=current,indices=[],etfs=[],index_details={},etf_groups={})
            preserve(model,payload,NOW+pd.Timedelta(seconds=1))
            chart=ProductCharts('IH','上证50');page=FuturesOverviewPage()
            try:
                chart.render(payload['futures'],market['futures_details']['IH'])
                page.render(payload['futures'],market['indices'],market['futures_details']);page.select('IH')
                for displayed in (chart.curve_points,page.curve_points):
                    self.assertEqual([p['slot'] for p in displayed],[0,1,2,3])
                    self.assertEqual([p['slot'] for p in displayed if p['saved']],[1,2])
                self.assertFalse(page.curve.listDataItems()[0].curve.getPath().isEmpty())
                self.assertIn('沿用 2',chart.term_note.text());self.assertIn('混合时点',chart.term_note.text())
                self.assertIn('沿用',chart.curve.toolTip());self.assertIn('沿用 2',page.term.note.text())
                updated=deepcopy(rows)
                for r in updated:
                    r['basis_future_source_at']=NOW.isoformat();r['basis_spot_source_at']=NOW.isoformat();r['basis_source_at']=NOW.isoformat()
                fresh=dict(futures=updated,indices=[],etfs=[],index_details={},etf_groups={})
                preserve(model,fresh,NOW+pd.Timedelta(seconds=2));chart.render(fresh['futures'],{})
                self.assertEqual(len(chart.curve_points),4);self.assertFalse(any(p['saved'] for p in chart.curve_points))
            finally:chart.close();page.close();APP.processEvents()

    def test_cache_requires_same_contract_expiry_valid_pair_and_t_at_least_five(self):
        _,rows=self.payload();row=deepcopy(rows[0]);cached=deepcopy(row);cached['saved']=True
        row.update(annual_pct=None,basis_points=None,basis_display=cached)
        self.assertTrue(points([row])[0]['saved'])
        for mutate in (lambda r:r.update(expiry='2026-11-21'),lambda r:r.update(days=4),
                       lambda r:r['basis_display'].update(symbol='IH_OTHER'),
                       lambda r:r['basis_display'].update(basis_spot_source_at=(NOW-pd.Timedelta(seconds=20)).isoformat())):
            bad=deepcopy(row);mutate(bad);self.assertEqual(points([bad]),[])

    def test_known_near_expiry_days_remain_available_when_current_pair_is_missing(self):
        from dashboard.native.market_overview import futures_values
        _,rows=self.payload();row=rows[0];symbol=row['symbol']
        futures_values(row,{}, {},{symbol:dict(expiry_date='2026-10-29')},NOW)
        self.assertEqual(row['days'],3);self.assertIsNone(row['annual_pct'])


class PathsAndCredentialsTests(unittest.TestCase):
    def test_known_mapped_share_migrates_only_at_runtime(self):
        config={'overview_dividend_source_dir':MAPPED_DEFAULT_SOURCE};before=dict(config)
        self.assertEqual(source_directory(config),DEFAULT_SOURCE);self.assertEqual(config,before)
        self.assertTrue(DEFAULT_SOURCE.startswith(r'\\192.168.91.230\FTPServer'+'\\'))
        self.assertEqual(source_directory({'overview_dividend_source_dir':''}),'')
        self.assertEqual(source_directory({'overview_dividend_source_dir':'Y:/custom'}),'Y:/custom')

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_vpn_credentials_are_local_protected_and_existing_files_untouched(self):
        from index_strategy.history.protected_config import load_config
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'old-vpn.local.json';old.write_bytes(b'existing profile')
            result=prepare_vpn(tmp,'https://vpn.example:10443','A'*64,'fixture-vpn-user','fixture-vpn-password')
            raw=Path(result['history_vpn_config']).read_bytes()
            self.assertNotIn(b'fixture-vpn-user',raw);self.assertNotIn(b'fixture-vpn-password',raw)
            restored=load_config(result['history_vpn_config'])
            self.assertEqual(restored['id'],'fixture-vpn-user');self.assertEqual(restored['password'],'fixture-vpn-password')
            self.assertEqual(vpn_metadata(result['history_vpn_config'],result['history_vpn_trust'])['fingerprint'],'A'*64)
            self.assertEqual(old.read_bytes(),b'existing profile')

    def test_invalid_vpn_gateway_and_certificate_do_not_write_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for gateway,fingerprint in [('http://vpn.example','A'*64),('https://vpn.example','bad')]:
                with self.assertRaises(Exception):prepare_vpn(tmp,gateway,fingerprint,'user','password')
            self.assertEqual(list(Path(tmp).iterdir()),[])

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_settings_save_both_accounts_without_stopping_existing_ddb(self):
        from dashboard.native.inline_settings import InlineSettings
        from index_strategy.history.protected_config import load_config,save_config
        from tests.test_overview_ddb_refresh import SettingsLayoutTests
        helper=SettingsLayoutTests();window,pipeline=helper.fixture();self.addCleanup(helper.doCleanups)
        root=pipeline.model.local_root;old=root/'old-ddb.local.json'
        save_config(old,dict(host='existing.invalid',port=8904,username='old-user',password='old-password'))
        old_bytes=old.read_bytes();pipeline.model.config['history_connection_file']=str(old)
        pipeline.history.process=object();pipeline.readonly=unittest.mock.Mock()
        widget=InlineSettings(pipeline);self.addCleanup(widget.deleteLater)
        widget.fields['username'].setText('new-ddb-user');widget.fields['password'].setText('new-ddb-password')
        widget.save_credentials();new_ddb=Path(pipeline.model.config['history_connection_file'])
        self.assertNotEqual(new_ddb,old);self.assertEqual(old.read_bytes(),old_bytes)
        self.assertEqual(load_config(new_ddb)['username'],'new-ddb-user')
        self.assertNotIn(b'new-ddb-password',new_ddb.read_bytes())
        widget.fields['vpn_gateway'].setText('https://vpn.example:10443');widget.fields['vpn_fingerprint'].setText('A'*64)
        widget.fields['vpn_username'].setText('new-vpn-user');widget.fields['vpn_password'].setText('new-vpn-password')
        widget.save_vpn();vpn=Path(pipeline.model.config['history_vpn_config'])
        self.assertEqual(load_config(vpn)['id'],'new-vpn-user');self.assertNotIn(b'new-vpn-password',vpn.read_bytes())
        self.assertEqual(widget.fields['history_vpn_config'].text(),str(vpn));pipeline.readonly.assert_not_called()
        self.assertNotIn('new-vpn-password',json.dumps(pipeline.model.config))

    def test_fresh_profile_uses_its_own_ddb_path(self):
        from dashboard.native.model import NativeModel
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.data_package.activate_config',side_effect=lambda config,*_:config):
            model=NativeModel(tmp)
            try:self.assertEqual(model.config['history_connection_file'],str(Path(tmp)/'ddb.connection.local.json'))
            finally:model.close()

    def test_settings_opens_environment_tool_without_stopping_pipeline(self):
        from dashboard.native.inline_settings import InlineSettings
        from tests.test_overview_ddb_refresh import SettingsLayoutTests
        helper=SettingsLayoutTests();window,pipeline=helper.fixture();self.addCleanup(helper.doCleanups)
        pipeline.readonly=unittest.mock.Mock();widget=InlineSettings(pipeline);self.addCleanup(widget.deleteLater)
        with patch('subprocess.Popen') as child:widget.python_setup()
        self.assertIn('-FromApp',child.call_args.args[0]);pipeline.readonly.assert_not_called()

    def test_moved_local_credentials_rebase_without_changing_custom_paths(self):
        from dashboard.app_config import rebase_local_profiles
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'new'/'app';ddb=root/'ddb_profiles'/('ddb-'+'a'*32+'.local.json')
            vpn=root/'vpn_profiles'/('ddb-vpn-'+'b'*32+'.local.json')
            trust=root/'vpn_profiles'/('ddb-vpn-'+'b'*32+'.trust.local.json')
            for path in (ddb,vpn,trust):path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
            config=dict(history_connection_file=str(Path(tmp)/'old/app/ddb_profiles'/ddb.name),
                        history_vpn_config=str(Path(tmp)/'old/app/vpn_profiles'/vpn.name),
                        history_vpn_trust=str(Path(tmp)/'old/app/vpn_profiles'/trust.name))
            result=rebase_local_profiles(config,root)
            self.assertEqual(result['history_connection_file'],str(ddb.resolve()))
            self.assertEqual(result['history_vpn_config'],str(vpn.resolve()))
            self.assertEqual(result['history_vpn_trust'],str(trust.resolve()))
            custom={**config,'history_connection_file':str(Path(tmp)/'custom.json')}
            self.assertEqual(rebase_local_profiles(custom,root)['history_connection_file'],custom['history_connection_file'])


class PythonEnvironmentTests(unittest.TestCase):
    def test_external_wind_or_history_python_never_inherits_incompatible_overlay(self):
        parent=os.path.abspath('app-python.exe');other=os.path.abspath('wind-python.exe');overlay=os.path.abspath('app-overlay')
        env=dict(DELTA1_APP_PYTHON=parent,DELTA1_APP_OVERLAY=overlay,PYTHONPATH=os.pathsep.join([overlay,'other-user-path']))
        self.assertEqual(pyenv.child_environment(parent,env),env)
        child=pyenv.child_environment(other,env)
        self.assertEqual(child['PYTHONPATH'],'other-user-path');self.assertNotIn('DELTA1_APP_OVERLAY',child)
        self.assertIn(overlay,env['PYTHONPATH'])

    def test_requirement_versions_and_selection_are_local(self):
        self.assertTrue(pyenv.version_matches('2.3.1','>=2.2,<4'))
        self.assertFalse(pyenv.version_matches('4.0.0','>=2.2,<4'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=root/'other'/'python.exe';exe.parent.mkdir();exe.touch()
            with patch.object(sys,'executable',str(exe)):
                result=pyenv.select(root=root)
            choice=json.loads((root/'dashboard/localsetting/app/python.local.json').read_text(encoding='utf8'))
            self.assertEqual(choice['mode'],'external');self.assertEqual(choice['python'],str(exe.resolve()))
            self.assertEqual(result['stage'],'selected')

    def test_unsupported_python_is_reported_without_trying_to_import_packages(self):
        with tempfile.TemporaryDirectory() as tmp,patch('dashboard.python_environment.struct.calcsize',return_value=4),\
             patch('dashboard.python_environment.requirements',side_effect=AssertionError('must not load packages')):
            result=pyenv.probe(root=tmp)
            self.assertFalse(result['ok']);self.assertEqual(result['stage'],'unsupported_python');self.assertEqual(result['packages'],[])

    def test_bundled_overlay_identity_survives_moving_the_package(self):
        first=Path('C:/first-folder');second=Path('D:/second-folder')
        a=pyenv.identity(first/'runtime/python/python.exe',root=first,version='3.13',bits=64)
        b=pyenv.identity(second/'runtime/python/python.exe',root=second,version='3.13',bits=64)
        self.assertEqual(a,b)

    def test_offline_one_click_installs_into_isolated_overlay_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';dashboard=root/'dashboard';wheelhouse=dashboard/'wheelhouse'
            wheelhouse.mkdir(parents=True);(dashboard/'__init__.py').touch()
            shutil.copyfile(Path(pyenv.__file__),dashboard/'python_environment.py')
            (dashboard/'requirements-app.txt').write_text('colorama==99.0.0\n',encoding='utf8')
            dist='colorama-99.0.0.dist-info';files={
                'colorama/__init__.py':b"__version__='99.0.0'\n",
                dist+'/METADATA':b'Metadata-Version: 2.1\nName: colorama\nVersion: 99.0.0\n\n',
                dist+'/WHEEL':b'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n'}
            files[dist+'/RECORD']=''.join(name+',,\n' for name in [*files,dist+'/RECORD']).encode()
            with zipfile.ZipFile(wheelhouse/'colorama-99.0.0-py3-none-any.whl','w') as wheel:
                for name,data in files.items():wheel.writestr(name,data)
            with patch.dict(os.environ,{'PIP_NO_INDEX':'1'}):result=pyenv.install(root=root)
            self.assertTrue(result['ok'],result);self.assertEqual(result['source'],'offline_wheels')
            self.assertEqual(result['check']['packages'][0]['version'],'99.0.0')
            overlay=pyenv.active_overlay(root);self.assertTrue((overlay/'colorama'/'__init__.py').is_file())
            self.assertNotEqual(Path(sys.executable).parent,overlay)

    def test_failed_install_keeps_previous_working_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wheelhouse=root/'dashboard/wheelhouse';wheelhouse.mkdir(parents=True)
            (wheelhouse/'fixture.whl').touch();base=pyenv.overlay_root(root);old='a'*32
            (base/old).mkdir(parents=True);pyenv.atomic_json(base/'current.json',dict(generation=old))
            before=(base/'current.json').read_bytes();failure=SimpleNamespace(returncode=1)
            with patch.object(pyenv,'probe',return_value=dict(compatible=True,ok=False)),\
                 patch.object(pyenv,'_pip_command',return_value=['fixture-python','-m','pip']):
                result=pyenv.install(root=root,runner=unittest.mock.Mock(return_value=failure))
            self.assertFalse(result['ok']);self.assertEqual((base/'current.json').read_bytes(),before)
            self.assertEqual(pyenv.active_overlay(root),base/old)

    @unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Windows PowerShell required')
    def test_launcher_uses_explicit_selection_and_portable_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'dashboard/localsetting/app';profile.mkdir(parents=True)
            selected=root/'selected python/python.exe';selected.parent.mkdir();selected.touch()
            bundled=root/'runtime/python/python.exe';bundled.parent.mkdir(parents=True);bundled.touch()
            script=Path(__file__).resolve().parents[1]/'dashboard/app_python.ps1'
            command=root/'resolve.ps1';command.write_text('param([string]$s,[string]$r)\n. $s\nGet-AppPython $r\n',encoding='ascii')
            def run():
                env={**os.environ,'SWHY_DELTA1_PYTHON':str(root/'legacy.exe')}
                return subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(command),str(script),str(root)],
                    env=env,creationflags=subprocess.CREATE_NO_WINDOW,text=True).strip()
            choice=profile/'python.local.json'
            choice.write_text(json.dumps(dict(schema='dashboard-python-selection-v1',mode='external',python=str(selected))),encoding='utf8')
            self.assertEqual(Path(run()),selected)
            choice.write_text(json.dumps(dict(schema='dashboard-python-selection-v1',mode='bundled')),encoding='utf8')
            self.assertEqual(Path(run()),bundled)

    @unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Windows PowerShell required')
    def test_setup_window_checks_selected_python_without_showing_a_window(self):
        script=Path(__file__).resolve().parents[1]/'dashboard/configure_python.ps1'
        with tempfile.TemporaryDirectory() as tmp:
            env={**os.environ,'TEMP':tmp,'TMP':tmp}
            output=subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                '-File',str(script),'-SelfTest','-TestPython',sys.executable],env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,timeout=70)
            report=json.loads(output.decode('utf-8-sig'))
            self.assertIn('检查环境',report['buttons']);self.assertIn('一键补齐依赖',report['buttons'])
            self.assertIn('pandas',report['result']);self.assertIn('dolphindb',report['result'])
            fake=Path(tmp)/'other-overlay';fake.mkdir();(fake/'colorama.py').write_text("raise RuntimeError('wrong environment')\n")
            env.update(DELTA1_APP_PYTHON=str(Path(tmp)/'other-python.exe'),DELTA1_APP_OVERLAY=str(fake),PYTHONPATH=str(fake))
            clean=subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                '-File',str(script),'-SelfTest','-TestPython',sys.executable],env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,timeout=70)
            actual=json.loads(clean.decode('utf-8-sig'))
            expected=next(line for line in report['result'].splitlines() if line.startswith('colorama：'))
            self.assertIn(expected,actual['result'])


if __name__=='__main__':unittest.main()
