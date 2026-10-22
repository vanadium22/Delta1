"""Deterministic T-1 representatives and fixed research entities.

No current quote, rank slot or availability of an indicator changes an entity.
Unknown historical publication evidence is reported instead of invented.
"""
from hashlib import sha256
from itertools import combinations, product
import math
import pandas as pd

from dashboard.native.instruments import UNDERLYINGS

PRODUCTS=('IF','IH','IC','IM')
VISIBILITY_UNVERIFIED='修订历史参考 / 可见性未认证'


def _stamp(value):
    stamp=pd.Timestamp(value)
    return stamp.tz_localize('Asia/Shanghai') if stamp.tzinfo is None else stamp.tz_convert('Asia/Shanghai')


def _number(value):
    try:return not isinstance(value,bool) and math.isfinite(float(value))
    except (ValueError,TypeError):return False


def decision_day(observed_at, calendar):
    """The supplied trading calendar is authoritative, including missing data days."""
    day=_stamp(observed_at).date()
    days=sorted({_stamp(t).date() for t in calendar if _stamp(t).date()<day})
    return str(days[-1]) if days else None


def _day_row(frame, day):
    if frame is None or frame.empty or not day:return None
    values=frame.copy(deep=False)
    if 'event_time' in values:values=values.set_index('event_time')
    index=pd.DatetimeIndex(values.index)
    index=index.tz_localize('Asia/Shanghai') if index.tz is None else index.tz_convert('Asia/Shanghai')
    selected=values.loc[index.strftime('%Y-%m-%d')==day]
    # Conflicting duplicate sessions are not reliable ranking evidence.
    if len(selected)!=1:return None
    row=selected.iloc[0].to_dict()
    if row.get('is_final') is not True:return None
    return {**row,'event_time':pd.Timestamp(selected.index[0]).isoformat()}


def _reliable(row, field):
    if not row or not _number(row.get(field)) or float(row[field])<0:return False
    if row.get(field+'_reliable') is False:return False
    if field=='open_interest':
        status=str(row.get('oi_status') or '').lower()
        if status in ('placeholder','unreliable','missing','http_placeholder','invalid'):return False
        if row.get('http_placeholder') or row.get('open_interest_placeholder'):return False
        # HTTP zero OI is not historical open interest, even with a valid close.
        if float(row[field])==0 and ('http' in str(row.get('source','')).lower()):return False
    return True


def candidates(metadata, observed_at, *, day=None):
    cutoff=str(_stamp(observed_at).date()) if day is None else str(day)
    return sorted(s for s,r in metadata.items() if s[:2] in PRODUCTS
                  and r.get('listing_date','9999')<=cutoff<r.get('expiry_date','0000'))


def entity(category, left, right=None, metadata=None):
    metadata=metadata or {}
    if category=='basis':right=UNDERLYINGS[left[:2]][0]
    elif category=='calendar' and metadata.get(left,{}).get('expiry_date','')>metadata.get(right,{}).get('expiry_date',''):
        left,right=right,left
    elif category=='cross' and PRODUCTS.index(left[:2])>PRODUCTS.index(right[:2]):
        left,right=right,left
    exp_a=metadata.get(left,{}).get('expiry_date')
    exp_b=metadata.get(right,{}).get('expiry_date')
    return dict(entity_id=category+':'+left+('|' + right if right else ''),kind='contract_pair',
                category=category,left=left,right=right,title=left+(' − '+right if category!='basis' else ''),
                root=left[:2],roots=[left[:2]] if category=='basis' else [left[:2],right[:2]],
                expiry_type='single' if category=='basis' else 'same' if exp_a and exp_a==exp_b else 'mixed',
                expiry_dates=[exp_a] if category=='basis' else [exp_a,exp_b],
                legs=[left,right] if right else [left])


def all_entities(metadata, observed_at, category, *, include_history=False, expiry_mode='all'):
    day=str(_stamp(observed_at).date())
    symbols=sorted(s for s,r in metadata.items() if s[:2] in PRODUCTS and r.get('listing_date','9999')<=day) if include_history else candidates(metadata,observed_at)
    if category=='basis':return [entity(category,s,metadata=metadata) for s in symbols]
    result=[]
    for a,b in combinations(symbols,2):
        if (a[:2]==b[:2]) != (category=='calendar'):continue
        item=entity(category,a,b,metadata)
        if category=='calendar' and item['expiry_dates'][0]>=item['expiry_dates'][1]:continue
        if category=='cross' and expiry_mode!='all' and item['expiry_type']!=expiry_mode:continue
        result.append(item)
    return result


def _visibility(symbols, rows, metadata, cutoff):
    if not symbols:return VISIBILITY_UNVERIFIED
    end=pd.Timestamp(cutoff+' 23:59:59',tz='Asia/Shanghai') if cutoff else None
    for s in symbols:
        row=rows.get(s) or {};ref=metadata.get(s,{})
        # A timestamp alone is insufficient. Certification must be explicit.
        if row.get('pit_certified') is not True or ref.get('pit_certified') is not True:return VISIBILITY_UNVERIFIED
        for value in (row.get('available_at'),ref.get('known_at')):
            try:
                stamp=pd.Timestamp(value)
                if not value or end is None or pd.isna(stamp) or stamp.tzinfo is None or stamp>end:return VISIBILITY_UNVERIFIED
            except (ValueError,TypeError):return VISIBILITY_UNVERIFIED
    return '当时可见证据已认证'


def representatives(metadata, daily, calendar, observed_at, category):
    """Check coverage of every T-1 candidate before calling a result main/OI ranked."""
    day=decision_day(observed_at,calendar)
    symbols=candidates(metadata,observed_at,day=day) if day else candidates(metadata,observed_at)
    rows={s:_day_row(daily.get(s),day) for s in symbols}
    pools={root:[s for s in symbols if s.startswith(root)] for root in PRODUCTS}
    keys=[(r,) for r in PRODUCTS] if category!='cross' else list(combinations(PRODUCTS,2))
    result=[]
    for roots in keys:
        pool=[s for root in roots for s in pools[root]]
        if category=='basis':options=[entity(category,s,metadata=metadata) for s in pool]
        elif category=='calendar':options=[entity(category,a,b,metadata) for a,b in combinations(pool,2)
                                         if metadata[a]['expiry_date']!=metadata[b]['expiry_date']]
        else:options=[entity(category,a,b,metadata) for a,b in product(*(pools[r] for r in roots))
                      if metadata[a]['expiry_date']==metadata[b]['expiry_date']]
        oi_ok=bool(pool) and day is not None and all(_reliable(rows[s],'open_interest') for s in pool)
        vol_ok=bool(pool) and day is not None and all(_reliable(rows[s],'volume') for s in pool)
        label='主力' if category=='basis' else 'OI瓶颈代表'
        if not oi_ok:label='成交最活跃参考' if vol_ok else '近月参考'
        def order(item):
            legs=[item['left']] if category=='basis' else [item['left'],item['right']]
            oi=min(float(rows[s]['open_interest']) for s in legs) if oi_ok else 0
            volume=min(float(rows[s]['volume']) for s in legs) if vol_ok else 0
            expiries=[pd.Timestamp(metadata[s]['expiry_date']).toordinal() for s in legs]
            spread=abs(expiries[-1]-expiries[0]) if len(expiries)>1 else 0
            return (-oi,-volume,spread,min(expiries),tuple(legs))
        reason='' if oi_ok else 'T-1全部候选可靠OI覆盖不足；按完整成交量覆盖排序' if vol_ok else 'T-1全部候选可靠OI及成交量覆盖不足；仅为到期近月参考'
        coverage=dict(candidates=len(pool),oi=sum(_reliable(rows[s],'open_interest') for s in pool),
                      volume=sum(_reliable(rows[s],'volume') for s in pool),complete_oi=oi_ok,complete_volume=vol_ok)
        if options:
            chosen=min(options,key=order)
            chosen.update(selection_type=label,selection_reason=reason,decision_date=day,coverage=coverage,
                          visibility_status=_visibility(pool,rows,metadata,day),group_key='/'.join(roots))
        else:
            chosen=dict(entity_id=None,kind='unavailable',category=category,title='/'.join(roots),left=None,right=None,
                        roots=list(roots),group_key='/'.join(roots),selection_type='无同期代表' if category=='cross' else '无可用代表',
                        selection_reason='没有到期日一致的候选；请在详情显式选择异期' if category=='cross' else '缺少挂牌且未到期的合约',
                        decision_date=day,coverage=coverage,visibility_status=VISIBILITY_UNVERIFIED)
        result.append(chosen)
    return result


def fixed_collections(metadata, observed_at, category):
    """Freeze actual members into identity. Never consult the selected main contract."""
    symbols=candidates(metadata,observed_at)
    pools={r:sorted(s for s in symbols if s[:2]==r) for r in PRODUCTS}
    pairs=[(r,) for r in PRODUCTS] if category=='calendar' else list(combinations(PRODUCTS,2))
    result=[]
    for roots in pairs:
        common=None
        for root in roots:
            months={s[2:] for s in pools[root]}
            common=months if common is None else common&months
        groups=[sorted(s for s in pools[root] if s[2:] in common) for root in roots]
        members=[s for group in groups for s in group]
        signature='|'.join('/'.join(group) for group in groups)
        identity=sha256(signature.encode()).hexdigest()[:20]
        result.append(dict(entity_id=category+':set:'+identity,collection_id='fixed-oi:'+identity,
                           kind='collection',category=category,title='/'.join(roots)+' 固定月份集合',
                           left=groups[0][0] if groups[0] else None,
                           right=groups[1][0] if len(groups)>1 and groups[1] else None,
                           root=roots[0],roots=list(roots),members=members,member_groups=groups,
                           legs=members,expiry_type='same',selection_type='固定成员集合',
                           reference_type='原稿固定四月集合' if all(len(g)==4 for g in groups) else '共同月份固定集合参考',
                           selection_reason=('四个具体月份成员冻结；' if all(len(g)==4 for g in groups) else
                                             '成员不足四个月份，仅为明确成员的集合参考；')+'不同成员即为不同研究实体',
                           visibility_status=VISIBILITY_UNVERIFIED))
    return result


def paginate(entities, selection):
    root=selection.get('root') or selection.get('product')
    left=selection.get('left');right=selection.get('right')
    values=[r for r in entities if (not root or root in r.get('roots',[]))
            and (not left or left==r.get('left') or left in r.get('members',[]))
            and (not right or right==r.get('right') or right in r.get('members',[]))]
    try:offset=max(0,int(selection.get('offset') or 0))
    except (TypeError,ValueError):offset=0
    try:limit=min(100,max(1,int(selection.get('limit') or 20)))
    except (TypeError,ValueError):limit=20
    return values[offset:offset+limit],len(values),offset,limit
