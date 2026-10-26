"""Read-only company overview evidence: no App, HTTP, Wind query, VPN or writes to inputs."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import pandas as pd

from dashboard.marketdata.overview_reference import load, ranking, ROOTS
from dashboard.marketdata.overview_contributions import read_equities, contributions
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
        return {k:value[k] for k in ('status','started_at','finished_at','error_type','reason','warnings','diagnostics') if k in value}
    except (OSError, ValueError):
        return dict(status='not_recorded')


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
    detail = {}
    try:
        previous = previous_session(today)
        for root,symbol in ROOTS.items():
            value = contributions(reference['data'].get('indices',{}).get(root,{}),equity,dict(symbol=symbol),now,previous,reference['version'])
            detail[root] = {k:value.get(k) for k in ('weight_date','source_at','snapshot_at','coverage_pct','covered','expected','reason')}
            detail[root]['classified'] = sum(bool(r.get('industry')) for r in reference['data'].get('indices',{}).get(root,{}).get('rows',[]))
    except Exception as exc:
        errors.append(dict(stage='contributions',error_type=type(exc).__name__))
    return dict(at=now.isoformat(),observations=observations,etfs=groups,indices=detail,
        reference=dict(fetched_at=reference['data'].get('fetched_at'),due=reference['due'],error=reference['error'],errors=reference['data'].get('errors',[])),
        wind=read_status(Path(local_root)/'overview_reference/status.json'),iopv_source_fields=discovery,errors=errors)


def collect(local_root, *, samples=2, interval=3):
    root = Path(local_root); path = root/'native.json'; before = path.read_bytes(); config = json.loads(before)
    result = dict(schema='overview-company-check-v1',python=sys.executable,session=session_policy(),
        app_started=False,network_requested=False,wind_requested=False,vpn_changed=False,
        configuration_sha256=hashlib.sha256(before).hexdigest(),samples=[])
    for i in range(samples):
        if i:time.sleep(interval)
        result['samples'].append(sample(config,root))
    first,last = result['samples'][0]['observations'],result['samples'][-1]['observations']
    result['source_advanced_symbols'] = [s for s,q in last.items() if s in first and q.get('source_at') and
        first[s].get('source_at') and pd.Timestamp(q['source_at']) > pd.Timestamp(first[s]['source_at'])]
    result['configuration_unchanged'] = path.read_bytes() == before
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
