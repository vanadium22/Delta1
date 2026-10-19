import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from dashboard import data_package as dp
from dashboard.short_paths import migrate_history, migrate_realtime, short_name
from dashboard.marketdata.bars import BarDataset, _atomic_bytes, _json_bytes
from dashboard.marketdata.history_publication import maintenance_root, read_publication, publish
from index_strategy.instant_dld.short_files import publish_bytes
from index_strategy.instant_dld.realtime_store import RealtimeStore, WriterBusyError
from index_strategy.instant_dld.reader import RealtimeReader
from tests import test_dashboard_data_package as fixtures
from tests.test_dashboard_data_package import bar
from tests.test_realtime_store import batch


class ShortFileTests(unittest.TestCase):
    def test_concurrent_publish_identical_and_distinct_content(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            payloads=[b'one',b'two',b'three']*8
            with ThreadPoolExecutor(max_workers=8) as pool:
                paths=list(pool.map(lambda raw:publish_bytes(raw,root,'2026-10-19'),payloads))
            self.assertEqual(len(set(paths)),3)
            for raw,path in zip(payloads,paths):
                self.assertEqual(path.read_bytes(),raw)
                self.assertTrue(short_name(path.name))
            self.assertFalse(list(root.glob('*.tmp')))

    def test_failed_publication_exposes_no_partial_file(self):
        with TemporaryDirectory() as tmp:
            with patch('index_strategy.instant_dld.short_files._publish',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):publish_bytes(b'data',Path(tmp),'2026-10-19')
            self.assertEqual(list(Path(tmp).iterdir()),[])


class HistoryShortTests(unittest.TestCase):
    setUp=fixtures.DataPackageTests.setUp
    def legacy(self):
        snap=self.store.snapshot();part=snap['parts'][0];old=self.store._path(part['path'])
        long=old.with_name(part['trade_date']+'.'+part['sha256']+'.parquet')
        old.rename(long)
        part['path']=long.relative_to(self.store.root).as_posix()
        raw=_json_bytes(snap)
        _atomic_bytes(self.store.root/'versions'/f"{snap['version']}.json",raw)
        _atomic_bytes(self.store.root/'current.json',_json_bytes(dict(version=snap['version'],
            manifest=f"versions/{snap['version']}.json",sha256=dp.digest(raw))))
        return snap,long

    def test_migration_preserves_pinned_readers_revisions_and_config(self):
        before,old=self.legacy();old_bytes=old.read_bytes();config=(self.local/'native.json').read_bytes()
        result=migrate_history([self.store.root]);self.assertEqual(result['changed'],1)
        self.assertEqual(self.store._rows(before),self.store._rows(self.store.snapshot()))
        self.assertTrue(short_name(Path(self.store.snapshot()['parts'][0]['path']).name))
        self.assertEqual(old.read_bytes(),old_bytes)
        self.assertEqual((self.local/'native.json').read_bytes(),config)
        self.assertEqual(migrate_history([self.store.root])['changed'],0)
        changed=bar();changed.update(revision=1,close=4000.5)
        self.store.commit([changed])
        snap=self.store.snapshot()
        self.assertEqual(len(snap['parts']),2)
        self.assertTrue(all(short_name(Path(p['path']).name) for p in snap['parts']))
        self.assertEqual(self.store.commit([changed])['inserted'],0)
        self.assertEqual(len(self.store._rows(before)),1)

    def test_migration_validates_before_switch_and_can_retry_after_interruption(self):
        before,old=self.legacy();raw=old.read_bytes();pointer=(self.store.root/'current.json').read_bytes()
        old.write_bytes(b'broken')
        with self.assertRaises(ValueError):migrate_history([self.store.root])
        self.assertEqual((self.store.root/'current.json').read_bytes(),pointer)
        old.write_bytes(raw)
        with patch('dashboard.short_paths.sync_current',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):migrate_history([self.store.root])
        published=read_publication(maintenance_root([self.store.root])/'publication.json',{'indexes':self.store})['indexes']
        self.assertTrue(short_name(Path(published['parts'][0]['path']).name))
        self.assertEqual(self.store.snapshot()['version'],before['version'])
        migrate_history([self.store.root])
        self.assertEqual(self.store.snapshot()['version'],published['version'])

    def test_export_legacy_source_always_short_and_second_package_does_not_conflict(self):
        before,old=self.legacy()
        one=dp.export_package(self.local,self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            metadata=dp.inspect_archive(archive)
            for name in metadata['files']:
                if name.endswith('.parquet'):self.assertTrue(short_name(Path(name).name))
        dp.install_package(self.archive,self.destination)
        two=dp.export_package(self.local,self.root/'second.zip')
        self.assertNotEqual(one['package_id'],two['package_id'])
        dp.install_package(self.root/'second.zip',self.destination)
        self.assertTrue(old.exists());self.assertEqual(self.wind.read_bytes(),b'company Wind data')


class RealtimeShortTests(unittest.TestCase):
    def test_migrate_catalogue_backup_old_file_and_future_append(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);reader=RealtimeReader(root)
            with RealtimeStore(root) as store:
                store.batch(batch())
                with self.assertRaises(WriterBusyError):migrate_realtime(root)
            with closing(sqlite3.connect(root/'live/quotes.sqlite3')) as connection, connection:
                old_paths=[]
                for relative, in connection.execute('SELECT path FROM parquet_parts').fetchall():
                    path=root/relative;raw=path.read_bytes()
                    long=path.with_name('2026-09-18.'+hashlib.sha256(raw).hexdigest()+'.parquet');path.rename(long)
                    connection.execute('UPDATE parquet_parts SET path=? WHERE path=?',(long.relative_to(root).as_posix(),relative))
                    old_paths.append((long,raw))
                for event_id,description in connection.execute("SELECT id,description FROM events WHERE kind='raw_http_batch'").fetchall():
                    reference=json.loads(description);path=root/reference['path'];raw=path.read_bytes()
                    long=path.with_name(reference['sha256']+'.json');path.rename(long)
                    reference['path']=long.relative_to(root).as_posix()
                    connection.execute('UPDATE events SET description=? WHERE id=?',(json.dumps(reference),event_id))
                    old_paths.append((long,raw))
            # Failure after the first catalogue UPDATE must roll back the whole transaction.
            real_publish=publish_bytes;calls=[]
            def fail_second(*args,**kwargs):
                calls.append(1)
                if len(calls)==2:raise OSError('interrupted')
                return real_publish(*args,**kwargs)
            with patch('dashboard.short_paths.publish_bytes',side_effect=fail_second):
                with self.assertRaises(OSError):migrate_realtime(root)
            with closing(sqlite3.connect(root/'live/quotes.sqlite3')) as connection:
                paths=[p for p, in connection.execute('SELECT path FROM parquet_parts')]
                self.assertTrue(all(not short_name(Path(p).name) for p in paths))
            result=migrate_realtime(root);self.assertEqual(result['changed'],2)
            self.assertEqual(result['raw_changed'],1)
            self.assertTrue((Path(result['backup'])/'before.sqlite3').exists())
            self.assertEqual(migrate_realtime(root)['changed'],0)
            with RealtimeStore(root) as store:store.batch(batch(1100,received='2026-09-18T09:31:00+08:00'))
            self.assertEqual(len(reader.read_parquet_day('000001.SZ','2026-09-18')),2)
            for path,raw in old_paths:self.assertEqual(path.read_bytes(),raw)
            for path in reader.parquet_files('000001.SZ','2026-09-18'):self.assertTrue(short_name(path.name))
