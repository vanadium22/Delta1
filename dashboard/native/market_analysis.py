"""On-demand analysis adapters; reuse query contracts without starting research."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import re
import subprocess
import threading
import time

import pandas as pd

from index_futures_basis.security_model import SecurityQuery, calculate, numeric, local_time
from index_futures_basis.security_data import SecurityService, SecurityProvider, SecurityResult, read_document
from index_futures_basis.config import DEFAULTS
from index_futures_basis.sync import Cancelled
from shared_data import DataPaths


class QueryCancellation(threading.Event):
    def __init__(self, budget=90):
        super().__init__()
        self.deadline=time.monotonic()+budget

    def clear(self):
        # Each request gets a new event. The reused service may not clear a
        # cancellation that arrived while its worker was starting.
        pass

    def is_set(self):
        return super().is_set() or time.monotonic() >= self.deadline


class OwnedQueryProvider(SecurityProvider):
    """Its SDK process only reads Wind; the service thread owns cache writes."""
    def __init__(self, config):
        super().__init__(config)
        self.close_lock=threading.Lock()
        self.closed=False
        self.last_operation=None

    def _start(self):
        with self.close_lock:
            if self.closed:raise Cancelled('cancelled')
            super()._start()

    def request(self, operation, **kwargs):
        self.last_operation=operation
        if self.closed:raise Cancelled('cancelled')
        return super().request(operation,**kwargs)

    def close(self):
        with self.close_lock:
            self.closed=True
            process=self.process
            if process is None:return
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=1.5)
            reader=getattr(self,'reader',None)
            if reader is not None:reader.join(timeout=1)
            for stream in (process.stdin,process.stdout):
                if stream is not None:
                    try:stream.close()
                    except OSError:pass
            self.responses.put(None)
            self.process=None


def safe_error(exc, operation=None):
    code=re.search(r'(?:ErrorCode|错误码)\s*[=:：]?\s*(-?\d+)',str(exc))
    return dict(error_type=type(exc).__name__,stage=operation or 'query',
        error_code=int(code[1]) if code else None,
        cancelled=isinstance(exc,Cancelled))


def seed_verified_cache(query, source_paths, destination):
    """Copy only relevant hash-verified query cache, never alter the old App."""
    from index_futures_basis.security_data import write_document
    source=source_paths.root/'cache/market/security_query/wind'/query.frequency
    if not source.is_dir() or source.resolve()==destination.resolve():return 0
    files=[source/'reference.json']
    if query.frequency!='snapshot':
        files += [p for p in source.glob('????-??-??/'+query.code+'-*.json')
            if query.start[:10] <= p.stem[-10:] <= query.end[:10]]
    copied=0
    for path in files:
        target=destination/path.relative_to(source)
        if (target.exists() and path.name!='reference.json') or not path.is_file() or path.stat().st_size>16*1024*1024:continue
        try:
            doc=read_document(path)
            if path.name=='reference.json':
                if not isinstance(doc.get('names'),dict) or not isinstance(doc.get('calendar'),dict):continue
                if target.exists():
                    prior=read_document(target)
                    doc['names']={**doc['names'],**prior['names']}
                    for market,days in prior['calendar'].items():doc['calendar'][market]={**doc['calendar'].get(market,{}),**days}
                    if doc==prior:continue
            elif (doc.get('code'),doc.get('frequency'),doc.get('adjustment'))!=(query.code,query.frequency,'none'):continue
            write_document(target,doc);copied+=1
        except (OSError,ValueError,KeyError):continue
    return copied


def native_futures(config, local_root, query, cancel, now):
    """Use already published overview daily bars, not another App's live store."""
    from dashboard.marketdata.repository import MarketDataRepository,ReferenceBook
    from dashboard.marketdata.contract_reference import latest_contracts
    from dashboard.marketdata.history_publication import maintenance_root
    from dashboard.marketdata.overview_daily import read_day,merge_daily
    from dashboard.native.continuous import slot_map
    from dashboard.indicator_v6.sources import dates_between
    from index_futures_basis.security_futures import future_name
    if query.frequency!='1d':raise ValueError('股指期货仅支持已缓存日线，不能把日线当成分钟或最新行情')
    if local_time(query.end).date()>now.date():raise ValueError('结束日期不能晚于今日')
    days=dates_between(query.start,query.end)
    if not days:raise ValueError('所选窗口没有已核验交易日')
    if len(days)>1800:raise ValueError('股指日线单次最多1800交易日，请分段')
    meta=latest_contracts(ReferenceBook(config.get('reference_file')).data)
    continuous=len(query.code.split('.')[0])==4
    mapping={d:slot_map(meta,query.code[:2],d)[0].get(query.code) if continuous else query.code for d in days}
    roots=config.get('history_roots') or []
    repo=MarketDataRepository(roots,allow_unverified=config.get('allow_unverified',False),publication=maintenance_root(roots)/'publication.json') if roots else None
    frozen=repo.freeze() if repo is not None else {}
    tables={};fields=dict(close='close',open='open',high='high',low='low',volume='volume',amt='turnover',oi='open_interest')
    for symbol in sorted({s for s in mapping.values() if s}):
        if cancel.is_set():raise Cancelled('cancelled')
        try:
            if repo:
                key,source=repo.locate(symbol,'1d',frozen)
                frame=source.read_bars(symbol,'1d',start=local_time(query.start),
                    end=local_time(query.end)+pd.Timedelta(days=1)-pd.Timedelta(nanoseconds=1),
                    as_of=now,fields=(*fields.values(),'is_final'),version=frozen[key]['version'],
                    allow_unverified_availability=config.get('allow_unverified',False))
            else:frame=pd.DataFrame()
        except (OSError,ValueError):frame=pd.DataFrame()
        tables[symbol]=frame
    for day in days:
        if cancel.is_set():raise Cancelled('cancelled')
        symbol=mapping[day]
        row=read_day(config,local_root,day).get('rows',{}).get(symbol)
        if row and pd.Timestamp(row['source_at'])<=now:
            tables[symbol]=merge_daily(tables.get(symbol,pd.DataFrame()),[dict(row,event_time=pd.Timestamp(row['source_at']),is_final=True,
                turnover=row.get('amount'),open_interest=row.get('oi'))])
    values={symbol:{str(row['trade_date'])[:10]:row for row in frame.to_dict('records') if row.get('is_final')==True}
        for symbol,frame in tables.items()}
    rows=[dict(time=d,**{f:numeric(values.get(mapping[d],{}).get(d,{}).get(fields[f]),f) for f in query.required_fields}) for d in days]
    frame=pd.DataFrame(rows)
    for f in query.required_fields:frame[f]=pd.to_numeric(frame[f],errors='coerce')
    valid=frame.loc[frame[query.required_fields].notna().any(axis=1),'time']
    return SecurityResult(query,frame,calculate(query,frame),dict(schema_version=1,query=query.metadata(),mode='offline',
        query_time=now.isoformat(),name=future_name(query.code),source='本看板已发布日线',
        requests=0,actual_start=valid.iloc[0] if len(valid) else None,actual_end=valid.iloc[-1] if len(valid) else None,
        expected_rows=len(frame),missing_cells=int(frame[query.required_fields].isna().sum().sum()),
        contract_mapping=[dict(date=d,actual_code=mapping[d]) for d in days],
        versions={k:v['version'] for k,v in frozen.items()},timezone='Asia/Shanghai',
        units=dict(volume={k:v.get('descriptor',{}).get('volume_unit','未核验') for k,v in frozen.items()},
            amount='沿用源字段单位，未换算',price='原始报价单位，不复权',oi='手'),
        notes=['仅读已完成日线；当前日收盘尚未生成时留空，可选择上一交易日。','连续档位逐日实际合约拼接，不复权、不计算分红调整。']))


def execute(query, config, local_root, *, mode='wind', cancel=None, progress=lambda text:None, provider_factory=OwnedQueryProvider, now=None):
    from dashboard.marketdata.overview_windpy import executable
    now=local_time(now or datetime.now().astimezone())
    cancel=cancel if cancel is not None else QueryCancellation()
    if cancel.is_set():raise Cancelled('cancelled')
    if query.is_future:return native_futures(config,local_root,query,cancel,now)
    repo=Path(__file__).resolve().parents[2]
    shared=DataPaths.for_repo(repo)
    own=DataPaths.for_repo(repo,data_root=Path(config.get('overview_analysis_cache') or Path(local_root)/'analysis_data'))
    if own.root.resolve()==shared.root.resolve():raise ValueError('行情分析缓存需与原App数据目录分开')
    backend=deepcopy(DEFAULTS)
    backend.update(wind_python=executable(config,local_root),wind_timeout_seconds=45)
    # Own query files keep a different App's slow SDK request from holding our
    # writer lock. Relevant old verified cache is copied locally before querying.
    from shared_data.io import file_lock
    @contextmanager
    def cancellable_lock(path):
        while True:
            if cancel.is_set():raise Cancelled('cancelled')
            lease=file_lock(path,timeout=.2)
            try:lease.__enter__()
            except TimeoutError:continue
            break
        try:yield
        finally:lease.__exit__(None,None,None)
    service=SecurityService(own,backend,mode,cancel=cancel,lock_factory=cancellable_lock)
    _,cache_root=service.cache(query.frequency)
    # The independent App's catalog and lock files remain untouched, including
    # offline queries. Only verified relevant documents enter this App's cache.
    with cancellable_lock(cache_root/'.writer.lock'):
        seed_verified_cache(query,shared,cache_root)
    provider=provider_factory(backend) if mode=='wind' else None
    finished=threading.Event()
    def watch():
        while not finished.wait(.1):
            if cancel.is_set():
                if provider is not None:provider.close()
                return
    watcher=threading.Thread(target=watch,name='analysis-cancellation',daemon=True)
    watcher.start()
    try:
        result=service.query(query,progress,provider=provider,now=now)
        if cancel.is_set():raise Cancelled('cancelled')
        return result
    except Exception as exc:
        if cancel.is_set():raise Cancelled('cancelled') from None
        exc.query_stage=getattr(provider,'last_operation',None)
        raise
    finally:
        finished.set()
        if provider is not None:provider.close()
        watcher.join(timeout=2)
