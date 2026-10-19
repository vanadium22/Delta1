"""UI-independent native state, data queries, formulas and result archives."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import pandas as pd

from dashboard.marketdata.repository import MarketDataRepository,ReferenceBook
from dashboard.marketdata.adapters import read_realtime_observations
from dashboard.results import ResultStore
from index_strategy.instant_dld.service import write_json
from index_strategy.instant_dld.reader import RealtimeReader

from .demo import UNDERLYINGS,generate
from .factors import TEMPLATES,definition,evaluate
from .metrics import summarize,executable_spread
from .analytics import enrich_state,carry_values
from .pair_research import build_research

MODULE_ROOT=Path(__file__).resolve().parents[1]


def records(frame):
    return json.loads(frame.to_json(orient="records",date_format="iso",date_unit="ns"))


class NativeModel:
    def __init__(self,local_root=None):
        self.local_root=Path(local_root or MODULE_ROOT/"localsetting").resolve()
        self.local_root.mkdir(parents=True,exist_ok=True)
        self.path=self.local_root/"native.json"
        self.config={"history_roots":[],"realtime_root":"","realtime_id":"","reference_file":"",
            "results_root":str(MODULE_ROOT/"runtime"/"native_results"),"allow_unverified":False,
            "product":"IC","frequency":"1m","collection_symbols":[v[0] for v in UNDERLYINGS.values()],
            "dividend_missing_policy":"previous_contract"}
        if self.path.exists():
            self.config.update(json.loads(self.path.read_text(encoding="utf-8")))
        from dashboard.data_package import activate_config
        from dashboard.marketdata.paths import DATA_ROOT
        self.config=activate_config(self.config,self.local_root,DATA_ROOT)
        formula_file=self.local_root/"native_formulas.json"
        self.formulas=[definition(x) for x in json.loads(formula_file.read_text(encoding="utf-8"))] if formula_file.exists() else [definition(x) for x in TEMPLATES]
        self.demo=False
        self.repo=None
        self.root_key=None
        self.results=None
        self.results_key=None
        self.live_cursor=0
        self.live_rows=pd.DataFrame()
        self.live_key=None
        self.formula_cache={}
        self.last_signature=None
        self.live_deadline=None
        self.quote_deadlines=[]

    def save_config(self,config):
        if config.get("product","IC") not in UNDERLYINGS or config.get("frequency","1m") not in {"1d","1m","1s"}:
            raise ValueError("品种或频率无效")
        registered={}
        for root in config.get("history_roots",[]):
            report=MarketDataRepository.inspect(root)
            if report["synthetic"]:
                raise ValueError("合成样例请从演示入口查看，不能注册为新真实数据")
            for row in report["coverage"]:
                key=(row["instrument_id"],row["frequency"])
                if key in registered and registered[key] != report["root"]:
                    raise ValueError(f"{key}存在多个来源，先合并核验冲突，不能重复注册")
                registered[key]=report["root"]
        write_json(self.path,config)
        self.config=deepcopy(config)
        self.root_key=None
        if hasattr(self,"research_engine"): del self.research_engine
        return deepcopy(self.config)

    def sync_contract_reference(self, *, force=False):
        """Explicit UI/collector action; snapshot() remains offline and read-only."""
        from dashboard.session_clock import session_policy
        policy = session_policy()
        if not policy['allowed']:
            return dict(status='offline', message=policy['reason'], reference_file=self.config.get('reference_file'))
        from dashboard.marketdata.contract_reference import synchronize
        status=synchronize(self.config.get('reference_file'),self.local_root/'contract_reference',force=force)
        candidate=deepcopy(self.config)
        candidate.update(reference_file=status['reference_file'],
                         collection_symbols=[*status['active_contracts'],*[v[0] for v in UNDERLYINGS.values()]])
        if candidate!=self.config:
            backup=self.local_root/'contract_reference'/'native.before_auto.json'
            if not backup.exists():write_json(backup,self.config)
            self.save_config(candidate)
        self.contract_sync=status
        return status

    def publish_formula(self,value):
        spec=definition(value)
        candidate=[spec if item["id"]==spec["id"] else item for item in self.formulas]
        if not any(item["id"]==spec["id"] for item in candidate):
            candidate.append(spec)
        if len(candidate)>12:
            raise ValueError("初版最多保留 12 个公式")
        write_json(self.local_root/"native_formula_versions"/spec["id"]/(spec["version"]+".json"),spec)
        write_json(self.local_root/"native_formulas.json",candidate)
        self.formulas=candidate
        return spec

    def configure_repository(self,demo):
        roots=generate(MODULE_ROOT/"runtime"/"native_demo_v3") if demo else self.config["history_roots"]
        key=(demo,tuple(roots),self.config.get("allow_unverified",False))
        if self.root_key!=key:
            from dashboard.marketdata.history_publication import maintenance_root
            publication=maintenance_root(roots)/'publication.json' if roots and not demo else None
            self.repo=MarketDataRepository(roots,allow_unverified=self.config.get("allow_unverified",False),publication=publication)
            self.root_key=key
            self.formula_cache.clear()
        self.demo=demo
        return self.repo

    def result_directory(self):
        return (self.local_root/"demo_results" if self.demo else Path(self.config["results_root"])).resolve()

    def live_instruments(self,frozen,roles,reference,as_of,specs):
        instruments=self.repo.symbols(frozen)
        for code,_,_ in UNDERLYINGS.values():
            instruments.setdefault(code,{"asset_type":"cn_index","market_region":"CN"})
        symbols=[*self.config.get("collection_symbols",[]),*roles.values(),
                 *[i["instrument_id"] for spec in specs for i in spec["inputs"]]]
        for symbol in symbols:
            symbol=roles.get(symbol,symbol)
            if not symbol: continue
            if re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE",symbol):
                try: symbol=reference.resolve_alias(symbol,as_of)
                except ValueError: continue
            if re.fullmatch(r"(?:IF|IH|IC|IM)[0-9]{4}\.CFE",symbol) and 1<=int(symbol[-6:-4])<=12:
                instruments.setdefault(symbol,{"asset_type":"cn_index_future","market_region":"CN"})
        return instruments

    def bindings(self,product,as_of,repo,frozen,reference):
        symbols=repo.symbols(frozen)
        extra=[] if self.demo else self.config.get("collection_symbols",[])
        for alias in extra:
            if re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE",alias):
                try: extra=[*extra,reference.resolve_alias(alias,as_of)]
                except ValueError: pass
        candidates=sorted((s for s in set(symbols)|set(extra) if re.fullmatch(product+r"[0-9]{4}\.CFE",s)),key=lambda s:s[len(product):len(product)+4])
        day=pd.Timestamp(as_of).tz_convert("Asia/Shanghai").date().isoformat()
        verified=[s for s in candidates if (r:=reference.contract(s,as_of)) and r["listing_date"]<=day<=r["expiry_date"]]
        has_reference=any(reference.contract(s,as_of) is not None for s in candidates)
        order=verified if has_reference else candidates
        return {"$near":order[0] if order else None,"$far":order[1] if len(order)>1 else None,
                "$spot":symbols.get(order[0],{}).get("underlying_id",UNDERLYINGS[product][0]) if order else UNDERLYINGS[product][0]},order,bool(verified)

    def _live(self,instruments,as_of=None):
        root=self.config.get("realtime_root")
        if self.demo or not root:
            return {}
        path=Path(root)/"live"/"quotes.sqlite3"
        if not path.is_file():
            return {}
        identifier=self.config.get("realtime_id") or hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
        # Reset when the caller-selected database is replaced, not just when its path changes.
        stat=path.stat()
        key=(str(path.resolve()),getattr(stat,"st_birthtime_ns",stat.st_ino),identifier,tuple(sorted(instruments)))
        if key!=self.live_key:
            with RealtimeReader(root).connect() as con:
                self.live_cursor=max(0,int(con.execute("SELECT COALESCE(MAX(sequence),0) FROM quotes").fetchone()[0])-5000)
            self.live_rows=pd.DataFrame()
            self.live_key=key
        frame,cursor=read_realtime_observations(root,dataset_id=identifier,instruments=instruments,after_sequence=self.live_cursor,limit=10000)
        self.live_cursor=cursor["sequence"]
        if len(frame):
            self.live_rows=pd.concat([self.live_rows,frame],ignore_index=True).drop_duplicates("observation_id").tail(10000)
        eligible=self.live_rows
        if as_of is not None and len(eligible): eligible=eligible[eligible["observed_at"]<=pd.Timestamp(as_of)]
        return {str(row.instrument_id):row.to_dict() for _,row in eligible.sort_values("sequence").drop_duplicates("instrument_id",keep="last").iterrows()} if len(eligible) else {}

    def _formula(self,spec,roles,as_of,frozen,reference,live=None):
        inputs={}
        provenance=[]
        quote_times=[]
        limited_history=False
        for declaration in spec["inputs"]:
            symbol=roles.get(declaration["instrument_id"],declaration["instrument_id"])
            if symbol is None:
                raise ValueError("对应合约尚无新数据")
            if re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE",symbol):
                symbol=reference.resolve_alias(symbol,as_of)
            if declaration.get("kind")=="quote_observation":
                quote=(live or {}).get(symbol)
                if not quote:
                    raise ValueError(f"缺少 {symbol} 的新实时观测")
                stamp=pd.Timestamp(quote["observed_at"])
                if not 0<=(pd.Timestamp(as_of)-stamp).total_seconds()<=declaration.get("max_age_seconds",30):
                    raise ValueError(f"{symbol} 实时接收时刻过期或晚于截止时刻")
                quote_times.append(stamp)
                selected={key:quote.get(key) for key in declaration["fields"]}
                selected.update(observed_at=stamp,source_time_verified=False,instrument_id=symbol)
                inputs[declaration["name"]]=records(pd.DataFrame([selected]))
                provenance.append({"name":declaration["name"],"instrument_id":symbol,"dataset_id":self.config.get("realtime_id"),
                    "frequency":"observation","rows":1,"as_of":pd.Timestamp(as_of).isoformat(),
                    "received_at":stamp.isoformat(),"source_time_verified":False,"cursor":self.live_cursor})
                continue
            frame=self.repo.read_window(symbol,declaration["frequency"],count=declaration["count"],
                unit=declaration.get("unit","bars"),as_of=as_of,fields=declaration["fields"],
                frozen=frozen,dataset_id=declaration.get("dataset_id"))
            if frame.empty:
                raise ValueError(f"{symbol} / {declaration['frequency']} 没有截止时刻已可用的输入")
            limited=frame["available_at"].isna().any() or frame.attrs["availability_policy"]!="source_reported" or ((frame["quality_flags"].astype("uint32") & 191)!=0).any()
            limited_history=limited_history or bool(limited)
            inputs[declaration["name"]]=records(frame)
            provenance.append({"name":declaration["name"],"instrument_id":symbol,"dataset_id":frame.attrs["dataset_id"],
                 "version":frame.attrs["version"],"frequency":declaration["frequency"],"rows":len(frame),
                 "as_of":pd.Timestamp(as_of).isoformat(),"last_event_time":frame.iloc[-1].event_time.isoformat(),
                 "last_trade_date":str(frame.iloc[-1].trade_date),
                 "quality_limited":bool(limited),
                 "availability_policy":frame.attrs["availability_policy"]})
        if quote_times and (max(quote_times)-min(quote_times)).total_seconds()>3:
            raise ValueError("实时公式两腿接收时刻偏差超过 3 秒")
        fingerprint=hashlib.sha256(json.dumps({"version":spec["version"],"inputs":inputs,"product_roles":roles},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        if fingerprint not in self.formula_cache:
            self.formula_cache[fingerprint]=evaluate(spec,inputs)
            if len(self.formula_cache)>100:
                self.formula_cache.pop(next(iter(self.formula_cache)))
        values=self.formula_cache[fingerprint]
        return {"spec":spec,"values":values,"inputs":provenance,"fingerprint":fingerprint,
                "quality":"synthetic" if self.demo else "warmup" if any(v is None for v in values.values()) else "unverified_observation" if quote_times else "unverified_history" if limited_history else "research"}

    def preview(self,spec,request):
        spec=definition(spec)
        repo=self.configure_repository(request.get("demo",False))
        frozen=repo.freeze()
        reference=ReferenceBook(None if self.demo else self.config.get("reference_file"))
        as_of=request.get("as_of") or self.default_time(frozen)
        roles,_,_=self.bindings(request.get("product","IC"),as_of,repo,frozen,reference)
        instruments=self.live_instruments(frozen,roles,reference,as_of,[spec,*self.formulas])
        return self._formula(spec,roles,as_of,frozen,reference,self._live(instruments,as_of))

    def default_time(self,frozen):
        if self.demo:
            ends=[pd.Timestamp(p["max_time"]) for m in frozen.values() for p in m["parts"]]
            return max(ends)+pd.Timedelta(seconds=2) if ends else pd.Timestamp.now(tz="UTC")
        return pd.Timestamp.now(tz="UTC")

    def snapshot(self,request):
        if self.config.get("dashboard_mode") == "nonregression" and not request.get("demo"):
            from .nonregression import ResearchEngine
            if not hasattr(self, "research_engine"): self.research_engine = ResearchEngine(self)
            return self.research_engine.snapshot(request)
        # Capture before reading: a commit arriving during calculation must trigger the next refresh.
        observed_signature=self.source_signature() if not request.get("demo") and not request.get("as_of") else None
        repo=self.configure_repository(request.get("demo",False))
        frozen=repo.freeze()
        product=request.get("product","IC")
        frequency=request.get("frequency","1m")
        reference=ReferenceBook(None if self.demo else self.config.get("reference_file"))
        as_of=pd.Timestamp(request.get("as_of") or self.default_time(frozen))
        roles,contracts,verified=self.bindings(product,as_of,repo,frozen,reference)
        errors=[]
        def load(symbol,freq=frequency,count=180,fields=("close",)):
            if not symbol:
                return pd.DataFrame()
            try:
                return repo.read_window(symbol,freq,count=count,as_of=as_of,fields=fields,frozen=frozen)
            except ValueError as exc:
                errors.append(str(exc))
                return pd.DataFrame()
        near,far,spot=[load(roles[key],count=600 if frequency=="1s" else 180) for key in ("$near","$far","$spot")]
        values,reasons,spread,basis=summarize(near,far,spot,frequency)
        indices=[]
        for code,name,_ in UNDERLYINGS.values():
            current=load(code,count=2,fields=("close","prev_close"))
            daily=load(code,"1d",count=3,fields=("close","prev_close"))
            last=current.iloc[-1] if len(current) else None
            previous=None
            if last is not None and len(daily):
                same=daily[daily["trade_date"]==last.trade_date]
                if len(same) and pd.notna(same.iloc[-1].prev_close):
                    previous=float(same.iloc[-1].prev_close)
                else:
                    before=daily[daily["trade_date"]<last.trade_date]
                    if len(before): previous=float(before.iloc[-1].close)
            close=float(last.close) if last is not None and pd.notna(last.close) else None
            indices.append({"symbol":code,"name":name,"close":close,
                "change":(close/previous-1)*100 if close is not None and previous not in (None,0) else None,
                "time":last.event_time.isoformat() if last is not None else None})
        term=[]
        contract_frames={}
        contract_metadata={}
        for symbol in contracts:
            frame=near if symbol==roles["$near"] else far if symbol==roles["$far"] else load(symbol,count=180)
            contract_frames[symbol]=frame
            contract_metadata[symbol]=reference.contract(symbol,as_of) or {}
            if len(frame) and pd.notna(frame.iloc[-1].close):
                term.append({"symbol":symbol,"close":float(frame.iloc[-1].close),"time":frame.iloc[-1].event_time.isoformat()})
        # A term curve uses only points at one event time, never mixed stale months.
        if term:
            same_time=max(item["time"] for item in term)
            term=[item for item in term if item["time"]==same_time]
        instruments=self.live_instruments(frozen,roles,reference,as_of,self.formulas)
        live=self._live(instruments,as_of)
        for item in indices:
            if item["symbol"] in live:
                quote=live[item["symbol"]]
                item.update(close=float(quote["close"]),change=None,time=quote["observed_at"].isoformat(),observation=True)
        book,book_reason=executable_spread(live.get(roles["$near"]),live.get(roles["$far"]),as_of)
        self.live_deadline=min(pd.Timestamp(live[s]["observed_at"]) for s in (roles["$near"],roles["$far"]))+pd.Timedelta(seconds=30) if all(s in live for s in (roles["$near"],roles["$far"])) else None
        self.quote_deadlines=[]
        for spec in self.formulas:
            if not spec["enabled"]: continue
            for declaration in spec["inputs"]:
                symbol=roles.get(declaration["instrument_id"],declaration["instrument_id"])
                if symbol and re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE",symbol):
                    try: symbol=reference.resolve_alias(symbol,as_of)
                    except ValueError: continue
                if declaration.get("kind")=="quote_observation" and symbol in live:
                    self.quote_deadlines.append(pd.Timestamp(live[symbol]["observed_at"])+pd.Timedelta(seconds=declaration.get("max_age_seconds",30)))
        if book and values["spread"] is None:
            values["spread"]=book["mid"]
            reasons["spread"]="一档盘口中间价差 · 源日期待核验"
        factors=[]
        for spec in deepcopy(self.formulas):
            if not spec["enabled"]: continue
            try:
                factors.append(self._formula(spec,roles,as_of,frozen,reference,live))
            except Exception as exc:
                factors.append({"spec":spec,"values":{},"quality":"missing","error":str(exc)})
        timeline=[]
        if roles["$near"]:
            try:
                frame=repo.read_window(roles["$near"],frequency,count=2000,as_of=self.default_time(frozen),fields=("close",),frozen=frozen)
                timeline=[(r.available_at if pd.notna(r.available_at) else r.event_time).isoformat() for _,r in frame.iterrows()]
            except ValueError:
                pass
        state={"as_of":as_of.isoformat(),"product":product,"frequency":frequency,"demo":self.demo,
            "roles":roles,"contracts_verified":verified,"indices":indices,"values":values,"reasons":reasons,
            "spread":spread,"basis":basis,"near":near,"far":far,"spot":spot,"term":term,"book":book,"book_reason":book_reason,
            "contract_frames":contract_frames,"contract_metadata":contract_metadata,
            "factors":factors,"timeline":timeline,"versions":{k:v["version"] for k,v in frozen.items()},
            "errors":list(dict.fromkeys(errors)),"reference_version":reference.version,
            "live_receipts":{s:live[s]["observed_at"].isoformat() for s in (roles["$near"],roles["$far"]) if s in live},
            "history_limited":any(len(f) and (f["available_at"].isna().any() or ((f["quality_flags"].astype("uint32") & 191)!=0).any() or f.attrs.get("availability_policy")!="source_reported") for f in (near,far,spot)),
            "replay":bool(request.get("as_of")),"live_quotes":len(live),"live_cursor":self.live_cursor}
        enrich_state(state)
        rate_inputs=self.config.get("carry",{}).get(product,{})
        near_contract=reference.contract(roles["$near"],as_of) if roles["$near"] else None
        far_contract=reference.contract(roles["$far"],as_of) if roles["$far"] else None
        synced=len(near) and len(spot) and near.iloc[-1].event_time==spot.iloc[-1].event_time
        far_synced=synced and len(far) and near.iloc[-1].event_time==far.iloc[-1].event_time
        state["analytics"]["carry"]=carry_values(
            float(spot.iloc[-1].close) if synced else None,float(near.iloc[-1].close) if synced else None,
            float(near.iloc[-1].close) if far_synced else None,float(far.iloc[-1].close) if far_synced else None,
            near.iloc[-1].event_time if synced else as_of,near_contract.get("expiry_date") if near_contract else None,
            far_contract.get("expiry_date") if far_contract else None,
            rate_inputs.get("financing_rate"),rate_inputs.get("dividend_yield"),rate_inputs.get("cost_bp"))
        state["pair_research"]=build_research({product:state})
        if request.get("save",True) and (len(spread) or any(f.get("values") for f in factors)):
            try: self.archive(state)
            except Exception as exc:
                # A locked/unwritable output directory must not hide the whole UI.
                state["archive_error"]=str(exc)
        if not request.get("as_of") and not self.demo:
            self.last_signature=observed_signature
        return state

    def source_signature(self):
        paths=[Path(root)/"current.json" for root in self.config["history_roots"]]
        if self.config.get("reference_file"): paths.append(Path(self.config["reference_file"]))
        signature=[(str(p),hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in paths]
        root=self.config.get("realtime_root")
        if root and (Path(root)/"live"/"quotes.sqlite3").is_file():
            stat=(Path(root)/"live"/"quotes.sqlite3").stat()
            with RealtimeReader(root).connect() as con:
                signature.append((root,getattr(stat,"st_birthtime_ns",stat.st_ino),con.execute("SELECT COALESCE(MAX(sequence),0) FROM quotes").fetchone()[0]))
        signature.append(("book_expired",bool(self.live_deadline is not None and pd.Timestamp.now(tz="UTC")>self.live_deadline)))
        signature.append(("quote_expired",tuple(pd.Timestamp.now(tz="UTC")>deadline for deadline in self.quote_deadlines)))
        return signature

    def auto_snapshot(self,request):
        if self.config.get("dashboard_mode") == "nonregression": return self.snapshot(request)
        if self.source_signature()==self.last_signature: return None
        return self.snapshot(request)

    def archive(self,state):
        root=self.result_directory()
        if self.results_key!=str(root):
            if self.results: self.results.close()
            self.results=ResultStore(root)
            self.results_key=str(root)
        summary_spec={"id":"market_summary","name":"市场观察指标","version":"native_metrics_v1","unit":"mixed"}
        entries=[{"spec":summary_spec,"values":state["values"],"quality":"synthetic" if self.demo else "unverified_observation" if state["book"] and not len(state["near"]) else "unverified_history" if state["history_limited"] else "research"},*state["factors"]]
        for item in entries:
            if not item.get("values"): continue
            spec=item["spec"]
            inputs={"as_of":state["as_of"],"versions":state["versions"],"roles":state["roles"],
                    "frequency":state["frequency"],"product":state["product"],"demo":self.demo,
                    "reference_version":state["reference_version"],"declarations":item.get("inputs",[]),
                    "live_cursor":state["live_cursor"],"realtime_id":self.config.get("realtime_id"),
                    "observation_time_basis":"received_at; source event date unverified" if state["live_quotes"] else None}
            stable={"versions":state["versions"],"roles":state["roles"],"frequency":state["frequency"],
                    "fingerprint":item.get("fingerprint"),"reference_version":state["reference_version"],
                    "live_receipts":state["live_receipts"] if state["book"] and not len(state["near"]) else {},
                    "last_events":[f.iloc[-1].event_time.isoformat() if len(f) else None for f in (state["near"],state["spot"])]}
            identity=hashlib.sha256(json.dumps([spec["id"],spec["version"],stable,item["values"]],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
            input_days=[i["last_trade_date"] for i in item.get("inputs",[]) if i.get("last_trade_date")]
            received_days=[pd.Timestamp(i["received_at"]).tz_convert("Asia/Shanghai").date().isoformat() for i in item.get("inputs",[]) if i.get("received_at")]
            day=max(input_days or received_days) if input_days or received_days else str(state["near"].iloc[-1].trade_date) if len(state["near"]) else pd.Timestamp(state["as_of"]).tz_convert("Asia/Shanghai").date().isoformat()
            self.results.register_formula(spec)
            self.results.append({"id":identity,"factor_id":spec["id"],"version":spec["version"],"name":spec["name"],
                "calculated_at":datetime.now(timezone.utc).isoformat(),"trade_date":day,
                "quality":item["quality"],"unit":spec["unit"],"values":item["values"],"inputs":inputs})

    def result_history(self):
        root=self.result_directory()
        if self.results and self.results_key==str(root): return self.results.history(limit=200)
        path=root/"dashboard_live"/"results.sqlite3"
        if not path.is_file(): return []
        con=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
        try:
            con.row_factory=sqlite3.Row
            rows=[dict(r) for r in con.execute("SELECT * FROM results ORDER BY calculated_at DESC LIMIT 200")]
            for row in rows:
                row["values"]=json.loads(row.pop("values_json"));row["inputs"]=json.loads(row.pop("inputs_json"))
            return rows
        finally: con.close()

    def close(self):
        if self.results:
            self.results.close()
            self.results=None
