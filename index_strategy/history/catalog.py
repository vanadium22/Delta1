"""Verified source routing and explicit field semantics."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re

FREQUENCIES = {"1分钟": "1m", "3分钟": "3m", "5分钟": "5m", "10分钟": "10m",
               "15分钟": "15m", "30分钟": "30m", "60分钟": "60m", "日线": "1d",
               "原始快照": "tick", "1秒（快照聚合）": "1s", "5秒（快照聚合）": "5s"}
MARKETS = {"SHF": "shfe", "DCE": "dce", "CZC": "czce", "INE": "ine",
           "GFE": "gfex", "CFE": "cffex", "SH": "sh", "SZ": "sz"}
BASE = {"open": "OpenPrice", "high": "HighPrice", "low": "LowPrice",
        "close": "ClosePrice", "volume": "Volume", "amount": "Amount"}
DAILY = {"open": "S_DQ_OPEN", "high": "S_DQ_HIGH", "low": "S_DQ_LOW",
         "close": "S_DQ_CLOSE", "volume": "S_DQ_VOLUME", "amount": "S_DQ_AMOUNT",
         "oi": "S_DQ_OI"}


@lru_cache(maxsize=1)
def sources():
    return json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))["sources"]


def identify(symbol: str, asset="auto"):
    symbol = symbol.strip().upper()
    match = re.fullmatch(r"([A-Z]+\d{0,4}|\d{6})\.([A-Z]+)", symbol)
    if not match or match[2] not in MARKETS:
        raise ValueError(f"不支持的代码 {symbol}；请使用 AU2612.SHF、600000.SH 等格式")
    code, exchange = match.groups()
    if exchange not in {"SH", "SZ"}:
        if not re.fullmatch(r"[A-Z]+(?:\d{2}|\d{3}|\d{4})?", code):
            raise ValueError(f"期货代码无效：{symbol}")
        if asset not in {"auto", "future"}:
            raise ValueError(f"{symbol} 是期货，请选择自动识别或期货")
        root = re.match("[A-Z]+", code)[0]
        kind = "ff" if exchange == "CFE" and root in {"IF", "IH", "IC", "IM"} else (
            "tf" if exchange == "CFE" else "future")
        asset = "future"
    else:
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(f"沪深证券代码应为六位数字：{symbol}")
        if asset == "auto":
            asset = "index" if (exchange == "SH" and code.startswith("000")) or code.startswith("399") else (
                "etf" if code.startswith(("5", "15", "16")) else "stock")
        if asset not in {"stock", "index", "etf"}:
            raise ValueError(f"{symbol} 请指定股票、指数或 ETF")
        kind = asset
    return {"symbol": symbol, "code": code, "exchange": exchange, "market": MARKETS[exchange],
            "kind": kind, "asset": asset}


def route(symbol: str, frequency: str, asset="auto"):
    info = identify(symbol, asset)
    if frequency not in FREQUENCIES.values():
        raise ValueError("不支持的下载频率")
    native = "tick" if frequency.endswith("s") else frequency
    wanted_kind = info["kind"] if native == "1d" or info["asset"] == "future" else "l1"
    wanted_market = "all" if native == "1d" else info["market"]
    matches = [s for s in sources() if s["kind"] == wanted_kind and s["market"] == wanted_market
               and s["frequency"] == native]
    if not matches:
        raise ValueError(f"目录中没有 {symbol} 的 {frequency} 来源；可尝试原始快照或其他频率")
    if len(matches) != 1:
        raise ValueError(f"{symbol} 存在多个来源，需要先明确数据表")
    return info, matches[0]


def field_map(source, *, asset, depth=3, oi=True):
    names = {c["name"] for c in source["columns"]}
    daily, tick = source["frequency"] == "1d", source["frequency"] == "tick"
    mapping = dict(DAILY if daily else BASE)
    if tick:
        # Snapshot OHLC are session-to-date values, never claim they are second bars.
        mapping = {"last": "LastPrice", "session_open": "OpenPrice", "session_high": "HighPrice",
                   "session_low": "LowPrice", "session_close": "ClosePrice", "volume": "TradeVolume", "amount": "TradeAmount",
                   "volume_total": "TotalVolume", "amount_total": "TotalAmount"}
    elif not daily and "TotalVolume" in names:
        mapping["volume_total"] = "TotalVolume"
    if not daily and oi and asset == "future":
        mapping["oi"] = "TotalPosition" if tick else "Position"
    if not oi or asset != "future":
        mapping.pop("oi", None)
    # An index has no tradable order book, even if its common table has book columns.
    if not daily and asset != "index":
        for level in range(1, depth + 1):
            for side, prefix in [("bid", "Buy"), ("ask", "Sell")]:
                mapping[f"{side}_price_{level}"] = f"{prefix}Price{level:02d}"
                mapping[f"{side}_volume_{level}"] = f"{prefix}Volume{level:02d}"
    missing = [name for name, column in mapping.items() if column not in names]
    return {name: column for name, column in mapping.items() if column in names}, missing


def source_note(info, source):
    if source["frequency"] == "1d":
        return "日线不含盘口；成交额统一为元，证券量为股/份，期货和指数为手；未复权"
    if info["asset"] == "index":
        return "指数行情无真实委托盘口；快照生成秒桶时只保留有数据的桶"
    return "价格未复权；缺档保留为空；秒桶仅表示快照观测，不填充无观测区间"


def order_book_source(source):
    matches = [s for s in sources() if s["kind"] == "future_l2" and s["market"] == source["market"]
               and s["frequency"] == "tick"]
    return matches[0] if len(matches) == 1 else None
