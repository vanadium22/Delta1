"""Deterministic selector, independent variants and shared-result contracts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import pandas as pd

from dashboard.indicator_catalog import catalog,find_variant,applicability
from dashboard.indicator_selection import (all_entities,entity,representatives,
                                           fixed_collections,paginate,VISIBILITY_UNVERIFIED)
from dashboard.indicator_workspace import (evaluate,load_preferences,save_preferences,
                                           page_rows,detail_rows,directory_rows)


def fixture():
    metadata={};daily={};calendar=pd.date_range('2026-10-19 07:00Z',periods=3,freq='D')
    expiries=('2026-10-30','2026-11-20','2026-12-18','2027-03-19')
    for root in ('IF','IH','IC','IM'):
        for k,(month,expiry) in enumerate(zip(('2610','2611','2612','2703'),expiries)):
            symbol=root+month+'.CFE'
            metadata[symbol]=dict(listing_date='2026-01-01',expiry_date=expiry,
                                  known_at='2026-10-01T00:00Z')
            # Deliberately make an independent main month for each product.
            main={'IF':1,'IH':2,'IC':3,'IM':0}[root]
            daily[symbol]=pd.DataFrame(dict(open_interest=[100,1000 if k==main else 100+k,1e8 if k==0 else 1],
                                             volume=[10,200+k,1e9],is_final=True),index=calendar)
    return metadata,daily,calendar


class RepresentativeTests(unittest.TestCase):
    def test_t_minus_one_independent_main_and_no_current_day_influence(self):
        metadata,daily,calendar=fixture()
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')
        self.assertEqual([r['left'] for r in result],['IF2611.CFE','IH2612.CFE','IC2703.CFE','IM2610.CFE'])
        self.assertTrue(all(r['decision_date']=='2026-10-20' for r in result))
        self.assertTrue(all(r['visibility_status']==VISIBILITY_UNVERIFIED for r in result))
        self.assertTrue(all(r['coverage']['complete_oi'] for r in result))

    def test_full_candidate_coverage_and_explicit_volume_fallback(self):
        metadata,daily,calendar=fixture()
        daily['IF2610.CFE'].loc[calendar[1],'open_interest']=None
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')[0]
        self.assertEqual(result['selection_type'],'成交最活跃参考')
        self.assertEqual(result['left'],'IF2703.CFE')
        self.assertEqual(result['coverage']['oi'],3)
        daily['IF2610.CFE'].loc[calendar[1],'volume']=None
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')[0]
        self.assertEqual(result['selection_type'],'近月参考')
        self.assertEqual(result['left'],'IF2610.CFE')

    def test_missing_whole_decision_day_is_not_replaced_with_old_session(self):
        metadata,daily,calendar=fixture()
        for symbol in daily:daily[symbol]=daily[symbol].drop(calendar[1])
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')
        self.assertTrue(all(r['decision_date']=='2026-10-20' and r['coverage']['oi']==0 for r in result))
        self.assertTrue(all(r['selection_type']=='近月参考' for r in result))

    def test_http_placeholder_zero_is_not_reliable_oi(self):
        metadata,daily,calendar=fixture()
        daily['IF2610.CFE']['source']='http_quote'
        daily['IF2610.CFE'].loc[calendar[1],'open_interest']=0
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')[0]
        self.assertEqual(result['selection_type'],'成交最活跃参考')

    def test_only_explicit_pit_with_real_publication_and_reference_evidence_can_certify(self):
        metadata,daily,calendar=fixture()
        for s in metadata:
            metadata[s]['pit_certified']=True
            daily[s]['pit_certified']=True
            daily[s]['available_at']='2026-10-20T08:00Z'
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')[0]
        self.assertEqual(result['visibility_status'],'当时可见证据已认证')
        daily['IF2610.CFE']['available_at']='NaT'
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')[0]
        self.assertEqual(result['visibility_status'],VISIBILITY_UNVERIFIED)
        daily['IF2610.CFE']['available_at']='2026-10-22T08:00Z'
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','basis')[0]
        self.assertEqual(result['visibility_status'],VISIBILITY_UNVERIFIED)

    def test_calendar_uses_bottleneck_then_interval_not_nearest_to_main(self):
        metadata,daily,calendar=fixture()
        scores=(100,400,500,300)
        for (symbol,frame),score in zip([(s,daily[s]) for s in sorted(daily) if s.startswith('IF')],scores):
            frame.loc[calendar[1],'open_interest']=score
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','calendar')[0]
        self.assertEqual((result['left'],result['right']),('IF2611.CFE','IF2612.CFE'))

    def test_cross_requires_actual_same_expiry_and_stable_orientation(self):
        metadata,daily,calendar=fixture()
        for s in metadata:
            if s.startswith('IH'):metadata[s]['expiry_date']=str(pd.Timestamp(metadata[s]['expiry_date'])+pd.Timedelta(days=1))[:10]
        result=representatives(metadata,daily,calendar,'2026-10-21T14:00+08:00','cross')
        self.assertEqual(result[0]['selection_type'],'无同期代表')
        self.assertIsNone(result[0]['entity_id'])
        all_cross=all_entities(metadata,'2026-10-21T14:00+08:00','cross')
        self.assertTrue(all(r['left'].startswith('IF') for r in all_cross if set(r['roots'])=={'IF','IC'}))
        mixed=next(r for r in all_cross if set(r['roots'])=={'IF','IH'})
        ok,reason=applicability(find_variant(family_id='A06',category='cross'),mixed)
        self.assertFalse(ok);self.assertIn('异期',reason)

    def test_all_entities_are_complete_and_paged_without_metric_filtering(self):
        metadata,_,_=fixture()
        self.assertEqual([len(all_entities(metadata,'2026-10-21','basis')),
                          len(all_entities(metadata,'2026-10-21','calendar')),
                          len(all_entities(metadata,'2026-10-21','cross'))],[16,24,96])
        entities=all_entities(metadata,'2026-10-21','cross')
        part,n,start,size=paginate(entities,dict(root='IF',offset=2,limit=7))
        self.assertEqual((len(part),n,start,size),(7,48,2,7))
        self.assertEqual(len({r['entity_id'] for r in entities}),96)
        roots=('IF','IH','IC','IM')
        for row in entities:self.assertLess(roots.index(row['left'][:2]),roots.index(row['right'][:2]))
        for row in all_entities(metadata,'2026-10-21','calendar'):
            self.assertLess(metadata[row['left']]['expiry_date'],metadata[row['right']]['expiry_date'])

    def test_fixed_collection_identity_does_not_follow_main_and_changes_with_members(self):
        metadata,daily,calendar=fixture()
        first=fixed_collections(metadata,'2026-10-21','cross')[0]
        daily['IF2610.CFE'].loc[calendar[1],'open_interest']=1e10
        self.assertEqual(first['entity_id'],fixed_collections(metadata,'2026-10-21','cross')[0]['entity_id'])
        changed=deepcopy(metadata);changed.pop('IF2610.CFE')
        self.assertNotEqual(first['entity_id'],fixed_collections(changed,'2026-10-21','cross')[0]['entity_id'])

    def test_historical_entity_pool_includes_expired_but_not_future_listings(self):
        metadata,_,_=fixture()
        metadata['IF2601.CFE']=dict(listing_date='2025-01-01',expiry_date='2026-01-16')
        metadata['IF2709.CFE']=dict(listing_date='2027-01-01',expiry_date='2027-09-17')
        entities=all_entities(metadata,'2026-10-21','basis',include_history=True)
        self.assertIn('IF2601.CFE',[r['left'] for r in entities])
        self.assertNotIn('IF2709.CFE',[r['left'] for r in entities])


class ContractTests(unittest.TestCase):
    def model(self):
        metadata,daily,calendar=fixture();calls=[]
        def snapshot(request):
            calls.append(request)
            val={'future':4000.,'basis':-12.,'annual':-2.,'log_basis':-13.}.get(request['price_input'],-1.)
            return dict(versions={'data':'frozen-v1'},metrics=[dict(id='A03.percentile',title='分位',
                        value=val,current=val+1,time='2026-10-20T07:00:00+00:00',current_time='2026-10-21T06:00Z',
                        unit='%',n=20,current_n=20,reference_end='2026-10-19T07:00Z',
                        history=[dict(time='2026-10-20T07:00Z',value=val)],formula='half weight')])
        model=SimpleNamespace(snapshot=snapshot,local_root=Path('.'),indicator_context=dict(
            metadata=metadata,daily=daily,calendar=calendar,versions={'data':'frozen-v1'},
            reference_version='ref-v1',dividend_version='div-v1'))
        return model,calls

    def test_one_selected_independent_variant_default_four_and_shared_projection(self):
        model,calls=self.model()
        result=evaluate(model,dict(request_id='new',page='basis',family_id='A03.percentile',input='basis'),
                        '2026-10-21T14:00+08:00')
        page=result['pages']['basis']
        self.assertEqual(result['request_id'],'new');self.assertEqual(len(calls),4)
        self.assertEqual(sum(g['loaded'] for p in result['pages'].values() for g in p['groups']),1)
        self.assertTrue(len(page['groups'])>50)
        row=page['entities'][0]['primary']
        self.assertEqual((row['value'],row['unit'],row['n']),(-11.,'%',20))
        self.assertEqual(row['history_cutoff'],'2026-10-19T07:00Z')
        self.assertEqual(row['visibility_status'],VISIBILITY_UNVERIFIED)
        self.assertTrue(all(t is None for t in row['source_times'].values()))
        self.assertEqual(len(page_rows(page)[0]),11);self.assertEqual(len(detail_rows(page)[0]),11)
        self.assertEqual(len(directory_rows(page)),len(page['groups']))

    def test_nested_preferences_daily_clears_provisional_and_keeps_history(self):
        model,calls=self.model()
        variant=find_variant(family_id='A03.percentile',input_id='log_basis',category='cross')
        result=evaluate(model,dict(active_page='cross',pages={'cross':dict(variant_id=variant['variant_id'],timing='日终')}),
                        '2026-10-21T14:00+08:00')
        row=result['pages']['cross']['entities'][0]['primary']
        self.assertEqual(len(calls),6);self.assertEqual(row['value'],-13.)
        self.assertIsNone(row['current']);self.assertEqual(len(row['history']),1)
        self.assertEqual(row['data_status'],'daily_reference')
        self.assertEqual(row['input_id'],'log_basis')

    def test_default_choice_frozen_during_day_and_never_switched_for_missing_indicator(self):
        model,calls=self.model()
        selection=dict(page='basis',family_id='A03.percentile',input='basis')
        first=evaluate(model,selection,'2026-10-21T10:00+08:00')['pages']['basis']['representatives'][0]
        frame=model.indicator_context['daily']['IF2610.CFE']
        frame.iloc[1,frame.columns.get_loc('open_interest')]=1e12
        second=evaluate(model,{**selection,'family_id':'A13','input':'fixed'},'2026-10-21T14:00+08:00')['pages']['basis']['representatives'][0]
        self.assertEqual(first['entity_id'],second['entity_id'])
        self.assertEqual(second['selection_versions'],{'data':'frozen-v1'})

    def test_fixed_collection_results_require_every_member_and_never_use_main_series(self):
        model,_=self.model()
        # A six-day window and positive aggregate for each immutable member.
        calendar=pd.date_range('2026-10-14 07:00Z',periods=6,freq='D')
        model.indicator_context['calendar']=calendar
        for symbol in model.indicator_context['daily']:
            model.indicator_context['daily'][symbol]=pd.DataFrame(dict(open_interest=[100,101,102,103,104,110],volume=100),index=calendar)
        state=evaluate(model,dict(page='cross',family_id='B08',input='fixed'),'2026-10-20T14:00+08:00')
        entity=state['pages']['cross']['entities'][0]
        self.assertEqual(entity['kind'],'collection');self.assertEqual(entity['primary']['value'],0.)
        self.assertEqual(entity['primary']['n'],6)
        member=entity['members'][0]
        model.indicator_context['daily'][member].iloc[-1,0]=None
        state=evaluate(model,dict(page='cross',family_id='B08',input='fixed'),'2026-10-20T14:00+08:00')
        self.assertIsNone(state['pages']['cross']['entities'][0]['primary']['value'])

    def test_all_registered_primary_metrics_exist_in_production_calculate(self):
        from tests.indicator_frozen_fixture import FrozenIndicatorModel,OBSERVED_AT
        model=FrozenIndicatorModel(Path('.deps'))
        for category,right in [('basis','000300.SH'),('calendar','IF2703.CFE'),('cross','IC2612.CFE')]:
            cache={}
            for entry in catalog(category):
                if entry['entity_kind']=='collection':continue
                price='basis' if entry['input_id']=='fixed' else entry['input_id']
                if price not in cache:
                    state=model.snapshot(dict(left='IF2612.CFE',right=right,category=category,price_input=price,as_of=OBSERVED_AT.isoformat()))
                    cache[price]={r['id'] for r in state['metrics']}
                self.assertIn(entry['primary'],cache[price],(category,entry['variant_id']))

    def test_catalog_identity_and_matrix_exclude_cross_raw_points(self):
        rows=catalog();ids=[r['variant_id'] for r in rows]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all(r['input_id']!='future' for r in catalog('cross')))
        required={'family_id','variant_id','source_ref','formula_version','categories','input_id',
                  'fixed_inputs','required_fields','frequency','window','unit','timing','missing_policy'}
        self.assertTrue(all(required.issubset(r) for r in rows))
        one=catalog();one[0]['title']='changed';self.assertNotEqual(catalog()[0]['title'],'changed')

    def test_submetric_applicability_keeps_index_clv_but_excludes_nonexistent_legs(self):
        for entry in catalog('basis'):
            ids=entry['metric_ids']
            self.assertFalse(any(code.startswith(('B03.B.','B04.B.','B09.B.','B11.B.')) for code in ids))
            self.assertNotIn('B11.max',ids);self.assertNotIn('B07.volume',ids)
            if entry['family_id']=='B07':self.assertIn('B07.B.clv',ids)
            if entry['family_id']=='B11' and entry['input_id']=='future':self.assertNotIn('B11.sample',ids)
        self.assertFalse(any(code.startswith('B08.B.') for entry in catalog('calendar') for code in entry['metric_ids']))
        for category in ('basis','calendar','cross'):
            for entry in catalog(category):
                self.assertEqual(set(entry['metric_ids']),set(entry['metric_definitions']))
                self.assertTrue(all(m['unit'] and m['formula'] and m['missing_reason']
                                    for m in entry['metric_definitions'].values()))

    def test_missing_collection_children_have_explicit_typed_blank_contracts(self):
        from tests.indicator_frozen_fixture import FrozenIndicatorModel,OBSERVED_AT
        model=FrozenIndicatorModel(Path('.deps'))
        for family,expected in [('B02',('B02.collection_center','B02.collection_gap')),('B11',('B11.sample',))]:
            for page in ('basis','calendar','cross'):
                state=evaluate(model,dict(page=page,family_id=family,input='annual'),OBSERVED_AT)
                for entity in state['pages'][page]['entities']:
                    rows={m['id']:m for m in entity['metrics']}
                    for code in expected:
                        row=rows[code]
                        self.assertIsNone(row['value']);self.assertEqual(row['data_status'],'missing_input')
                        self.assertEqual(row['implementation_status'],'implemented')
                        self.assertIn('采集区间',row['scope']);self.assertIn('非',row['reason'])
                        self.assertTrue(row['formula']);self.assertTrue(row['current_supported'])
                        if code.startswith('B02.collection'):self.assertEqual(row['unit'],'年化百分点')
                        else:self.assertEqual(row['unit'],'倍' if page=='basis' else '对数倍数')
        # No-bars/failure schemas also use each child's dimension, not B02's X.
        model.snapshot=lambda request:dict(metrics=[],versions=model.versions)
        state=evaluate(model,dict(page='basis',family_id='B02',input='basis'),OBSERVED_AT)
        rows={m['id']:m for m in state['pages']['basis']['entities'][0]['metrics']}
        self.assertEqual(rows['B02.weight_sum']['unit'],'手')
        self.assertEqual(rows['B02.weighted_sum']['unit'],'bp×手')
        self.assertEqual(rows['B02.n']['unit'],'根')

    def test_input_version_change_clears_whole_group(self):
        model,_=self.model();snapshot=model.snapshot;calls=[0]
        def changed(request):
            calls[0]+=1;state=snapshot(request)
            if calls[0]>1:state['versions']={'data':'new-v2'}
            return state
        model.snapshot=changed
        state=evaluate(model,dict(page='basis',family_id='A03.percentile',input='basis'),'2026-10-21T14:00+08:00')
        for row in state['pages']['basis']['entities']:
            self.assertIsNone(row['primary']['value'])
            self.assertEqual(row['primary']['data_status'],'input_version_changed')

    def test_legacy_preferences_migrate_read_only_to_separate_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);legacy=folder/'research_watchlist.json'
            legacy.write_text(json.dumps(dict(rows=[dict(category='跨指数',left='IF2611.CFE',right='IC2611.CFE',input='基差bp')]),ensure_ascii=False),encoding='utf8')
            before=legacy.read_bytes();value=load_preferences(folder)
            self.assertEqual(value['active_page'],'cross');self.assertEqual(len(value['legacy_rows']),1)
            save_preferences(folder,value)
            self.assertEqual(legacy.read_bytes(),before)
            self.assertTrue((folder/'indicator_research_preferences.json').is_file())
            self.assertEqual(load_preferences(folder)['legacy_rows'],value['legacy_rows'])


if __name__=='__main__':unittest.main()
