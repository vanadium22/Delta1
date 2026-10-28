"""Call the independent collector, without its old settings/calendar defaults."""
from datetime import datetime,timezone
from pathlib import Path
import re
import threading
import time

from dashboard.marketdata.repository import ReferenceBook
from index_strategy.instant_dld.client import MarketDataClient
from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.contract_aliases import DualIdentityStore
from index_strategy.instant_dld.service import write_json

HEADLINE_INTERVAL_SECONDS=3
REQUEST_TIMEOUTS=(1,2)


class ScopedResolver:
    def __init__(self,index_ids,reference_file=None):
        self.index_ids=set(index_ids)
        self.reference=ReferenceBook(reference_file)
        self.store=None

    def resolve_many(self,symbols):
        result,errors={},{}
        for symbol in symbols:
            try:
                actual=symbol
                if re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE",symbol):
                    actual=self.reference.resolve_alias(symbol,datetime.now(timezone.utc))
                if actual not in self.index_ids and not re.fullmatch(r"(?:IF|IH|IC|IM)[0-9]{4}\.CFE",actual):
                    raise ValueError("仅支持已注册 A 股指数与 IF/IH/IC/IM 具体合约")
                if actual.endswith(".CFE") and not 1<=int(actual[-6:-4])<=12:
                    raise ValueError("具体合约月份须为 01–12")
                # Receipt date is not an exchange-certified event date.
                result[symbol]={"source_symbol":actual,"mapping_date":None,"trading_date":None}
            except ValueError as exc:
                errors[symbol]=str(exc)
        return result,errors


class RollingResolver:
    """Stable local slot subscriptions, re-resolved on every polling cycle."""
    def __init__(self, index_ids, reference_file, directory, *, now=None, synchronizer=None):
        from dashboard.marketdata.contract_reference import synchronize
        self.index_ids=set(index_ids)
        self.reference_file=reference_file
        self.directory=directory
        self.now=now or (lambda: datetime.now(timezone.utc))
        self.synchronize=synchronizer or synchronize
        self.status={}
        self.store=None

    def resolve_many(self, symbols):
        from dashboard.marketdata.contract_reference import latest_contracts
        from .continuous import slot_map
        now=self.now()
        self.status=self.synchronize(self.reference_file,self.directory,now=now)
        self.reference_file=self.status['reference_file']
        metadata=latest_contracts(ReferenceBook(self.reference_file).data)
        mappings={p:slot_map(metadata,p,now) for p in ('IF','IH','IC','IM')}
        result,errors={},{}
        for symbol in symbols:
            if symbol in self.index_ids:
                actual=symbol
            elif re.fullmatch(r'(?:IF|IH|IC|IM)0[0-3]\.CFE',symbol):
                mapping,error=mappings[symbol[:2]]
                actual=mapping.get(symbol)
                if not actual:
                    errors[symbol]=error;continue
            elif symbol in self.status['active_contracts']:
                actual=symbol
            else:
                errors[symbol]='合约不在当前有效挂牌范围';continue
            result[symbol]=dict(source_symbol=actual,mapping_date=None,trading_date=None)
        return result,errors


class CollectionJob:
    def __init__(self,local_root,*,lifetime_stop=None):
        self.local_root=Path(local_root)
        self.lifetime_stop=lifetime_stop
        self.worker=None
        self.stop_event=threading.Event()
        self.status={"status":"idle","rows":0,"polls":0,"error":None}
        self.lock=threading.Lock()

    def _policy(self):
        from dashboard.session_clock import session_policy
        if self.lifetime_stop is not None and self.lifetime_stop.is_set():
            return dict(allowed=False,reason='启动器已退出，停止本次采集')
        return session_policy()

    def state(self):
        with self.lock: return dict(self.status)

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def start(self,root,symbols,index_ids,reference_file=None,once=False,client_factory=MarketDataClient,auto_roll=False,config=None):
        from dashboard.session_clock import session_policy, SessionStop
        policy = self._policy()
        if not policy['allowed']:
            self.status.update(status='offline', error=None, note=policy['reason'])
            return
        if self.running():
            raise ValueError("采集任务正在运行")
        if not str(root).strip():
            raise ValueError("先选择新的实时保存目录")
        if not symbols or len(symbols)>100:
            raise ValueError("订阅需要 1–100 个代码")
        if auto_roll:
            from .overview_instruments import quote_registry
            extra_ids=set(quote_registry(config or {}))
            symbols=[f'{p}0{i}.CFE' for p in ('IF','IH','IC','IM') for i in range(4)]+sorted(set(index_ids)|extra_ids)
            if len(symbols)>100:
                raise ValueError('概览订阅超过100个代码，请缩减自选ETF/IOPV')
            resolver=RollingResolver(set(index_ids)|extra_ids,reference_file,self.local_root/'contract_reference')
        else:
            resolver=ScopedResolver(index_ids,reference_file)
            _,errors=resolver.resolve_many(symbols)
            if errors:
                raise ValueError("；".join(f"{s}: {error}" for s,error in errors.items()))
        symbols_file=self.local_root/"native_collection_symbols.json"
        self._overview_symbols=None
        write_json(symbols_file,symbols)
        self.stop_event.clear()
        self.status={"status":"starting","rows":0,"polls":0,"error":None}
        def work():
            client=None
            equities=None
            lease=None;leased=False
            try:
                if not self._policy()['allowed']:
                    self.status.update(status='stopped');return
                import json
                from dashboard.session_guard import network_lease
                path=self.local_root/'native.json'
                self.status.update(stage='network_lock',started_at=datetime.now(timezone.utc).isoformat())
                lease=network_lease(config if config is not None else json.loads(path.read_text(encoding='utf8')) if path.exists() else {})
                lease.__enter__()
                leased=True
                if not self._policy()['allowed']:
                    self.status.update(status='stopped');return
                client=client_factory(connect_timeout=REQUEST_TIMEOUTS[0],read_timeout=REQUEST_TIMEOUTS[1])
                self.status.update(interval_seconds=HEADLINE_INTERVAL_SECONDS,request_timeouts=list(REQUEST_TIMEOUTS))
                if auto_roll and not once:
                    from .equity_collection import EquitySampler
                    equities=EquitySampler(self.local_root,config or {},
                        lambda:self._policy() if not self.stop_event.is_set() else dict(allowed=False),client_factory)
                    self.equities=equities
                    equities.start()
                raw_fetch=client.fetch
                def guarded_fetch(symbols):
                    if not self._policy()['allowed']:
                        self.stop_event.set()
                        return dict(status='session_closed', received_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=0)
                    started=time.perf_counter()
                    self.status.update(stage='request',request_started_at=datetime.now(timezone.utc).isoformat())
                    result=raw_fetch(symbols)
                    if auto_roll:
                        # A completed weekly review changes ETF subscriptions on
                        # the next collector cycle without restarting the App.
                        from dashboard.marketdata.overview_reference import load
                        from .overview_instruments import quote_registry
                        current=load(config or {},self.local_root)
                        extra=set(quote_registry(config or {},current['data']))
                        desired=[f'{p}0{i}.CFE' for p in ('IF','IH','IC','IM') for i in range(4)]+sorted(set(index_ids)|extra)
                        if len(desired)<=100 and desired!=getattr(self,'_overview_symbols',None):
                            resolver.index_ids=set(index_ids)|extra
                            write_json(symbols_file,desired)
                            self._overview_symbols=desired
                    self.status.update(request_seconds=time.perf_counter()-started,received_at=result.get('received_at'))
                    return result
                client.fetch=guarded_fetch
                with DualIdentityStore(Path(root)) as store:
                    original=store.batch
                    def batch(record):
                        started=time.perf_counter();self.status['stage']='validation_and_storage'
                        original(record)
                        with self.lock:
                            good=record.get("status") in {"success", "partial"}
                            self.status.update(status="running" if good else "disconnected",rows=self.status["rows"]+len(store.last_rows),
                                               polls=record["poll"],last_at=record["received_at"],
                                               last_result=record.get("status"),error=None if good else record.get("error",record.get("status")))
                            self.status['missing_symbols']=record.get('missing_symbols',[])
                            self.status['reference']=getattr(resolver,'status',{})
                            if good:self.status['last_success_at']=record['received_at']
                            else:self.status.update(last_failure_at=record['received_at'],last_failure_status=record.get('status'))
                            self.status.update(stage='waiting_new_quote' if good else 'request_failed',
                                storage_finished_at=datetime.now(timezone.utc).isoformat(),storage_seconds=time.perf_counter()-started,
                                data_sequence=max((r['sequence'] for r in store.last_rows),default=self.status.get('data_sequence',0)),
                                valid_rows=len(store.last_rows),validation_status=(store.last_report or {}).get('status'),
                                invalid_symbols=(store.last_report or {}).get('failed_symbols',[]))
                    store.batch=batch
                    collect(client,store,[symbols_file],interval=HEADLINE_INTERVAL_SECONDS,max_polls=1 if once else 0,
                            stop=SessionStop(self.stop_event, self._policy),resolver=resolver)
                with self.lock: self.status["status"]="stopped" if not self.status.get("error") else "failed"
            except Exception as exc:
                from dashboard.connection_diagnostics import error_detail
                with self.lock:self.status.update(status="failed",error=type(exc).__name__,
                    diagnostics=error_detail(exc,self.status.get('stage','collection')))
            finally:
                try:
                    if equities is not None:
                        equities.stop()
                        while equities.running():equities.worker.join(.1)
                    if client is not None: client.close()
                finally:
                    if leased: lease.__exit__(None,None,None)
        self.worker=threading.Thread(target=work,name="native-market-collection",daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        if getattr(self,'equities',None) is not None:self.equities.stop()
