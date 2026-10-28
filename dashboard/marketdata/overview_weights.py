"""Explicit, full-universe fixed-quantity weight estimates between weekly reviews."""
from copy import deepcopy
from datetime import date

from .overview_reference import finite
from .overview_daily import read_day,quote_rows


def roll(group,config,local_root,previous):
    if group.get('weights_complete') is False:return group
    anchor=group.get('as_of')
    if not anchor or not previous or anchor==previous:return group
    if not 0<abs((date.fromisoformat(previous)-date.fromisoformat(anchor)).days)<=14:return group
    prior=read_day(config,local_root,previous).get('rows',{})
    anchors=read_day(config,local_root,anchor).get('rows',{})
    adjusted=[]
    for member in group.get('rows',[]):
        old=anchors.get(member['symbol'],{});new=prior.get(member['symbol'],{})
        a=old.get('close')
        if not finite(a) and member.get('anchor_date')==anchor:a=member.get('anchor_close')
        p=new.get('close')
        if not all(finite(v) and v>0 for v in (a,p)):return group
        factors=(old.get('adjustment_factor'),new.get('adjustment_factor'))
        if all(finite(v) for v in factors) and factors[0]!=factors[1]:return group
        if not .5<p/a<2:return group
        adjusted.append((member,member['weight_pct']*p/a))
    total=sum(v for _,v in adjusted)
    if not total:return group
    result=deepcopy(group)
    result.update(official_as_of=anchor,as_of=previous,weight_method='fixed_quantity_estimate',
        weight_reason='全成分收盘价滚动估算；假设成分、自由流通股本不变，未认证公司行动；非官方昨日权重')
    result['rows']=[dict(m,official_weight_pct=m['weight_pct'],weight_pct=100*v/total) for m,v in adjusted]
    return result


def closed_snapshot(config,local_root,day,version):
    data=read_day(config,local_root,day)
    return dict(schema='overview-equities-v1',snapshot_id='close:'+str(day)+':'+str(data.get('fetched_at')),
        reference_version=version,finished_at=data.get('fetched_at'),pricing_day=day,
        pricing_at=str(day)+'T15:00:00+08:00',mode='completed_daily',quotes=quote_rows(config,local_root,day))
