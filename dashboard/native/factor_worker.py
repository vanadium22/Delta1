"""Bounded v2 formula worker. Standard library only, launched in isolation."""
import ast
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys

spec=importlib.util.spec_from_file_location("_base_formula",Path(__file__).resolve().parents[1]/"formula_worker.py")
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def column(rows,field):
    if not isinstance(rows,list) or len(rows)>2000 or not isinstance(field,str):
        raise ValueError("column 需要不超过 2000 行的数据及字段名")
    values=[r.get(field) for r in rows]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise ValueError("输入列包含缺失或无效值")
    return values


def last(rows,field):
    return rows[-1].get(field) if rows else None


def sma(rows,field,window):
    if type(window) is not int or not 1<=window<=2000:
        raise ValueError("window 必须为 1–2000 的整数")
    if len(rows)<window:
        return None
    return statistics.mean(column(rows[-window:],field))


def aligned_difference(left,right,field="close"):
    if max(len(left),len(right))>2000:
        raise ValueError("对齐输入最多 2000 行")
    lookup={(r["event_time"],r["trade_date"],r.get("session_id")):r for r in right}
    rows=[]
    for item in left:
        match=lookup.get((item["event_time"],item["trade_date"],item.get("session_id")))
        if match is not None and item.get(field) is not None and match.get(field) is not None:
            rows.append({"event_time":item["event_time"],"trade_date":item["trade_date"],
                         "session_id":item.get("session_id"),"frequency":item.get("frequency"),
                         "close":item[field]-match[field]})
    return rows


def zscore(rows,field,window):
    if type(window) is not int or not 2<=window<=1999:
        raise ValueError("zscore window 需要 2–1999")
    if rows and rows[-1].get("frequency") in {"1m","1s"}:
        latest=rows[-1]
        rows=[r for r in rows if (r.get("trade_date"),r.get("session_id"))==(latest.get("trade_date"),latest.get("session_id"))]
    if len(rows)<window+1:
        return None
    prior=column(rows[-window-1:-1],field)
    sigma=statistics.stdev(prior)
    return (column(rows[-1:],field)[0]-statistics.mean(prior))/sigma if sigma>1e-12 else None


HELPERS={**base.HELPERS,"column":column,"last":last,"sma":sma,
         "aligned_difference":aligned_difference,"zscore":zscore}


def run(payload):
    tree=base.validate(payload["code"],api="v2",helpers=HELPERS)
    tree=ast.fix_missing_locations(base.NumericOperations().visit(tree))
    namespace={"__builtins__":{},**HELPERS,"_arithmetic":base.bounded_arithmetic}
    exec(compile(tree,"<formula-v2>","exec"),namespace)
    values=namespace["compute"](payload["inputs"],payload["params"])
    if not isinstance(values,dict) or not 1<=len(values)<=20:
        raise ValueError("输出须为包含 1–20 个指标的 dict")
    for key,value in values.items():
        if not isinstance(key,str) or not 1<=len(key)<=60:
            raise ValueError("指标名称需要 1–60 字")
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e15):
            raise ValueError("指标必须为有限数值或 None")
    return values


if __name__=="__main__":
    try:
        payload=json.loads(sys.stdin.buffer.read(2_000_001))
        response={"values":run(payload)}
    except Exception as exc:
        response={"error":f"{type(exc).__name__}: {exc}"}
    sys.stdout.buffer.write(json.dumps(response,ensure_ascii=False,allow_nan=False).encode("utf-8"))
