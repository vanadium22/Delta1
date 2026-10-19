"""The dashboard's only boundary to the independent market-data package."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, time
import json
from pathlib import Path
import threading

import pandas as pd

from index_strategy.instant_dld.client import MarketDataClient
from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.contract_aliases import DualIdentityStore, ExpiryAliasResolver
from index_strategy.instant_dld.quotes import CHINA
from index_strategy.instant_dld.reader import RealtimeReader
from index_strategy.instant_dld.service import write_json

LABELS = {"000300.SH": "沪深300", "000905.SH": "中证500", "000016.SH": "上证50", "000852.SH": "中证1000",
          "510300.SH": "沪深300 ETF", "510500.SH": "中证500 ETF", "510050.SH": "上证50 ETF",
          "512100.SH": "中证1000 ETF", "000001.SZ": "平安银行", "AU.SHF": "黄金 · 主力映射"}


def records(frame):
    return json.loads(frame.reset_index().to_json(orient="records", date_format="iso"))


def category(symbol):
    if symbol.endswith(".CFE"):
        return "股指"
    if symbol.endswith((".SHF", ".DCE", ".CZC", ".INE", ".GFE")):
        return "商品"
    if symbol in {"000300.SH", "000905.SH", "000016.SH", "000852.SH"}:
        return "指数"
    if symbol.startswith(("15", "16", "50", "51", "52", "56", "58")):
        return "ETF"
    return "股票"


def session_hint(symbol, now):
    """Conservative clock hint only; never certifies an exchange trading day."""
    hour = now.time().replace(tzinfo=None)
    if symbol.startswith("AU") and symbol.endswith(".SHF"):
        return (time(9) <= hour <= time(10, 15) or time(10, 30) <= hour <= time(11, 30)
                or time(13, 30) <= hour <= time(15) or hour >= time(21) or hour <= time(2, 30))
    if category(symbol) == "商品":
        return False
    return now.weekday() < 5 and (time(9, 30) <= hour <= time(11, 30) or time(13) <= hour <= time(15))


class MarketGateway:
    def __init__(self, local_root: Path):
        self.local_root = local_root
        self.lock = threading.RLock()
        self.worker = None
        self.stop_event = threading.Event()
        self.state = {"status": "idle", "quotes_saved": 0, "polls": 0, "error": None}
        self.logs = deque(maxlen=80)

    def collection_status(self):
        with self.lock:
            return {**deepcopy(self.state), "logs": list(self.logs)[-12:]}

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def update_symbols(self, symbols):
        # The existing collector reloads this file at the start of each poll.
        with self.lock:
            write_json(self.local_root / "collection_symbols.json", symbols)

    @staticmethod
    def resolver(config):
        return ExpiryAliasResolver(Path(config["mapping_file"]), Path(config["calendar_file"]))

    def universe(self, config):
        return self.resolver(config).candidates()

    def snapshot(self, config, symbols):
        reader = RealtimeReader(config["market_root"])
        if not reader.db_path.is_file():
            return {}, {}, "行情库尚未创建；选择已有目录或开始采集。"
        latest = records(reader.latest(symbols))
        now = datetime.now(CHINA)
        quotes = {}
        for row in latest:
            observed = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            age = max(0, (now - observed).total_seconds())
            symbol = row["symbol"]
            bid, ask = row.get("bid_price_1"), row.get("ask_price_1")
            valid_book = bid is not None and ask is not None and 0 < bid <= ask
            quality = "stale" if age > config["max_age_seconds"] else "unverified"
            if not session_hint(symbol, now) and age < 86400:
                quality = "closed"
            row.update(name=LABELS.get(symbol, symbol), category=category(symbol), age_seconds=round(age, 1),
                       mid=(bid + ask) / 2 if valid_book else None,
                       spread=ask - bid if valid_book else None, quality=quality,
                       source_time_verified=False,
                       depth_levels=sum(row.get(f"bid_price_{i}") is not None and row.get(f"ask_price_{i}") is not None
                                        for i in range(1, 6)))
            quotes[symbol] = row
        history = {symbol: [] for symbol in quotes}
        if latest:
            cutoff = max(row["sequence"] for row in latest)
            recent = records(reader.read_since(max(0, cutoff - 20000), symbols=list(quotes), limit=20000))
            for row in recent:
                current = quotes[row["symbol"]]
                same_day = row.get("trading_date") == current.get("trading_date") if current.get("trading_date") else (
                    datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).astimezone(CHINA).date() ==
                    datetime.fromisoformat(current["timestamp"].replace("Z", "+00:00")).astimezone(CHINA).date())
                if (row["sequence"] <= current["sequence"] and row["source_symbol"] == current["source_symbol"] and same_day):
                    history[row["symbol"]].append(row)
            for symbol, rows in history.items():
                history[symbol] = rows[-300:]
                quotes[symbol]["trail"] = [{"time": r["timestamp"], "value": r["close"]} for r in rows[-60:]]
                first = rows[0]["close"] if rows else None
                quotes[symbol]["observed_change"] = (quotes[symbol]["close"] / first - 1) * 100 if first else None
        return quotes, history, None

    def start(self, config, *, once=False):
        with self.lock:
            if self.running():
                raise ValueError("本看板的采集任务正在运行")
            symbols_path = self.local_root / "collection_symbols.json"
            write_json(symbols_path, config["symbols"])
            self.stop_event = threading.Event()
            self.state = {"status": "starting", "quotes_saved": 0, "polls": 0, "error": None}
            self.logs.clear()
            self.worker = threading.Thread(target=self._collect, args=(deepcopy(config), symbols_path, once), daemon=True)
            self.worker.start()
        return self.collection_status()

    def _collect(self, config, symbols_path, once):
        owner = self
        class ObservedStore(DualIdentityStore):
            def batch(self, record):
                super().batch(record)
                with owner.lock:
                    owner.state["quotes_saved"] += len(self.last_rows)
                    owner.state["polls"] = record["poll"]
                    owner.logs.append({"time": record["received_at"], "message": self.last_report["description"],
                                       "status": self.last_report["status"]})
        client = MarketDataClient(connect_timeout=6, read_timeout=15)
        try:
            with ObservedStore(Path(config["market_root"])) as store:
                with self.lock:
                    self.state["status"] = "stopping" if self.stop_event.is_set() else "running"
                collect(client, store, [symbols_path], interval=config["interval"], stop=self.stop_event,
                        max_polls=1 if once else 0, resolver=self.resolver(config))
            with self.lock:
                self.state["status"] = "stopped"
        except Exception as exc:
            with self.lock:
                self.state.update(status="failed", error=str(exc))
        finally:
            client.close()

    def stop(self):
        with self.lock:
            if self.running():
                self.state["status"] = "stopping"
                self.stop_event.set()
        return self.collection_status()

    def close(self):
        self.stop()
        if self.worker is not None:
            self.worker.join(30)
