"""Small, editable, restricted-Python factor templates."""

TEMPLATES = [
    {"id": "calendar_spread", "name": "跨期价差", "description": "近月 − 远月；同时观察两侧盘口价差。",
     "symbols": ["IC00.CFE", "IC01.CFE"], "params": {"near": "IC00.CFE", "far": "IC01.CFE"}, "unit": "点",
     "code": '''def compute(quotes, history, params):
    near = quotes[params["near"]]
    far = quotes[params["far"]]
    return {
        "中间价差": near["mid"] - far["mid"],
        "买入价差": near["ask_price_1"] - far["bid_price_1"],
        "卖出价差": near["bid_price_1"] - far["ask_price_1"],
    }
'''},
    {"id": "index_basis", "name": "期现基差", "description": "期货最新价 − 指数；仅作观察，指数本身不可直接成交。",
     "symbols": ["IC00.CFE", "000905.SH"], "params": {"future": "IC00.CFE", "index": "000905.SH"}, "unit": "点",
     "code": '''def compute(quotes, history, params):
    future = quotes[params["future"]]["close"]
    index = quotes[params["index"]]["close"]
    return {"期现基差": future - index}
'''},
    {"id": "orderbook_balance", "name": "一档盘口不平衡", "description": "买卖一档数量之差 / 数量之和；不代表主动买卖成交。",
     "symbols": ["510300.SH"], "params": {"symbol": "510300.SH"}, "unit": "比例",
     "code": '''def compute(quotes, history, params):
    quote = quotes[params["symbol"]]
    bid = quote["bid_volume_1"]
    ask = quote["ask_volume_1"]
    total = bid + ask
    if total <= 0:
        return {"盘口不平衡": None}
    return {"盘口不平衡": (bid - ask) / total}
'''},
    {"id": "rolling_deviation", "name": "价格偏离", "description": "相对最近 N 条有效采样均值的偏离；采样条数不是秒数。",
     "symbols": ["AU.SHF"], "params": {"symbol": "AU.SHF", "window": 20}, "unit": "基点",
     "code": '''def compute(quotes, history, params):
    symbol = params["symbol"]
    average = sma(history[symbol], "close", params["window"])
    if average is None:
        return {"均值偏离": None}
    return {"均值偏离": (quotes[symbol]["close"] / average - 1) * 10000}
'''},
]
