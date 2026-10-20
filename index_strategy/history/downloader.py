"""Direct-route query adapter from the existing history client; no VPN operations."""
from pathlib import Path
import time as clock
import numpy as np
import pandas as pd
from .catalog import identify, field_map, order_book_source, source_note
from .contracts import source_query_identity
from .transforms import normalize_units, units
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / 'dashboard/localsetting/ddb.connection.local.json'

def merge_book(bars, book):
    """As-of book never uses a later quote or carries one across a long session gap."""
    columns = [c for c in book if c.startswith(("bid_", "ask_"))]
    left = bars.copy()
    right = book.rename(columns={"timestamp": "book_timestamp", **{c: "l2_" + c for c in columns}})
    result = pd.merge_asof(left.sort_values("timestamp"), right.sort_values("book_timestamp"),
                         left_on="timestamp", right_on="book_timestamp", direction="backward",
                         tolerance=pd.Timedelta(seconds=60))
    fills = [[] for _ in range(len(result))]
    for column in sorted(columns, key=lambda c: "_volume_" in c):
        if column not in result:
            result[column] = np.nan
        if "_price_" in column:
            result[column] = result[column].where((result[column] > 0) & (result[column] < 1e100))
        mask = result[column].isna() & result["l2_" + column].notna()
        if "_volume_" in column:
            price = column.replace("_volume_", "_price_")
            # A displayed quote and its size must refer to the same price.
            mask &= np.isclose(result[price], result["l2_" + price], rtol=0, atol=1e-9) if price in result and "l2_" + price in result else False
        result.loc[mask, column] = result.loc[mask, "l2_" + column]
        for index in np.flatnonzero(mask):
            fills[index].append(column)
    result["filled_fields"] = [", ".join(x) for x in fills]
    result["data_origin"] = ["mixed" if x else "native" for x in fills]
    return result.drop(columns=["l2_" + c for c in columns])

class Client:
    def __init__(self, *args, **kwargs):
        raise RuntimeError('Use dashboard.marketdata.history_maintenance.open_direct')

    def close(self):
        if self._closed:
            return
        self._closed = True
        session, self.session = self.session, None
        if session is not None:
            session.close()

    def bind(self, source, symbol):
        self.session.upload({"downloadDb": source["db"], "downloadTable": source["table"],
                             "downloadCode": symbol})
        key = source["db"], source["table"]
        # Fail explicitly if the installed catalog has drifted from the live source.
        if key not in self.source_cache:
            actual = self.session.run("schema(loadTable(downloadDb,downloadTable)).colDefs")
            if not set(c["name"] for c in source["columns"]).issubset(set(actual["name"])):
                raise RuntimeError(f"{source['table']} 字段已变化，需要刷新目录")
            self.source_cache.add(key)
        self.session.run("downloadSource = loadTable(downloadDb,downloadTable)")

    def fetch(self, source, actual, day, request):
        info = identify(actual, request["asset"])
        l2 = order_book_source(source) if request["depth"] > 1 and info["asset"] == "future" else None
        if source["frequency"] == "tick" and l2:
            source = l2
        query_identity = source_query_identity(source, actual, day)
        code = query_identity["source_query_code"]
        self.bind(source, code)
        mapping, missing = field_map(source, asset=info["asset"], depth=request["depth"], oi=request["oi"])
        daily, tick = source["frequency"] == "1d", source["frequency"] == "tick"
        day_col, code_col = ("TRADE_DT", "S_INFO_WINDCODE") if daily else ("TradingDate", "Symbol")
        self.session.upload({"downloadDate": np.datetime64(day, "D")})
        condition = f"{day_col} = downloadDate, {code_col} = downloadCode"
        fields = [f"{day_col} as trading_date", ("TRADE_DT" if daily else "TradingTime") + " as timestamp"]
        fields += [f"{column} as {name}" for name, column in mapping.items()]
        start = clock.perf_counter()
        n = int(self.session.run(f"exec count(*) from downloadSource where {condition}"))
        if n > 500000:
            raise ValueError(f"{actual} {day} 超过单日 50 万行，请缩小数据类型或进一步分块")
        raw = self.session.run(f"select {', '.join(fields)} from downloadSource where {condition} order by timestamp")
        book_note = None
        raw, unit_factors = normalize_units(raw, info, source["frequency"])
        if not raw.empty and not daily and not tick and l2 and request.get("mode") != "native":
            self.bind(l2, source_query_identity(l2, actual, day)["source_query_code"])
            book_map, _ = field_map(l2, asset="future", depth=request["depth"], oi=False)
            book_map = {k: v for k, v in book_map.items() if k.startswith(("bid_", "ask_"))}
            book_fields = ['TradingTime as timestamp'] + [f'{v} as {k}' for k,v in book_map.items()]
            count = int(self.session.run(f"exec count(*) from downloadSource where {condition}"))
            if count > 500000:
                raise ValueError("L2 盘口超过单日 50 万行，需要进一步分块")
            book = self.session.run(f"select {', '.join(book_fields)} from downloadSource where {condition} order by timestamp")
            if len(book) != count:
                raise RuntimeError("盘口源表在查询期间发生变化")
            if not book.empty:
                book, _ = normalize_units(book, info, "tick")
                raw = merge_book(raw, book)
                book_note = {"source": f"{l2['db']}/{l2['table']}", "source_rows": len(book),
                             "rule": "取不晚于分钟标签的最后一条L2盘口，最多相差60秒；book_timestamp为实际盘口时间",
                             "field_mapping": book_map,
                             "columns": l2["columns"]}
            else:
                missing.append("L2盘口：该日无记录，保留原表有效档位")
        query_seconds = clock.perf_counter() - start
        if len(raw) != n:
            raise RuntimeError("源表在查询期间发生变化，请稍后重试")
        if raw.empty:
            return raw, {"source_rows": 0, "query_seconds": query_seconds, "missing_fields": missing,
                         **query_identity}
        if not raw.trading_date.dt.date.eq(day).all():
            raise RuntimeError("返回的交易日与请求不一致")
        start = clock.perf_counter()
        for column in raw:
            if "_price_" in column or column in {"open", "high", "low", "close", "last", "session_open", "session_high", "session_low"}:
                raw[column] = raw[column].where((raw[column] > 0) & (raw[column] < 1e100))
        for side in ("bid", "ask"):
            for level in range(1, request["depth"] + 1):
                price, volume = f"{side}_price_{level}", f"{side}_volume_{level}"
                if price in raw and volume in raw:
                    raw[volume] = raw[volume].where(raw[price].notna())
        data = raw
        duplicates_removed = 0
        if not tick:
            before = len(data)
            data = data.drop_duplicates()
            duplicates_removed = before - len(data)
            if data.duplicated(["trading_date", "timestamp"]).any():
                raise ValueError(f"{actual} {day} 同一时间有冲突行情，不能自动选择版本")
        return data, {"source_rows": n, "query_seconds": query_seconds, **query_identity,
                      "transform_seconds": clock.perf_counter() - start, "missing_fields": missing,
                      "null_counts": {k: int(v) for k, v in data.isna().sum().items()},
                      "field_mapping": mapping, "source_columns": source["columns"],
                      "source_frequency": source["frequency"], "unit_factors": unit_factors,
                      "units": units(info), "duplicates_removed": duplicates_removed,
                      "source": f"{source['db']}/{source['table']}", "order_book": book_note,
                      "note": source_note(info, source),
                      "bar_semantics": "左闭右开，时间为桶起点；无快照的桶不生成；成交量为源分笔期间量求和，盘口/OI取末条（含空值）"
                          if request["frequency"].endswith("s") else (
                          "原始快照：session_*为当日累计OHLC；last为最新价" if tick else "源表原始频率、原始时间标签；价格未复权；量额已统一单位")}
