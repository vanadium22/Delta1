"""Formula validation and process execution, independent of the collector."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

from index_strategy.instant_dld.symbols import parse_symbols
from .formula_worker import validate


def definition(value):
    if not isinstance(value, dict):
        raise ValueError("公式必须为 JSON 对象")
    result = {key: deepcopy(value.get(key)) for key in ("id", "name", "symbols", "params", "code", "unit")}
    if not isinstance(result["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", result["id"]):
        raise ValueError("公式 ID 需为小写字母开头的字母、数字、下划线，最多 50 位")
    if not isinstance(result["name"], str) or not 1 <= len(result["name"].strip()) <= 60:
        raise ValueError("请输入 1–60 字的公式名称")
    result["name"] = result["name"].strip()
    if not isinstance(result["unit"], str) or len(result["unit"]) > 20:
        raise ValueError("单位最多 20 字")
    raw_symbols = result["symbols"]
    result["symbols"] = parse_symbols(json.dumps(raw_symbols) if isinstance(raw_symbols, list) else raw_symbols,
                                      ".json" if isinstance(raw_symbols, list) else ".txt")
    if not 1 <= len(result["symbols"]) <= 20:
        raise ValueError("每个公式声明 1–20 个输入标的")
    if not isinstance(result["params"], dict):
        raise ValueError("参数必须为 JSON 对象")
    def check(v, depth=0):
        if depth > 4:
            raise ValueError("参数嵌套过深")
        if isinstance(v, dict):
            for k, item in v.items():
                if not isinstance(k, str):
                    raise ValueError("参数键必须为字符串")
                check(item, depth + 1)
        elif isinstance(v, list):
            for item in v:
                check(item, depth + 1)
        elif v is not None and (not isinstance(v, (str, bool, int, float)) or
                               isinstance(v, (int, float)) and (not math.isfinite(v) or abs(v) > 1e12)):
            raise ValueError("参数包含无效数值")
    check(result["params"])
    if len(json.dumps(result["params"], ensure_ascii=False)) > 4000:
        raise ValueError("参数过长")
    validate(result["code"])
    result["version"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    result["enabled"] = bool(value.get("enabled", True))
    return result


def evaluate(spec, quotes, history):
    missing = [symbol for symbol in spec["symbols"] if symbol not in quotes]
    if missing:
        raise ValueError("缺少输入行情：" + ", ".join(missing))
    payload = {"code": spec["code"], "params": spec["params"],
               "quotes": {s: quotes[s] for s in spec["symbols"]},
               "history": {s: history.get(s, [])[-300:] for s in spec["symbols"]}}
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > 2_000_000:
        raise ValueError("公式输入超过 2 MB")
    try:
        completed = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).with_name("formula_worker.py"))],
                                   input=encoded, capture_output=True, timeout=3,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise ValueError("公式运行超过 3 秒，已终止工作进程") from None
    if completed.returncode or len(completed.stdout) > 16000:
        raise ValueError("公式工作进程异常或输出过大")
    response = json.loads(completed.stdout)
    if response.get("error"):
        raise ValueError(response["error"])
    return response["values"]
