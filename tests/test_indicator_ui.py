"""Selector identities and unchanged frozen contracts, without UI formulas."""
from copy import deepcopy
import tempfile
import unittest

from dashboard.indicator_catalog import catalog
from dashboard.indicator_ui import (families, input_label, input_options,
                                    resolve_variant, selection_from_controls, ui_controls)
from dashboard.indicator_workspace import evaluate, load_preferences, save_preferences
from tests.indicator_frozen_fixture import FrozenIndicatorModel, OBSERVED_AT


class IndicatorControlTests(unittest.TestCase):
    def test_every_registered_variant_is_reachable_by_chinese_controls(self):
        for page in ('basis', 'calendar', 'cross'):
            controls = ui_controls(page)
            labels = [r['label'] for r in families(page)]
            self.assertEqual(len(labels), len(set(labels)))
            for item in controls['variants']:
                chosen = selection_from_controls(page, item['family_label'], item['input_label'])
                self.assertEqual(chosen['variant_id'], item['variant_id'])
                self.assertNotIn('selection_error', chosen)
            self.assertEqual(len(controls['variants']), len(catalog(page)))

    def test_changed_input_preserves_family_and_contract_filters(self):
        saved = dict(variant_id='A03.z::basis::v1', family_id='A03.z', input='basis',
                     scope='specified', left='IF2611.CFE', right='IH2611.CFE',
                     root='IF', timing='历史日', date='2026-10-21', offset=40,
                     participation=0, saved_entities=[{'left': 'IF2612.CFE'}])
        old = deepcopy(saved)
        selected = selection_from_controls('cross', 'A03.z', 'annual', saved)
        self.assertEqual(selected['variant_id'], 'A03.z::annual::v1')
        self.assertEqual(selected['offset'], 0)
        for key in ('scope', 'left', 'right', 'root', 'timing', 'date', 'participation', 'saved_entities'):
            self.assertEqual(selected[key], saved[key])
        self.assertEqual(saved, old)

    def test_not_applicable_removes_old_identity_and_never_substitutes(self):
        for page, family, price in [('cross', 'A03.mean', 'future'),
                                    ('basis', 'B07', 'basis'), ('basis', 'A03.z', 'unknown')]:
            choice = selection_from_controls(page, family, price, {'variant_id': 'A03.z::basis::v1'})
            self.assertIsNone(choice['variant_id'])
            self.assertTrue(choice['selection_error'])
        self.assertNotIn('future', [v['input_id'] for v in input_options('cross')])
        self.assertEqual([v['input_id'] for v in input_options('basis', False)], ['future', 'basis', 'annual'])

    def test_fixed_economic_definition_has_only_one_identity(self):
        for page in ('basis', 'calendar', 'cross'):
            for family in (f for f in families(page) if f['fixed']):
                ids = set()
                for price in ('future', 'basis', 'annual', 'log_basis'):
                    entry, note = resolve_variant(page, family['family_id'], price)
                    self.assertEqual(entry['input_id'], 'fixed')
                    self.assertIn('固定口径', note)
                    ids.add(entry['variant_id'])
                self.assertEqual(len(ids), 1)

    def test_legacy_b3_and_preferences_keep_stable_variant_and_watchlist(self):
        with tempfile.TemporaryDirectory() as root:
            rows = [{'category': '跨期', 'left': 'IF2611.CFE', 'right': 'IF2612.CFE',
                     'input': '年化', 'timing': '日终'}]
            import json
            from pathlib import Path
            old_file = Path(root) / 'research_watchlist.json'
            old_file.write_text(json.dumps({'rows': rows}), encoding='utf8')
            before = old_file.read_bytes()
            migrated = load_preferences(root)
            selected = selection_from_controls('calendar', 'A03.z::log_annual::v1', None,
                                               migrated['pages']['calendar'])
            self.assertEqual(selected['input'], 'log_annual')
            self.assertEqual(selected['saved_entities'], rows)
            save_preferences(root, {'active_page': 'calendar', 'pages': {'calendar': selected}})
            self.assertEqual(load_preferences(root)['pages']['calendar']['variant_id'], 'A03.z::log_annual::v1')
            self.assertEqual(old_file.read_bytes(), before)

    def test_close_label_separates_live_and_completed_daily_price(self):
        self.assertEqual(input_label('future'), '期货收盘价 close')
        self.assertIn('最新价（盘中）', input_label('future', '盘中优先'))
        self.assertIn('close（日终）', input_label('future', '盘中优先'))

    def test_saved_invalid_choice_recovers_without_retaining_transient_error(self):
        with tempfile.TemporaryDirectory() as root:
            invalid = selection_from_controls('basis', 'B07', 'annual',
                                               {'saved_entities': [{'left': 'IF2611.CFE'}]})
            save_preferences(root, {'active_page': 'basis', 'pages': {'basis': invalid}})
            self.assertEqual(load_preferences(root)['pages']['basis']['selection_error'], invalid['selection_error'])
            # Widgets only send editable fields; keep watchlist but clear old error.
            valid = selection_from_controls('basis', 'B07', 'future')
            save_preferences(root, {'active_page': 'basis', 'pages': {'basis': valid}})
            restored = load_preferences(root)['pages']['basis']
            self.assertNotIn('selection_error', restored)
            self.assertEqual(restored['variant_id'], 'B07::future::v1')
            self.assertEqual(restored['saved_entities'], invalid['saved_entities'])

    def test_rejected_combination_cannot_fall_back_to_another_backend_result(self):
        from types import SimpleNamespace
        model = SimpleNamespace(local_root='unused')
        invalid = selection_from_controls('cross', 'A03.z', 'future')
        result = evaluate(model, {'active_page': 'cross', 'request_id': 'invalid',
                                  'pages': {'cross': invalid}}, now=OBSERVED_AT)
        self.assertEqual(result['pages'], {})
        self.assertEqual(result['request_id'], 'invalid')
        self.assertEqual(result['error'], invalid['selection_error'])
        self.assertIsNone(result['selection']['pages']['cross']['variant_id'])

    def test_inactive_rejected_page_has_no_selected_first_variant(self):
        from tests.test_indicator_workspace import ContractTests
        model, _ = ContractTests().model()
        invalid = selection_from_controls('basis', 'B07', 'basis')
        result = evaluate(model, {'active_page': 'calendar', 'pages': {
            'basis': invalid, 'calendar': {'family_id': 'A03.percentile', 'input': 'basis'}}},
            now='2026-10-21T14:00+08:00')
        self.assertIsNone(result['pages']['basis']['selected_variant_id'])
        self.assertFalse(result['pages']['basis']['loaded'])
        self.assertEqual(result['pages']['calendar']['selected_variant_id'], 'A03.percentile::basis::v1')

    def test_primary_controls_load_exact_frozen_backend_results(self):
        with tempfile.TemporaryDirectory() as root:
            model = FrozenIndicatorModel(root)
            model.enable_live()
            for page in ('basis', 'calendar', 'cross'):
                for family in ('A03.mean', 'A03.std', 'A03.z', 'A03.percentile', 'A03.change5', 'B10'):
                    for option in input_options(page, False):
                        price = option['input_id']
                        choice = selection_from_controls(page, family, price, {'timing': '日终'})
                        actual = evaluate(model, dict(page=page, pages={page: choice}), now=OBSERVED_AT)
                        direct = evaluate(model, dict(page=page, family_id=family, input=price, timing='日终'), now=OBSERVED_AT)
                        loaded = actual['pages'][page]
                        self.assertEqual(loaded['selected_variant_id'], family + '::' + price + '::v1')
                        self.assertEqual(len(loaded['entities']), 6 if page == 'cross' else 4)
                        self.assertEqual(loaded['entities'], direct['pages'][page]['entities'])
                        for entity in loaded['entities']:
                            self.assertEqual(entity['primary']['input_id'], price)


if __name__ == '__main__':
    unittest.main()
