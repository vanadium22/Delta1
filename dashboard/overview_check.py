"""Read-only company overview evidence: no App, HTTP, Wind query, VPN or writes to inputs."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pandas as pd

from dashboard.marketdata.overview_reference import load, ranking, ROOTS, path_for
from dashboard.marketdata.overview_contributions import read_equities, contributions, equity_path
from dashboard.marketdata.quote_quality import quote_quality
from dashboard.native.overview_instruments import quote_registry
from dashboard.native.overview_instruments import etfs
from dashboard.native.market_overview import previous_session
from dashboard.session_clock import session_policy


def read_status(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf8'))
        # Only the fields produced by the new reference worker. Never include
        # arbitrary settings, driver exceptions, connection strings or secrets.
        return {k:value[k] for k in ('status','started_at','finished_at','error_type','reason','warnings','diagnostics','provider') if k in value}
    except (OSError, ValueError,TypeError,AttributeError):
        return dict(status='not_recorded')


def profile_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def app_reports(local_root, runtime_root=None):
    """Safe snapshots of existing reports, never a claim that a PID is alive."""
    directory=Path(runtime_root) if runtime_root is not None else Path(__file__).parent/'runtime/app_sessions'
    matching=[];others=[]
    try:
        paths=sorted(directory.glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    except OSError:
        return dict(status='unavailable',matching_profile=[],other_profiles=[])
    for path in paths[:100]:
        try:
            if path.stat().st_size>4*1024*1024:continue
            value=json.loads(path.read_text(encoding='utf8'))
            if value.get('schema')!='app-update-evidence-v1' or not value.get('local_root'):continue
            same=profile_key(value['local_root'])==profile_key(local_root)
            collection=value.get('collection') or {};runtime=value.get('overview_runtime') or {}
            scheduler=runtime.get('reference_scheduler') or {}
            entry={k:value.get(k) for k in ('observed_at','local_root','phase','closing',
                'collection_worker_running','history_worker_running')}
            entry.update(report_path=str(path.resolve()),same_profile=same,
                collection={k:collection.get(k) for k in ('status','stage','polls','rows','last_success_at',
                    'last_failure_at','last_failure_status','received_at')},
                overview_runtime=dict(schema=runtime.get('schema'),pipeline_enabled=runtime.get('pipeline_enabled'),
                    reference_scheduler={k:scheduler.get(k) for k in ('status','reason','checked_at','worker_running','worker_exit_code')}))
            target=matching if same else others
            if len(target)<3:target.append(entry)
        except (OSError,ValueError,TypeError,AttributeError):
            continue
    return dict(status='existing_reports_only',matching_profile=matching,other_profiles=others,
                note='状态文件保留原记录时间，不证明进程此刻存活；不同配置报告分开列示')


def attempt_status(local_root):
    try:
        value=json.loads((Path(local_root)/'overview_reference/attempt.json').read_text(encoding='utf8'))
        return dict(status='recorded',week=value.get('week'),attempted_at=value.get('attempted_at'))
    except (OSError,ValueError,TypeError,AttributeError):
        return dict(status='not_recorded')


def wind_setup(config,local_root):
    """Check file/module presence only; do not read credentials or initialise a client."""
    if (config.get('overview_reference_backend') or 'windpy')=='windpy':
        from dashboard.marketdata.overview_windpy import setup
        return setup(config,local_root)
    from dashboard.marketdata.overview_wind import settings_path
    root=Path(local_root).resolve();settings=settings_path(config,root)
    choices=[root.parent.parent/'index_strategy/data_dld/.deps',Path(__file__).resolve().parent.parent/'index_strategy/data_dld/.deps']
    try:driver=importlib.util.find_spec('oracledb') is not None
    except (ImportError,ValueError):driver=False
    return dict(settings_file=str(settings.resolve()),settings_file_exists=settings.is_file(),driver_module_available=driver,
        local_dependency_available=any((p/'oracledb').is_dir() for p in choices),
        environment_credentials_complete=all(bool(os.environ.get(k)) for k in ('WIND_DB_USER','WIND_DB_PASSWORD','WIND_DB_DSN')),
        credentials_read=False,connection_attempted=False)


def raw_etf_fields(reader, symbols):
    """Inspect only field NAMES in the latest immutable, hash-checked response."""
    try:
        with reader.connect() as con:
            event = con.execute("SELECT description FROM events WHERE kind='raw_http_batch' ORDER BY rowid DESC LIMIT 1").fetchone()
        if not event:return dict(status='no_raw_event')
        reference = json.loads(event[0]); root=reader.root.resolve(); path=(root/reference['path']).resolve()
        if not path.is_relative_to(root) or path.stat().st_size>8*1024*1024:
            raise ValueError('原始响应路径或大小无效')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=reference['sha256']:raise ValueError('原始响应校验失败')
        envelope=json.loads(raw); body=envelope.get('response_body') or {}
        content=base64.b64decode(body['base64'],validate=True)
        if len(content)!=body['bytes'] or hashlib.sha256(content).hexdigest()!=body['sha256']:
            raise ValueError('原始HTTP内容校验失败')
        data=json.loads(content).get('data',{})
        fields={s:sorted(str(k) for k in data[s]) for s in symbols if isinstance(data.get(s),dict)}
        return dict(status='inspected_existing_raw_only',received_at=envelope.get('request_and_collection',{}).get('received_at'),
            fields=fields,iopv_candidate_fields={s:[k for k in keys if 'iopv' in k.lower() or 'indicative' in k.lower()] for s,keys in fields.items()},
            conclusion='字段名仅供核验，不猜字段含义或自动启用IOPV映射')
    except Exception as exc:
        return dict(status='unavailable',error_type=type(exc).__name__)


def sample(config, local_root, *, now=None):
    from index_strategy.instant_dld.reader import RealtimeReader
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    today = str(now.tz_convert('Asia/Shanghai').date())
    reference = load(config, local_root, now=now.to_pydatetime())
    registry = {**{s:dict(asset_type='cn_index',market_region='CN') for s in ROOTS.values()},
                **quote_registry(config,reference['data'],today)}
    quotes = {}; errors = []
    discovery = dict(status='no_quote_database')
    try:
        reader = RealtimeReader(config.get('realtime_root') or Path(local_root)/'missing-realtime')
        if reader.db_path.is_file():
            discovery = raw_etf_fields(reader,[r['symbol'] for r in etfs(config,reference['data'],today)])
            frame = reader.latest(sorted(registry))
            for row in frame.to_dict('records'):
                q = dict(row, observed_at=row.get('received_at'))
                quotes[row['source_symbol']] = q
    except Exception as exc:
        errors.append(dict(stage='quote_cache',error_type=type(exc).__name__))
    observations = {s:dict(source_at=q.get('source_event_time'), received_at=q.get('received_at'),
                            sequence=int(q.get('sequence') or 0), quality=quote_quality(q,now)) for s,q in quotes.items()}
    groups = {}
    for root in ROOTS:
        selected,meta = ranking(reference['data'],root,today=today)
        groups[root] = dict(ranking=meta, selected=[dict(symbol=r['symbol'],name=r['name'],rank=r['rank'],
            aum_date=r['aum_date'],aum_share_pct=r['aum_share_pct']) for r in selected])
        groups[root]['iopv'] = [dict(etf_id=r['symbol'],iopv_id=r.get('iopv_id'),
            status='待有效同步观测' if r.get('iopv_id') else '待明确IOPV映射或字段') for r in etfs(config,reference['data'],today) if r['root']==root]
    equity = read_equities(config,local_root)
    detail = {};closed_evidence={}
    try:
        previous = previous_session(today)
        from dashboard.marketdata.overview_weights import roll,closed_snapshot
        from dashboard.marketdata.overview_sessions import latest_completed_session
        from dashboard.marketdata.overview_daily import quote_rows,directory
        from dashboard.native.latest_snapshot import load as load_snapshot
        completed=latest_completed_session(now.to_pydatetime())
        completed_quotes=quote_rows(config,local_root,completed)
        snapshot_quotes=load_snapshot(local_root).get('quotes',{})
        closed_evidence=dict(expected_completed_session=completed,
            daily_quotes={s:dict(source_at=q.get('source_event_time'),received_at=q.get('observed_at'),trade_date=q.get('trade_date')) for s,q in completed_quotes.items() if s in registry},
            http_snapshots={s:dict(source_at=q.get('source_event_time'),received_at=q.get('observed_at'),date_basis=q.get('source_date_basis')) for s,q in snapshot_quotes.items() if s in registry})
        try:
            pending=json.loads((directory(config,local_root)/'status.json').read_text(encoding='utf8'))
            closed_evidence['daily_maintenance']={k:pending.get(k) for k in ('status','target','inserted','pending_rows','pending_batches','error_types','updated_at')}
        except (OSError,ValueError):pass
        if not session_policy(now.to_pydatetime())['allowed']:
            equity=closed_snapshot(config,local_root,completed,reference['version'])
            previous=previous_session(completed)
        for root,symbol in ROOTS.items():
            group=roll(reference['data'].get('indices',{}).get(root,{}),config,local_root,previous)
            value = contributions(group,equity,dict(symbol=symbol),now,previous,reference['version'])
            detail[root] = {k:value.get(k) for k in ('mode','weight_date','official_weight_date','weight_method','weight_reason','source_at','snapshot_at','coverage_pct','covered','expected','reason')}
            detail[root]['classified'] = sum(bool(r.get('industry')) for r in reference['data'].get('indices',{}).get(root,{}).get('rows',[]))
    except Exception as exc:
        errors.append(dict(stage='contributions',error_type=type(exc).__name__))
    return dict(at=now.isoformat(),observations=observations,etfs=groups,indices=detail,
        reference=dict(fetched_at=reference['data'].get('fetched_at'),due=reference['due'],error=reference['error'],errors=reference['data'].get('errors',[])),
        wind=read_status(Path(local_root)/'overview_reference/status.json'),iopv_source_fields=discovery,
        closed_data=closed_evidence,errors=errors)


def collect(local_root, *, samples=2, interval=3, runtime_root=None):
    root = Path(local_root); path = root/'native.json'; before = path.read_bytes(); config = json.loads(before)
    result = dict(schema='overview-company-check-v1',python=sys.executable,session=session_policy(),
        app_started=False,network_requested=False,wind_requested=False,vpn_changed=False,
        configuration_sha256=hashlib.sha256(before).hexdigest(),samples=[])
    realtime=Path(config['realtime_root']).resolve() if config.get('realtime_root') else None
    result['diagnostic_profile']=dict(local_root=str(root.resolve()),native_file=str(path.resolve()),
        realtime_root=str(realtime) if realtime is not None else None,
        reference_file=str(path_for(config,root).resolve()),equity_file=str(equity_path(config,root).resolve()),
        wind_enabled=config.get('overview_wind_enabled',True) is not False)
    result['reference_attempt']=attempt_status(root)
    try:result['wind_setup']=wind_setup(config,root)
    except (OSError,ValueError,TypeError) as exc:
        result['wind_setup']=dict(status='unavailable',error_type=type(exc).__name__,credentials_read=False,connection_attempted=False)
    result['app_reports']=app_reports(root,runtime_root)
    for i in range(samples):
        if i:time.sleep(interval)
        result['samples'].append(sample(config,root))
    first,last = result['samples'][0]['observations'],result['samples'][-1]['observations']
    result['source_advanced_symbols'] = [s for s,q in last.items() if s in first and q.get('source_at') and
        first[s].get('source_at') and pd.Timestamp(q['source_at']) > pd.Timestamp(first[s]['source_at'])]
    result['configuration_unchanged'] = path.read_bytes() == before
    def latest(field):
        values=pd.to_datetime([q.get(field) for q in first.values()],utc=True,errors='coerce').dropna()
        return values.max().tz_convert('Asia/Shanghai').isoformat() if len(values) else None
    result['quote_cache_summary']=dict(latest_source_at=latest('source_at'),latest_received_at=latest('received_at'),
        checked_in_continuous_session=bool(result['session']['allowed']),
        fresh_symbols_in_first_sample=[s for s,q in first.items() if q.get('quality',{}).get('usable')],
        note='盘后两样本不推进不能判连接失败；缓存若停在更早盘中时刻，仍需核对对应配置的采集状态')
    result['continuous_collection_verified'] = False
    result['note'] = '两次只读样本不代替公司长时间运行验收；休市时源时不推进属正常。IOPV需明确映射；本程序不猜代码、不连接任何接口。'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        value = collect(args.local_root)
    except Exception as exc:
        value = dict(schema='overview-company-check-v1',error_type=type(exc).__name__,network_requested=False,vpn_changed=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as out:
        json.dump(value,out,ensure_ascii=False,allow_nan=False,indent=2)
    print(str(args.output))
    return 0 if 'error_type' not in value else 1


if __name__=='__main__':
    raise SystemExit(main())
