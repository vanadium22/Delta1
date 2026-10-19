import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

from dashboard.marketdata.bars import BarDataset, _row_key
from dashboard.marketdata.history_backfill import clone_history, map_rows, missing_only, local_destination, read_matrix
from dashboard.marketdata.history_remote import gap_plan, repair


class BackfillTests(unittest.TestCase):
    def row(self, **kwargs):
        return dict(instrument_id='IF2610.CFE',source_symbol='IF2610.CFE',frequency='1m',
                    event_time=pd.Timestamp('2026-10-15T01:31Z'),trade_date=pd.Timestamp('2026-10-15').date(),
                    recorded_at=pd.Timestamp('2026-10-19T01:00Z'),available_at=None,is_final=True,
                    revision=0,quality_flags=8,close=4000.,**kwargs)

    def store(self,path):
        store=BarDataset.create(path,dict(dataset_id='base',source_id='test',series_kind='concrete',
            price_adjustment='none',volume_unit='contracts',availability_policy='unknown',
            instruments={'IF2610.CFE':dict(asset_type='cn_index_future',market_region='CN')}))
        store.commit([self.row()]);return store

    def test_copy_preserves_source_and_old_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=self.store(Path(tmp)/'base');old=base.snapshot()
            part=base._path(old['parts'][0]['path']);before=hashlib.sha256(part.read_bytes()).hexdigest()
            copy=clone_history(base.root,Path(tmp)/'copy')
            self.assertNotEqual(copy.descriptor['dataset_id'],base.descriptor['dataset_id'])
            row=self.row();row['event_time']+=pd.Timedelta(minutes=1)
            copy.commit([row])
            self.assertEqual(len(base._rows(base.snapshot())),1)
            self.assertEqual(len(copy._rows(copy.snapshot())),2)
            self.assertEqual(base.snapshot()['version'],old['version'])
            self.assertEqual(hashlib.sha256(part.read_bytes()).hexdigest(),before)

    def test_idempotent_fill_retains_conflicts_and_revisions(self):
        row=self.row();existing={_row_key(row):row}
        different={**row,'close':4100.}
        new={**row,'event_time':row['event_time']+pd.Timedelta(minutes=1)}
        chosen,report=missing_only([row,different,new,new],existing)
        self.assertEqual(chosen,[new]);self.assertEqual(report['conflicts_retained'],1)
        self.assertEqual(existing[_row_key(row)]['close'],4000.)
        self.assertFalse(missing_only([row,new],existing)[0])

    def test_same_day_mapping_and_session_filter_no_forward_fill(self):
        index=pd.DatetimeIndex(['2026-10-15 09:30','2026-10-15 09:31','2026-10-16 09:31','2026-10-19 09:31'])
        frames={'close':pd.DataFrame({'IF.CFE':[4000.,4001.,4002.,4100.]},index=index)}
        mapping=pd.DataFrame({'IF.CFE':['IF2610.CFE','IF2611.CFE']},index=pd.to_datetime(['2026-10-15','2026-10-19']))
        metadata={'IF2610.CFE':dict(listing_date='2026-08-24',expiry_date='2026-10-16'),
                  'IF2611.CFE':dict(listing_date='2026-09-21',expiry_date='2026-11-20')}
        rows,skipped=map_rows(frames,mapping,metadata,'1m',pd.Timestamp('2026-10-20T00:00Z'),start='2026-10-15',end='2026-10-19')
        self.assertEqual([r['instrument_id'] for r in rows],['IF2610.CFE','IF2611.CFE'])
        self.assertEqual(skipped['opening_or_outside_session'],1)
        self.assertEqual(skipped['unknown_contract_or_outside_listing'],1)
        self.assertIsNone(rows[0]['volume'])
        mapping.loc[pd.Timestamp('2026-10-15'),'IF.CFE']='IC2610.CFE'
        metadata['IC2610.CFE']=metadata['IF2610.CFE']
        rows,_=map_rows(frames,mapping,metadata,'1m',pd.Timestamp('2026-10-20T00:00Z'),start='2026-10-15',end='2026-10-15')
        self.assertFalse(rows)

    def test_source_matrix_date_objects_are_read_only_and_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.pkl';archive=Path(tmp)/'archive';archive.mkdir()
            pd.DataFrame({'IF.CFE':['IF2610.CFE']},index=[pd.Timestamp('2026-10-15').date()]).to_pickle(path)
            before=path.read_bytes();evidence=[]
            frame=read_matrix(path,archive,evidence)
            self.assertEqual(path.read_bytes(),before)
            self.assertIsInstance(frame.index,pd.DatetimeIndex)
            self.assertTrue(Path(evidence[0]['local_subset']).exists())

    def test_output_guard_rejects_source_and_nonproject_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('dashboard.marketdata.history_backfill.DATA_ROOT',root/'data'):
                self.assertEqual(local_destination(root/'data/target',root/'source'),root/'data/target')
                with self.assertRaises(ValueError):local_destination(root/'source/target',root/'source')

    def test_gap_plan_uses_observed_days_and_listing_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=self.store(Path(tmp)/'base')
            meta={'IF2610.CFE':dict(listing_date='2026-08-24',expiry_date='2026-10-16'),
                  'IF2706.CFE':dict(listing_date='2026-10-19',expiry_date='2027-06-18')}
            jobs=gap_plan({'cn_index_future':store},meta,['2026-10-15'],'2026-10-01','2026-10-18')
            self.assertFalse(any(j['symbol']=='IF2706.CFE' for j in jobs))
            self.assertEqual(next(j for j in jobs if j['symbol']=='IF2610.CFE' and j['frequency']=='1m')['observed'],1)

    def test_database_unavailable_does_not_invoke_vpn_or_change_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=self.store(Path(tmp)/'base');version=store.snapshot()['version']
            config=Path(tmp)/'connection.json';config.write_text(json.dumps(dict(host='localhost',port=1)))
            with patch('index_strategy.history.downloader.DEFAULT_CONFIG',config),patch('socket.create_connection',side_effect=TimeoutError('unreachable')),patch('index_strategy.history.downloader.Client.__init__') as constructor:
                result=repair({'cn_index_future':store},{},Path(tmp)/'out','2026-10-01','2026-10-18')
            self.assertEqual(result['state'],'unavailable');constructor.assert_not_called()
            self.assertEqual(store.snapshot()['version'],version)

    def test_native_remote_rows_are_local_and_missing_only(self):
        import pandas.core.arrays.arrow.extension_types  # Register before sys.modules is patched.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);future=self.store(root/'future')
            index=BarDataset.create(root/'index',dict(dataset_id='indices',source_id='test',series_kind='concrete',
                price_adjustment='none',volume_unit='source_aggregate_not_futures_contracts',availability_policy='unknown',
                instruments={s:dict(asset_type='cn_index',market_region='CN') for s in ('000300.SH','000016.SH','000905.SH','000852.SH')}))
            config=root/'connection.json';config.write_text(json.dumps(dict(host='localhost',port=1,username='test')))
            def fetch(source,symbol,day,request):
                stamp=pd.Timestamp(day)+(pd.Timedelta(hours=9,minutes=31) if request['frequency']=='1m' else pd.Timedelta(0))
                return pd.DataFrame([dict(trading_date=pd.Timestamp(day),timestamp=stamp,open=4100.,high=4100.,low=4100.,close=4100.,volume=2.,amount=3.,oi=4.)]),dict(units={'volume':'手','amount':'元'})
            metadata={'IF2610.CFE':dict(listing_date='2026-08-24',expiry_date='2026-10-16')}
            with patch('index_strategy.history.downloader.DEFAULT_CONFIG',config),patch('socket.create_connection'),patch.dict('sys.modules',{'dolphindb':MagicMock()}),patch('index_strategy.history.downloader.Client.available_dates',return_value=[pd.Timestamp('2026-10-15').date()]),patch('index_strategy.history.downloader.Client.fetch',side_effect=fetch):
                result=repair({'cn_index_future':future,'cn_index':index},metadata,root/'out','2026-10-15','2026-10-15')
            self.assertEqual(result['inserted'],9)
            self.assertEqual(result['datasets']['cn_index_future']['conflicts_retained'],1)
            original=[r for r in future._rows(future.snapshot()) if r['frequency']=='1m'][0]
            self.assertEqual(original['close'],4000.)


if __name__=='__main__':unittest.main()
