"""Read-only Z-drive imports into a local, append-only composite history.

Raw continuous slots are resolved using their *same-day* concrete contract map.
Existing observations win; collisions are reported, never silently revised.
No source-side locks, checkpoints, temporary files, or writes are performed.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import threading
import time
import uuid

import pandas as pd

from .bars import BarDataset, _atomic_bytes, _json_bytes, _row_key
from .contract_reference import latest_contracts
from .paths import DATA_ROOT, HISTORY_ROOT
from dashboard.native.instruments import UNDERLYINGS

SOURCE = Path('Z:/Project_data/future_investment/data')
DEST = DATA_ROOT / 'market/index_futures/dashboard/history_backfill'
LOCK = threading.Lock()
FIELDS = {'open':'open', 'high':'high', 'low':'low', 'close':'close',
          'volume':'volume', 'turnover':'amount', 'open_interest':'open_interest'}


def fingerprint(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def local_destination(path, source):
    path, source = Path(path).resolve(), Path(source).resolve()
    if not path.is_relative_to(DATA_ROOT.resolve()) or path.is_relative_to(source):
        raise ValueError('补缺输出必须在本项目 data 内，禁止写入源目录')
    return path


def clone_history(base, destination):
    """Copy immutable local partitions; publish the new manifest only at the end."""
    original, store = BarDataset(base), BarDataset(destination)
    if (store.root/'current.json').exists():
        return store
    snapshot = original.snapshot()
    descriptor = {**original.descriptor, 'dataset_id':'backfilled_'+original.descriptor['dataset_id'],
                  'source_id':'local_ddb_plus_readonly_z_v1',
                  'base_dataset':str(original.root), 'base_version':snapshot['version'],
                  'merge_policy':'Existing bars win; missing keys only; source hashes in backfill audits'}
    store = BarDataset.create(destination, descriptor)
    for part in snapshot['parts']:
        source, target = original._path(part['path']), store._path(part['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            # Copies, not links: subsequent writes elsewhere cannot alter this store.
            temporary = target.with_name(target.name+'.copying')
            shutil.copyfile(source, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != part['sha256']:
                raise ValueError('本地历史分片复制校验失败')
            temporary.replace(target)
    version = uuid.uuid4().hex
    manifest = {**snapshot, 'dataset_id':descriptor['dataset_id'], 'descriptor':store.descriptor,
                'version':version, 'previous_version':None,
                'checkpoint':{'base_root':str(original.root), 'base_version':snapshot['version']}}
    raw = _json_bytes(manifest); relative = f'versions/{version}.json'
    _atomic_bytes(store._path(relative), raw)
    _atomic_bytes(store.root/'current.json', _json_bytes(dict(version=version, manifest=relative,
                                                           sha256=hashlib.sha256(raw).hexdigest())))
    return store


def missing_only(rows, existing):
    """Keep the highest existing revision; report economic disagreements."""
    chosen, duplicates, conflicts, examples = [], 0, 0, []
    for row in rows:
        key = _row_key(row)
        old = existing.get(key)
        if old is not None:
            duplicates += 1
            # Price disagreements may indicate mapping/source differences. Never overwrite.
            changed = [k for k in FIELDS if old.get(k) is not None and row.get(k) is not None
                       and abs(float(old[k])-float(row[k])) > max(1e-7, abs(float(old[k]))*1e-9)]
            if changed:
                conflicts += 1
                if len(examples)<10:
                    examples.append(dict(symbol=row['instrument_id'], time=str(row['event_time']), fields=changed,
                                         existing={k:old[k] for k in changed}, source={k:row[k] for k in changed}))
            continue
        chosen.append(row); existing[key] = row
    return chosen, dict(duplicates=duplicates, conflicts_retained=conflicts, conflict_examples=examples)


def map_rows(frames, mapping, metadata, frequency, recorded_at, *, start, end):
    """Convert trusted local matrices. No fill, interpolation, or alias-price borrowing."""
    output, skipped = [], Counter()
    close = frames['close']
    for root in UNDERLYINGS:
        column = root+'.CFE'
        if column not in close or column not in mapping:
            continue
        prices = close[column].dropna()
        prices = prices[(prices.index>=pd.Timestamp(start)) & (prices.index<pd.Timestamp(end)+pd.Timedelta(days=1))]
        columns={target:frames[name][column] for target,name in FIELDS.items()
                 if name in frames and column in frames[name]}
        for stamp, price in prices.items():
            day = pd.Timestamp(stamp).normalize()
            symbol = mapping[column].get(day)
            ref = metadata.get(symbol, {})
            if not isinstance(symbol,str) or not symbol.startswith(root) or not ref or not ref['listing_date']<=str(day.date())<=ref['expiry_date']:
                skipped['unknown_contract_or_outside_listing'] += 1; continue
            event = pd.Timestamp(stamp).tz_localize('Asia/Shanghai')
            if frequency=='1d':
                event = event.normalize()+pd.Timedelta(hours=15); session = 'day'
            else:
                minute = event.hour*60+event.minute
                if not (570<minute<=690 or 780<minute<=900) or event.second or event.microsecond:
                    skipped['opening_or_outside_session'] += 1; continue
                session = 'am' if minute<=690 else 'pm'
            row = dict(instrument_id=symbol, source_symbol=symbol, frequency=frequency,
                       event_time=event.tz_convert('UTC'), trade_date=day.date(), session_id=session,
                       bar_start=None, available_at=None, recorded_at=recorded_at,
                       is_final=True, revision=0, quality_flags=8|128)
            for target, name in FIELDS.items():
                value = columns[target].get(stamp) if target in columns else None
                row[target] = None if value is None or pd.isna(value) else float(value)
            try:
                if not price>0:raise ValueError('invalid close')
                if any(v is not None and not math.isfinite(v) for v in (row[k] for k in FIELDS)):
                    raise ValueError('nonfinite value')
                if any(row[k] is not None and row[k]<0 for k in ('volume','turnover','open_interest')):
                    raise ValueError('negative quantity')
                lo,hi=row['low'],row['high']
                if lo is not None and hi is not None and (lo>hi or any(row[k] is not None and not lo<=row[k]<=hi for k in ('open','close'))):
                    raise ValueError('invalid OHLC')
            except (ValueError, TypeError):
                skipped['invalid_bar'] += 1; continue
            output.append(row)
    return output, dict(skipped)


def read_matrix(path, archive, evidence):
    before = fingerprint(path)
    # Pickles are trusted user-owned data. Hash exactly the bytes deserialized.
    raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
    frame = pd.read_pickle(io.BytesIO(raw))
    del raw
    if fingerprint(path)!=before:
        raise ValueError(f'读取期间源文件更新，请下次重试：{path.name}')
    frame = frame[[c for c in frame if c in {r+'.CFE' for r in UNDERLYINGS}]].copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    if frame.index.has_duplicates or frame.index.tz is not None:
        raise ValueError('源矩阵日期重复或时区口径发生变化')
    evidence.append(dict(path=str(path), fingerprint=before, sha256=digest))
    saved = archive/(digest+'.parquet')
    if not saved.exists():
        frame.to_parquet(saved)
    evidence[-1]['local_subset'] = str(saved)
    return frame


def synchronize(config, *, force=False, source=SOURCE, destination=DEST, progress=None):
    """Explicit one-shot command only. Never called by the running dashboard."""
    source = Path(source).resolve(); destination = local_destination(destination, source)
    status_path = destination/'status.json'
    if not LOCK.acquire(blocking=False):
        return {'state':'running', 'message':'历史补缺进行中'}
    try:
        previous = json.loads(status_path.read_text(encoding='utf8')) if status_path.exists() else {}
        if not force and time.time()-previous.get('checked_epoch',0)<1800:
            return previous
        report = dict(state='running', checked_epoch=time.time(), source=str(source),
                      started_at=datetime.now(timezone.utc).isoformat(), batches=[], inserted=0,
                      source_policy='read-only', errors=[], history_roots=config['history_roots'])
        destination.mkdir(parents=True, exist_ok=True)
        if not (source/'raw/day/next/+0/close.pkl').is_file():
            report.update(state='unavailable', message='Z 盘历史源不可用，保留本地历史')
            _atomic_bytes(status_path,_json_bytes(report));return report
        metadata = latest_contracts(json.loads(Path(config['reference_file']).read_text(encoding='utf8')))
        now = pd.Timestamp.now(tz='Asia/Shanghai')
        # Completed days only; current-day polling is not historical OHLCV.
        end = str((now.normalize()-pd.Timedelta(days=1)).date())
        start = config.get('history_backfill_start','2025-07-01')
        report.update(start=start,end=end)
        roots=[]; stores={}
        for root in config['history_roots']:
            original=BarDataset(root)
            kind=next(iter(original.descriptor['instruments'].values()))['asset_type']
            target=local_destination(HISTORY_ROOT/('backfilled_'+kind),source)
            store=original if original.root==target else clone_history(root,target)
            stores[kind]=store;roots.append(str(store.root))
        report['history_roots']=roots
        store=stores['cn_index_future']
        existing={};loaded_pairs=set()
        cache_path=destination/'sources.json'
        cached=json.loads(cache_path.read_text(encoding='utf8')) if cache_path.exists() else {}
        archive=destination/'source_subsets';archive.mkdir(exist_ok=True)
        def commit(rows,evidence,key,signature,skipped):
            needed={(r['instrument_id'],r['frequency']) for r in rows}-loaded_pairs
            if needed:
                snapshot=store.snapshot()
                subset={**snapshot,'parts':[p for p in snapshot['parts'] if (p['instrument_id'],p['frequency']) in needed]}
                for old in store._rows(subset):
                    identity=_row_key(old)
                    if identity not in existing or old['revision']>existing[identity]['revision']:existing[identity]=old
                loaded_pairs.update(needed)
            # Do not mutate the persisted-key cache until the commit succeeds.
            pending=dict(existing)
            chosen,details=missing_only(rows,pending)
            if chosen:
                template=next(iter(store.descriptor['instruments'].values()))
                registration={s:{**template,'underlying_id':UNDERLYINGS[s[:2]][0]}
                    for s in {r['instrument_id'] for r in chosen} if s not in store.descriptor['instruments']}
                if registration:store.register_instruments(registration)
                result=store.commit(chosen,checkpoint={'backfill_source':key,'evidence':evidence})
                existing.update({_row_key(r):r for r in chosen})
            else:result={'inserted':0,'version':store.snapshot()['version']}
            batch=dict(source=key,**result,**details,skipped=skipped,evidence=evidence)
            report['batches'].append(batch);report['inserted']+=result['inserted']
            cached[key]=signature;_atomic_bytes(cache_path,_json_bytes(cached))
            # Persist each completed batch so interruption cannot erase provenance.
            _atomic_bytes(destination/'audits'/(uuid.uuid4().hex+'.json'),_json_bytes(batch))
            if progress:progress(dict(source=key,inserted=result['inserted'],skipped=skipped))
        # Native archive bars are preferred to mixed-provider raw matrices.
        from .ddb_import import manifest_file, convert_file
        archive_root=source/'source_archive/ddb/historical'
        for run_path in sorted(archive_root.glob('*/run.json')):
            try:
                raw=run_path.read_bytes();run=json.loads(raw)
                if run.get('version')!=2:continue
                for item in run.get('files',[]):
                    if not isinstance(item,dict):continue
                    symbol=item.get('source_symbol','');day=item.get('trading_date','')
                    if symbol not in metadata or item.get('frequency')!='1m' or not start<=day<=end:continue
                    key=str(run_path)+'|'+symbol+'|'+day
                    signature=[item.get('sha256'),start,end]
                    if cached.get(key)==signature:continue
                    path=manifest_file(run_path,item)
                    frame=pd.read_parquet(path)
                    # Archive symbol is a main alias, but source_symbol and query
                    # identity must both certify the same concrete contract.
                    if item.get('source_query_symbol')!=symbol or set(frame.source_symbol)!={symbol}:
                        raise ValueError('归档查询合约证明缺失或与实际身份不符')
                    frame=frame.copy();frame['symbol']=symbol
                    local=archive/(item['sha256']+'.parquet');frame.to_parquet(local,index=False)
                    adapted={**item,'file':str(local),'bytes':local.stat().st_size,
                             'sha256':hashlib.sha256(local.read_bytes()).hexdigest()}
                    rows,skipped=convert_file(adapted)
                    if not metadata[symbol]['listing_date']<=day<=metadata[symbol]['expiry_date']:
                        raise ValueError('归档合约不在挂牌区间')
                    commit(rows,[dict(path=str(path),sha256=item['sha256'],local_subset=str(local),
                                      run_sha256=hashlib.sha256(raw).hexdigest())],key,signature,skipped)
            except (ValueError,OSError,KeyError,TypeError) as exc:
                report['errors'].append(f'{run_path}: {exc}')
                if progress:progress({'error':str(exc),'source':str(run_path)})
        for frequency,folder in [('1d','day'),('1m','minute')]:
            for layer in ['next/+0','next/+1','next/+2','next/+3','main']:
                base=source/'raw'/folder/layer
                map_path=source/'raw/day'/layer/'month_contract_code.pkl'
                paths=[base/(name+'.pkl') for name in FIELDS.values() if (base/(name+'.pkl')).exists()]
                if not (base/'close.pkl').exists() or not map_path.exists():continue
                key=str(base)
                try:
                    signature={'files':{str(p):fingerprint(p) for p in [*paths,map_path]},'start':start,'end':end}
                    if cached.get(key)==signature:continue
                    evidence=[]
                    mapping=read_matrix(map_path,archive,evidence)
                    frames={p.stem:read_matrix(p,archive,evidence) for p in paths}
                    if any(fingerprint(Path(p))!=token for p,token in signature['files'].items()):
                        raise ValueError('读取期间源批次发生变化，未导入，请重试')
                    rows,skipped=map_rows(frames,mapping,metadata,frequency,now.tz_convert('UTC'),start=start,end=end)
                    commit(rows,evidence,key,signature,skipped)
                    del frames,rows
                except (ValueError,OSError,KeyError,TypeError) as exc:
                    report['errors'].append(f'{base}: {exc}')
                    if progress:progress({'error':str(exc),'source':str(base)})
        report['coverage']=[]
        from .history_remote import repair
        report['remote']=repair(stores,metadata,destination/'remote',start,end)
        report['inserted']+=report['remote']['inserted']
        for kind,s in stores.items():
            for frequency in ('1d','1m'):
                for root in (UNDERLYINGS if kind=='cn_index_future' else [v[0] for v in UNDERLYINGS.values()]):
                    parts=[p for p in s.snapshot()['parts'] if p['frequency']==frequency and p['instrument_id'].startswith(root)]
                    if parts:report['coverage'].append(dict(symbol=root,frequency=frequency,last=max(p['trade_date'] for p in parts),rows=sum(p['rows'] for p in parts)))
        report.update(state='partial' if report['errors'] or report['remote']['state']!='complete' else 'complete', finished_at=datetime.now(timezone.utc).isoformat(),
                      message=f"历史补缺本次新增 {report['inserted']} 条；源内不存在的数据保留缺口")
        _atomic_bytes(status_path,_json_bytes(report));return report
    finally:
        LOCK.release()


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    from dashboard.native.model import NativeModel
    model=NativeModel()
    try:
        result=synchronize(model.config,force=args.force,progress=lambda x:print(json.dumps(x,ensure_ascii=False),flush=True))
        if result.get('history_roots')!=model.config['history_roots']:
            candidate={**model.config,'history_roots':result['history_roots']}
            candidate.pop('history_backfill_enabled',None)
            model.save_config(candidate)
        print(json.dumps({k:v for k,v in result.items() if k!='batches'},ensure_ascii=False,indent=2))
    finally:model.close()


if __name__=='__main__':main()
