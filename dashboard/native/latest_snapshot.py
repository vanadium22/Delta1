"""Bounded out-of-session quote lookup; never written into the realtime store."""
from datetime import time
import hashlib
import json
from pathlib import Path
import uuid

import pandas as pd

from dashboard.marketdata.bars import _atomic_bytes,_json_bytes
from dashboard.marketdata.overview_reference import load as load_reference
from dashboard.marketdata.overview_sessions import latest_completed_session
from dashboard.marketdata.quote_quality import quote_quality
from index_strategy.instant_dld.quotes import normalize_quote
from index_strategy.instant_dld.raw_store import publish_raw_batch
from .instruments import UNDERLYINGS
from .overview_instruments import quote_registry


def load(local_root):
    try:
        value=json.loads((Path(local_root)/'overview_snapshots/latest.json').read_text(encoding='utf8'))
        return value if isinstance(value,dict) and value.get('schema')=='overview-latest-snapshot-v1' and isinstance(value.get('quotes'),dict) and all(isinstance(q,dict) for q in value['quotes'].values()) else {}
    except (OSError,ValueError,TypeError):return {}


def fingerprint(quote):
    keys=('close','prev_close','open','high','low','volume_total','quote_time')
    return hashlib.sha256(json.dumps([quote.get(k) for k in keys],allow_nan=False,default=str).encode()).hexdigest()


def collect(config,local_root,*,now=None,client_factory=None,stop=lambda:False):
    from dashboard.session_guard import network_lease
    from dashboard.marketdata.repository import ReferenceBook
    from dashboard.marketdata.contract_reference import active_contracts
    from index_strategy.instant_dld.client import MarketDataClient
    from index_strategy.instant_dld.reader import RealtimeReader
    now=pd.Timestamp(now or pd.Timestamp.now(tz='Asia/Shanghai'))
    day=latest_completed_session(now.to_pydatetime())
    source_day_hint=latest_completed_session(now.to_pydatetime(),ready_at=time(15,0))
    reference=load_reference(config,local_root,now=now.to_pydatetime())
    registry=quote_registry(config,reference['data'],day)
    symbols=sorted(set(registry)|{v[0] for v in UNDERLYINGS.values()})
    try:symbols=sorted(set(symbols)|set(active_contracts(ReferenceBook(config.get('reference_file')).data,day)))
    except (OSError,ValueError):pass
    if len(symbols)>100:raise ValueError('概览快照代码超过100个')
    before=load(local_root);previous=before.get('quotes',{}).copy();known={}
    if config.get('realtime_root'):
        reader=RealtimeReader(config['realtime_root'])
        if reader.db_path.is_file():
            for row in reader.latest(symbols).to_dict('records'):
                at=row.get('received_at')
                if at and quote_quality(row,pd.Timestamp(at)).get('usable'):
                    known[row['source_symbol']]=row
    with network_lease(config):
        if stop():return dict(status='cancelled')
        client=(client_factory or MarketDataClient)(connect_timeout=1,read_timeout=2)
        try:result=client.fetch(symbols)
        finally:client.close()
        result.update(symbols=symbols,poll=1,batch=1,batch_count=1)
        root=Path(local_root)/'overview_snapshots'
        evidence=publish_raw_batch(root,uuid.uuid4().hex,result)
        if result.get('status') not in ('success','partial'):
            return dict(status='unavailable',response_status=result.get('status'),received_at=result.get('received_at'),raw=evidence)
        data=(result.get('response') or {}).get('data',{});received=0
        for symbol in symbols:
            raw=data.get(symbol)
            if not isinstance(raw,dict):continue
            try:
                row=normalize_quote(symbol,raw,result['received_at'])
                if not row.get('quote_time'):continue
                date_basis='日历推定，行情源日期未认证';source_day=source_day_hint;explicit=False
                for field in ('tradeDate','tradingDate','tradingDay'):
                    if raw.get(field) is not None:
                        parsed=pd.Timestamp(str(raw[field])).date().isoformat()
                        if parsed>str(now.tz_convert('Asia/Shanghai').date()):raise ValueError('未来交易日期')
                        source_day=parsed;date_basis='源端显式交易日';explicit=True;break
                old=known.get(symbol) or previous.get(symbol)
                if not explicit and old and fingerprint(old)==fingerprint(row) and old.get('source_event_time'):
                    source_day=str(pd.Timestamp(old['source_event_time']).tz_convert('Asia/Shanghai').date())
                    date_basis='相同报价保留原源日期；非新的市场变化'
                source=source_day+'T'+row['quote_time']+'+08:00'
                if pd.Timestamp(source)>now+pd.Timedelta(seconds=3):continue
                row.update(source_event_time=source,observed_at=result['received_at'],
                    source_date_basis=date_basis,observation_mode='off_session_snapshot',source_kind='http_snapshot')
                previous[symbol]=row
                received+=1
            except (ValueError,TypeError,KeyError):continue
        value=dict(schema='overview-latest-snapshot-v1',fetched_at=result['received_at'],
                   expected_completed_session=day,quotes=previous,raw=evidence)
        if received and not stop():_atomic_bytes(root/'latest.json',_json_bytes(value))
        return dict(status='snapshot_received' if received else 'no_valid_quotes',symbols=len(symbols),observations=len(previous),received_quotes=received,
                    received_at=result['received_at'],expected_completed_session=day,
                    note='盘前盘后最新获取快照，非实时；源日期依据逐值保留')
