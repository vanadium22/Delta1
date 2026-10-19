import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from dashboard import data_package as dp
from dashboard.marketdata.bars import BarDataset,_atomic_bytes,_json_bytes
from datetime import date
import pandas as pd

def bar(symbol='000300.SH',freq='1m',day='2026-10-16',minute=571,**updates):
    return dict(instrument_id=symbol,source_symbol=symbol,frequency=freq,trade_date=date.fromisoformat(day),
        event_time=pd.Timestamp(day,tz='Asia/Shanghai')+pd.Timedelta(minutes=900 if freq=='1d' else minute),
        recorded_at=pd.Timestamp('2026-10-19T02:00Z'),available_at=None,is_final=True,revision=0,quality_flags=8,
        open=4000.,high=4001.,low=3999.,close=4000.,volume=10.,turnover=40000.,**updates)





class DataPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.local=self.root/'local';self.local.mkdir()
        self.store=BarDataset.create(self.root/'source',dict(dataset_id='indexes',source_id='test',series_kind='concrete',
            price_adjustment='none',volume_unit='contracts',availability_policy='unknown',
            instruments={'000300.SH':dict(asset_type='cn_index',market_region='CN')}))
        self.store.commit([bar()])
        ref=self.root/'reference.json';ref.write_text('{"contracts":[]}',encoding='utf8')
        div=self.root/'dividends';div.mkdir();(div/'forecast.xlsx').write_bytes(b'fixture')
        self.config=dict(history_roots=[str(self.store.root)],reference_file=str(ref),dividend_root=str(div))
        (self.local/'native.json').write_text(json.dumps(self.config),encoding='utf8')
        self.archive=self.root/'bundle.zip';dp.export_package(self.local,self.archive)
        self.destination=self.root/'company-data';self.destination.mkdir()
        self.wind=self.destination/'wind'/'history.bin';self.wind.parent.mkdir();self.wind.write_bytes(b'company Wind data')

    def test_install_rebase_read_and_preserve_company_files(self):
        first=dp.install_package(self.archive,self.destination)
        second=dp.install_package(self.archive,self.destination)
        self.assertGreater(first['written'],0);self.assertEqual(second['written'],0)
        self.assertEqual(self.wind.read_bytes(),b'company Wind data')
        company=self.root/'company-local';company.mkdir()
        config={'history_connection_file':'private.local.json','dividend_root':self.config['dividend_root']}
        value=dp.activate_config(config,company,self.destination)
        self.assertEqual(value['history_connection_file'],'private.local.json')
        self.assertEqual(value['dividend_root'],config['dividend_root'])
        store=BarDataset(value['history_roots'][0]);rows=store._rows(store.snapshot())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['close'],4000)
        self.assertNotIn(str(self.store.root),json.dumps(value))
        self.assertEqual(dp.activate_config(value,company,self.destination),value)

    def test_numeric_copy_activation_never_rewrites_original_config_or_wind(self):
        from dashboard.numeric_config import prepare_config
        from dashboard.native.model import NativeModel
        dp.install_package(self.archive,self.destination)
        module=self.root/'module';original=module/'localsetting/native.json'
        original.parent.mkdir(parents=True)
        raw=b'{"history_roots":[],"company_only":"synthetic"}'
        original.write_bytes(raw)
        local=prepare_config(module_root=module)
        with patch('dashboard.marketdata.paths.DATA_ROOT',self.destination):
            model=NativeModel(local)
        self.addCleanup(model.close)
        self.assertTrue(model.config['history_roots'])
        self.assertEqual(model.config['company_only'],'synthetic')
        self.assertEqual(original.read_bytes(),raw)
        self.assertEqual(self.wind.read_bytes(),b'company Wind data')
        self.assertNotEqual((local/'native.json').read_bytes(),raw)

    def test_conflict_rejects_before_activation(self):
        with zipfile.ZipFile(self.archive) as archive:
            meta=dp.inspect_archive(archive)
        name=next(n for n in meta['files'] if n.endswith('.parquet'))
        target=self.destination/name.removeprefix('data/');target.parent.mkdir(parents=True);target.write_bytes(b'company original')
        with self.assertRaises(ValueError):dp.install_package(self.archive,self.destination)
        self.assertFalse((self.destination/dp.ACTIVE).exists())
        self.assertEqual(target.read_bytes(),b'company original')

    def test_source_discrepancy_notes_travel_with_package(self):
        from dashboard.marketdata.history_publication import maintenance_root
        notes={'schema':'history_source_notes_v1','entries':[{'symbol':'000300.SH','frequency':'1m','day':'2026-10-16','policy':'preserve_existing_fill_missing_only'}]}
        _atomic_bytes(maintenance_root(self.config['history_roots'])/'quality_notes.json',_json_bytes(notes))
        dp.export_package(self.local,self.archive);dp.install_package(self.archive,self.destination)
        value=dp.activate_config({},self.root/'company-local',self.destination)
        self.assertEqual(json.loads(Path(value['history_quality_notes']).read_text(encoding='utf8')),notes)

    def test_rejects_wind_path_and_checksum_tampering(self):
        with zipfile.ZipFile(self.archive) as archive:entries={n:archive.read(n) for n in archive.namelist()}
        metadata=json.loads(entries['PACKAGE.json']);name='data/wind/history.bin'
        entries[name]=b'bad';metadata['files'][name]=dict(size=3,sha256=dp.digest(b'bad'))
        entries['PACKAGE.json']=_json_bytes(metadata)
        bad=self.root/'bad.zip'
        with zipfile.ZipFile(bad,'w') as archive:
            for n,raw in entries.items():archive.writestr(n,raw)
        with self.assertRaises(ValueError):dp.install_package(bad,self.destination)
        self.assertEqual(self.wind.read_bytes(),b'company Wind data')

    def test_atomic_transient_sharing_and_permanent_failure(self):
        import os
        target=self.root/'state.json';target.write_bytes(b'old')
        replace=os.replace
        with patch('dashboard.marketdata.bars.os.replace',side_effect=[PermissionError(),PermissionError(),None]) as mocked,\
             patch('dashboard.marketdata.bars.time.sleep'):
            if os.name=='nt':
                _atomic_bytes(target,b'new');self.assertEqual(mocked.call_count,3)
        with patch('dashboard.marketdata.bars.os.replace',side_effect=PermissionError()),\
             patch('dashboard.marketdata.bars.time.sleep'):
            with self.assertRaises(PermissionError):_atomic_bytes(target,b'new')
        self.assertEqual(target.read_bytes(),b'old');self.assertFalse(list(self.root.glob('*.tmp')))
        _atomic_bytes(target,b'new');self.assertEqual(target.read_bytes(),b'new')


if __name__=='__main__':unittest.main()
