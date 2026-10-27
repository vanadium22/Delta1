"""Real archives and boundary checks, without touching business data or Git."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from tools import workspace_cleanup as cleanup


class WorkspaceCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.tracked={'dashboard/example.py'}

    def save(self,name,data=b'old verification data',*,old=True):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        if old:
            stamp=time.time()-3*86400;os.utime(p,(stamp,stamp));os.utime(p.parent,(stamp,stamp))
        return p

    def plan(self):return cleanup.plan(self.root,tracked=self.tracked,min_age_hours=24)

    def test_verified_archive_preserves_bytes_and_only_removes_old_ignored_copies(self):
        a=self.save('.deps/pair_intraday/nested/report.json',b'{"value":123}')
        os.utime(a.parent.parent,(time.time()-3*86400,)*2)
        b=self.save('.deps/calendar-health-tests.log',b'passed')
        data=self.save('data/market/quotes.sqlite3',b'protected business quotes')
        dependency=self.save('.deps/dashboard_native/runtime.dll',b'protected dependency')
        source=self.save('dashboard/example.py',b'print(1)')
        cache=self.save('dashboard/__pycache__/example.cpython-313.pyc',b'reproducible bytecode')
        originals={p.relative_to(self.root).as_posix():p.read_bytes() for p in (a,b)}
        value=self.plan();result=cleanup.apply(self.root,value,tracked=self.tracked)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['deleted_files'],2)
        self.assertEqual(result['bytecode_removed'],1);self.assertFalse(cache.exists())
        with zipfile.ZipFile(self.root/result['archive']) as archive:
            manifest=json.loads(archive.read('archive_manifest.json'))
            for row in manifest['files']:
                raw=archive.read(row['path']);self.assertEqual(raw,originals[row['path']])
                self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])
        self.assertTrue(data.exists());self.assertTrue(dependency.exists());self.assertTrue(source.exists())

    def test_recent_outputs_and_tracked_files_are_preserved(self):
        recent=self.save('.deps/pair_intraday/recent.json',old=False)
        tracked=self.save('.deps/short_verify/tracked.txt');self.tracked.add('.deps/short_verify/tracked.txt')
        value=self.plan();self.assertEqual(value['archive_files'],[])
        self.assertEqual({r['reason'] for r in value['excluded']},{'recent_output_preserved','tracked_files_preserved'})
        self.assertTrue(recent.exists());self.assertTrue(tracked.exists())

    def test_local_configuration_reference_keeps_existing_validation_data(self):
        source=self.save('.deps/pair_intraday/a.txt')
        self.save('dashboard/localsetting/native.json',json.dumps(dict(history_roots=[str(source.parent)])).encode())
        value=self.plan();self.assertEqual(value['archive_files'],[])
        self.assertEqual(value['excluded'][0]['reason'],'referenced_by_configuration')

    def test_new_configuration_reference_after_plan_prevents_deletion(self):
        source=self.save('.deps/pair_intraday/a.txt');value=self.plan()
        self.save('dashboard/localsetting/native.json',json.dumps(dict(results_root=str(source.parent))).encode())
        with self.assertRaises(cleanup.UnsafePath):cleanup.apply(self.root,value,tracked=self.tracked)
        self.assertTrue(source.exists())

    def test_new_reference_to_an_empty_directory_is_preserved(self):
        source=self.root/'.deps/app_v6_temp';source.mkdir(parents=True)
        stamp=time.time()-3*86400;os.utime(source,(stamp,stamp));value=self.plan()
        self.save('dashboard/localsetting/native.json',json.dumps(dict(results_root='dashboard/../.deps/app_v6_temp')).encode())
        with self.assertRaises(cleanup.UnsafePath):cleanup.apply(self.root,value,tracked=self.tracked)
        self.assertTrue(source.is_dir())

    def test_outside_path_or_dependency_in_modified_plan_cannot_be_removed(self):
        self.save('.deps/pair_intraday/a.txt');value=self.plan()
        for relative in ('../outside.txt','.deps/dashboard_native/runtime.dll','data/market.db'):
            mutated=deepcopy(value);mutated['archive_files'][0]['path']=relative
            with self.assertRaises((cleanup.UnsafePath,FileNotFoundError)):cleanup.apply(self.root,mutated,tracked=self.tracked)
            self.assertTrue((self.root/'.deps/pair_intraday/a.txt').is_file())

    def test_changed_source_after_planning_is_preserved(self):
        source=self.save('.deps/pair_intraday/a.txt');value=self.plan();source.write_text('new work',encoding='utf8')
        with self.assertRaises(cleanup.UnsafePath):cleanup.apply(self.root,value,tracked=self.tracked)
        self.assertEqual(source.read_text(),'new work');self.assertFalse((self.root/'local_artifacts').exists())

    def test_failed_archive_verification_never_removes_originals(self):
        source=self.save('.deps/pair_intraday/a.txt');value=self.plan()
        with patch.object(cleanup,'verify_archive',side_effect=cleanup.UnsafePath('corrupt archive')):
            with self.assertRaises(cleanup.UnsafePath):cleanup.apply(self.root,value,tracked=self.tracked)
        self.assertTrue(source.exists())

    def test_reparse_directory_is_excluded_before_traversal(self):
        source=self.save('.deps/pair_intraday/a.txt');original=cleanup.is_reparse
        with patch.object(cleanup,'is_reparse',side_effect=lambda p:p==source.parent or original(p)):
            value=self.plan()
        self.assertEqual(value['archive_files'],[]);self.assertEqual(value['excluded'][0]['reason'],'UnsafePath')
        self.assertTrue(source.exists())

    def test_only_bytecode_with_a_tracked_source_is_reproducible(self):
        self.save('dashboard/example.py');normal=self.save('dashboard/__pycache__/example.cpython-313.pyc')
        orphan=self.save('dashboard/__pycache__/plugin.cpython-313.pyc')
        private=self.save('dashboard/localsetting/__pycache__/private.cpython-313.pyc')
        self.assertEqual([r['path'] for r in self.plan()['bytecode']],[normal.relative_to(self.root).as_posix()])
        self.assertTrue(orphan.exists());self.assertTrue(private.exists())

    def test_readonly_validation_pack_is_removed_only_after_verified_archive(self):
        source=self.save('.deps/numeric_refresh/bundle/objects/pack/test.pack',b'old test fixture')
        for parent in source.parents:
            if parent==self.root/'.deps':break
            os.utime(parent,(time.time()-3*86400,)*2)
        source.chmod(stat.S_IREAD)
        self.addCleanup(lambda:source.chmod(stat.S_IREAD|stat.S_IWRITE) if source.exists() else None)
        value=self.plan();result=cleanup.apply(self.root,value,tracked=self.tracked)
        self.assertEqual(result['status'],'complete');self.assertFalse(source.exists())
        with zipfile.ZipFile(self.root/result['archive']) as archive:
            self.assertEqual(archive.read(value['archive_files'][0]['path']),b'old test fixture')


if __name__=='__main__':unittest.main()
