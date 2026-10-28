import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from dashboard.marketdata import history_maintenance as hm
from dashboard.marketdata.history_quick import quick_check,incremental_scan,save_ledger


class AppHistoryTests(unittest.TestCase):
    def test_overview_only_does_not_scan_download_or_rewrite_research_history(self):
        c=self.fixture();c.cycle()
        protected={name:(c.root/name).read_bytes() for name in ('status.json','pending.json','coverage_ledger.json','coverage_summary.json')}
        distribution=dict(start='2026-07-01',end='2026-10-16',mapping_gaps=[])
        factory=Mock(side_effect=AssertionError('No remote gap'))
        with patch.object(hm,'scan',side_effect=AssertionError('No research scan')),\
             patch.object(hm,'plan',side_effect=AssertionError('No minute plan')),\
             patch('dashboard.marketdata.overview_percentiles.requirements',return_value=distribution),\
             patch('dashboard.marketdata.overview_daily.seed_local',return_value=12),\
             patch('dashboard.marketdata.overview_daily.requests',return_value=[]):
            result=hm.run_cycle(c.local,overview_only=True,direct_factory=factory,now='2026-10-19T10:00:00+08:00')
        self.assertEqual(result['state'],'complete');self.assertFalse(result['research_downloads_enabled'])
        self.assertEqual(result['scope'],'overview_completed_closes_only');factory.assert_not_called()
        for name,raw in protected.items():self.assertEqual((c.root/name).read_bytes(),raw)

    def test_overview_only_gap_uses_daily_filler_and_closes_owned_session(self):
        c=self.fixture();c.cycle();fetch=Mock(side_effect=AssertionError('No legacy minute fetch'))
        with patch('dashboard.marketdata.overview_percentiles.requirements',return_value=dict(start='2026-07-01',end='2026-10-16',mapping_gaps=[])),\
             patch('dashboard.marketdata.overview_daily.seed_local',return_value=0),\
             patch('dashboard.marketdata.overview_daily.requests',return_value=[dict(day='2026-10-16',asset='index',symbols=['000300.SH'])]),\
             patch('dashboard.marketdata.overview_daily.fill',return_value=dict(inserted=1,pending_rows=0,pending_batches=0,status='complete')) as daily:
            result=hm.run_cycle(c.local,overview_only=True,direct_factory=lambda _:c.client,fetcher=fetch,now='2026-10-19T10:00:00+08:00')
        self.assertEqual(result['state'],'complete');self.assertEqual(result['inserted'],1)
        daily.assert_called_once();fetch.assert_not_called();self.assertGreater(c.client.close.call_count,0)

    def test_overview_missing_historical_slot_mapping_is_not_reported_as_complete(self):
        c=self.fixture();c.cycle()
        with patch('dashboard.marketdata.overview_daily.fill',return_value=dict(status='complete',target='2026-10-16',
                pending_rows=0,pending_batches=0,inserted=1)):
            result=c.cycle(overview_daily=True,incremental=True)
        self.assertEqual(result['state'],'waiting_reference')
        self.assertGreater(result['overview_continuous']['mapping_missing'],0)
        self.assertIn('seeded_local',result['overview_daily'])

    def test_completed_today_is_opt_in_and_never_downloaded_before_close(self):
        c=self.fixture()
        before=c.cycle(include_completed_today=True,now='2026-10-19T15:09:59+08:00')
        self.assertEqual(before['target'],'2026-10-16')
        after=hm.run_cycle(c.local,force=False,direct_factory=lambda _:c.client,fetcher=c.full_fetch,
            today='2026-10-19',include_completed_today=True,now='2026-10-19T15:10:00+08:00')
        self.assertEqual(after['target'],'2026-10-19')
        self.assertEqual(after['state'],'complete')

    def fixture(self):
        from tests.test_history_maintenance import HistoryMaintenanceTests
        case=HistoryMaintenanceTests();case.setUp();self.addCleanup(case.doCleanups);return case

    def test_quick_path_does_not_open_manifest_or_stat_partition(self):
        c=self.fixture();c.cycle()
        with patch.object(hm.BarDataset,'snapshot',side_effect=AssertionError('manifest read')),\
             patch.object(hm.BarDataset,'_rows',side_effect=AssertionError('partition read')):
            result=quick_check(c.config,today='2026-10-19')
        self.assertTrue(result['minute_verified']);self.assertEqual(result['known_pending'],0)
        self.assertEqual({r['frequency'] for r in result['coverage']},{'1m','1d'})
        self.assertEqual(len(result['coverage']),40)
        self.assertEqual(result['partition_stats'],0)

    def test_old_publication_zero_never_certifies_minutes(self):
        c=self.fixture();c.cycle();(c.root/'coverage_summary.json').unlink()
        result=quick_check(c.config,today='2026-10-19')
        self.assertFalse(result['minute_verified']);self.assertIsNone(result['known_pending'])

    def test_quick_calendar_does_not_fetch_missing_previous_year(self):
        with tempfile.TemporaryDirectory() as t, patch('requests.Session.get',side_effect=AssertionError('quick check must stay offline')):
            result=quick_check({'history_roots':[t]},today='2025-01-02')
        self.assertEqual(result['state'],'waiting_calendar');self.assertIsNone(result['target'])

    def test_incremental_cycle_authenticates_downloads_jointly_publishes_and_closes(self):
        c=self.fixture();start=__import__('time').perf_counter()
        result=c.cycle(incremental=True)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['inserted'],4820)
        self.assertEqual(result['verification_scope'],'incremental');c.client.close.assert_called_once()
        self.assertTrue(quick_check(c.config,today='2026-10-19')['minute_verified'])
        self.assertLess(__import__('time').perf_counter()-start,30)

    def test_incremental_without_ledger_marks_old_present_groups_unknown(self):
        c=self.fixture();c.cycle();snapshots={k:s.snapshot() for k,s in c.stores.items()}
        with patch.object(hm.BarDataset,'_rows',side_effect=AssertionError('old partitions must not be opened')):
            coverage,ledger,metrics=incremental_scan(c.stores,snapshots,{},recent_start='2026-10-19',stop=lambda:False,progress=lambda n:None)
        self.assertEqual(metrics['unknown_groups'],40)
        jobs,summary=hm.plan(coverage,c.metadata,['2026-10-16'],'2026-10-16','2026-10-16')
        self.assertEqual(jobs,[]);self.assertTrue(all(r['unverified_days']==1 for r in summary))
        self.assertTrue(all(r['complete_through'] is None for r in summary))

    def test_verified_unchanged_history_reused_without_partition_access(self):
        c=self.fixture();c.cycle();snapshots={k:s.snapshot() for k,s in c.stores.items()}
        with patch.object(hm.BarDataset,'_rows',side_effect=AssertionError('old partitions must not be opened')):
            _,_,metrics=incremental_scan(c.stores,snapshots,hm.read_json(c.root/'coverage_ledger.json'),
                recent_start='2026-10-19',stop=lambda:False,progress=lambda n:None)
        self.assertEqual(metrics['reused'],40);self.assertEqual(metrics['unknown_groups'],0)

    def test_changed_partition_and_known_gap_are_checked(self):
        c=self.fixture();c.cycle();snapshots={k:s.snapshot() for k,s in c.stores.items()}
        ledger=hm.read_json(c.root/'coverage_ledger.json');first=next(iter(ledger['groups']))
        ledger['groups'][first]['signature']='changed'
        _,_,metrics=incremental_scan(c.stores,snapshots,ledger,recent_start='2026-10-19',stop=lambda:False,progress=lambda n:None,
            known_jobs=[dict(symbol='000300.SH',frequency='1m',day='2026-10-16')])
        self.assertGreaterEqual(metrics['read_groups'],1);self.assertLessEqual(metrics['read_groups'],2)

    def test_recent_corrupt_partition_fails_without_publishing(self):
        c=self.fixture();c.cycle();snapshots={k:s.snapshot() for k,s in c.stores.items()}
        p=next(iter(snapshots['indexes']['parts']));c.stores['indexes']._path(p['path']).write_bytes(b'bad')
        with self.assertRaises(ValueError):
            incremental_scan(c.stores,snapshots,hm.read_json(c.root/'coverage_ledger.json'),recent_start='2026-10-16',
                             stop=lambda:False,progress=lambda n:None)

    def test_cancel_keeps_previous_summary_and_ledger(self):
        c=self.fixture();c.cycle();before=(c.root/'coverage_summary.json').read_bytes()
        with patch.object(hm,'scan',side_effect=hm.Stopped()):result=c.cycle()
        self.assertFalse(result['scan_complete']);self.assertEqual(before,(c.root/'coverage_summary.json').read_bytes())

    def test_profile_reuses_company_paths_and_keeps_original(self):
        from dashboard.app_config import prepare_config
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);numeric=base/'localsetting/numeric_excel';numeric.mkdir(parents=True)
            original=json.dumps(dict(history_roots=['D:/data/existing'],reference_file='D:/data/ref.json',
                                     history_connection_file='D:/private/existing.json'))
            (numeric/'native.json').write_text(original)
            target=prepare_config(module_root=base)
            self.assertEqual((target/'native.json').read_text(),original)
            self.assertEqual((numeric/'native.json').read_text(),original)
            (target/'native.json').write_text('{}');prepare_config(module_root=base)
            self.assertEqual((target/'native.json').read_text(),'{}')

    def test_credential_probe_does_not_export_or_migrate_password(self):
        from dashboard.app_config import credential_state
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'c.json';p.write_text('{"protected_credentials":{"scheme":"current-user"}}')
            with patch('index_strategy.history.credentials.load_config',return_value=dict(password='NEVER_EXPORT',username='PRIVATE',host='host',port=1)):
                result=credential_state(dict(history_connection_file=str(p)))
            self.assertTrue(result['available']);self.assertNotIn('NEVER_EXPORT',json.dumps(result));self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertEqual(json.loads(p.read_text())['protected_credentials']['scheme'],'current-user')

    def test_normalization_preserves_nanoseconds_and_missing_values(self):
        import pandas as pd
        from tests.test_history_maintenance import bar
        raw=bar();raw['recorded_at']=pd.Timestamp('2026-10-19T02:00:00.123456789Z')
        normalized=hm.normalized_rows([raw])[0]
        self.assertEqual(normalized['recorded_at'],raw['recorded_at']);self.assertIsNone(normalized['available_at'])


if __name__=='__main__':unittest.main()
