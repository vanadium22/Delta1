"""Minute equity snapshots and index-internal attribution, without acquisition."""
from collections import defaultdict
import json
from pathlib import Path

import pandas as pd

from .overview_reference import finite
from .quote_quality import quote_quality


def equity_path(config, local_root):
    return Path(config.get('overview_equity_file') or Path(local_root)/'overview_equities/latest.json')


def read_equities(config, local_root):
    try:
        data = json.loads(equity_path(config, local_root).read_text(encoding='utf8'))
        if (not isinstance(data,dict) or data.get('schema') != 'overview-equities-v1' or
            not isinstance(data.get('quotes'), dict) or not isinstance(data.get('snapshot_id'),str)):
            raise ValueError('成分快照格式无效')
        valid={s:q for s,q in data['quotes'].items() if isinstance(q,dict)}
        data['invalid_quote_count']=len(data['quotes'])-len(valid)
        data['quotes']=valid
        return data
    except (OSError, ValueError, TypeError):
        return {}


def equity_max_age(snapshot):
    if snapshot.get('mode')!='rolling':return 30
    try:return max(30,min(900,float(snapshot.get('quote_max_age_seconds',360))))
    except (ValueError,TypeError):return 360


def contributions(group, snapshot, index_row, now, previous, reference_version):
    rows=group.get('rows',[]);closed=snapshot.get('mode')=='completed_daily'
    result=dict(rows=[],industries=[],leaders=[],laggards=[],source_at=None,snapshot_at=snapshot.get('finished_at'),
        coverage_pct=None,covered=0,weighted_covered=0,expected=len(rows),up=None,down=None,flat=None,up_pct=None,
        actual_points=None,actual_return_pct=None,pricing_day=None,contribution_points=None,residual_points=None,
        weight_date=group.get('as_of'),official_weight_date=group.get('official_as_of',group.get('as_of')),
        weight_method=group.get('weight_method','provided_reference'),weight_reason=group.get('weight_reason'),
        weight_source_dates=group.get('weight_source_dates',[]),industry_standard=group.get('industry_standard'),
        mode=snapshot.get('mode','minute'),reason='缺成分名单；股票数据缺口数量尚未知',estimate=True,
        weights_complete=group.get('weights_complete') is not False,
        inputs=dict(membership_available=bool(rows),missing_weights=0,missing_industries=0,missing_quotes=0,
            missing_previous_closes=0,index_previous_close_valid=False,reference_matches=False,previous_weights_valid=False))
    if not rows:
        for key in ('missing_weights','missing_industries','missing_quotes','missing_previous_closes'):result['inputs'][key]=None
        return result
    try:
        cutoff=pd.Timestamp(snapshot.get('finished_at'))
        if pd.isna(cutoff) or cutoff.tzinfo is None or cutoff>now:cutoff=None
    except (ValueError,TypeError):cutoff=None
    same_day=bool(snapshot.get('pricing_day') and snapshot['pricing_day']<=str(now.tz_convert('Asia/Shanghai').date())) if closed else bool(cutoff is not None and cutoff.tz_convert('Asia/Shanghai').date()==now.tz_convert('Asia/Shanghai').date())
    valid_cutoff=cutoff is not None and same_day
    if valid_cutoff:
        result['pricing_day']=snapshot.get('pricing_day') if closed else str(cutoff.tz_convert('Asia/Shanghai').date())
    # A reference SHA also changes for NAV updates. Match current membership by
    # stock code; an unrelated reference update must not erase valid prices.
    quotes=snapshot.get('quotes',{}) if valid_cutoff else {}
    base_quote=quotes.get(index_row['symbol'],{})
    if not isinstance(base_quote,dict):base_quote={}
    base=base_quote.get('prev_close')
    if not finite(base) or base<=0:
        candidate=index_row.get('prev_close')
        try:source=pd.Timestamp(index_row.get('source_at'));source_day=str(source.tz_convert('Asia/Shanghai').date()) if source.tzinfo is not None else None
        except (ValueError,TypeError):source_day=None
        wanted=snapshot.get('pricing_day') if closed else str(now.tz_convert('Asia/Shanghai').date())
        if source_day==wanted and finite(candidate) and candidate>0:base=candidate
    base_valid=finite(base) and base>0
    def weight(member):
        value=member.get('weight_pct')
        return value if finite(value) and 0<=value<=100 else None
    result['inputs'].update(missing_weights=sum(weight(r) is None for r in rows),
        missing_industries=sum(not r.get('industry') for r in rows),index_previous_close_valid=bool(base_valid),
        reference_matches=snapshot.get('reference_version')==reference_version,
        previous_weights_valid=group.get('weights_complete') is not False and group.get('as_of')==previous,
        snapshot_valid=bool(valid_cutoff))
    def usable(q):
        if not isinstance(q,dict):return False
        if closed:return (q.get('source_kind')=='completed_daily' and q.get('trade_date')==snapshot.get('pricing_day') and
            q.get('source_event_time')==snapshot.get('pricing_at') and finite(q.get('close')) and q['close']>0)
        return bool(q) and quote_quality(q,cutoff,max_age=equity_max_age(snapshot))['usable']
    groups=defaultdict(list);times=[]
    for member in rows:
        q=quotes.get(member['symbol'],{})
        if not isinstance(q,dict):q={}
        prior=q.get('prev_close');valid=usable(q) and finite(prior) and prior>0
        if not usable(q):result['inputs']['missing_quotes']+=1
        if not finite(prior) or prior<=0:result['inputs']['missing_previous_closes']+=1
        ret=100*(q['close']/prior-1) if valid else None;w=weight(member)
        point=base*w/100*ret/100 if valid and w is not None and base_valid else None
        item=dict(symbol=member['symbol'],name=member.get('name') or member['symbol'],industry=member.get('industry') or '待分类',
            weight_pct=w,weight_date=(group.get('as_of') if group.get('weight_method')=='fixed_quantity_estimate' else
                member.get('reference_date') or (None if group.get('weights_complete') is False else group.get('as_of'))),
            change_pct=ret,contribution_points=point,source_at=q.get('source_event_time') if valid else None)
        result['rows'].append(item);groups[item['industry']].append(item)
        if valid:times.append(pd.Timestamp(q['source_event_time']))
    covered=[r for r in result['rows'] if r['change_pct'] is not None]
    weighted=[r for r in covered if r['weight_pct'] is not None]
    result.update(covered=len(covered),weighted_covered=len(weighted),coverage_pct=sum(r['weight_pct'] for r in weighted) if weighted else None,
        partial=len(weighted)<len(rows),complete=len(weighted)==len(rows),
        up=sum(r['change_pct']>0 for r in covered),down=sum(r['change_pct']<0 for r in covered),flat=sum(r['change_pct']==0 for r in covered),
        up_pct=100*sum(r['change_pct']>0 for r in covered)/len(covered) if covered else None,
        source_at=min(times).isoformat() if times else None)
    for name,members in groups.items():
        known=[r for r in members if r['weight_pct'] is not None]
        priced=[r for r in known if r['change_pct'] is not None]
        total=sum(r['weight_pct'] for r in known);used=sum(r['weight_pct'] for r in priced)
        points=[r['contribution_points'] for r in priced if r['contribution_points'] is not None]
        partial=len(priced)<len(members)
        reason='按已有 '+str(len(priced))+'/'+str(len(members))+'只及已知权重计算；权重日 '+str(group.get('as_of') or '待核验')
        missing_prices=sum(r['change_pct'] is None for r in members)
        if missing_prices:reason+='；缺有效行情 '+str(missing_prices)+'只'
        if len(known)<len(members):reason+='；缺权重 '+str(len(members)-len(known))+'只'
        result['industries'].append(dict(name=name,weight_pct=total if known else None,covered_weight_pct=used if priced else None,
            change_pct=sum(r['weight_pct']*r['change_pct'] for r in priced)/used if used>0 else None,
            contribution_points=sum(points) if points else None,complete=not partial,partial=partial,
            covered=len(priced),expected=len(members),reason=reason,
            members=members))
    result['industries'].sort(key=lambda r:(r['weight_pct'] is None,-(r['weight_pct'] or 0),r['name']))
    eligible=[r for r in result['industries'] if r['name']!='待分类' and r['contribution_points'] is not None]
    result['leaders']=sorted((r for r in eligible if r['contribution_points']>0),key=lambda r:-r['contribution_points'])[:3]
    result['laggards']=sorted((r for r in eligible if r['contribution_points']<0),key=lambda r:r['contribution_points'])[:3]
    points=[r['contribution_points'] for r in weighted if r['contribution_points'] is not None]
    result['contribution_points']=sum(points) if points else None
    index_quote=quotes.get(index_row['symbol'],{})
    if not isinstance(index_quote,dict):index_quote={}
    if valid_cutoff and usable(index_quote) and finite(index_quote.get('prev_close')) and index_quote['prev_close']>0:
        result['actual_points']=index_quote['close']-index_quote['prev_close']
        result['actual_return_pct']=100*(index_quote['close']/index_quote['prev_close']-1)
    if result['actual_points'] is not None and result['contribution_points'] is not None:
        result['residual_points']=result['actual_points']-result['contribution_points']
    result['reason']=('收盘参考 '+snapshot['pricing_day']+'；' if closed else '')+'按有效成分已有权重计算；权重日 '+str(group.get('as_of') or '待核验')
    if not valid_cutoff:result['reason']='待同日有效成分报价；保留上次显示结果'
    if group.get('as_of')!=previous:result['reason']+='；权重非准确昨日，保留原参考日期'
    if snapshot.get('reference_version')!=reference_version:result['reason']+='；资料版本变化，按当前成员代码匹配'
    for key,label in [('missing_weights','缺权重'),('missing_industries','缺行业'),('missing_quotes','缺有效报价'),('missing_previous_closes','缺昨收')]:
        if result['inputs'][key]:result['reason']+='；'+label+str(result['inputs'][key])+'只'
    if not base_valid:result['reason']+='；缺指数昨收，点贡献待来源'
    return result
