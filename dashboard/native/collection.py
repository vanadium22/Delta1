"""Call the independent collector, without its old settings/calendar defaults."""
from datetime import datetime,timezone
from pathlib import Path
import re
import threading

from dashboard.marketdata.repository import ReferenceBook
from index_strategy.instant_dld.client import MarketDataClient
from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.contract_aliases import DualIdentityStore
from index_strategy.instant_dld.service import write_json


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
    def __init__(self,local_root):
        self.local_root=Path(local_root)
        self.worker=None
        self.stop_event=threading.Event()
        self.status={"status":"idle","rows":0,"polls":0,"error":None}
        self.lock=threading.Lock()

    def state(self):
        with self.lock: return dict(self.status)

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def start(self,root,symbols,index_ids,reference_file=None,once=False,client_factory=MarketDataClient,auto_roll=False):
        if self.running():
            raise ValueError("采集任务正在运行")
        if not str(root).strip():
            raise ValueError("先选择新的实时保存目录")
        if not symbols or len(symbols)>100:
            raise ValueError("订阅需要 1–100 个代码")
        if auto_roll:
            symbols=[f'{p}0{i}.CFE' for p in ('IF','IH','IC','IM') for i in range(4)]+sorted(index_ids)
            resolver=RollingResolver(index_ids,reference_file,self.local_root/'contract_reference')
        else:
            resolver=ScopedResolver(index_ids,reference_file)
            _,errors=resolver.resolve_many(symbols)
            if errors:
                raise ValueError("；".join(f"{s}: {error}" for s,error in errors.items()))
        symbols_file=self.local_root/"native_collection_symbols.json"
        write_json(symbols_file,symbols)
        self.stop_event.clear()
        self.status={"status":"starting","rows":0,"polls":0,"error":None}
        def work():
            client=None
            try:
                client=client_factory(connect_timeout=5,read_timeout=10)
                with DualIdentityStore(Path(root)) as store:
                    original=store.batch
                    def batch(record):
                        original(record)
                        with self.lock:
                            good=record.get("status") in {"success", "partial"}
                            self.status.update(status="running" if good else "disconnected",rows=self.status["rows"]+len(store.last_rows),
                                               polls=record["poll"],last_at=record["received_at"],
                                               last_result=record.get("status"),error=None if good else record.get("error",record.get("status")))
                            self.status['missing_symbols']=record.get('missing_symbols',[])
                            self.status['reference']=getattr(resolver,'status',{})
                    store.batch=batch
                    collect(client,store,[symbols_file],interval=2,max_polls=1 if once else 0,
                            stop=self.stop_event,resolver=resolver)
                with self.lock: self.status["status"]="stopped" if not self.status.get("error") else "failed"
            except Exception as exc:
                with self.lock: self.status.update(status="failed",error=str(exc))
            finally:
                if client is not None: client.close()
        self.worker=threading.Thread(target=work,name="native-market-collection",daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
