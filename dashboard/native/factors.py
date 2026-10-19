from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

from dashboard.formula_worker import validate
from .factor_worker import HELPERS

TEMPLATES=[
 {"id":"spread_z","name":"跨期分钟 Z 值","unit":"σ","params":{"window":30},
  "inputs":[{"name":"near","instrument_id":"$near","frequency":"1m","fields":["close"],"count":121,"unit":"bars"},
            {"name":"far","instrument_id":"$far","frequency":"1m","fields":["close"],"count":121,"unit":"bars"}],
  "code":"def compute(inputs, params):\n    spread = aligned_difference(inputs['near'], inputs['far'])\n    return {'价差 Z 值': zscore(spread, 'close', params['window'])}\n"},
 {"id":"multi_frequency","name":"日频背景与分钟偏离","unit":"bp","params":{"daily_window":20,"minute_window":30},
  "inputs":[{"name":"daily","instrument_id":"$spot","frequency":"1d","fields":["close"],"count":60,"unit":"trading_days"},
            {"name":"minutes","instrument_id":"$near","frequency":"1m","fields":["close"],"count":120,"unit":"bars"}],
  "code":"def compute(inputs, params):\n    day_mean = sma(inputs['daily'], 'close', params['daily_window'])\n    minute_mean = sma(inputs['minutes'], 'close', params['minute_window'])\n    spot = last(inputs['daily'], 'close')\n    future = last(inputs['minutes'], 'close')\n    return {'日频均值偏离': None if day_mean is None or spot is None else (spot / day_mean - 1) * 10000, '分钟均值偏离': None if minute_mean is None or future is None else (future / minute_mean - 1) * 10000}\n"},
 {"id":"second_mean","name":"秒级短窗偏离","unit":"bp","params":{"window":60},
  "inputs":[{"name":"seconds","instrument_id":"$near","frequency":"1s","fields":["close"],"count":180,"unit":"seconds"}],
  "code":"def compute(inputs, params):\n    reference = sma(inputs['seconds'], 'close', params['window'])\n    latest = last(inputs['seconds'], 'close')\n    return {'短窗偏离': None if reference is None or latest is None else (latest / reference - 1) * 10000}\n"},
 {"id":"live_calendar_book","name":"实时盘口跨期价差","unit":"点","params":{},
  "inputs":[{"name":"near","instrument_id":"$near","kind":"quote_observation","fields":["bid_price_1","ask_price_1"],"count":1,"max_age_seconds":30},
            {"name":"far","instrument_id":"$far","kind":"quote_observation","fields":["bid_price_1","ask_price_1"],"count":1,"max_age_seconds":30}],
  "code":"def compute(inputs, params):\n    near_ask = last(inputs['near'], 'ask_price_1')\n    near_bid = last(inputs['near'], 'bid_price_1')\n    far_ask = last(inputs['far'], 'ask_price_1')\n    far_bid = last(inputs['far'], 'bid_price_1')\n    if near_ask is None or near_bid is None or far_ask is None or far_bid is None:\n        return {'买入价差': None, '卖出价差': None}\n    if not (0 < near_bid <= near_ask and 0 < far_bid <= far_ask):\n        return {'买入价差': None, '卖出价差': None}\n    return {'买入价差': near_ask - far_bid, '卖出价差': near_bid - far_ask}\n"}
]


def definition(value):
    result={k:deepcopy(value.get(k)) for k in ("id","name","unit","params","inputs","code")}
    if not isinstance(result["id"],str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,49}",result["id"]):
        raise ValueError("公式 ID 需为小写字母开头的字母、数字、下划线")
    if not isinstance(result["name"],str) or not 1<=len(result["name"].strip())<=60:
        raise ValueError("请输入 1–60 字的公式名称")
    if not isinstance(result["unit"],str) or len(result["unit"])>20:
        raise ValueError("单位最多 20 字")
    if not isinstance(result["params"],dict) or len(json.dumps(result["params"],allow_nan=False))>4000:
        raise ValueError("参数需要小型 JSON 对象")
    def check(item,depth=0):
        if depth>4:
            raise ValueError("参数嵌套过深")
        if isinstance(item,dict):
            for key,val in item.items():
                if not isinstance(key,str):
                    raise ValueError("参数键必须为字符串")
                check(val,depth+1)
        elif isinstance(item,list):
            for val in item: check(val,depth+1)
        elif item is not None and (not isinstance(item,(str,bool,int,float)) or
            isinstance(item,(int,float)) and (not math.isfinite(item) or abs(item)>1e12)):
            raise ValueError("参数含无效值")
    check(result["params"])
    inputs=result["inputs"]
    if not isinstance(inputs,list) or not 1<=len(inputs)<=8:
        raise ValueError("公式需要声明 1–8 个输入")
    names=set()
    for item in inputs:
        if not isinstance(item,dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}",str(item.get("name",""))) or item["name"] in names:
            raise ValueError("输入名必须唯一，使用小写字母和下划线")
        names.add(item["name"])
        if not isinstance(item.get("instrument_id"),str) or not item["instrument_id"]:
            raise ValueError("请输入具体标的、映射别名或 $near/$far/$spot")
        if item["instrument_id"].startswith("$") and item["instrument_id"] not in {"$near","$far","$spot"}:
            raise ValueError("标的角色只支持 $near/$far/$spot")
        observation=item.get("kind")=="quote_observation"
        if item.get("kind","bars") not in {"bars","quote_observation"}:
            raise ValueError("输入种类只支持 bars 或 quote_observation")
        if not observation and (item.get("frequency") not in {"1d","1m","1s"} or item.get("unit","bars") not in {"bars","trading_days","seconds"}):
            raise ValueError("频率或窗口单位无效")
        if not observation and (item.get("unit")=="seconds" and item["frequency"]!="1s" or item.get("unit")=="trading_days" and item["frequency"]!="1d"):
            raise ValueError("seconds 窗口仅用于 1s；trading_days 窗口仅用于 1d")
        if type(item.get("count")) is not int or not 1<=item["count"]<=2000:
            raise ValueError("输入窗口为 1–2000")
        fields={"close","volume_total","bid_price_1","ask_price_1","bid_volume_1","ask_volume_1"} if observation else {"open","high","low","close","volume","turnover","open_interest","settlement","prev_close"}
        if observation and (item["count"]!=1 or type(item.get("max_age_seconds",30)) is not int or not 1<=item.get("max_age_seconds",30)<=3600):
            raise ValueError("实时观测输入当前支持最新 1 笔及 1–3600 秒接收过期阈值")
        if not isinstance(item.get("fields"),list) or not item["fields"] or not all(f in fields for f in item["fields"]):
            raise ValueError("请选择有效输入字段")
    validate(result["code"],api="v2",helpers=HELPERS)
    result["api"]="v2"
    result["version"]=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()[:16]
    result["enabled"]=bool(value.get("enabled",True))
    return result


def evaluate(spec, inputs):
    payload=json.dumps({"code":spec["code"],"params":spec["params"],"inputs":inputs},ensure_ascii=False,allow_nan=False).encode("utf-8")
    if len(payload)>2_000_000:
        raise ValueError("公式输入超过 2 MB，请缩短窗口或减少字段")
    try:
        completed=subprocess.run([sys.executable,"-I","-B",str(Path(__file__).with_name("factor_worker.py"))],
            input=payload,capture_output=True,timeout=3,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except subprocess.TimeoutExpired:
        raise ValueError("公式超过 3 秒，工作进程已终止") from None
    if completed.returncode or len(completed.stdout)>16000:
        raise ValueError("公式执行进程异常")
    result=json.loads(completed.stdout)
    if result.get("error"):
        raise ValueError(result["error"])
    return result["values"]
