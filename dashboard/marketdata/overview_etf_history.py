"""Bounded, read-only comparisons of dated AUM for the current three ETFs."""
from datetime import datetime
import json

from .overview_reference import available_sections,path_for,finite


def archive_token(config,local_root):
    path=path_for(config,local_root).parent/'archive'
    try:return (str(path),path.stat().st_mtime_ns)
    except OSError:return (str(path),None)


def read_aum_history(config,local_root,reference):
    """Freeze availability at the current reference, independent of later files."""
    result=dict(snapshots=[],files_read=0,truncated=False)
    try:
        cutoff=datetime.fromisoformat(reference['fetched_at'])
        paths=sorted((path_for(config,local_root).parent/'archive').glob('*.json'),reverse=True)
    except (OSError,ValueError,KeyError,TypeError):return result
    result['truncated']=len(paths)>64;total=0
    for path in paths[:64]:
        try:
            size=path.stat().st_size
            if size>4*1024*1024:continue
            if total+size>32*1024*1024:result['truncated']=True;break
            raw=path.read_bytes();total+=len(raw);result['files_read']+=1
            decoded=json.loads(raw)
            if not isinstance(decoded,dict):continue
            value,_=available_sections({k:decoded[k] for k in ('schema','fetched_at','reference_reviewed_at','etfs') if k in decoded})
            if datetime.fromisoformat(value['fetched_at'])>cutoff:continue
            result['snapshots'].append(dict(fetched_at=value['fetched_at'],etfs=value['etfs']))
        except (OSError,ValueError,TypeError,KeyError):continue
    return result


def size_changes(root,selected,history):
    result=[]
    for current in selected[:3]:
        row=dict(symbol=current['symbol'],name=current.get('name') or current['symbol'],
            aum_current_cny=current.get('aum_cny'),aum_current_date=current.get('aum_date'),
            aum_previous_cny=None,aum_previous_date=None,aum_change_cny=None,aum_change_pct=None,
            reason='待同一ETF更早已披露规模')
        candidates=[]
        if finite(row['aum_current_cny']) and row['aum_current_cny']>0 and row['aum_current_date']:
            for snapshot in history.get('snapshots',[]):
                group=snapshot.get('etfs',{}).get(root,{})
                if not group.get('as_of') or group['as_of']>=row['aum_current_date']:continue
                for past in group.get('rows',[]):
                    if past['symbol']==row['symbol'] and finite(past.get('aum_cny')) and past['aum_cny']>0:
                        candidates.append((group['as_of'],datetime.fromisoformat(snapshot['fetched_at']),past['aum_cny']))
        if candidates:
            latest=max((day,at) for day,at,_ in candidates)
            amounts={amount for day,at,amount in candidates if (day,at)==latest}
            if len(amounts)==1:
                previous=next(iter(amounts))
                row.update(aum_previous_cny=previous,aum_previous_date=latest[0],
                    aum_change_cny=row['aum_current_cny']-previous,aum_change_pct=100*(row['aum_current_cny']/previous-1),
                    reason='同一ETF两期已披露规模之差；包含净值涨跌影响')
            else:row['reason']='同日同时点规模冲突，等待核验'
        result.append(row)
    return result
