"""Compare validated dated index-weight snapshots without acquiring data."""
from collections import defaultdict
from datetime import date,datetime
import json
from zoneinfo import ZoneInfo

from .overview_reference import available_sections,finite,path_for


def token(config,local_root):
    path=path_for(config,local_root).parent/'archive'
    try:return str(path),path.stat().st_mtime_ns
    except OSError:return str(path),None


def weights(group):
    rows=group.get('rows') or []
    if not rows or group.get('weights_complete') is False or not group.get('as_of'):
        return None
    if any(not finite(r.get('weight_pct')) or not 0<=r['weight_pct']<=100 for r in rows):return None
    totals=defaultdict(float);classifications={}
    for row in rows:
        name=row.get('industry') or '待分类'
        totals[name]+=row['weight_pct'];classifications[row['symbol']]=name
    return dict(totals=dict(totals),classifications=classifications,
                classified=sum(v for k,v in totals.items() if k!='待分类'))


def compare(current,previous,*,previous_at=None):
    a=weights(current);b=weights(previous)
    if not a or not b:return dict(rows=[],reason='权重或成分不完整，等待可比快照')
    if not current.get('index_id') or current.get('index_id')!=previous.get('index_id') or previous['as_of']>current['as_of']:
        return dict(rows=[],reason='指数身份或权重日期不匹配')
    standard=current.get('industry_standard')
    if not standard or standard!=previous.get('industry_standard'):
        return dict(rows=[],reason='行业分类口径缺失或变化，等待可比快照')
    method=current.get('weight_method','provided_reference');old_method=previous.get('weight_method','provided_reference')
    anchored=False
    if method!=old_method:
        official={r.get('symbol'):r.get('official_weight_pct') for r in current.get('rows',[])}
        prior={r.get('symbol'):r.get('weight_pct') for r in previous.get('rows',[])}
        anchored=(method=='fixed_quantity_estimate' and old_method=='provided_reference' and
                  current.get('official_as_of')==previous.get('as_of') and official.keys()==prior.keys() and
                  bool(official) and all(finite(official[k]) and finite(prior[k]) and abs(official[k]-prior[k])<1e-9 for k in official))
        if not anchored:return dict(rows=[],reason='权重方法不同，等待同口径快照')
    common=a['classifications'].keys() & b['classifications'].keys()
    changed=sum(a['classifications'][s]!=b['classifications'][s] for s in common)
    rows=[dict(name=name,current_pct=a['totals'].get(name,0.0),previous_pct=b['totals'].get(name,0.0),
               change_pp=a['totals'].get(name,0.0)-b['totals'].get(name,0.0))
          for name in a['totals'].keys() | b['totals'].keys()]
    rows.sort(key=lambda r:(-abs(r['change_pp']),r['name']))
    reason='两次同口径行业总权重之差，单位百分点'
    if anchored:reason+='；当前按上次官方权重滚动估算'
    elif method=='fixed_quantity_estimate':reason+='；两次均为固定持股滚动估算'
    if changed:reason+='；'+str(changed)+'只成分的行业分类发生变化'
    return dict(rows=rows,reason=reason,current_date=current['as_of'],previous_date=previous['as_of'],
        previous_fetched_at=previous_at,industry_standard=standard,weight_method=method,previous_weight_method=old_method,
        current_classified_weight=a['classified'],previous_classified_weight=b['classified'],reclassified=changed,
        comparison_kind='complete_history',partial=False)


def _row_day(group,row):
    """Incomplete groups require each weight's own real source date."""
    raw=row.get('reference_date')
    if not raw and group.get('weights_complete') is False:return None
    try:
        actual=date.fromisoformat(raw or group['as_of']).isoformat()
        limit=date.fromisoformat(group['as_of']).isoformat()
    except (TypeError,ValueError,KeyError):return None
    if actual>limit or (group.get('weights_complete') is not False and actual!=limit):return None
    return actual


def partial_compare(current,previous,*,previous_at=None):
    """Compare only genuinely dated, paired constituent weights; never fill gaps."""
    if not current.get('index_id') or current.get('index_id')!=previous.get('index_id'):return None
    if not current.get('industry_standard') or current.get('industry_standard')!=previous.get('industry_standard'):return None
    if not current.get('source') or current.get('source')!=previous.get('source'):return None
    if current.get('weights_complete') is not False and previous.get('weights_complete') is not False:return None
    a=current.get('weight_method','provided_reference');b=previous.get('weight_method','provided_reference')
    if a!=b and not {a,b}<={'source_reference','incomplete_reference'}:return None
    old={r.get('symbol'):r for r in previous.get('rows',[]) if isinstance(r,dict) and r.get('symbol')}
    totals=defaultdict(lambda:[0.,0.]);current_days=[];previous_days=[];count=0;unknown=0;reclassified=0
    for row in current.get('rows',[]):
        prior=old.get(row.get('symbol'))
        if not prior:continue
        x,y=row.get('weight_pct'),prior.get('weight_pct');today=_row_day(current,row);before=_row_day(previous,prior)
        if not (finite(x) and finite(y) and 0<=x<=100 and 0<=y<=100 and today and before and before<today):continue
        now_industry=row.get('industry');old_industry=prior.get('industry')
        if now_industry and old_industry and now_industry!=old_industry:
            reclassified+=1;continue
        name=now_industry if now_industry and old_industry else '待分类'
        if name=='待分类':unknown+=1
        totals[name][0]+=x;totals[name][1]+=y
        current_days.append(today);previous_days.append(before);count+=1
    if not count:return None
    rows=[dict(name=name,current_pct=pair[0],previous_pct=pair[1],change_pp=pair[0]-pair[1]) for name,pair in totals.items()]
    rows.sort(key=lambda r:(-abs(r['change_pp']),r['name']))
    current_range=[min(current_days),max(current_days)];previous_range=[min(previous_days),max(previous_days)]
    current_weight=sum(v[0] for v in totals.values());previous_weight=sum(v[1] for v in totals.values())
    reason=('部分成分配对：'+str(count)+'/'+str(len(current.get('rows',[])))+'只；当前样本权重 '+
            f'{current_weight:.2f}%；缺权重、缺日期及未配对成分不纳入，非完整指数变化')
    if previous_range[0]!=previous_range[1] or current_range[0]!=current_range[1]:reason+='；源权重日期不完全一致'
    if unknown:reason+='；'+str(unknown)+'只待分类'
    if reclassified:reason+='；'+str(reclassified)+'只分类变化未纳入'
    return dict(rows=rows,reason=reason,comparison_kind='partial_history',partial=True,
        current_date=current_range[0] if current_range[0]==current_range[1] else None,
        previous_date=previous_range[0] if previous_range[0]==previous_range[1] else None,
        current_date_range=current_range,previous_date_range=previous_range,previous_fetched_at=previous_at,
        industry_standard=current['industry_standard'],weight_method=a,previous_weight_method=b,
        paired_members=count,current_members=len(current.get('rows',[])),paired_current_weight=current_weight,
        paired_previous_weight=previous_weight,unclassified_paired=unknown,reclassified_excluded=reclassified)


def estimate_from_returns(detail,previous_day):
    """Estimate weight movement from real paired returns and existing weights."""
    if not isinstance(detail,dict) or not detail.get('snapshot_at') or not previous_day:return None
    try:
        cutoff=datetime.fromisoformat(detail['snapshot_at']);previous=date.fromisoformat(previous_day).isoformat()
        if cutoff.tzinfo is None:return None
        pricing=date.fromisoformat(detail.get('pricing_day') or cutoff.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()).isoformat()
        if pricing>cutoff.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat():return None
        if detail.get('mode')=='completed_daily' and not detail.get('pricing_day'):return None
    except (ValueError,TypeError):return None
    if previous>=pricing:return None
    members=[]
    for row in detail.get('rows',[]):
        weight=row.get('weight_pct');change=row.get('change_pct');source=row.get('source_at')
        try:
            at=datetime.fromisoformat(source);weight_day=date.fromisoformat(row['weight_date']).isoformat()
            if at.tzinfo is None or at>cutoff or at.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()!=pricing:continue
        except (TypeError,ValueError,KeyError):continue
        if not (finite(weight) and 0<weight<=100 and finite(change) and change>-100 and weight_day<=previous):continue
        members.append((row,weight,change,weight_day))
    if not members:return None
    total=sum(w for _,w,_,_ in members)
    if not total:return None
    index_return=detail.get('actual_return_pct')
    if finite(index_return) and index_return>-100:
        denominator=1+index_return/100;denominator_source='同快照指数涨跌'
    else:
        denominator=sum(w*(1+r/100) for _,w,r,_ in members)/total
        denominator_source='已覆盖成分加权涨跌估算'
    if denominator<=0:return None
    groups=defaultdict(lambda:[0.,0.]);dates=[]
    for row,weight,change,weight_day in members:
        name=row.get('industry') or '待分类';groups[name][0]+=weight*(1+change/100)/denominator;groups[name][1]+=weight;dates.append(weight_day)
    rows=[dict(name=name,current_pct=values[0],previous_pct=values[1],change_pp=values[0]-values[1]) for name,values in groups.items()]
    rows.sort(key=lambda r:(-abs(r['change_pp']),r['name']))
    anchor=[min(dates),max(dates)];stale=bool(detail.get('stale'))
    reason=('估算：沿用既有权重，按同次成分相对涨跌推算；'+str(len(members))+'/'+str(len(detail.get('rows',[])))+
            f'只、样本权重 {total:.2f}%；缺失不补零；分母为'+denominator_source+'；非官方完整权重变化')
    if anchor[0]!=anchor[1]:reason+='；基准权重日期不完全一致'
    if stale:reason+='；成分数据已停更，保留原截止时间'
    return dict(rows=rows,reason=reason,comparison_kind='return_estimate',partial=True,estimate=True,stale=stale,
        current_date=pricing,previous_date=previous,current_date_range=[pricing,pricing],
        anchor_date_range=anchor,source_at=min((row['source_at'] for row,_,_,_ in members),key=datetime.fromisoformat),snapshot_at=detail['snapshot_at'],
        industry_standard=detail.get('industry_standard'),weight_method='return_estimate',
        previous_weight_method=detail.get('weight_method'),denominator_source=denominator_source,
        paired_members=len(members),current_members=len(detail.get('rows',[])),anchor_weight=total,
        paired_current_weight=sum(r['current_pct'] for r in rows),
        current_classified_weight=sum(r['current_pct'] for r in rows if r['name']!='待分类'))


def load(config,local_root,reference,current_groups,*,previous_day=None):
    result={root:dict(rows=[],reason='暂无上一份可比权重快照',current_date=group.get('as_of'),
        industry_standard=group.get('industry_standard'),weight_method=group.get('weight_method','provided_reference'))
        for root,group in current_groups.items()}
    try:
        cutoff=datetime.fromisoformat(reference['fetched_at'])
        paths=sorted((path_for(config,local_root).parent/'archive').glob('*.json'),reverse=True)
    except (OSError,ValueError,KeyError,TypeError):return result
    candidates={root:[] for root in current_groups};partials={root:[] for root in current_groups};total=0;truncated=len(paths)>64;files_read=0
    checks={root:dict(archive_groups=0,duplicate_groups=0,incompatible_groups=0,invalid_groups=0,
        partial_groups=0,roll_attempted=False,roll_comparable=False,last_incompatible_reason=None,
        current_members=len(group.get('rows') or []),unclassified_members=sum(not r.get('industry') for r in group.get('rows') or []))
        for root,group in current_groups.items()}
    if previous_day:
        from .overview_weights import roll
        for root,current in current_groups.items():
            anchor=reference.get('indices',{}).get(root,{})
            anchor_day=anchor.get('as_of');current_day=current.get('as_of')
            if (current.get('weight_method')!='fixed_quantity_estimate' or not anchor_day or not current_day or
                    not anchor_day<=previous_day<current_day):continue
            checks[root]['roll_attempted']=True
            previous=roll(anchor,config,local_root,previous_day)
            compared=compare(current,previous,previous_at=reference['fetched_at'])
            if compared.get('rows'):
                candidates[root].append((previous['as_of'],cutoff,compared));checks[root]['roll_comparable']=True
    for path in paths[:64]:
        try:
            size=path.stat().st_size
            if size>4*1024*1024:continue
            if total+size>32*1024*1024:truncated=True;break
            raw=path.read_bytes();total+=len(raw);files_read+=1;decoded=json.loads(raw)
            if not isinstance(decoded,dict):continue
            value,issues=available_sections({k:decoded[k] for k in ('schema','fetched_at','reference_reviewed_at','indices') if k in decoded})
            fetched=datetime.fromisoformat(value['fetched_at'])
            if fetched>cutoff:continue
            for root,current in current_groups.items():
                if any(i.get('scope')=='indices.'+root for i in issues):checks[root]['invalid_groups']+=1
                old=value.get('indices',{}).get(root)
                if not old or not current.get('as_of'):continue
                if old['as_of']>current['as_of'] and old.get('weights_complete') is not False:continue
                checks[root]['archive_groups']+=1
                old_weights=weights(old)
                if old['as_of']==current['as_of'] and (fetched>=cutoff or (old_weights is not None and old_weights==weights(current))):
                    checks[root]['duplicate_groups']+=1;continue
                compared=compare(current,old,previous_at=value['fetched_at'])
                if compared.get('rows'):candidates[root].append((old['as_of'],fetched,compared))
                else:
                    checks[root]['incompatible_groups']+=1;checks[root]['last_incompatible_reason']=compared.get('reason')
                    partial=partial_compare(current,old,previous_at=value['fetched_at'])
                    if partial:
                        partials[root].append((partial['previous_date_range'][1],partial['paired_current_weight'],fetched,partial))
                        checks[root]['partial_groups']+=1
        except (OSError,ValueError,TypeError,KeyError,AttributeError):continue
    for root,items in candidates.items():
        if items:result[root]=max(items,key=lambda item:(item[0],item[1]))[2]
        elif partials[root]:result[root]=max(partials[root],key=lambda item:(item[0],item[1],item[2]))[3]
        else:
            current=current_groups[root];check=checks[root]
            if not weights(current):result[root]['reason']='当前权重或成分不完整，等待可比快照'
            elif not current.get('industry_standard'):result[root]['reason']='当前行业分类口径缺失，等待可比快照'
            elif check['incompatible_groups']:result[root]['reason']='上一份不可比：'+str(check['last_incompatible_reason'])
            elif check['archive_groups'] and check['archive_groups']==check['duplicate_groups']:
                result[root]['reason']='归档仅有相同权重，等待上一份可比快照'
            elif check['invalid_groups']:result[root]['reason']='历史权重分组不完整，等待可比快照'
        result[root]['archive_truncated']=truncated
        result[root]['diagnostics']=dict(checks[root],archive_files_read=files_read)
        if truncated and not items:result[root]['reason']+='；归档读取已达上限'
    return result


def summary(value):
    """Only the comparison decision and bounded counts, never member rows."""
    if not isinstance(value,dict):return None
    keys=('reason','current_date','previous_date','current_date_range','previous_date_range','anchor_date_range',
          'previous_fetched_at','industry_standard','weight_method','previous_weight_method','comparison_kind',
          'partial','estimate','stale','paired_members','current_members','anchor_weight','paired_current_weight','paired_previous_weight',
          'unclassified_paired','reclassified_excluded','denominator_source','source_at','snapshot_at','historical_fallback_reason',
          'current_classified_weight','previous_classified_weight','reclassified','archive_truncated')
    out={k:value.get(k) for k in keys}
    rows=value.get('rows') if isinstance(value.get('rows'),list) else []
    out['row_count']=value.get('row_count') if type(value.get('row_count')) is int else len(rows)
    d=value.get('diagnostics') if isinstance(value.get('diagnostics'),dict) else {}
    fields=('archive_files_read','archive_groups','duplicate_groups','incompatible_groups','invalid_groups','partial_groups',
            'roll_attempted','roll_comparable','last_incompatible_reason','current_members','unclassified_members')
    out['diagnostics']={k:d.get(k) for k in fields}
    return out
