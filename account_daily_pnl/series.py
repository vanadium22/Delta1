"""Versioned daily account series consumed by downstream return statistics."""

from collections import defaultdict
from datetime import date
import json

from shared_data.io import atomic_json

from .baseline import ACCOUNTS, BASE_DAY
from .ledger import rounded


SERIES_FILENAME = "account_daily_pnl.json"
SCHEMA_VERSION = 1
TOTAL = "total"
AMOUNT_KEYS = (
    ("pnl", "net_pnl"), ("modeled_pnl", "trade_net_pnl"), ("equity_pnl", "equity_net_pnl"),
    ("fees", "fee"), ("net_flow", "net_external_flow"), ("prior_equity", "opening_equity"),
    ("equity", "closing_equity"), ("history_pnl", "since_baseline_net_pnl"), ("ytd_pnl", "ytd_net_pnl"),
)
RATE_KEYS = (
    ("day_return", "daily_return"), ("history_return", "since_baseline_return"), ("ytd_return", "ytd_return"),
)


def series_payload(timeline):
    rows = []
    for row in timeline:
        values = {"trading_date": row["day"], "account_id": row["account"] if row["account"] in ACCOUNTS else TOTAL,
                  "pnl_source": row["pnl_source"], "equity_source": row["equity_source"], "status": row["status"]}
        for current, exported in AMOUNT_KEYS:
            values[exported] = None if row[current] is None else format(rounded(row[current]), "f")
        for current, exported in RATE_KEYS:
            values[exported] = None if row[current] is None else format(row[current], "f")
        rows.append(values)
    payload = {"schema_version": SCHEMA_VERSION, "baseline_date": BASE_DAY,
               "through": timeline[-1]["day"], "currency": "CNY", "rows": rows}
    validate_series(payload)
    return payload


def validate_series(payload, required_through=None):
    if (payload.get("schema_version") != SCHEMA_VERSION or payload.get("currency") != "CNY"
            or payload.get("baseline_date") != BASE_DAY):
        raise ValueError("账户收益数据版本、基准日或币种不匹配。")
    by_day = defaultdict(set)
    account_ids = set(ACCOUNTS) | {TOTAL}
    for row in payload["rows"]:
        day, account = row["trading_date"], row["account_id"]
        if date.fromisoformat(day).isoformat() != day or day <= BASE_DAY or account in by_day[day]:
            raise ValueError("账户收益数据包含无效或重复的交易日和账户组合。")
        by_day[day].add(account)
    if (not by_day or max(by_day) != payload["through"]
            or any(accounts != account_ids for accounts in by_day.values())):
        raise ValueError("账户收益数据缺少交易日或账户。")
    if required_through is not None and payload["through"] != required_through:
        raise ValueError(f"账户收益数据截止 {payload['through']}，当前统计需要 {required_through}。")


def write_series(path, timeline):
    atomic_json(path, series_payload(timeline))


def load_series(path, *, required_through=None):
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_series(payload, required_through)
    return payload
