"""Versioned, display-only snapshots. Viewer never imports the calculation model."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import uuid

import pandas as pd
from .pair_research import export_research
from .presentation import (FREQUENCY_OPTIONS,FRAME_NAMES,VALUE_NAMES,ANALYTIC_NAMES,
    SHOW_SPECIAL,SHOW_EVENTS,SHOW_DETAIL,SHOW_EVENT_DETAIL)

PRODUCTS = ("IF", "IH", "IC", "IM")
FREQUENCIES = tuple(item[0] for item in FREQUENCY_OPTIONS)
SCHEMA = "delta1_dashboard_view_v3"
DEFAULT_PUBLISH_ROOT = Path(__file__).resolve().parents[1] / "runtime" / "published"
FRAME_KEYS = FRAME_NAMES
FRAME_COLUMNS = ("event_time", "trade_date", "session_id", "close", "value")
STATE_KEYS = ("as_of", "product", "frequency", "demo", "roles", "contracts_verified", "indices",
              "values", "reasons", "term", "book", "book_reason", "history_limited", "live_quotes")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def view_key(product, frequency):
    if product not in PRODUCTS or frequency not in FREQUENCIES:
        raise ValueError("不支持的品种或频率")
    return product + ":" + frequency


def empty_state(request):
    names = ("沪深300", "上证50", "中证500", "中证1000")
    return {"as_of":utc_now(), "product":request.get("product", "IC"),
        "frequency":request.get("frequency", "1m"), "demo":bool(request.get("demo")),
        "roles":{"$near":None,"$far":None,"$spot":None}, "contracts_verified":False,
        "indices":[{"name":name,"close":None,"change":None,"time":None} for name in names],
        "values":dict.fromkeys(("spread","basis_bp","zscore","realized_bp","percentile")),
        "reasons":{}, **{key:pd.DataFrame() for key in FRAME_KEYS}, "term":[], "book":None,
        "book_reason":"等待已发布盘口结果", "factors":[], "timeline":[], "versions":{},
        "errors":[], "history_limited":False, "replay":False, "live_quotes":0,
        "analytics":{}, "events":[], "relative_value":[],
        "publication_error":"等待市场数据", "publication_stale":True}


def encode_state(state):
    # Explicit allowlists keep code, credentials, local paths, and raw errors out.
    result = {key:deepcopy(state[key]) for key in STATE_KEYS}
    result["frames"] = {}
    for key in FRAME_KEYS:
        frame = state.get(key,pd.DataFrame())
        columns = [c for c in FRAME_COLUMNS if c in frame]
        result["frames"][key] = json.loads(frame[columns].tail(2000).to_json(orient="records",date_format="iso"))
    result["factors"] = []
    for factor in state["factors"]:
        spec = factor["spec"]
        result["factors"].append({"spec":{**{k:spec[k] for k in ("id","name","version","unit")},
            "inputs":[{"frequency":i.get("frequency","实时观测")} for i in spec["inputs"]]},
            "values":deepcopy(factor.get("values",{})), "quality":factor["quality"],
            **({"error":"指标输入不足或计算失败"} if factor.get("error") else {})})
    analytics=state.get("analytics",{})
    numeric_keys=("calendar_bp","calendar_z","basis_z","beta","r_squared","residual_bp","residual_z","samples","window")
    result["analytics"] = {k:deepcopy(analytics[k]) for k in numeric_keys if k in analytics}
    result["analytics"]["reasons"]={k:v for k,v in analytics.get("reasons",{}).items() if k in numeric_keys}
    if "carry" in analytics:
        carry=analytics["carry"]
        carry_keys=("fair_value","fair_deviation_bp","net_space_bp","annualized_basis_pct","implied_carry_pct","near_days","far_days")
        result["analytics"]["carry"]={k:deepcopy(carry[k]) for k in carry_keys if k in carry}
        result["analytics"]["carry"]["reasons"]={k:v for k,v in carry.get("reasons",{}).items() if k in (*carry_keys,"model","expiry")}
    result["events"] = [{k:deepcopy(item[k]) for k in
        ("product","type","title","event_time","last_time","value","peak","unit","threshold","status","duration","lifecycle","quality","reason") if k in item}
        for item in state.get("events",[])[:24]]
    pair_keys=("left","right","basis_gap_bp","beta","r_squared","residual_bp","residual_z","samples","window")
    result["relative_value"] = [{**{k:deepcopy(pair[k]) for k in pair_keys if k in pair},
        "reasons":{k:v for k,v in pair.get("reasons",{}).items() if k in pair_keys}} for pair in state.get("relative_value",[])[:12]]
    result["has_history"] = bool(state["versions"])
    if SHOW_SPECIAL:
        if SHOW_DETAIL:
            result["pair_research"] = export_research(state.get("pair_research",{}))
    receipts=state.get("live_receipts",{})
    result["book_valid_until"] = (min(pd.Timestamp(t) for t in receipts.values())+pd.Timedelta(seconds=30)).isoformat() if receipts and state["book"] else None
    return result


def decode_state(value):
    result = {key:deepcopy(value[key]) for key in STATE_KEYS}
    result["values"]={key:result["values"].get(key) for key in VALUE_NAMES}
    def numeric(number):
        if number is not None and (isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number)):
            raise ValueError("发布数值无效")
    if pd.Timestamp(result["as_of"]).tzinfo is None: raise ValueError("行情截止时刻缺少时区")
    for number in result["values"].values(): numeric(number)
    if len(result["indices"])!=4: raise ValueError("指数卡片数量无效")
    for item in result["indices"]:
        numeric(item["close"]);numeric(item["change"])
        if item["time"] and pd.Timestamp(item["time"]).tzinfo is None: raise ValueError("指数时刻无效")
    if SHOW_DETAIL:
        for item in result["term"]:
            if not isinstance(item["symbol"],str): raise ValueError("合约代码无效")
            numeric(item["close"])
        if result["book"]:
            for key in ("buy","sell","mid"): numeric(result["book"][key])
    else:
        result.update(term=[],book=None,book_reason="")
    for key in ("$near","$far","$spot"):
        if result["roles"][key] is not None and not isinstance(result["roles"][key],str): raise ValueError("标的绑定无效")
    factors=[]
    if SHOW_SPECIAL:
        for factor in value["factors"]:
            for key in ("id","name","version","unit"):
                if not isinstance(factor["spec"][key],str): raise ValueError("指标说明无效")
            if not isinstance(factor["spec"]["inputs"],list): raise ValueError("指标输入说明无效")
            for item in factor["values"].values(): numeric(item)
            if not isinstance(factor["quality"],str): raise ValueError("指标质量无效")
            allowed=set(FREQUENCIES)
            if SHOW_DETAIL: allowed.add("实时观测")
            if all(i.get("frequency") in allowed for i in factor["spec"]["inputs"]): factors.append(deepcopy(factor))
    for key in FRAME_KEYS:
        rows = value["frames"].get(key,[])
        if not isinstance(rows,list) or len(rows)>2000:
            raise ValueError("发布图表规模无效")
        frame = pd.DataFrame(rows)
        if len(frame):
            required={"event_time","trade_date","session_id","value" if key in ("spread","basis","regression") else "close"}
            if not required.issubset(frame): raise ValueError("图表字段不完整")
            frame["event_time"] = pd.to_datetime(frame["event_time"],utc=True,errors="raise")
            frame["trade_date"] = pd.to_datetime(frame["trade_date"],errors="raise").dt.date
            for column in ("close","value"):
                if column in frame: frame[column]=pd.to_numeric(frame[column],errors="raise")
        result[key] = frame
    def validate_numbers(item):
        if isinstance(item,dict):
            for nested in item.values(): validate_numbers(nested)
        elif isinstance(item,list):
            for nested in item: validate_numbers(nested)
        elif isinstance(item,(int,float)) and not isinstance(item,bool): numeric(item)
    extensions=[("analytics",{})]
    if SHOW_EVENTS: extensions.append(("events",[]))
    if SHOW_SPECIAL: extensions.append(("relative_value",[]))
    if SHOW_SPECIAL:
        if SHOW_DETAIL:
            extensions.append(("pair_research",{}))
    result.update(events=[],relative_value=[])
    for key,default in extensions:
        item=value.get(key,default)
        if not isinstance(item,type(default)): raise ValueError("观察指标结构无效")
        validate_numbers(item)
        result[key]=deepcopy(item)
    result["analytics"]={key:item for key,item in result["analytics"].items() if key in ANALYTIC_NAMES}
    if SHOW_EVENTS:
        for event in result["events"]:
            if pd.Timestamp(event["event_time"]).tzinfo is None: raise ValueError("事件时刻缺少时区")
        if SHOW_EVENT_DETAIL: pass
        else:
            result["events"]=[{k:v for k,v in e.items() if k in {"event_time","product","type","title","value","unit","threshold","status","quality","reason"}} for e in result["events"]]
    result.update(factors=factors,timeline=[],errors=[],replay=False,
                  versions={"published":"view"} if value["has_history"] else {})
    result["book_valid_until"]=value.get("book_valid_until")
    return result


def write_publication(root, bundle):
    root = Path(root)
    root.mkdir(parents=True,exist_ok=True)
    path = root / ("demo.json" if bundle["demo"] else "current.json")
    payload = json.dumps(bundle,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=root,suffix=".tmp",delete=False) as out:
            temporary = Path(out.name)
            out.write(payload);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()
    return path


def make_bundle(states, demo=False):
    now = utc_now()
    return {"schema_version":SCHEMA,"snapshot_id":uuid.uuid4().hex,"generated_at":now,
        "heartbeat_at":now,"demo":bool(demo),
        "views":{view_key(s["product"],s["frequency"]):encode_state(s) for s in states}}


class ViewerModel:
    """Only consumes publication files. It cannot edit settings, execute or collect."""
    edition = "viewer"

    def __init__(self, publish_root=None, local_root=None, max_age_seconds=120):
        self.publish_root = Path(publish_root or DEFAULT_PUBLISH_ROOT).resolve()
        self.local_root = Path(local_root or Path(__file__).resolve().parents[1]/"localsetting"/"viewer").resolve()
        self.config = {"product":"IC","frequency":"1m"}
        self.max_age_seconds = max_age_seconds
        self._last_good = {}
        self._last_signature = None
        self._read_errors = {}

    def snapshot(self,request):
        key = view_key(request.get("product","IC"),request.get("frequency","1m"))
        demo = bool(request.get("demo"))
        path = self.publish_root / ("demo.json" if demo else "current.json")
        error = None
        try:
            if path.stat().st_size>32*1024*1024: raise ValueError("发布文件过大")
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if bundle["schema_version"]!=SCHEMA: raise ValueError("版本不兼容，请更新看板程序")
            if bundle["demo"] is not demo: raise ValueError("演示与真实快照不匹配")
            stamp = pd.Timestamp(bundle["heartbeat_at"])
            if stamp.tzinfo is None: raise ValueError("发布时间缺少时区")
            if (stamp-pd.Timestamp.now(tz="UTC")).total_seconds()>5: raise ValueError("发布时间晚于本机时钟")
            state = decode_state(bundle["views"][key])
            if view_key(state["product"],state["frequency"])!=key or state["demo"] is not demo:
                raise ValueError("发布视图标识不匹配")
            # Validate a complete frequency before caching it: every column uses one snapshot.
            decoded={key:state}
            for product in PRODUCTS:
                other_key=view_key(product,state["frequency"])
                if other_key not in decoded and other_key in bundle["views"]:
                    other=decode_state(bundle["views"][other_key])
                    if view_key(other["product"],other["frequency"])!=other_key or other["demo"] is not demo:
                        raise ValueError("市场视图标识不匹配")
                    decoded[other_key]=other
            for profile,item in decoded.items():
                self._last_good[(demo,profile)] = (item,bundle["snapshot_id"],bundle["generated_at"],bundle["heartbeat_at"])
        except FileNotFoundError:
            error = "等待市场数据；保留末次可用结果"
        except Exception as exc:
            error = "市场数据不可用，保留末次可用结果" + ("；请更新看板程序" if "版本不兼容" in str(exc) else "")
        self._read_errors[demo]=error
        result=self._cached_state(request)
        self._last_signature = self._signature(request,result)
        return result

    def _cached_state(self,request):
        demo=bool(request.get("demo"))
        key=view_key(request.get("product","IC"),request.get("frequency","1m"))
        error=self._read_errors.get(demo)
        cached = self._last_good.get((demo,key))
        if cached is None:
            result = empty_state(request)
            result["publication_error"] = error or "该品种 / 频率尚未发布"
        else:
            result = deepcopy(cached[0])
            age = (pd.Timestamp.now(tz="UTC")-pd.Timestamp(cached[3])).total_seconds()
            result.update(publication_id=cached[1],published_at=cached[2],publication_stale=bool(error) or (not demo and age>self.max_age_seconds))
            if result["book"] and (result["publication_stale"] or not result.get("book_valid_until") or pd.Timestamp.now(tz="UTC")>pd.Timestamp(result["book_valid_until"])):
                result["book"]=None
                result["book_reason"]="已发布盘口接收时间过期，等待重新计算"
            if error: result["publication_error"] = error
        return result

    def market_states(self,frequency,demo=False):
        return {product:self._cached_state({"product":product,"frequency":frequency,"demo":demo})
                for product in PRODUCTS}

    def _signature(self,request,state):
        limit={"1d":129600,"1m":120,"1s":5}[state["frequency"]]
        freshness=tuple(bool(len(state[key])) and (pd.Timestamp.now(tz="UTC")-state[key].iloc[-1].event_time).total_seconds()>limit for key in FRAME_KEYS)
        return (request.get("demo",False),request.get("product","IC"),request.get("frequency","1m"),
                state.get("publication_id"),state.get("publication_error"),state.get("publication_stale"),state.get("book_reason"),freshness)

    def auto_snapshot(self,request):
        previous = self._last_signature
        state = self.snapshot(request)
        return None if self._last_signature==previous else state

    def _deny(self,*args,**kwargs):
        raise PermissionError("精简版仅允许读取已发布指标")

    save_config = publish_formula = preview = archive = result_history = _deny

    def close(self):
        pass
