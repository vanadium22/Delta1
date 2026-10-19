"""One symbol/day per file, interruptible between queries, no database mutations."""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time as clock
import uuid

import numpy as np
import pandas as pd

from .catalog import field_map, identify, route, source_note, order_book_source
from .contracts import source_query_identity
from ..instant_dld.contracts import MainContractResolver, MAIN_SYMBOL, DEFAULT_MAPPING_FILE, DEFAULT_CALENDAR_FILE
from ..instant_dld.quotes import CHINA
from ..instant_dld.symbols import parse_symbols
from .transforms import (BASE_FIELDS, MODES, DERIVE_SOURCES, MAIN_RULES, normalize_units,
                         units, required_fields)

PUBLIC_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PUBLIC_ROOT / "dolphindb_data/config/connection.local.json"
if not DEFAULT_CONFIG.is_file():
    DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / 'dashboard/localsetting/ddb.connection.local.json'
DEFAULT_OUTPUT = Path(r"T:\inani\下载\AI\DolphinDB")


class Cancelled(Exception):
    pass


def validate(request):
    value = dict(request)
    symbols = value.get("symbols", "")
    value["symbols"] = parse_symbols(symbols if isinstance(symbols, str) else json.dumps(symbols))
    if not value["symbols"]:
        raise ValueError("请填写至少一个标的")
    start, end = (date.fromisoformat(value[k]) for k in ("start", "end"))
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    if end > datetime.now(CHINA).date():
        raise ValueError("结束日期不能晚于今天")
    value.setdefault("frequency", "1m")
    value.setdefault("asset", "auto")
    value.setdefault("mode", "fill")
    value.setdefault("derive_source", "auto")
    value.setdefault("main_rule", "same_day")
    value.setdefault("next_source", "local")
    value.setdefault("fields", list(BASE_FIELDS))
    if value["mode"] not in MODES.values() or value["derive_source"] not in DERIVE_SOURCES.values():
        raise ValueError("请选择有效的数据获取模式和生成来源")
    if value["main_rule"] not in MAIN_RULES.values() or value["next_source"] not in {"local", "wind"}:
        raise ValueError("历史合约映射规则无效")
    if not isinstance(value["fields"], list) or not value["fields"] or any(f not in BASE_FIELDS for f in value["fields"]):
        raise ValueError("至少选择一个有效行情字段")
    value["fields"] = list(dict.fromkeys(value["fields"]))
    value["depth"] = int(value.get("depth", 3))
    if value["depth"] not in range(4):
        raise ValueError("盘口档位只能选择 0、1、2、3")
    if value["frequency"] == "1d":
        value["depth"] = 0
    if value["frequency"] == "tick":
        if value["mode"] == "derived":
            raise ValueError("原始快照不能由更低频率数据还原，请选择原始优先或仅原始")
    elif value["frequency"].endswith("s"):
        value["mode"], value["derive_source"] = "derived", "tick"
    if value["mode"] == "derived" and value["derive_source"] == "1m" and value["frequency"] == "1m":
        raise ValueError("生成1分钟线应选择原始快照；1分钟不能从同频率重新生成")
    value["oi"] = bool(value.get("oi", True))
    value["output_dir"] = str(Path(value.get("output_dir") or DEFAULT_OUTPUT).expanduser().resolve())
    from .jobs import source_candidates
    for symbol in value["symbols"]:
        source_candidates(symbol, value)
    return value


def aggregate_seconds(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Half-open [t,t+N seconds) buckets labelled by start; no gap filling."""
    ordered = frame.sort_values("timestamp", kind="stable").copy()
    ordered["bucket"] = ordered["timestamp"].dt.floor(frequency)
    keys = ["trading_date", "bucket"]
    grouped = ordered.groupby(keys, sort=True, observed=True)
    result = grouped["last"].ohlc()
    # Last snapshot, including its nulls; groupby.last() would resurrect stale book levels.
    tail = ordered.drop_duplicates(keys, keep="last").set_index(keys)
    for column in ordered.columns:
        if column in {"timestamp", "bucket", "trading_date", "last"} or column.startswith("session_"):
            continue
        if column in {"volume", "amount"}:
            result[column] = grouped[column].sum(min_count=1)
        else:
            result[column] = tail[column]
    result["snapshot_count"] = grouped.size()
    return result.reset_index().rename(columns={"bucket": "timestamp"})


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
    def __init__(self, config_path=DEFAULT_CONFIG):
        import dolphindb as ddb
        # Shared clients and the dashboard understand current-user DPAPI profiles.
        from .credentials import load_config
        self.config = load_config(config_path)
        c = self.config
        import importlib.util
        vpn_path = PUBLIC_ROOT / "dolphindb_data/sslvpn.py"
        vpn_spec = importlib.util.spec_from_file_location("swhy_sslvpn", vpn_path)
        if vpn_spec is None or vpn_spec.loader is None:
            raise RuntimeError(f"SSLVPN helper is unavailable: {vpn_path}")
        vpn = importlib.util.module_from_spec(vpn_spec)
        vpn_spec.loader.exec_module(vpn)
        self.session = None
        self._closed = False
        self._vpn_entered = False
        self._vpn_scope = vpn.connection_scope(c["host"], c["port"])
        try:
            self.vpn_status = self._vpn_scope.__enter__()
            self._vpn_entered = True
            self.session = ddb.session(enableSSL=c.get("enable_ssl", True))
            started = clock.perf_counter()
            if not self.session.connect(c["host"], c["port"], c["username"],
                    os.environ.get("DDB_PASSWORD") or c.get("password", ""), readTimeout=60, writeTimeout=30):
                raise RuntimeError("DolphinDB 登录失败，请检查内网 VPN 和密码")
            self.connect_seconds = clock.perf_counter() - started
            self.mapping_cache = {}
            self.source_cache = set()
        except BaseException:
            # Constructor failure happens before the caller can close this client.
            self.close()
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        session, self.session = self.session, None
        try:
            if session is not None:
                session.close()
        finally:
            if self._vpn_entered:
                self._vpn_entered = False
                self._vpn_scope.__exit__(*sys.exc_info())

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

    def continuous(self, symbol, day):
        if symbol not in self.mapping_cache:
            self.session.upload({"aliasCode": symbol})
            self.mapping_cache[symbol] = self.session.run(
                'select S_INFO_WINDCODE,FS_MAPPING_WINDCODE,STARTDATE,ENDDATE,OPDATE '
                'from loadTable("dfs://ods_tsdb_wind","cfuturescontractmapping") '
                'where S_INFO_WINDCODE = aliasCode')
        rows = self.mapping_cache[symbol]
        valid = rows[(rows.STARTDATE.dt.date <= day) & (rows.ENDDATE.isna() | (rows.ENDDATE.dt.date >= day))]
        actuals = valid.FS_MAPPING_WINDCODE.dropna().unique()
        if len(actuals) != 1:
            raise ValueError(f"{symbol} 在 {day} 的连续映射缺失或冲突，未下载")
        chosen = valid.sort_values("OPDATE").iloc[-1]
        return {"source_symbol": str(actuals[0]), "mapping_date": str(chosen.STARTDATE.date()),
                "mapping_rule": "Wind有效区间（历史修订口径，非点时快照）"}

    def available_dates(self, source, code, start, end):
        self.bind(source, code)
        day_col, code_col = ("TRADE_DT", "S_INFO_WINDCODE") if source["frequency"] == "1d" else ("TradingDate", "Symbol")
        self.session.upload({"downloadStart": np.datetime64(start, "D"), "downloadEnd": np.datetime64(end, "D")})
        result = self.session.run(f"select distinct {day_col} as day from downloadSource where "
            f"{day_col} >= downloadStart, {day_col} <= downloadEnd, {code_col} = downloadCode order by day")
        return [x.date() for x in pd.to_datetime(result["day"])]

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


def resolve_for_day(client, resolver, symbol, day):
    from .contracts import HistoricalResolver
    if isinstance(resolver, HistoricalResolver):
        return resolver.resolve(symbol, day, client)
    info = identify(symbol)
    if info["asset"] != "future" or any(ch.isdigit() for ch in info["code"]) and len(''.join(filter(str.isdigit, info["code"]))) >= 3:
        return {"source_symbol": symbol, "mapping_date": None, "mapping_rule": "具体代码"}
    if MAIN_SYMBOL.fullmatch(symbol):
        historical = HistoricalResolver(resolver.mapping_file, resolver.calendar_file)
        return historical.resolve(symbol, day, client)
    return client.continuous(symbol, day)


def write_json(path, value):
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    partial.replace(path)


def register(paths, source, purpose, output):
    default_root = DEFAULT_OUTPUT.parent.resolve()
    root = default_root if output.resolve().is_relative_to(default_root) else output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    index = root / "下载索引.md"
    # Byte-range locking serializes concurrent GUI/benchmark runs on Windows.
    with (root / ".download-index.lock").open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            with index.open("a", encoding="utf-8") as handle:
                for path in paths:
                    if not path.is_file() or not path.stat().st_size:
                        raise OSError(f"文件未成功保存：{path}")
                    clean = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
                    fields = [datetime.now(CHINA).isoformat(timespec="seconds"), path.name,
                              path.resolve(), source, purpose, f"{path.stat().st_size} bytes"]
                    handle.write("- " + " | ".join(map(clean, fields)) + "\n")
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def run_download(request, *, emit=lambda event: None, cancelled=lambda: False, client_factory=Client):
    from .jobs import run_download as execute
    return execute(request, emit=emit, cancelled=cancelled, client_factory=client_factory)
