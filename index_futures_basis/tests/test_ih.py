"""IH cache upgrades, complete inputs and independently checked calendar windows."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from index_futures_basis.demo import snapshot, dividends
from index_futures_basis.report import chart_catalog
from index_futures_basis.service import BasisService
from index_futures_basis.store import Store
from index_futures_basis.sync import synchronize
from index_futures_basis.term_structure import term_distributions
from index_futures_basis.tests.test_sync import FakeProvider


def remove_ih(store):
    with store.connection() as con:
        con.execute("DELETE FROM mapping WHERE root='IH'")
        con.execute("DELETE FROM contracts WHERE code LIKE 'IH%'")
        con.execute("DELETE FROM quotes WHERE code LIKE 'IH%' OR code='000016.SH'")


class IHTests(unittest.TestCase):
    def test_upgrade_only_downloads_ih_and_reuses_other_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'market.sqlite')
            start, end = '2026-07-06', '2026-07-10'
            provider = FakeProvider()
            synchronize(store, provider, start, end)
            remove_ih(store)
            before_quotes, before_mapping = store.quotes(start, end), store.mappings(start, end)
            self.assertIsNone(store.coverage(start, end)['latest_complete'])
            with self.assertRaisesRegex(ValueError, '缺少品种IH'):
                store.panel(start, end)
            provider.calls.clear()
            result = synchronize(store, provider, start, end)
            self.assertEqual(result['state'], 'complete')
            self.assertEqual(store.coverage(start, end)['latest_complete'], end)
            for call in provider.calls:
                if call[0] in {'mapping', 'series'}:
                    self.assertTrue(call[1].startswith('IH') or call[1] == '000016.SH', call)
                elif call[0] == 'expiries':
                    self.assertTrue(all(code.startswith('IH') for code in call[1]))
                else:
                    self.fail(f'Unnecessary request: {call}')
            self.assertEqual({k: store.quotes(start, end)[k] for k in before_quotes}, before_quotes)
            self.assertEqual({k: store.mappings(start, end)[k] for k in before_mapping}, before_mapping)
            provider.calls.clear()
            self.assertEqual(synchronize(store, provider, start, end)['requests'], 0)

    def test_demo_upgrade_is_local_and_does_not_fill_real_or_offline_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            demo = BasisService(root, 'demo')
            live = BasisService(root, 'wind')
            offline = BasisService(root, 'offline')
            for service in (demo, live, offline):
                service.store.import_raw(snapshot(), {'kind': service.mode})
                remove_ih(service.store)
            with patch('index_futures_basis.service.WindProvider', side_effect=AssertionError('network')):
                self.assertTrue(np.isfinite(BasisService(root, 'demo').query('IH', 4)['current']))
                for mode in ('wind', 'offline'):
                    service = BasisService(root, mode)
                    self.assertNotIn('IH', service.store.roots())
                    with self.assertRaisesRegex(ValueError, '待补齐品种：IH'):
                        service.analyze()

    def test_incomplete_offline_import_does_not_replace_four_root_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'market.sqlite')
            raw = snapshot()
            store.import_raw(raw, {'kind': 'offline'})
            before = store.quotes('2026-10-08', '2026-10-08')
            legacy = copy.deepcopy(raw)
            legacy['records'] = [r for r in legacy['records'] if r['root'] != 'IH']
            with self.assertRaisesRegex(ValueError, '缺少品种IH'):
                store.import_raw(legacy, {'kind': 'offline'})
            self.assertEqual(store.quotes('2026-10-08', '2026-10-08'), before)

    def test_ih_inputs_queries_and_all_derived_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BasisService(Path(directory), 'demo')
            a = service.analyze()
            for frame in (a.panel, a.fixed, a.fixed90, a.history, a.annual_quantiles,
                          a.spread, a.totals, a.fixed90_quantiles, a.calendar_annualized, a.calendar_quantiles):
                self.assertEqual(set(frame.root), {'IF', 'IC', 'IM', 'IH'})
            latest = a.panel[a.panel.root.eq('IH') & a.panel.trade_date.eq(a.end)].set_index('slot')
            for metric, far, near in [('calendar_02_00', 3, 1), ('calendar_03_02', 4, 3)]:
                q = service.query('IH', 1, metric)
                expected = ((latest.loc[far, 'futures_close'] + latest.loc[far, 'dividend_points'])
                            - (latest.loc[near, 'futures_close'] + latest.loc[near, 'dividend_points']))
                expected *= 36500 / latest.loc[near, 'spot_close'] / (latest.loc[far, 'expiry_date'] - latest.loc[near, 'expiry_date']).days
                self.assertAlmostEqual(q['current'], expected)
                self.assertEqual(q['statistics'].months.tolist(), [3, 6, 12])
            self.assertEqual(len([name for name in chart_catalog() if name.startswith('IH_')]), 7)
            chosen = 'IH_年化基差分位蜡烛图'
            output = Path(service.export('figures', [chosen]))
            self.assertEqual([p.stem for p in (output / 'figures').glob('*.png')], [chosen])
            missing = dividends(a.end)
            missing = missing[~missing.code.str.startswith('IH')]
            with patch('index_futures_basis.demo.dividends', return_value=missing), \
                 self.assertRaisesRegex(ValueError, '缺少.*分红'):
                service._cache = None
                service.analyze()

    def test_calendar_three_month_boundary_and_ties_exclude_today(self):
        g = pd.DataFrame({'root': 'IH', 'pair': '02-00', 'trade_date': pd.to_datetime(
            ['2025-10-01', '2026-07-15', '2026-07-16', '2026-09-01', '2026-10-15', '2026-10-16']),
            'annualized_basis_pct': [-10, -100, -6, -4, -2, -4]})
        q = term_distributions(g, pd.Timestamp('2026-10-16'), ['root', 'pair'], windows=(3, 6, 12)).set_index('months')
        self.assertEqual(q.loc[3, 'n'], 3)
        self.assertEqual(q.loc[3, 'p50'], -4)
        self.assertEqual(q.loc[3, 'percentile'], 50)
        self.assertEqual(q.loc[3, 'sample_start'], pd.Timestamp('2026-07-16'))
        self.assertEqual(q.loc[3, 'sample_end'], pd.Timestamp('2026-10-15'))
