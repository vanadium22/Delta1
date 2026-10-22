"""Shared frozen input and the Excel projection must preserve every result field."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.indicator_catalog import catalog
from dashboard.indicator_selection import all_entities
from dashboard.indicator_workspace import evaluate
from dashboard.numeric_view import add_research_view
from tests.indicator_frozen_fixture import FrozenIndicatorModel, OBSERVED_AT


def frozen_research(model, *, page='basis', variant=None, request_id='frozen-1', **choices):
    selected=dict(active_page=page,request_id=request_id,pages={page:dict(
        variant_id=variant or 'A03.percentile::basis::v1',scope='representatives',
        timing='日终',offset=0,limit=12,**choices)})
    return evaluate(model,selected,OBSERVED_AT)


class IndicatorExcelTests(unittest.TestCase):
    def setUp(self):
        self.model=FrozenIndicatorModel(Path('.deps/metric_implementation/frozen'))

    def test_candidate_counts_and_representative_identity_use_real_legs(self):
        self.assertEqual([len(all_entities(self.model.metadata,OBSERVED_AT,c))
                          for c in ('basis','calendar','cross')],[16,24,96])
        for page,count in (('basis',4),('calendar',4),('cross',6)):
            result=frozen_research(self.model,page=page)
            entities=result['pages'][page]['entities']
            self.assertEqual(len(entities),count)
            for entity in entities:
                self.assertTrue(all(s in self.model.metadata or s.endswith('.SH') for s in entity['legs']))
                self.assertEqual(entity['primary']['visibility_status'],'修订历史参考 / 可见性未认证')
        selected=frozen_research(self.model)['pages']['basis']['entities']
        self.assertEqual(len({e['left'][2:6] for e in selected}),4)

    def test_excel_projection_preserves_value_unit_time_n_and_state_for_all_pages(self):
        for page in ('basis','calendar','cross'):
            for family in ('A03.mean','A03.std','A03.z','A03.percentile','A03.change5','B10'):
                for input_id in ('future','basis','annual','log_basis','log_annual'):
                    variant=family+'::'+input_id+'::v1'
                    shared=frozen_research(self.model,page=page,variant=variant)
                    original=deepcopy(shared)
                    rendered=add_research_view({},shared)['research']['excel_pages'][page]
                    self.assertEqual(shared,original)
                    for entity,row in zip(shared['pages'][page]['entities'],rendered['entities']):
                        source=entity['primary']
                        self.assertEqual(row[1:8],[source.get('value'),source.get('unit'),source.get('time'),
                            source.get('history_cutoff'),source.get('n'),source.get('implementation_status'),source.get('data_status')])
                        self.assertEqual(row[10],source['visibility_status'])
                    self.assertEqual(len(rendered['directory']),len(catalog(page)))
                    self.assertTrue(rendered['details'])

    def test_independent_inputs_do_not_relabel_a_cached_percentile(self):
        outputs=[]
        for input_id in ('future','basis','annual','log_basis','log_annual'):
            result=frozen_research(self.model,variant='A03.mean::'+input_id+'::v1')
            row=result['pages']['basis']['entities'][0]['primary']
            self.assertEqual(row['input_id'],input_id)
            outputs.append(row['value'])
        self.assertEqual(len(set(outputs)),len(outputs))

    def test_legacy_large_snapshot_keeps_main_table_bounded_and_details_complete(self):
        row=dict(id='A03.mean',value=0.,unit='bp',n=20,data_status='daily_reference',
                 implementation_status='implemented',source_times={},formula='shared fixture')
        entities=[dict(title='fixture-'+str(i),primary=dict(row),metrics=[dict(row)]) for i in range(100)]
        workspace=dict(pages={'basis':dict(entities=entities,total=100,loaded=True,selection=dict(
            family_id='A03.mean',input='basis',timing='日终',scope='all'))})
        page=add_research_view({},workspace)['research']['excel_pages']['basis']
        self.assertEqual(len(page['summary']),24)
        self.assertEqual(len(page['entities']),100)
        self.assertEqual(len(page['details']),100)
        self.assertEqual(page['summary'][0][1],0.)
        self.assertIn('完整结果见详情',page['status'])

    def test_pair_projection_explains_primary_and_auxiliary_without_changing_values(self):
        primary=dict(id='B03',title='合约对增仓漂移',value=0.,unit='bp',n=20,role='primary',
            pair_construction='配对 X 序列',formula_version='contract-pair-v3',formula='shared formula',
            implementation_status='implemented',data_status='daily_reference',source_times={})
        auxiliary=dict(primary,id='B03.legacy',title='单腿漂移差',value=None,role='auxiliary',
            reason='缺少可靠持仓')
        workspace=dict(pages={'cross':dict(entities=[dict(title='IF / IH',primary=primary,
            metrics=[primary,auxiliary])],total=1,loaded=True,selection=dict(
            variant_id='B03::future::v1',family_id='B03',input='future',timing='日终'))})
        variant=dict(variant_id='B03::future::v1',pair_construction='10000 ln(F_A / F_B)',
            direction='上升表示 A 相对 B 增强；单位 bp',explanation='衡量配对偏离的增仓确认',
            limitations='容量为代理估算，不等同于可成交量')
        controls=dict(variants=[variant],families=[dict(family_id='B03',label='合约对增仓漂移')],
            inputs=[dict(input_id='future',label='期货价格比（对数 bp）')])
        original=deepcopy(workspace)
        with patch('dashboard.indicator_ui.ui_controls',return_value=controls):
            rendered=add_research_view({},workspace)['research']['excel_pages']['cross']
        self.assertEqual(workspace,original)
        self.assertEqual(rendered['summary'][0][1],0.)
        self.assertEqual(rendered['details'][0][1],0.)
        self.assertIsNone(rendered['details'][1][1])
        self.assertTrue(rendered['details'][0][0].startswith('【主指标】'))
        self.assertTrue(rendered['details'][1][0].startswith('【辅助解释】'))
        self.assertIn('配对 X 序列',rendered['details'][0][10])
        self.assertIn('contract-pair-v3',rendered['details'][0][8])
        self.assertEqual(rendered['explanations']['pair_construction'],variant['pair_construction'])
        self.assertEqual(rendered['explanations']['limitations'],variant['limitations'])
        self.assertIn('期货价格比（对数 bp）',rendered['context'])

    def test_preferences_do_not_overwrite_legacy_watchlist(self):
        from dashboard.indicator_workspace import load_preferences,save_preferences
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'research_watchlist.json'
            raw=json.dumps(dict(rows=[dict(category='跨指数',left='IF2612.CFE',right='IH2612.CFE',
                input='基差bp',timing='历史日',date='2026-10-20')]),ensure_ascii=False).encode('utf8')
            path.write_bytes(raw)
            selected=load_preferences(folder)
            self.assertEqual(selected['active_page'],'cross')
            save_preferences(folder,selected)
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(load_preferences(folder)['legacy_rows'],selected['legacy_rows'])
            # A subsequent COM request emits only the cells it can edit.
            selected['pages']['cross']['saved_entities']=[dict(left='IF2612.CFE',right='IH2612.CFE')]
            save_preferences(folder,selected)
            save_preferences(folder,dict(active_page='cross',pages={'cross':dict(scope='all',participation=0.)}))
            retained=load_preferences(folder)
            self.assertEqual(retained['legacy_rows'],selected['legacy_rows'])
            self.assertEqual(retained['pages']['cross']['saved_entities'],selected['pages']['cross']['saved_entities'])
            self.assertEqual(retained['pages']['cross']['participation'],0.)
            self.assertEqual(path.read_bytes(),raw)


if __name__=='__main__':unittest.main()
