"""Pair identity, explanation and auxiliary isolation across shared adapters."""
import math
import tempfile
import unittest
from dashboard.indicator_catalog import catalog,find_variant
from dashboard.indicator_ui import ui_controls,selection_from_controls
from dashboard.indicator_workspace import evaluate


class PairContractTests(unittest.TestCase):
    def test_old_calculation_cache_cannot_be_relabelled_as_new_pair_version(self):
        from unittest.mock import patch
        from dashboard.numeric_evidence import cache_scope
        config={'history_roots':[],'dividend_mode':'fixed_snapshot'}
        current=cache_scope(config)
        with patch('dashboard.native.pair_metrics.PAIR_FORMULA_VERSION','nonregression-v2'):
            old=cache_scope(config)
        self.assertNotEqual(current,old)
        self.assertEqual(config,{'history_roots':[],'dividend_mode':'fixed_snapshot'})

    def test_every_pair_variant_has_readable_construction_and_typed_components(self):
        for page in ('calendar','cross'):
            for entry in catalog(page):
                with self.subTest(page=page,variant=entry['variant_id']):
                    self.assertEqual(entry['formula_version'],'contract-pair-v3')
                    for field in ('pair_construction','explanation','direction','limitations'):
                        self.assertIsInstance(entry[field],str)
                        self.assertTrue(entry[field].strip())
                    self.assertEqual(entry['metric_roles'][entry['primary']],'primary')
                    self.assertEqual(sum(r=='primary' for r in entry['metric_roles'].values()),1)
                    for code in entry['metric_ids']:
                        self.assertTrue(entry['metric_definitions'][code]['unit'])
                        self.assertTrue(entry['metric_definitions'][code]['formula'])
                        if '.legacy_' in code and not code.startswith('A03.'):
                            self.assertEqual(entry['metric_roles'][code],'auxiliary')
        self.assertTrue(all(e['formula_version']=='nonregression-v2' for e in catalog('basis')))

    def test_old_chinese_choices_keep_identity_and_new_close_is_explicit(self):
        for page in ('calendar','cross'):
            controls=ui_controls(page)
            for family in controls['families']:
                price=family['input_ids'][0]
                old_label=family['legacy_labels'][0]
                expected=find_variant(family_id=family['family_id'],input_id=price,category=page)
                self.assertEqual(selection_from_controls(page,old_label,price)['variant_id'],expected['variant_id'])
            close=next(x for x in controls['inputs'] if x['input_id']=='future')
            self.assertIn('价差' if page=='calendar' else '对数价比',close['label'])

    def test_pair_oi_growth_is_not_fixed_collection_growth_difference(self):
        from tests.indicator_frozen_fixture import FrozenIndicatorModel,OBSERVED_AT
        with tempfile.TemporaryDirectory() as root:
            model=FrozenIndicatorModel(root)
            for symbol,frame in model.daily.items():
                if symbol.endswith('.CFE'):frame['open_interest']=list(range(100,135))
            # Equal notionals make h=1. Both legs grow together, so old
            # collection-growth difference is zero while pair capacity grows.
            model.daily['IF2611.CFE']['close']=100.
            model.daily['IC2611.CFE']['close']=150.
            state=evaluate(model,dict(page='cross',family_id='B08',input='fixed',
                scope='specified',left='IF2611.CFE',right='IC2611.CFE',timing='日终'),OBSERVED_AT)
            entity=state['pages']['cross']['entities'][0]
            main=entity['primary'];old=next(r for r in entity['metrics'] if r['id']=='B08.legacy_collection')
            self.assertEqual(main['role'],'primary')
            self.assertEqual(main['formula_version'],'contract-pair-v3')
            self.assertAlmostEqual(main['value'],100*math.log(134/129))
            self.assertEqual(main['n'],6)
            self.assertEqual(main['pair_metadata']['unit'],main['unit'])
            self.assertEqual(main['pair_metadata']['construction'],main['formula'])
            self.assertEqual(old['value'],0.)
            self.assertEqual(old['role'],'auxiliary')
            self.assertEqual(old['formula_version'],'nonregression-v2')
            self.assertIn('collection',old['input_versions'])
            self.assertNotEqual(main['explanation'],old['explanation'])
            self.assertEqual(old['pair_metadata']['unit'],old['unit'])
            self.assertIn('固定',old['pair_construction'])

    def test_new_input_for_30_period_rule_keeps_new_formula_version(self):
        from tests.test_indicator_workspace import ContractTests
        model,_=ContractTests().model()
        state=evaluate(model,dict(page='calendar',family_id='A03.legacy_percentile30',input='annual'),
                       '2026-10-21T14:00+08:00')
        main=state['pages']['calendar']['entities'][0]['primary']
        self.assertEqual(main['formula_version'],'contract-pair-v3')
        self.assertEqual(main['role'],'primary')


if __name__=='__main__':unittest.main()
