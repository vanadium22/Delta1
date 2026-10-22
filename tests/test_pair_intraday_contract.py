"""Selection, metadata and daily fallback for the two pair live branches."""
from copy import deepcopy
from unittest.mock import patch
import unittest

from dashboard.indicator_catalog import catalog
from dashboard.indicator_workspace import evaluate
from dashboard.numeric_evidence import cache_scope


class PairIntradayContractTests(unittest.TestCase):
    def state(self, family, page, timing='盘中优先', value=0.0, versions_change=False):
        from tests.test_indicator_workspace import ContractTests
        model,_=ContractTests().model()
        live_id={'B09':'B09.same_time','B11':'B11.sample'}[family]
        daily=dict(id=family,title='日终',value=1.5,time='2026-10-20T07:00Z',
                   unit='倍',n=20,formula='daily formula',history=[dict(time='2026-10-20T07:00Z',value=1.5)])
        live=dict(id=live_id,title='盘中',value=None,current=value,current_time='2026-10-21T06:00Z',
                  current_n=20 if family=='B09' else 2,unit='倍',formula='live formula',
                  current_reason='' if value is not None else '缺前20日同步分钟',current_supported=True,
                  current_source_times={'IF2611.CFE':'2026-10-21T06:00Z'},
                  current_reference_end='2026-10-20T02:30Z',current_history_cutoff='2026-10-20T07:00Z',
                  current_history=[dict(time='2026-10-21T06:00Z',value=value)],
                  pair_intraday=dict(baseline_n=20,numerator=0,denominator=100),history=[])
        legacy=dict(id=family+'.legacy_log_ratio',title='原单腿比较',value=0.,unit='对数倍数',
                    time='2026-10-20T07:00Z',formula='legacy ratio',history=[])
        calls=[]
        def snapshot(request):
            calls.append(request)
            version='changed' if versions_change and len(calls)>1 else 'frozen-v1'
            return dict(metrics=deepcopy([daily,live,legacy]),versions={'data':version})
        model.snapshot=snapshot
        result=evaluate(model,dict(page=page,family_id=family,input='fixed' if family=='B09' else 'future',
                        timing=timing), '2026-10-21T14:00+08:00')
        return result['pages'][page], live_id

    def test_live_zero_primary_and_daily_aux_keep_their_own_version_and_explanation(self):
        for page in ('calendar','cross'):
            for family in ('B09','B11'):
                with self.subTest(page=page,family=family):
                    state,live_id=self.state(family,page)
                    group=state['selected_group']
                    self.assertEqual(group['primary'],live_id)
                    self.assertEqual(group,next(g for g in state['groups'] if g['variant_id']==group['variant_id']))
                    for entity in state['entities']:
                        rows={r['id']:r for r in entity['metrics']};main=entity['primary']
                        self.assertEqual((main['id'],main['value'],main['data_status']),(live_id,0.,'intraday_estimate'))
                        self.assertEqual(main['formula_version'],'contract-pair-intraday-v1')
                        self.assertEqual(rows[family]['formula_version'],'contract-pair-v3')
                        self.assertEqual(rows[family+'.legacy_log_ratio']['formula_version'],'nonregression-v2')
                        self.assertNotEqual(main['explanation'],rows[family]['explanation'])
                        self.assertEqual(sum(r['role']=='primary' for r in rows.values()),1)
                        self.assertEqual(main['pair_intraday']['denominator'],100)
                        self.assertEqual(main['history_cutoff'],'2026-10-20T07:00Z')

    def test_missing_or_nonfinite_live_falls_back_without_copying_daily_into_live_row(self):
        for missing in (None,float('nan'),float('inf')):
            for family in ('B09','B11'):
                state,live_id=self.state(family,'cross',value=missing)
                for entity in state['entities']:
                    main=entity['primary'];rows={r['id']:r for r in entity['metrics']}
                    self.assertEqual((main['id'],main['value'],main['formula_version']),(family,1.5,'contract-pair-v3'))
                    self.assertEqual(main['scope'],'完整日终参考')
                    self.assertIn('盘中分支不可用',main['reason'])
                    self.assertIsNone(rows[live_id]['value'])
                    self.assertEqual(rows[live_id]['role'],'auxiliary')
                    self.assertEqual(main['fallback_from'],live_id)

    def test_daily_selection_clears_intraday_curve_and_returns_original_daily_primary(self):
        for family in ('B09','B11'):
            state,live_id=self.state(family,'calendar',timing='日终')
            self.assertEqual(state['selected_group']['primary'],family)
            for entity in state['entities']:
                self.assertEqual(entity['primary']['id'],family)
                row=next(r for r in entity['metrics'] if r['id']==live_id)
                self.assertEqual(row['current_history'],[])
                self.assertIsNone(row['current'])
                self.assertIsNone(row['value'])
                self.assertIsNone(row['time'])
                self.assertIsNone(row['n'])

    def test_all_seven_pair_inputs_register_sample_branch_and_invalidate_old_caches(self):
        for page in ('calendar','cross'):
            rows=[r for r in catalog(page) if r['family_id']=='B11']
            self.assertEqual(len(rows),7)
            self.assertTrue(all('B11.sample' in r['metric_ids'] for r in rows))
            self.assertTrue(all(r['metric_definitions']['B11.sample']['current_supported'] for r in rows))
        config={'history_roots':[]};before=deepcopy(config)
        current=cache_scope(config)
        with patch('dashboard.native.pair_intraday.PAIR_INTRADAY_VERSION','old-placeholder'):
            self.assertNotEqual(cache_scope(config),current)
        self.assertEqual(config,before)

    def test_changed_dataset_version_clears_current_and_daily_plot_payloads(self):
        state,_=self.state('B11','cross',versions_change=True)
        for entity in state['entities']:
            self.assertEqual(entity['primary']['data_status'],'input_version_changed')
            for row in entity['metrics']:
                self.assertIsNone(row['value'])
                self.assertIsNone(row['current'])
                self.assertIsNone(row['current_time'])
                self.assertIsNone(row['current_n'])
                self.assertEqual(row['current_history'],[])
                self.assertEqual(row['history'],[])


if __name__=='__main__':unittest.main()
