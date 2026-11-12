"""Display valid term points, preserving each saved point's real source time."""
import math

import pandas as pd


def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def points(rows):
    result=[]
    for row in sorted(rows,key=lambda value:value.get('slot') if type(value.get('slot')) is int else 99):
        if type(row.get('slot')) is not int or not 0<=row['slot']<4:continue
        # A near-expiry exclusion is intentional, not a missing observation.
        if _number(row.get('days')) and row['days']<5:continue
        view=row
        saved=bool(row.get('display_saved'))
        if not _number(row.get('annual_pct')):
            view=row.get('basis_display') or {}
            if not view.get('saved'):continue
            if (not row.get('symbol') or view.get('symbol')!=row.get('symbol') or
                    view.get('slot')!=row.get('slot') or not row.get('expiry') or
                    view.get('expiry')!=row.get('expiry')):continue
            saved=True
        days=view.get('days');value=view.get('annual_pct')
        if not (_number(days) and days>=5 and _number(value)):continue
        try:
            times=[pd.Timestamp(view[k]) for k in ('basis_future_source_at','basis_spot_source_at')]
            if any(pd.isna(t) or t.tzinfo is None for t in times) or abs((times[0]-times[1]).total_seconds())>3:continue
        except (KeyError,TypeError,ValueError):continue
        result.append(dict(symbol=view['symbol'],slot=view['slot'],days=days,annual_pct=value,saved=saved,
            pricing_day=view.get('pricing_day'),basis_kind=view.get('basis_kind'),
            source_at=view.get('basis_source_at') or max(times).isoformat(),source_times=times))
    return result


def description(items):
    if not items:return '等待有效期现年化'
    saved=sum(bool(p['saved']) for p in items)
    identities={(p['pricing_day'],p['basis_kind']) for p in items}
    times=[t for p in items for t in p['source_times']]
    mixed=len(identities)>1 or (max(times)-min(times)).total_seconds()>3
    day=next(iter(identities))[0] if len(identities)==1 else None
    prefix='混合时点' if mixed else ('实时' if next(iter(identities))[1]=='realtime' else '参考')
    return prefix+(' '+str(day) if day else '')+' · 年化 '+str(len(items))+'/4'+(' · 沿用 '+str(saved) if saved else '')


def tooltip(items):
    return '\n'.join('0'+str(p['slot'])+' '+str(p['symbol'])+' · '+('沿用 ' if p['saved'] else '来源 ')+str(p['source_at']) for p in items)
