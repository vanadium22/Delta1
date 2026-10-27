"""Dated DDB close cache for overview ETFs/constituents, separate from bar stores.

The caller owns the existing DDB network lease/session. No credentials, VPN or
connections here. Raw selected rows and previous cache revisions are retained.
"""
from datetime import date,datetime,timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
from functools import lru_cache

import pandas as pd

from .bars import _atomic_bytes,_json_bytes
from .overview_reference import load as reference_load,finite,ROOTS


def directory(config,local_root):
    return Path(config.get('overview_daily_root') or Path(local_root)/'overview_daily')


@lru_cache(maxsize=1)
def side_sources():
    return json.loads(Path(__file__).with_name('overview_sources.json').read_text(encoding='utf8'))['sources']


def read_day(config,local_root,day):
    if not day:return {}
    try:
        path=directory(config,local_root)/'days'/(str(day)+'.json')
        value=json.loads(path.read_text(encoding='utf8'))
        if not isinstance(value,dict) or value.get('schema')!='overview-daily-v1' or value.get('trade_date')!=day or not isinstance(value.get('rows'),dict):return {}
        for symbol,row in value['rows'].items():
            if not isinstance(row,dict) or row.get('symbol')!=symbol or row.get('trade_date')!=day or row.get('is_final') is not True or not finite(row.get('close')) or row['close']<=0:return {}
            if row.get('source_at')!=day+'T15:00:00+08:00' or not isinstance(row.get('source'),str):return {}
        return value
    except (OSError,ValueError,TypeError):return {}


def publish_day(config,local_root,day,rows):
    root=directory(config,local_root);path=root/'days'/(day+'.json')
    prior=read_day(config,local_root,day)
    value=dict(schema='overview-daily-v1',trade_date=day,source='DDB audited daily catalog',
        fetched_at=datetime.now(timezone.utc).isoformat(),rows={**prior.get('rows',{}),**rows})
    if path.exists():
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()[:16]
        archive=root/'archive'/(day+'-'+digest+'.json')
        if not archive.exists():_atomic_bytes(archive,raw)
    _atomic_bytes(path,_json_bytes(value))
    return value


def requests(config,local_root,target,metadata,*,reference_data=None):
    from dashboard.native.market_overview import previous_session
    from dashboard.native.overview_instruments import etfs
    reference=reference_load(config,local_root)['data'] if reference_data is None else reference_data
    current={s for s,r in metadata.items() if s[:2] in ROOTS and r['listing_date']<=target<=r['expiry_date']}
    equities={r['symbol'] for g in reference.get('indices',{}).values() for r in g.get('rows',[])}
    funds={r['symbol'] for r in etfs(config,reference,target)}
    symbols=set(ROOTS.values())|current|equities|funds
    day_symbols={d:set(symbols) for d in (target,previous_session(target)) if d}
    from .overview_percentiles import requirements
    for item in requirements(metadata,target)['rows']:
        day_symbols.setdefault(item['day'],set()).add(item['symbol'])
    for group in reference.get('indices',{}).values():
        anchor=group.get('as_of')
        if anchor and 0<=(date.fromisoformat(target)-date.fromisoformat(anchor)).days<=14:
            # Retain the official-weight day's unadjusted close and factor so
            # later rolls can detect source-reported corporate action changes.
            needed={r['symbol'] for r in group.get('rows',[])}
            if needed:day_symbols.setdefault(anchor,set()).update(needed)
    result=[]
    from index_strategy.history.catalog import identify
    for day in sorted(day_symbols):
        saved=read_day(config,local_root,day).get('rows',{})
        groups={}
        for symbol in sorted(day_symbols[day]):
            if symbol in metadata and not metadata[symbol]['listing_date']<=day<=metadata[symbol]['expiry_date']:continue
            if symbol in saved:continue
            info=identify(symbol);groups.setdefault(info['asset'],[]).append(symbol)
        for asset in ('index','future','etf','stock'):
            codes=groups.get(asset,[])
            result.extend(dict(day=day,asset=asset,symbols=codes[i:i+100]) for i in range(0,len(codes),100))
    # Show latest headline closes first, then the full stock universe and older anchors.
    result.sort(key=lambda r:(r['asset']=='stock',-date.fromisoformat(r['day']).toordinal(),('index','future','etf','stock').index(r['asset'])))
    return result


def usable_records(frame):
    if frame is None or frame.empty:return []
    return [row for row in frame.to_dict('records') if row.get('is_final')==True and finite(row.get('close')) and row['close']>0]


def merge_daily(frame,additions):
    """A bad standard close cannot mask a verified side-cache close of that day."""
    rows=usable_records(frame)+list(additions)
    if not rows:return pd.DataFrame()
    result=pd.DataFrame(rows)
    result['trade_date']=result.trade_date.astype(str).str[:10]
    return result.drop_duplicates('trade_date',keep='first').sort_values('trade_date')


def local_copy_plan(jobs,daily):
    """Classify cache absence without copying, connecting or assuming remote supply."""
    available={s:{str(r['trade_date'])[:10] for r in usable_records(f)} for s,f in daily.items()}
    local=[];remaining=[]
    for job in jobs:
        codes=[s for s in job['symbols'] if job['asset'] in ('index','future') and job['day'] in available.get(s,set())]
        if codes:local.append(dict(job,symbols=codes))
        pending=[s for s in job['symbols'] if s not in codes]
        if pending:remaining.append(dict(job,symbols=pending))
    return dict(local_copy_rows=sum(len(j['symbols']) for j in local),local_copy_batches=local,
                remaining_rows=sum(len(j['symbols']) for j in remaining),remaining_batches=remaining)


def seed_local(repo,frozen,config,local_root,target,metadata,*,stop=lambda:False):
    """Build missing close cache from usable original bars before any network."""
    jobs=requests(config,local_root,target,metadata);wanted={}
    for job in jobs:
        if job['asset'] in ('index','future'):
            for symbol in job['symbols']:wanted.setdefault(symbol,set()).add(job['day'])
    pending={}
    for symbol,days in sorted(wanted.items()):
        if stop():break
        try:frame=repo.read_window(symbol,'1d',count=65,as_of=pd.Timestamp(target+'T23:59:59+08:00'),
            fields=('open','high','low','close','volume','turnover','open_interest'),frozen=frozen)
        except ValueError:continue
        for row in usable_records(frame):
            day=str(row['trade_date'])[:10]
            if day not in days:continue
            values={k:float(row[k]) if finite(row.get(k)) else None for k in ('open','high','low','close','volume')}
            values.update(amount=float(row['turnover']) if finite(row.get('turnover')) else None,
                oi=float(row['open_interest']) if finite(row.get('open_interest')) else None)
            pending.setdefault(day,{})[symbol]=dict(symbol=symbol,trade_date=day,source_at=day+'T15:00:00+08:00',
                is_final=True,source='local published normalized bars',acquisition='local_copy_no_network',
                original_event_time=str(row.get('event_time')),original_recorded_at=str(row.get('recorded_at')),
                source_versions={k:v.get('version') for k,v in frozen.items()},
                units={'volume':'lot','amount':'CNY','oi':'lot'},unit_factors={},**values)
    count=0
    for day,rows in pending.items():
        if stop():break
        publish_day(config,local_root,day,rows);count+=len(rows)
    return count


def fetch_batch(client,job,raw_root):
    import numpy as np
    from index_strategy.history.catalog import route,identify,field_map
    from index_strategy.history.transforms import normalize_units,units
    symbols=job['symbols'];day=job['day']
    if job['asset'] in ('stock','etf'):
        info=identify(symbols[0],job['asset'])
        source=next(s for s in side_sources() if s['kind']==job['asset'])
    else:info,source=route(symbols[0],'1d',job['asset'])
    if any(identify(s,job['asset'])['asset']!=info['asset'] for s in symbols):raise ValueError('日线批次类型不一致')
    client.bind(source,symbols[0])
    client.session.upload(dict(overviewCodes=symbols,overviewDate=np.datetime64(day,'D')))
    mapping,missing=field_map(source,asset=job['asset'],depth=0,oi=job['asset']=='future')
    if any(k not in mapping for k in ('open','high','low','close')):raise ValueError('日线源缺必要OHLC字段')
    columns={c['name'] for c in source['columns']}
    for column,key in (('S_DQ_PRECLOSE','source_prev_close'),('S_DQ_ADJFACTOR','adjustment_factor')):
        if column in columns:mapping[key]=column
    fields=['S_INFO_WINDCODE as symbol','TRADE_DT as trade_date']+[v+' as '+k for k,v in mapping.items()]
    where='TRADE_DT=overviewDate, S_INFO_WINDCODE in overviewCodes'
    count=int(client.session.run('exec count(*) from downloadSource where '+where))
    if count>len(symbols):raise ValueError('DDB日线同标的同日不唯一，未自动选版本')
    frame=client.session.run('select '+','.join(fields)+' from downloadSource where '+where+' order by symbol')
    if len(frame)!=count:raise ValueError('DDB查询期间数据发生变化')
    if frame.empty:return {}
    if not set(frame.symbol).issubset(symbols) or frame.symbol.duplicated().any():raise ValueError('DDB日线身份不一致')
    if not pd.to_datetime(frame.trade_date).dt.date.eq(date.fromisoformat(day)).all():raise ValueError('DDB日线日期不匹配')
    raw_root=Path(raw_root);raw_root.mkdir(parents=True,exist_ok=True)
    raw_file=raw_root/(uuid.uuid4().hex+'.parquet');frame.to_parquet(raw_file,index=False)
    _atomic_bytes(raw_file.with_suffix('.json'),_json_bytes(dict(source=source['table'],trade_date=day,
        sha256=hashlib.sha256(raw_file.read_bytes()).hexdigest(),rows=len(frame),field_mapping=mapping,
        raw_units='source native units; see audited catalog',fetched_at=datetime.now(timezone.utc).isoformat())))
    normal,factors=normalize_units(frame,info,'1d');result={}
    for row in normal.to_dict('records'):
        prices=[row.get(k) for k in ('open','high','low','close')]
        if any(not finite(v) or v<=0 for v in prices):continue
        if not row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high']:continue
        values={k:float(row[k]) if finite(row.get(k)) else None for k in
                ('open','high','low','close','volume','amount','oi','source_prev_close','adjustment_factor')}
        result[str(row['symbol'])]=dict(symbol=str(row['symbol']),trade_date=day,source_at=day+'T15:00:00+08:00',
            source='DDB '+source['table'],units=units(info),unit_factors=factors,is_final=True,**values)
    return result


def fill(client,config,local_root,target,metadata,*,stop=lambda:False,budget=45,fetcher=fetch_batch):
    root=directory(config,local_root);deadline=time.monotonic()+budget;inserted=0;errors=[]
    jobs=requests(config,local_root,target,metadata)
    for job in jobs:
        if stop() or time.monotonic()>=deadline:break
        try:
            rows=fetcher(client,job,root/'downloads')
            if rows:publish_day(config,local_root,job['day'],rows);inserted+=len(rows)
        except Exception as exc:
            errors.append(type(exc).__name__);break
    remaining=requests(config,local_root,target,metadata)
    value=dict(schema='overview-daily-status-v1',target=target,inserted=inserted,
        pending_batches=len(remaining),pending_rows=sum(len(r['symbols']) for r in remaining),
        status='complete' if not remaining else 'partial',error_types=errors,
        updated_at=datetime.now(timezone.utc).isoformat())
    _atomic_bytes(root/'status.json',_json_bytes(value));return value


def quote_rows(config,local_root,day):
    """Completed bars retain source close time, distinct from acquisition time."""
    data=read_day(config,local_root,day);rows=data.get('rows',{})
    from dashboard.native.market_overview import previous_session
    prior=read_day(config,local_root,previous_session(day)).get('rows',{}) if rows else {}
    result={}
    for symbol,row in rows.items():
        if not row.get('is_final') or row.get('trade_date')!=day:continue
        before=prior.get(symbol,{}).get('close')
        result[symbol]=dict(close=row['close'],prev_close=before,volume_total=row.get('volume'),
            open=row.get('open'),high=row.get('high'),low=row.get('low'),amount_cny=row.get('amount'),
            source_event_time=row['source_at'],observed_at=data.get('fetched_at'),
            source_kind='completed_daily',trade_date=day,source=row['source'],units=row.get('units'),
            adjustment_factor=row.get('adjustment_factor'))
    return result
