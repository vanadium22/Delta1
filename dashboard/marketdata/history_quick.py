"""Metadata-only startup inspection and versioned incremental verification.

The quick path never opens manifests or stats partitions. A date claim from an
older publication is explicitly weaker than per-symbol minute verification.
"""
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 'history-coverage-v3'


def read(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):return {}


def quick_check(config, *, today=None):
    from .history_publication import maintenance_root
    from .trading_calendar import trading_days, CalendarUnavailable, HOLIDAYS
    started=time.perf_counter()
    result=dict(schema=SCHEMA,checked_at=datetime.now(timezone.utc).isoformat(),
                scope='publication_and_coverage_metadata',partition_reads=0,partition_stats=0,
                minute_verified=False,known_pending=None)
    roots=config.get('history_roots') or []
    if not roots:
        return {**result,'state':'waiting_configuration','message':'未配置历史目录；请在内联设置中指定已有配置'}
    root=maintenance_root(roots)
    publication=read(root/'publication.json');summary=read(root/'coverage_summary.json');status=read(root/'status.json')
    versions={k:v.get('version') for k,v in publication.get('datasets',{}).items()}
    day=today or datetime.now().astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date().isoformat()
    try:
        # Startup never fetches an annual calendar over the network.
        cutoff=date.fromisoformat(day)
        years=range((cutoff-timedelta(days=20)).year,cutoff.year+1)
        if any(year not in HOLIDAYS and not (root/'calendar'/f'{year}.json').is_file() for year in years):
            raise CalendarUnavailable()
        _,target=trading_days(day,day,root/'calendar')
    except (CalendarUnavailable,ValueError):target=None
    current=(summary.get('schema')==SCHEMA and summary.get('versions')==versions and bool(versions))
    result.update(target=target,published_target=publication.get('target'),published_at=publication.get('published_at'),
                  versions=versions,summary_current=current,
                  coverage=summary.get('coverage',[]) if current else [],
                  known_pending=summary.get('pending_symbol_days') if current else None,
                  known_pending_dates=summary.get('pending_dates',[]) if current else [],
                  minute_verified=bool(current and status.get('scan_complete') is True and summary.get('unknown_groups')==0 and
                                       summary.get('target')==target and summary.get('pending_symbol_days')==0),
                  verified_at=summary.get('verified_at') if current else None,
                  unknown_groups=summary.get('unknown_groups') if current else None)
    result['state']='ready' if target else 'waiting_calendar'
    result['message']=(f"已发布目标 {result['published_target'] or '未记录'} · 上一交易日 {target or '待核验'} · " +
                       ('分钟完整性已核验' if result['minute_verified'] else '日期元数据快检；历史分钟完整性尚未全部深核'))
    result['seconds']=time.perf_counter()-started
    return result


def incremental_scan(stores,snapshots,ledger,*,recent_start,stop,progress,known_jobs=()):
    from .history_maintenance import Stopped,valid_slot,latest_rows,normalized_rows
    from .bars import normalize_bars,_json_bytes
    metrics=dict(groups=0,reused=0,read_groups=0,unknown_groups=0,partition_reads=0,
                 partition_stats=0,group_seconds=0,read_seconds=0)
    began=time.perf_counter();groups={}
    for key,snapshot in snapshots.items():
        for p in snapshot['parts']:
            if p['frequency'] in ('1m','1d'):
                groups.setdefault((key,p['instrument_id'],p['frequency'],p['trade_date']),[]).append(p)
    metrics['group_seconds']=time.perf_counter()-began
    previous=ledger.get('groups',{}) if ledger.get('schema')==SCHEMA else {}
    known={(j['symbol'],j['frequency'],j['day']) for j in known_jobs}
    entries={};coverage={}
    for n,((key,symbol,freq,day),parts) in enumerate(groups.items()):
        if stop():raise Stopped()
        group='|'.join((key,symbol,freq,day))
        token=hashlib.sha256(_json_bytes([(p['path'],p['sha256']) for p in parts])).hexdigest()
        old=previous.get(group,{})
        if old.get('signature')==token and day<recent_start and (symbol,freq,day) not in known and not old.get('entry',{}).get('unverified'):
            entry=old['entry'];metrics['reused']+=1
        elif day>=recent_start or (symbol,freq,day) in known or old and old.get('signature')!=token or old.get('entry',{}).get('invalid'):
            t=time.perf_counter()
            rows=normalized_rows(stores[key]._rows({**snapshots[key],'parts':parts}))
            latest=latest_rows(rows);slots=[valid_slot(r,symbol,freq,day) for r in latest.values()]
            entry=dict(slots=sorted({s for s in slots if s is not None}),invalid=slots.count(None))
            metrics['read_seconds']+=time.perf_counter()-t;metrics['read_groups']+=1
            metrics['partition_reads']+=len(parts);metrics['partition_stats']+=len(parts)
        else:
            # Presence establishes a date only. Never manufacture 240 minute slots.
            entry=dict(slots=[],invalid=0,unverified=True,date_present=True)
            metrics['unknown_groups']+=1
        entries[group]=dict(signature=token,entry=entry)
        coverage[symbol,freq,day]=entry
        if n%100==0:progress(n)
    metrics.update(groups=len(groups),seconds=time.perf_counter()-began)
    progress(len(groups))
    return coverage,dict(schema=SCHEMA,groups=entries),metrics


def save_ledger(root,stores,snapshots,coverage):
    """Persist only completed scan results, bound to immutable partition identities."""
    from .bars import _atomic_bytes,_json_bytes
    groups={}
    for key,snapshot in snapshots.items():
        for p in snapshot['parts']:
            if p['frequency'] in ('1m','1d'):
                groups.setdefault((key,p['instrument_id'],p['frequency'],p['trade_date']),[]).append(p)
    values={}
    for (key,symbol,freq,day),parts in groups.items():
        entry=coverage.get((symbol,freq,day))
        if entry is not None:
            token=hashlib.sha256(_json_bytes([(p['path'],p['sha256']) for p in parts])).hexdigest()
            values['|'.join((key,symbol,freq,day))]=dict(signature=token,entry=entry)
    _atomic_bytes(root/'coverage_ledger.json',_json_bytes(dict(schema=SCHEMA,groups=values)))


def save_summary(root,snapshots,summary,jobs,coverage,target):
    from .bars import _atomic_bytes,_json_bytes
    _atomic_bytes(root/'coverage_summary.json',_json_bytes(dict(schema=SCHEMA,
        versions={k:s['version'] for k,s in snapshots.items()},target=target,coverage=summary,
        pending_symbol_days=len(jobs),pending_dates=sorted({j['day'] for j in jobs}),
        unknown_groups=sum(bool(v.get('unverified')) for v in coverage.values()),
        verified_at=datetime.now(timezone.utc).isoformat())))
