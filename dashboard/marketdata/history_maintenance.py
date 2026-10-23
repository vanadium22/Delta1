"""Resumable direct-route DDB maintenance. Never operates a VPN or reads a Z drive."""
from contextlib import ExitStack
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import time
import uuid

import pandas as pd

from .bars import BarDataset, _atomic_bytes, _json_bytes, _row_key, _writer_lock, normalize_bars
from .contract_reference import latest_contracts
from .ddb_import import convert_file
from .history_publication import maintenance_root, publish, read_publication, sync_current
from .trading_calendar import CalendarUnavailable, trading_days
from dashboard.native.instruments import UNDERLYINGS

MINUTES = frozenset([*range(571,691), *range(781,901)])
RETRY = (300, 900, 1800)
INDEXES = {v[0] for v in UNDERLYINGS.values()}
MESSAGES = {
    'scanning':'正在核验本地历史与交易日缺口', 'downloading':'正在下载历史缺口',
    'validating':'下载完成，正在校验暂存数据；已发布版本继续可读',
    'waiting_network':'等待历史网络：DDB 不可达；未操作 VPN，实时采集不受此任务控制',
    'waiting_calendar':'等待官方交易日历；禁止按工作日或价格日期猜测',
    'waiting_credentials':'凭据不可用或登录失败；请在本机配置后手动重试',
    'waiting_reference':'合约参考覆盖不足；请更新合约参考',
    'waiting_sdk':'历史 Python 环境缺少 DDB SDK；请配置历史解释器',
    'partial':'已发布校验通过的数据，仍有缺口待重试', 'complete':'维护范围内日线与分钟数据完整',
    'paused':'历史维护已暂停，实时采集继续', 'failed':'历史维护失败，已发布版本保留；稍后重试',
    'review':'发现数据校验或来源冲突，原数据保留；请查看缺口原因',
    'stopped':'历史任务已结束，已发布版本保留', 'busy':'另一历史任务正在维护相同目录',
    'date_checked':'日期增量检查已完成；尚未深核的历史分钟范围保留待核验',
    'authenticating':'正在复用本机数据库凭据，建立已有网络上的 DDB 会话',
    'publishing':'正在共同发布已校验历史版本',
}


class Stopped(Exception):pass
class CredentialsUnavailable(Exception):pass
class SourceConflict(ValueError):pass
class SourcePending(Exception):pass


def read_json(path, default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:return {} if default is None else default


def now_iso():return datetime.now(timezone.utc).isoformat()


def normalized_rows(rows):
    """Validate Arrow schema without repeated optional timezone-module imports."""
    import pyarrow as pa
    from .bars import TIME_FIELDS
    table=normalize_bars(rows)
    columns=[name for name in table.column_names if name in TIME_FIELDS]
    for name in columns:
        table=table.set_column(table.schema.get_field_index(name),name,table[name].cast(pa.int64()))
    result=table.to_pylist()
    for row in result:
        for name in columns:
            if row[name] is not None:row[name]=pd.Timestamp(row[name],unit='ns',tz='UTC')
    return result


def valid_slot(row, symbol, frequency, day):
    if row['instrument_id']!=symbol or row['source_symbol']!=symbol or row['frequency']!=frequency or str(row['trade_date'])!=day:
        return None
    if not row['is_final'] or any(row.get(k) is None or not math.isfinite(row[k]) or row[k]<=0 for k in ('open','high','low','close')):
        return None
    if not row['low']<=row['open']<=row['high'] or not row['low']<=row['close']<=row['high']:
        return None
    stamp=pd.Timestamp(row['event_time']).tz_convert('Asia/Shanghai')
    if str(stamp.date())!=day or stamp.second or stamp.microsecond or stamp.nanosecond:return None
    minute=stamp.hour*60+stamp.minute
    return 900 if frequency=='1d' and minute==900 else minute if frequency=='1m' and minute in MINUTES else None


def latest_rows(rows):
    result={}
    for row in rows:
        key=_row_key(row)
        if key not in result or row['revision']>result[key]['revision']:result[key]=row
    return result


def scan(stores, snapshots, cache, stop=lambda:False, progress=lambda n:None, checkpoint=lambda cache:None, total_progress=lambda n:None, metrics=None):
    measured=metrics if metrics is not None else {}
    measured.update(cache_hits=0,cache_misses=0,partition_stats=0,read_seconds=0,checkpoint_seconds=0)
    began=time.perf_counter();last_checkpoint=began
    coverage={};updated={};groups={}
    for key,snapshot in snapshots.items():
        for part in snapshot['parts']:
            if part['frequency'] not in ('1d','1m'):continue
            group=(key,part['instrument_id'],part['frequency'],part['trade_date'])
            groups.setdefault(group,[]).append(part)
    total_progress(len(groups))
    for i,((key,symbol,freq,day),parts) in enumerate(groups.items()):
        if stop():raise Stopped()
        store=stores[key]
        token=hashlib.sha256(_json_bytes(['coverage-v2',str(store.root),[
            (p['sha256'],store._path(p['path']).stat().st_size,store._path(p['path']).stat().st_mtime_ns) for p in parts]])).hexdigest()
        measured['partition_stats']+=2*len(parts)
        entry=cache.get(token)
        if entry is None:
            measured['cache_misses']+=1;t=time.perf_counter()
            rows=store._rows({**snapshots[key],'parts':parts})
            rows=normalized_rows(rows)
            latest=latest_rows(rows)
            slots={valid_slot(r,symbol,freq,day) for r in latest.values()};slots.discard(None)
            entry=dict(slots=sorted(slots),invalid=sum(valid_slot(r,symbol,freq,day) is None for r in latest.values()))
            measured['read_seconds']+=time.perf_counter()-t
        else:measured['cache_hits']+=1
        updated[token]=entry;coverage[symbol,freq,day]=entry
        if i%100==0:
            progress(i)
            if time.perf_counter()-last_checkpoint>=5:
                t=time.perf_counter()
                checkpoint({**cache,**updated})
                measured['checkpoint_seconds']+=time.perf_counter()-t
                last_checkpoint=time.perf_counter()
    progress(len(groups))
    measured.update(groups=len(groups),seconds=time.perf_counter()-began)
    return coverage,updated


def plan(coverage, metadata, days, start, end):
    jobs=[];summary=[]
    symbols=sorted(INDEXES|{s for s in metadata if s[:2] in UNDERLYINGS})
    for symbol in symbols:
        r=metadata.get(symbol,{})
        eligible=[d for d in days if start<=d<=end and (symbol in INDEXES or r['listing_date']<=d<=r['expiry_date'])]
        if not eligible:continue
        for freq in ('1d','1m'):
            expected={900} if freq=='1d' else MINUTES
            missing=[];latest=None;complete=None;contiguous=True;unknown=0
            for day in eligible:
                entry=coverage.get((symbol,freq,day),{'slots':[],'invalid':0})
                if entry.get('unverified'):
                    unknown+=1;contiguous=False
                    if entry.get('date_present'):latest=day
                    continue
                present=set(entry['slots']);absent=expected-present
                if present:latest=day
                if absent or entry['invalid']:
                    missing.append(day);contiguous=False
                    jobs.append(dict(symbol=symbol,frequency=freq,day=day,observed=len(present),expected=len(expected),
                        missing=len(absent),invalid=entry['invalid']))
                elif contiguous:complete=day
            summary.append(dict(symbol=symbol,frequency=freq,start=eligible[0],target=eligible[-1],
                latest=latest,complete_through=complete,missing_days=len(missing),unverified_days=unknown))
    jobs.sort(key=lambda j:(j['frequency']!='1d',-date.fromisoformat(j['day']).toordinal(),j['symbol']))
    return jobs,summary


def job_key(job):return '|'.join(job[k] for k in ('symbol','frequency','day'))


def open_direct(config_path):
    """Reuse query transforms, never call Client.__init__/VPN connection_scope."""
    from index_strategy.history.credentials import load_config
    from index_strategy.history.downloader import Client
    try:
        config=load_config(config_path)
    except Exception:raise CredentialsUnavailable() from None
    try:
        with socket.create_connection((config['host'],int(config['port'])),timeout=3):pass
    except OSError:raise ConnectionError('existing_route_unavailable') from None
    import dolphindb as ddb
    client=Client.__new__(Client)
    client.config=config;client._closed=False;client._vpn_entered=False
    client.mapping_cache={};client.source_cache=set();client.session=None
    try:
        client.session=ddb.session(enableSSL=config.get('enable_ssl',True))
        if not config.get('password') or not client.session.connect(config['host'],config['port'],config['username'],
                config['password'],readTimeout=15,writeTimeout=10):raise CredentialsUnavailable()
    except Exception as exc:
        client.close()
        # Do not expose SDK messages, SQL text, endpoints, usernames or passwords.
        text=str(exc).lower()
        if isinstance(exc,CredentialsUnavailable) or any(s in text for s in ('password','authentication','login failed','用户名','密码')):
            raise CredentialsUnavailable() from None
        raise ConnectionError() from None
    return client


def fetch_job(client, job, destination):
    from index_strategy.history.catalog import route
    symbol,freq,day=(job[k] for k in ('symbol','frequency','day'))
    _,source=route(symbol,freq)
    frame,info=client.fetch(source,symbol,date.fromisoformat(day),dict(asset='auto',depth=0,oi=True,mode='native',frequency=freq))
    if frame.empty:return [],None
    if info.get('duplicates_removed',0):raise ValueError('duplicate_source_rows')
    for column in ('source_symbol','symbol'):
        if column in frame and not frame[column].eq(symbol).all():raise ValueError('source_identity_mismatch')
    frame=frame.copy();frame['source_symbol']=symbol;frame['symbol']=symbol
    # Keep source pending/partial flags; never relabel unfinished source bars.
    if 'quality' not in frame:frame['quality']='complete'
    path=Path(destination)/'downloads'/(uuid.uuid4().hex+'.parquet');path.parent.mkdir(parents=True,exist_ok=True)
    frame.to_parquet(path,index=False)
    item=dict(file=str(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=len(frame),
        schema_version=2,source_symbol=symbol,frequency=freq,trading_date=day,downloaded_at=now_iso(),
        units=info.get('units') or {},unit_factors=info.get('unit_factors') or {})
    _atomic_bytes(path.with_suffix('.json'),_json_bytes(item))
    rows,skipped=convert_file(item)
    rows=normalized_rows(rows)
    if skipped.get('unfinished') or skipped.get('invalid_close') or any(r.get(k) is None for r in rows for k in ('open','high','low','close')):
        raise SourcePending('source_not_final')
    if any(valid_slot(r,symbol,freq,day) is None for r in rows):raise ValueError('invalid_download')
    unique=latest_rows(rows)
    if len(unique)!=len(rows):raise ValueError('duplicate_source_rows')
    # The importer may remove the 09:30 auction record only. Other omissions remain visible.
    if any(k!='opening_or_outside_regular_session' and n for k,n in skipped.items()):
        raise ValueError('invalid_source_rows')
    return rows,dict(file=str(path),sha256=item['sha256'],excluded=skipped)


def merge_missing(store, snapshot, job, incoming, *, preserve_existing=False, notes=None):
    subset={**snapshot,'parts':[p for p in snapshot['parts'] if (p['instrument_id'],p['frequency'],p['trade_date'])==
            (job['symbol'],job['frequency'],job['day'])]}
    existing=latest_rows(store._rows(subset));chosen=[];differences=[]
    for row in incoming:
        old=existing.get(_row_key(row))
        if old is None:chosen.append(row);continue
        if valid_slot(old,job['symbol'],job['frequency'],job['day']) is None:raise SourceConflict()
        changed={}
        for field in ('open','high','low','close','volume','turnover','open_interest'):
            a,b=old.get(field),row.get(field)
            if a is not None and b is not None and not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-7):changed[field]=dict(retained=a,ddb=b)
        if changed:
            if not preserve_existing:raise SourceConflict()
            differences.append(dict(event_time=row['event_time'],fields=changed))
    if differences and notes is not None:
        from collections import Counter
        notes.append(dict(symbol=job['symbol'],frequency=job['frequency'],day=job['day'],policy='preserve_existing_fill_missing_only',
            overlap_conflicting_rows=len(differences),field_counts=dict(Counter(f for d in differences for f in d['fields'])),
            examples=differences[:5],retained_existing_rows=len(existing),added_missing_rows=len(chosen),
            missing_times=[r['event_time'] for r in chosen],reviewed_at=now_iso()))
    return chosen


def run_cycle(local_root, **kwargs):
    from dashboard.session_guard import network_lease
    with network_lease(read_json(Path(local_root)/'native.json')):
        return _run_cycle(local_root, **kwargs)


def _run_cycle(local_root, *, force=False, budget=120, limit=80, stop_file=None, direct_factory=open_direct, fetcher=fetch_job, today=None, preserve_existing=False, incremental=False, lifetime=None,reference_file=None):
    local_root=Path(local_root);config=read_json(local_root/'native.json')
    if reference_file:config['reference_file']=str(reference_file)
    roots=config.get('history_roots',[]);root=maintenance_root(roots);root.mkdir(parents=True,exist_ok=True)
    controls=local_root/'history_control.json'
    def stopped():return bool(stop_file and Path(stop_file).exists()) or bool(lifetime and lifetime.stopped.is_set()) or read_json(controls).get('paused',False)
    state=read_json(root/'status.json');state.update(network_policy='existing_route_only_no_vpn_change',roots=roots)
    def status(name, **values):
        state.update(state=name,message=MESSAGES[name],updated_at=now_iso(),**values)
        from dashboard.history_status import progress_text
        state['progress_message']=progress_text(state)
        _atomic_bytes(root/'status.json',_json_bytes(state))
    with _writer_lock(root):
        if stopped():status('paused',next_retry=None,scan_complete=False,pending_symbol_days=None,missing_bars=None);return state
        actual_today=str(pd.Timestamp.now(tz='Asia/Shanghai').date()) if today is None else str(today)
        if not force and state.get('next_retry') and state['next_retry']>time.time() and state.get('today')==actual_today:return state
        if not force and state.get('state')=='waiting_credentials':return state
        client=None;pending={};evidence=[];job_state=read_json(root/'jobs.json');cache={} if incremental else read_json(root/'coverage_cache.json')
        quality=read_json(root/'quality_notes.json',{'schema':'history_source_notes_v1','entries':[]});new_notes=[]
        state['source_discrepancies']=len(quality['entries'])
        status('scanning',today=actual_today,next_retry=None,error_type=None,queries=0,inserted=0,
               scan_id=uuid.uuid4().hex,scan_started_at=now_iso(),scan_complete=False,
               scan_groups=0,scan_total=None,pending_symbol_days=None,missing_bars=None,
               pending_scan_id=None,pending_target=None,current_job=None,target=None,start=None,versions={})
        state['verification_scope']='incremental' if incremental else 'deep'
        state['unknown_groups']=None
        try:
            stores={};kind_keys={}
            for path in roots:
                store=BarDataset(path);descriptor=store.descriptor
                key=descriptor['dataset_id'];kinds={v['asset_type'] for v in descriptor['instruments'].values()}
                if len(kinds)!=1 or key in stores:raise ValueError('ambiguous_registered_dataset')
                kind=kinds.pop()
                if kind in kind_keys:raise ValueError('multiple_registered_sources')
                stores[key]=store;kind_keys[kind]=key
            if set(kind_keys)!={'cn_index','cn_index_future'}:raise ValueError('missing_registered_dataset')
            pointer=root/'publication.json'
            snapshots=read_publication(pointer,stores) if pointer.exists() else {k:s.snapshot() for k,s in stores.items()}
            if not pointer.exists():publish(pointer,stores,snapshots,published_at=now_iso())
            # Recover a crash after joint publication but before compatibility pointers.
            # Only the immediately preceding generation is a recoverable pointer lag.
            # Never order external writes by wall-clock time (clocks can move backwards).
            for k,s in stores.items():
                current=s.snapshot()
                if current['version'] not in (snapshots[k]['version'],snapshots[k].get('previous_version')):
                    raise SourceConflict()
            sync_current(stores,snapshots)
            initial_versions={k:s['version'] for k,s in snapshots.items()}
            available=[p['trade_date'] for s in snapshots.values() for p in s['parts'] if p['frequency']=='1d']
            start=config.get('history_start') or min(available,default=actual_today)
            days,end=trading_days(start,actual_today,root/'calendar')
            metadata=latest_contracts(read_json(config.get('reference_file','')))
            if any(sum(r['listing_date']<=end<=r['expiry_date'] for s,r in metadata.items() if s.startswith(p))!=4 for p in UNDERLYINGS):
                status('waiting_reference',target=end,start=start,next_retry=time.time()+300);return state
            status('scanning',target=end,start=start)
            from .history_quick import incremental_scan,save_ledger,save_summary
            measurements={}
            if incremental:
                recent=days[-3] if len(days)>=3 else start
                coverage,ledger,measurements=incremental_scan(stores,snapshots,read_json(root/'coverage_ledger.json'),
                    recent_start=recent,stop=stopped,progress=lambda n:status('scanning',scan_groups=n),
                    known_jobs=read_json(root/'pending.json').get('jobs',[]))
                state['scan_total']=measurements['groups']
            else:
                coverage,cache=scan(stores,snapshots,cache,stopped,lambda n:status('scanning',scan_groups=n),
                    lambda data:_atomic_bytes(root/'coverage_cache.json',_json_bytes(data)),
                    total_progress=lambda n:status('scanning',scan_total=n),metrics=measurements)
                _atomic_bytes(root/'coverage_cache.json',_json_bytes(cache))
            state['scan_metrics']=measurements
            state['unknown_groups']=sum(bool(v.get('unverified')) for v in coverage.values())
            save_ledger(root,stores,snapshots,coverage)
            jobs,summary=plan(coverage,metadata,days,start,end)
            def save_pending():
                enriched=[{**j,**job_state.get(job_key(j),{})} for j in jobs]
                versions={k:s['version'] for k,s in snapshots.items()}
                _atomic_bytes(root/'pending.json',_json_bytes(dict(start=start,target=end,jobs=enriched,coverage=summary,
                              scan_id=state['scan_id'],versions=versions,generated_at=now_iso())))
                state.update(pending_symbol_days=len(jobs),missing_bars=sum(j['missing'] for j in jobs),start=start,target=end,
                    versions=versions,scan_complete=True,pending_scan_id=state['scan_id'],pending_target=end)
                save_summary(root,snapshots,summary,jobs,coverage,end)
            save_pending()
            if not jobs:
                name='date_checked' if state['unknown_groups'] else 'complete'
                status(name,failures=0,next_retry=time.time()+1800,**({'last_complete_at':now_iso()} if name=='complete' else {}));return state
            if stopped():raise Stopped()
            from dashboard.app_config import connection_path
            selected=[j for j in jobs if force or job_state.get(job_key(j),{}).get('retry_at',0)<=time.time()]
            if not selected:
                status('partial',next_retry=min(job_state[job_key(j)].get('retry_at',time.time()+300) for j in jobs));return state
            status('authenticating')
            client=direct_factory(connection_path(config))
            deadline=time.monotonic()+budget;query_failed=False
            for job in selected[:limit]:
                if stopped():raise Stopped()
                if time.monotonic()>=deadline:break
                key=job_key(job);attempt=job_state.get(key,{}).get('attempts',0)+1
                status('downloading',current_job=job,queries=state['queries']+1)
                reason='source_lag';count=0
                try:
                    rows,item=fetcher(client,job,root)
                    if job['day']>end:raise ValueError('download_past_cutoff')
                    if any(valid_slot(r,job['symbol'],job['frequency'],job['day']) is None for r in rows):raise ValueError('invalid_download')
                    dataset=kind_keys['cn_index_future' if job['symbol'].endswith('.CFE') else 'cn_index']
                    chosen=merge_missing(stores[dataset],snapshots[dataset],job,rows,preserve_existing=preserve_existing,notes=new_notes)
                    pending.setdefault(dataset,[]).extend(chosen);count=len(chosen)
                    if item:evidence.append(item)
                    coverage.setdefault((job['symbol'],job['frequency'],job['day']),{'slots':[],'invalid':0})['slots']=sorted(
                        set(coverage.get((job['symbol'],job['frequency'],job['day']),{}).get('slots',[]))|
                        {valid_slot(r,job['symbol'],job['frequency'],job['day']) for r in chosen})
                    reason='downloaded' if count else 'source_lag'
                except SourcePending:reason='source_lag'
                except SourceConflict:reason='conflict_requires_review'
                except ValueError:reason='validation_failed'
                except Exception:
                    reason='source_query_failed';query_failed=True
                job_state[key]=dict(attempts=attempt,reason=reason,last_attempt=now_iso(),
                    retry_at=time.time()+(86400 if reason in ('conflict_requires_review','validation_failed') else RETRY[min(attempt-1,2)]))
                _atomic_bytes(root/'jobs.json',_json_bytes(job_state))
                # Repeated query/network errors should not churn through thousands of jobs.
                if reason=='source_query_failed':break
            if stopped():raise Stopped()
            next_snapshots=dict(snapshots)
            status('validating',current_job=None)
            for key,rows in pending.items():
                if not rows:continue
                store=stores[key];template=next(iter(store.descriptor['instruments'].values()))
                additions={s:{**template,'underlying_id':UNDERLYINGS[s[:2]][0]} for s in {r['instrument_id'] for r in rows}
                           if s not in store.descriptor['instruments']}
                if additions:store.register_instruments(additions)
                committed=store.commit(rows,checkpoint={'history_maintenance':evidence,'target':end,'source_notes':new_notes},publish=False,base_version=snapshots[key]['version'])
                next_snapshots[key]=store.snapshot(committed['version']);state['inserted']+=committed['inserted']
                # Read every staged partition back through checksum/schema validation before publishing.
                old_paths={p['path'] for p in snapshots[key]['parts']}
                staged={**next_snapshots[key],'parts':[p for p in next_snapshots[key]['parts'] if p['path'] not in old_paths]}
                normalize_bars(store._rows(staged))
            if state['inserted']:
                with ExitStack() as locks:
                    for store in sorted(stores.values(),key=lambda s:str(s.root)):locks.enter_context(_writer_lock(store.root))
                    if any(s.snapshot()['version']!=initial_versions[k] for k,s in stores.items()):raise SourceConflict()
                    if new_notes:
                        combined={job_key(n):n for n in [*quality['entries'],*new_notes]}
                        quality['entries']=list(combined.values());state['source_discrepancies']=len(combined)
                        _atomic_bytes(root/'quality_notes.json',_json_bytes(quality))
                    status('publishing')
                    publish(pointer,stores,next_snapshots,published_at=now_iso(),target=end)
                    sync_current(stores,next_snapshots)
                snapshots=next_snapshots;state['last_published_at']=now_iso()
            jobs,summary=plan(coverage,metadata,days,start,end);save_pending()
            save_ledger(root,stores,snapshots,coverage)
            state['failures']=state.get('failures',0)+1 if query_failed else 0
            due=min((job_state.get(job_key(j),{}).get('retry_at',time.time()+5) for j in jobs),default=time.time()+1800)
            if query_failed:due=max(due,time.time()+RETRY[min(state['failures']-1,2)])
            name='partial' if jobs else 'date_checked' if state['unknown_groups'] else 'complete'
            if jobs and all(job_state.get(job_key(j),{}).get('reason') in ('conflict_requires_review','validation_failed') for j in jobs):name='review'
            if not jobs and not state['unknown_groups']:state['last_complete_at']=now_iso()
            status(name,next_retry=max(time.time()+5,due),current_job=None)
        except Stopped:status('paused' if read_json(controls).get('paused') else 'stopped',next_retry=None)
        except Exception as exc:
            name='waiting_network' if isinstance(exc,(ConnectionError,TimeoutError)) else 'waiting_credentials' if isinstance(exc,CredentialsUnavailable) else 'waiting_calendar' if isinstance(exc,CalendarUnavailable) else 'waiting_sdk' if isinstance(exc,ImportError) else 'review' if isinstance(exc,SourceConflict) else 'failed'
            failures=state.get('failures',0)+1
            status(name,failures=failures,error_type=type(exc).__name__,current_job=None,
                next_retry=None if name=='waiting_credentials' else time.time()+RETRY[min(failures-1,2)])
        finally:
            if client is not None:
                try:client.close()
                except Exception:pass
        return state


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path,default=Path(__file__).resolve().parents[1]/'localsetting')
    parser.add_argument('--once',action='store_true',help='One bounded cycle, suitable for Windows Task Scheduler')
    parser.add_argument('--force',action='store_true',help='Ignore cooldowns for this run')
    parser.add_argument('--preserve-existing',action='store_true',help='Explicitly retain differing existing values, fill missing keys only, and record source discrepancies')
    parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--incremental',action='store_true')
    parser.add_argument('--owner-pid',type=int)
    parser.add_argument('--reference-file',type=Path)
    args=parser.parse_args()
    try:
        from dashboard.process_lifetime import LauncherLifetime
        with LauncherLifetime(args.owner_pid,stop_file=args.stop_file) as lifetime:
            result=run_cycle(args.local_root,force=args.force,stop_file=args.stop_file,preserve_existing=args.preserve_existing,
                             incremental=args.incremental,lifetime=lifetime,reference_file=args.reference_file)
        print(json.dumps({k:result.get(k) for k in ('state','target','pending_symbol_days','inserted')},ensure_ascii=False))
        return 0 if result.get('state') in ('complete','date_checked') else 2
    except OSError:
        print('{"state":"busy_or_local_io_error"}');return 3
    except Exception:
        print('{"state":"configuration_error"}');return 4


if __name__=='__main__':raise SystemExit(main())
