"""Compare validated dated index-weight snapshots without acquiring data."""
from collections import defaultdict
from datetime import datetime
import json

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
        current_classified_weight=a['classified'],previous_classified_weight=b['classified'],reclassified=changed)


def load(config,local_root,reference,current_groups,*,previous_day=None):
    result={root:dict(rows=[],reason='暂无上一份可比权重快照') for root in current_groups}
    try:
        cutoff=datetime.fromisoformat(reference['fetched_at'])
        paths=sorted((path_for(config,local_root).parent/'archive').glob('*.json'),reverse=True)
    except (OSError,ValueError,KeyError,TypeError):return result
    candidates={root:[] for root in current_groups};total=0;truncated=len(paths)>64
    if previous_day:
        from .overview_weights import roll
        for root,current in current_groups.items():
            anchor=reference.get('indices',{}).get(root,{})
            anchor_day=anchor.get('as_of');current_day=current.get('as_of')
            if (current.get('weight_method')!='fixed_quantity_estimate' or not anchor_day or not current_day or
                    not anchor_day<=previous_day<current_day):continue
            previous=roll(anchor,config,local_root,previous_day)
            compared=compare(current,previous,previous_at=reference['fetched_at'])
            if compared.get('rows'):candidates[root].append((previous['as_of'],cutoff,compared))
    for path in paths[:64]:
        try:
            size=path.stat().st_size
            if size>4*1024*1024:continue
            if total+size>32*1024*1024:truncated=True;break
            raw=path.read_bytes();total+=len(raw);decoded=json.loads(raw)
            if not isinstance(decoded,dict):continue
            value,_=available_sections({k:decoded[k] for k in ('schema','fetched_at','reference_reviewed_at','indices') if k in decoded})
            fetched=datetime.fromisoformat(value['fetched_at'])
            if fetched>cutoff:continue
            for root,current in current_groups.items():
                old=value.get('indices',{}).get(root)
                if not old or not current.get('as_of') or old['as_of']>current['as_of']:continue
                if old['as_of']==current['as_of'] and (fetched>=cutoff or weights(old)==weights(current)):continue
                compared=compare(current,old,previous_at=value['fetched_at'])
                if compared.get('rows'):candidates[root].append((old['as_of'],fetched,compared))
        except (OSError,ValueError,TypeError,KeyError,AttributeError):continue
    for root,items in candidates.items():
        if items:result[root]=max(items,key=lambda item:(item[0],item[1]))[2]
        result[root]['archive_truncated']=truncated
        if truncated and not items:result[root]['reason']+='；归档读取已达上限'
    return result
