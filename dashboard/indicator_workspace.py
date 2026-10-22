"""One research service and projections consumed by Excel and both Apps.

Only the active variant and a bounded entity page are evaluated. The complete
directory remains visible, with unloaded groups explicitly marked as such.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import pandas as pd

from dashboard.indicator_catalog import catalog,find_variant,applicability,PAGES,FORMULA_VERSION
from dashboard.indicator_selection import (all_entities,representatives,fixed_collections,
                                           paginate,VISIBILITY_UNVERIFIED)

PREFERENCE_FILE='indicator_research_preferences.json'
PAGE_HEADERS=['指标族','独立变体','具体实体','值','单位','源时','历史截止','n','实现状态','数据状态','原因']
DETAIL_HEADERS=['指标','值','单位','源时','历史截止','n','实现状态','数据状态','输入版本','原因','公式']
DIRECTORY_HEADERS=['指标族','独立变体','名称','默认数量','加载状态']


def load_preferences(local_root):
    root=Path(local_root)
    try:
        value=json.loads((root/PREFERENCE_FILE).read_text(encoding='utf8'))
        if isinstance(value,dict):return value
    except (OSError,ValueError):pass
    try:
        old=json.loads((root/'research_watchlist.json').read_text(encoding='utf8'))
        if isinstance(old,dict) and isinstance(old.get('rows'),list):
            first=next((r for r in old['rows'] if isinstance(r,dict) and r.get('left')), {})
            page={'期现':'basis','跨期':'calendar','跨指数':'cross','跨品种':'cross'}.get(first.get('category'),'basis')
            input_id={'期货价':'future','基差bp':'basis','年化':'annual'}.get(first.get('input'),'basis')
            pages={}
            for label,key in (('期现','basis'),('跨期','calendar'),('跨指数','cross')):
                saved=[deepcopy(r) for r in old['rows'] if isinstance(r,dict) and r.get('category') in (label,'跨品种' if key=='cross' else label)]
                if not saved:continue
                row=saved[0]
                pages[key]=dict(scope='specified',left=row.get('left',''),right=row.get('right',''),
                                input={'期货价':'future','基差bp':'basis','年化':'annual'}.get(row.get('input'),'basis'),
                                timing=row.get('timing','盘中优先'),date=row.get('date',''),
                                family_id='A03.percentile',saved_entities=saved)
            return dict(schema_version=1,active_page=page,legacy_rows=deepcopy(old['rows']),
                        migrated_from='research_watchlist.json',pages=pages)
    except (OSError,ValueError):pass
    return None


def save_preferences(local_root,selection):
    from dashboard.numeric_snapshot import save_snapshot
    # Keep migrated rows in the new file; the legacy file is never rewritten.
    keys=('schema_version','active_page','pages','page','variant_id','family_id','input','scope',
          'left','right','root','product','timing','date','expiry_mode','offset','limit','legacy_rows','migrated_from')
    # COM and widget selectors only emit fields they edit. Preserve migrated
    # watchlist rows and saved page entities across those narrower requests.
    existing=load_preferences(local_root) or {}
    value={**existing,**selection}
    value['pages']={page:{**(existing.get('pages',{}).get(page,{}) or {}),
                         **(selection.get('pages',{}).get(page,{}) or {})}
                    for page in set(existing.get('pages',{}))|set(selection.get('pages',{}))}
    for page, updated in selection.get('pages',{}).items():
        if updated.get('variant_id') and not updated.get('selection_error'):
            value['pages'][page].pop('selection_error',None)
    save_snapshot({k:deepcopy(value[k]) for k in keys if k in value},Path(local_root)/PREFERENCE_FILE)


def _now(value):
    stamp=pd.Timestamp(value or pd.Timestamp.now(tz='UTC'))
    return stamp.tz_localize('Asia/Shanghai') if stamp.tzinfo is None else stamp.tz_convert('Asia/Shanghai')


def _normalize(selection,now):
    value=deepcopy(selection or {})
    active=value.get('active_page') or value.get('page') or 'basis'
    if active not in PAGES:active='basis'
    nested=value.get('pages') if isinstance(value.get('pages'),dict) else {}
    choices={}
    for page in PAGES:
        raw=nested.get(page,{}) if nested else value if page==active else {}
        raw=raw if isinstance(raw,dict) else {}
        if raw.get('selection_error'):
            # The UI resolver deliberately rejected this family/X combination.
            # Never turn that explicit empty state into the legacy first entry.
            choices[page]={**raw,'variant_id':None}
            continue
        pick=find_variant(raw['variant_id'],category=page) if raw.get('variant_id') else None
        if pick is None:pick=find_variant(family_id=raw.get('family_id') or 'A03.percentile',input_id=raw.get('input') or 'basis',category=page)
        if pick is None:pick=catalog(page)[0]
        timing={'intraday':'盘中优先','daily':'日终','historical':'历史日'}.get(raw.get('timing'),raw.get('timing','盘中优先'))
        if timing not in ('盘中优先','日终','历史日'):timing='盘中优先'
        scope=raw.get('scope','representatives')
        if scope not in ('representatives','all','history','specified'):scope='representatives'
        expiry=raw.get('expiry_mode','same' if page=='cross' else 'all')
        if expiry not in ('same','mixed','all'):expiry='same' if page=='cross' else 'all'
        choices[page]={**raw,'variant_id':pick['variant_id'],'family_id':pick['family_id'],
                       'input':pick['input_id'],'timing':timing,'scope':scope,'expiry_mode':expiry}
    return {**value,'schema_version':1,'active_page':active,'page':active,'pages':choices}


def _context(model,now):
    supplied=getattr(model,'indicator_context',None)
    if supplied is not None:return supplied(now) if callable(supplied) else supplied
    from dashboard.marketdata.repository import ReferenceBook
    from dashboard.marketdata.contract_reference import latest_contracts
    reference=ReferenceBook(model.config.get('reference_file') or None)
    metadata=latest_contracts(reference.data)
    active=[s for s,r in metadata.items() if r['listing_date']<=str(now.date())<r['expiry_date']]
    state=model.snapshot(dict(cards=False,metrics=False,category='basis',price_input='basis',left=next(iter(active),None),as_of=now.isoformat()))
    engine=getattr(model,'research_engine',None)
    return dict(metadata=metadata,daily=getattr(engine,'daily',{}),
                calendar=engine.calendar if engine is not None and engine.calendar is not None else [],
                versions=state.get('versions',{}),reference_version=reference.version,
                dividend_version=state.get('dividend_version'),seed=state)


def _isfinite(value):
    try:return not isinstance(value,bool) and math.isfinite(float(value))
    except (TypeError,ValueError):return False


def _bounded_context(context,at):
    """Explicit fixture contexts obey the same observation cutoff as repositories."""
    result=dict(context)
    index=pd.DatetimeIndex(context.get('calendar',[]))
    if len(index):
        stamps=index.tz_localize('Asia/Shanghai') if index.tz is None else index
        result['calendar']=index[stamps<=at]
    daily={}
    for symbol,frame in context.get('daily',{}).items():
        if frame.empty:daily[symbol]=frame;continue
        dates=pd.DatetimeIndex(frame['event_time'] if 'event_time' in frame else frame.index)
        stamps=dates.tz_localize('Asia/Shanghai') if dates.tz is None else dates
        daily[symbol]=frame.loc[stamps<=at]
    result['daily']=daily
    return result


def _fixed_daily_representatives(model,context,at,category):
    """Hold the decision within the model's day; an indicator cannot switch it."""
    cache=getattr(model,'indicator_representative_cache',None)
    if cache is None:
        cache={};model.indicator_representative_cache=cache
    key=(str(at.date()),category)
    if key not in cache:
        values=representatives(context.get('metadata',{}),context.get('daily',{}),context.get('calendar',[]),at,category)
        for value in values:value['selection_versions']=deepcopy(context.get('versions'))
        cache[key]=deepcopy(values)
        # Cache at most a month of explicitly viewed historical decisions.
        while len(cache)>96:cache.pop(next(iter(cache)))
    return deepcopy(cache[key])


def _history_sources(entity,context,time):
    """Return actual per-leg row timestamps, never a copied display timestamp."""
    sources={}
    target=_now(time).date() if time else None
    for symbol in entity.get('legs',[]):
        frame=context.get('daily',{}).get(symbol)
        if frame is None or frame.empty or target is None: sources[symbol]=None;continue
        index=pd.DatetimeIndex(frame['event_time'] if 'event_time' in frame else frame.index)
        local=index.tz_localize('Asia/Shanghai') if index.tz is None else index.tz_convert('Asia/Shanghai')
        matches=index[local.date==target]
        sources[symbol]=matches[-1].isoformat() if len(matches)==1 else None
    return sources


def result_contract(row,variant,entity,state,context,selection,now):
    """Project a metric without inventing sample counts or visibility evidence."""
    raw=deepcopy(row)
    live=selection['timing']=='盘中优先' and raw.get('current') is not None
    daily_value=raw.get('value');daily_time=raw.get('time')
    value=raw.get('current') if live else daily_value
    time=raw.get('current_time') if live else daily_time
    reason=(raw.get('current_reason') or '') if live else (raw.get('reason') or '')
    if selection['timing']=='盘中优先' and not live and raw.get('current_reason'):
        reason='；'.join(dict.fromkeys(s for s in (raw.get('current_reason'),reason) if s))
    impl=raw.get('implementation_status',variant['implementation_status'])
    if not entity.get('entity_id'):status='missing_entity';value=None;reason=entity.get('selection_reason','无代表')
    elif impl!='implemented':status='not_implemented';value=None
    elif not _isfinite(value) and not isinstance(value,str):status='missing_input';value=None
    elif not live and raw.get('last_valid'):status='old_history'
    elif live:status='intraday_estimate'
    else:status='daily_reference'
    # A complete current session is required for an explicit historical date.
    expected=selection.get('date') if selection['timing']=='历史日' else None
    if expected and time and str(_now(time).date())!=expected:
        status='old_history';reason=(reason+'；' if reason else '')+'所选历史日无有效值，保留最后有效历史及日期'
    n=raw.get('current_n') if live else raw.get('n')
    source_times=deepcopy(raw.get('current_source_times') if live and raw.get('current_source_times') else raw.get('source_times') or {})
    if live:
        quote_map={q.get('symbol'):q for q in state.get('quotes',[])}
        leg_times={s:quote_map.get(s,{}).get('source_event_time') for s in entity.get('legs',[])}
    else:leg_times=_history_sources(entity,context,time)
    source_times=source_times if live and raw.get('current_source_times') else {**leg_times,**source_times}
    history_cutoff=(raw.get('current_reference_end') or raw.get('current_history_cutoff')) if live else None
    if history_cutoff is None:history_cutoff=raw.get('reference_end') or raw.get('history_cutoff')
    if history_cutoff is None and not live and time:
        history_cutoff=time
        # Reference statistics explicitly exclude the displayed observation.
        if variant['family_id'].startswith('A03.') or variant['family_id'] in ('B09','B11'):
            history=[h.get('time') for h in raw.get('history',[]) if h.get('time') and _now(h['time'])<_now(time)]
            history_cutoff=max(history) if history else None
    versions=dict(dataset=state.get('versions',context.get('versions')),reference=context.get('reference_version'),
                  dividend=state.get('dividend_version',context.get('dividend_version')))
    versions.update(raw.get('input_versions') or {})
    visibility=entity.get('visibility_status',VISIBILITY_UNVERIFIED)
    role=variant.get('metric_roles',{}).get(raw.get('id'),'primary' if raw.get('id')==variant['primary'] else 'auxiliary')
    code=raw.get('id','')
    legacy=(code.startswith('pair.legacy_') or '.legacy_' in code and not code.startswith('A03.') or
            code.startswith(('B03.A.','B03.B.','B04.A.','B04.B.','B07.A.','B07.B.','B09.A.','B09.B.','B11.A.','B11.B.','B08.A.','B08.B.')) or
            code in ('B07.volume','B11.max','B12.balance'))
    construction=(raw.get('formula','') if role=='auxiliary' else variant.get('pair_construction') or raw.get('pair_construction',''))
    explanation=(variant.get('explanation','') if role=='primary' else
                 raw.get('explanation') or ('原口径辅助解释：' if legacy else '构造分量/辅助解释：')+raw.get('title',raw.get('id',''))+'。'+raw.get('formula',''))
    pair_metadata=deepcopy(raw.get('pair_metadata') or variant.get('pair_metadata') or {})
    if pair_metadata and (variant['input_id']=='fixed' or legacy):
        # Fixed Q/OI/capacity definitions must not inherit the default basis X
        # merely used to request all engine outputs. Legacy rows explain themselves.
        if legacy and not raw.get('id','').startswith('B12.legacy_'):
            pair_metadata={k:v for k,v in pair_metadata.items() if k in ('synchronization',)}
        pair_metadata.update(construction=raw.get('formula',''),unit=raw.get('unit',variant['unit']),
                             formula_version=FORMULA_VERSION if legacy else variant['formula_version'])
    result={**raw,'metric_id':raw.get('id'),'family_id':variant['family_id'],'variant_id':variant['variant_id'],
            'input_id':variant['input_id'],'entity_id':entity.get('entity_id'),'value':value,'time':time,
            'daily_value':daily_value,'daily_time':daily_time,'unit':raw.get('unit',variant['unit']),
            'source_times':source_times,'history_cutoff':history_cutoff,'n':n,
            'sample_status':'provided' if n is not None else '未提供有效样本计数',
            'input_versions':versions,'formula_version':FORMULA_VERSION if legacy else variant['formula_version'],
            'source_ref':raw.get('source_ref') or variant['source_ref'].split('；原 ')[-1] if legacy else variant['source_ref'],'implementation_status':impl,'data_status':status,
            'role':role,'pair_construction':construction,'explanation':explanation,
            'pair_metadata':pair_metadata,
            'direction':variant.get('direction','') if role=='primary' else '辅助解释；单位：'+str(raw.get('unit','')),
            'limitations':variant.get('limitations',''),
            'visibility_status':visibility,'reason':reason,'observed_at':now.isoformat(),
            'display_status':'visible',
            'current_supported':bool(raw.get('current_supported',raw.get('current') is not None or raw.get('current_reason') is not None))}
    if selection['timing']!='盘中优先':result.update(current=None,current_time=None,current_n=None)
    return result


def _collection_metrics(entity,context):
    from dashboard.native.nonregression import metric
    import numpy as np
    calendar=pd.DatetimeIndex(context.get('calendar',[]))
    groups=entity.get('member_groups',[]);growth=[];rows=[]
    for label,members in zip(('A','B'),groups):
        columns=[]
        for symbol in members:
            frame=context.get('daily',{}).get(symbol,pd.DataFrame()).reindex(calendar)
            oi=pd.to_numeric(frame.get('open_interest',pd.Series(np.nan,index=calendar)),errors='coerce')
            ref=context['metadata'].get(symbol,{})
            dates=calendar.tz_convert('Asia/Shanghai').strftime('%Y-%m-%d') if calendar.tz else calendar.strftime('%Y-%m-%d')
            oi=oi.where((dates>=ref.get('listing_date','9999'))&(dates<ref.get('expiry_date','0000')))
            columns.append(oi.rename(symbol))
        total=pd.concat(columns,axis=1).sum(axis=1,min_count=len(columns)) if columns else pd.Series(np.nan,index=calendar)
        valid=total.gt(0)&total.shift(5).gt(0)&total.notna().rolling(6).sum().eq(6)
        g=(100*np.log(total/total.shift(5))).where(valid);growth.append(g)
        for suffix,series,unit in (('total',total,'手'),('base',total.shift(5),'手'),('growth',g,'对数增长百分点'),('members',total*0+len(members),'份合约')):
            row=metric('B08.'+label+'.'+suffix,'固定集合'+label+' '+suffix,series,unit,
                       '100 ln(固定成员OI总和_t / 固定成员OI总和_t-5)',
                       '固定集合 '+entity['collection_id']+'；成员 '+', '.join(members))
            row.update(n=6 if suffix=='growth' and row['value'] is not None else None,
                       input_versions={'collection':entity['collection_id'],'members':members})
            rows.append(row)
    result=growth[0]-growth[1] if len(growth)==2 else growth[0] if growth else pd.Series(dtype=float)
    row=metric('B08','固定集合持仓扩张差' if len(growth)==2 else '固定集合持仓增长',result,'对数增长百分点',
               '两固定集合五日对数OI增长之差' if len(growth)==2 else '固定集合五日对数OI增长',
               '集合身份不随主力换月；不是实际账户移仓证据')
    row.update(n=6 if row['value'] is not None else None,input_versions={'collection':entity['collection_id'],'members':entity.get('members',[])})
    return [row,*rows]


def evaluate(model,selection=None,now=None,*,context=None):
    now=_now(now)
    if selection is None:selection=load_preferences(model.local_root) or {}
    selected=_normalize(selection,now);active=selected['active_page'];choice=selected['pages'][active]
    if choice.get('selection_error'):
        return dict(request_id=selected.get('request_id'),selection=selected,pages={},catalog=catalog(),
                    observed_at=now.isoformat(),error=choice['selection_error'])
    if choice['timing']=='历史日':
        date=choice.get('date','')
        try:
            historical=pd.Timestamp(date)
            if not date or historical.date()>=now.date():raise ValueError('历史日须早于今天')
            at=pd.Timestamp(str(historical.date())+' 15:01',tz='Asia/Shanghai')
        except (TypeError,ValueError):
            return dict(request_id=selected.get('request_id'),selection=selected,pages={},catalog=catalog(),
                        observed_at=now.isoformat(),error='历史日期无效或不早于今天')
    else:at=now
    context=_bounded_context(context if context is not None else _context(model,at),at)
    metadata=context.get('metadata',{});daily=context.get('daily',{});calendar=context.get('calendar',[])
    pages={}
    for page,title in PAGES.items():
        prefs=selected['pages'][page]
        variant=find_variant(prefs['variant_id'],category=page) if prefs.get('variant_id') else None
        reps=_fixed_daily_representatives(model,context,at,page)
        directory=[{**entry,'unit':entry.get('unit_by_category',{}).get(page,entry['unit']),
                    'loaded':False,'entities':[],'representative_count':6 if page=='cross' else 4} for entry in catalog(page)]
        pages[page]=dict(id=page,title=title,groups=directory,representatives=reps,entities=[],
                         selected_variant_id=variant['variant_id'] if variant else None,selected_group=None,selection=prefs,
                         total=0,offset=0,limit=20,loaded=False)
    page=pages[active];variant=find_variant(choice['variant_id'],category=active)
    if variant['entity_kind']=='collection':
        entities=fixed_collections(metadata,at,active)
        page['representatives']=deepcopy(entities)
    elif choice['scope']=='representatives':entities=deepcopy(page['representatives'])
    else:entities=all_entities(metadata,at,active,include_history=choice['scope']=='history',expiry_mode=choice['expiry_mode'])
    entities,total,offset,limit=paginate(entities,choice)
    values=[];frozen_versions=context.get('versions');versions_changed=False
    for item in entities:
        valid,why=applicability(variant,item)
        state={};metrics=[]
        if item.get('kind')=='collection':metrics=_collection_metrics(item,context)
        elif item.get('entity_id') and valid:
            state=model.snapshot(dict(cards=False,left=item['left'],right=item['right'],category=active,
                                      price_input='basis' if variant['input_id']=='fixed' else variant['input_id'],
                                      as_of=at.isoformat(),allow_mixed_expiry=True,
                                      participation=choice.get('participation')))
            metrics=[r for r in state.get('metrics',[]) if r['id'] in variant['metric_ids']]
            if variant['family_id']=='B08':
                roots=list(dict.fromkeys(item.get('roots',[])))
                collection=next((c for c in fixed_collections(metadata,at,active) if c['roots']==roots),None)
                if collection:
                    for legacy in _collection_metrics(collection,context):
                        if legacy['id']=='B08':legacy['id']='B08.legacy_collection'
                        legacy.update(role='auxiliary',source_times=_history_sources(collection,context,legacy.get('time')),
                                      collection_id=collection['collection_id'],collection_members=collection['members'])
                        metrics.append(legacy)
            why=state.get('pair_error') or why
            version=state.get('versions')
            if version is not None:
                if frozen_versions is None:frozen_versions=version
                elif version!=frozen_versions:
                    metrics=[];why='计算期间数据版本改变；请刷新完整页面';versions_changed=True
        # Registered, applicable children are part of the result schema even
        # when an engine branch needs collection observations it has not got.
        # Use the child's own dimensions/formula; never copy the primary unit.
        present={row['id']:row for row in metrics}
        ids=variant['metric_ids'] if valid else [variant['primary']]
        metrics=[]
        for code in ids:
            if code in present:
                metrics.append(present[code]);continue
            definition=variant['metric_definitions'][code]
            reason='；'.join(s for s in (why or item.get('selection_reason'),definition['missing_reason']) if s)
            metrics.append(dict(id=code,title=definition['title'],value=None,time=None,current=None,
                                current_time=None,n=None,unit=definition['unit'],formula=definition['formula'],
                                scope=definition['scope'],reason=reason,
                                current_reason=reason if definition['current_supported'] else None,
                                current_supported=definition['current_supported'],
                                implementation_status=variant['implementation_status'],history=[]))
        output=[result_contract(r,variant,item,state,context,choice,at) for r in metrics]
        if not valid:
            for r in output:r.update(data_status='not_applicable',value=None,reason=why)
        primary=next((r for r in output if r['id']==variant['primary']),output[0])
        values.append({**item,'metrics':output,'primary':primary,'error':why or None,
                       'selection_type':item.get('selection_type','指定具体实体'),
                       'visibility_status':item.get('visibility_status',VISIBILITY_UNVERIFIED)})
    if versions_changed:
        for item in values:
            item['error']='计算期间数据版本改变；请刷新完整页面'
            for row in item['metrics']:
                row.update(value=None,current=None,data_status='input_version_changed',reason=item['error'])
    group=next(g for g in page['groups'] if g['variant_id']==variant['variant_id'])
    group.update(loaded=True,entities=values)
    page.update(entities=values,selected_group=group,total=total,offset=offset,limit=limit,loaded=True)
    return dict(request_id=selected.get('request_id'),selection=selected,pages=pages,catalog=catalog(),contracts=sorted(metadata),
                observed_at=at.isoformat(),active_page=active,formula_version=variant['formula_version'],
                versions=context.get('versions'),error=None)


evaluate_pages=evaluate


def directory_rows(page):
    return [[g['family_id'],g['variant_id'],g['title'],g['representative_count'],
             '已加载' if g['loaded'] else '选择后加载'] for g in page.get('groups',[])]


def _times(row):
    return ' / '.join(s+': '+str(t or '未知') for s,t in (row.get('source_times') or {}).items())


def page_rows(page):
    values=[]
    for entity in page.get('entities',[]):
        row=entity.get('primary',{})
        note='；'.join(s for s in (entity.get('selection_type'),entity.get('selection_reason'),row.get('visibility_status'),row.get('reason')) if s)
        values.append([row.get('family_id'),row.get('variant_id'),entity.get('title'),row.get('value'),
                       row.get('unit'),_times(row),row.get('history_cutoff'),row.get('n'),
                       row.get('implementation_status'),row.get('data_status'),note])
    return values


def detail_rows(value):
    entities=value.get('entities',[]) if 'entities' in value else [value]
    return [[entity.get('title','')+' · '+r.get('id',''),r.get('value'),r.get('unit'),_times(r),
             r.get('history_cutoff'),r.get('n'),r.get('implementation_status'),r.get('data_status'),
             json.dumps(r.get('input_versions'),ensure_ascii=False,sort_keys=True),
             '；'.join(s for s in (r.get('reason'),r.get('visibility_status'),r.get('sample_status')) if s),r.get('formula','')]
            for entity in entities for r in entity.get('metrics',[])]
