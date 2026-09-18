"""Normalize the observed SWHY response without inventing an exchange date."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

CHINA = timezone(timedelta(hours=8))
DEPTH_COLUMNS = [f"{side}_{field}_{level}" for side in ("bid", "ask")
                 for level in range(1, 6) for field in ("price", "volume")]
IDENTITY_COLUMNS = ["source_symbol", "mapping_date", "trading_date"]
QUOTE_COLUMNS = ["sequence", "timestamp", "symbol", *IDENTITY_COLUMNS, "quote_time", "close", "volume", "volume_total",
                 *DEPTH_COLUMNS, "quality_flags"]
MISSING_PRICE_SENTINEL = (2**63 - 1) / 1_000_000
# Bit flags: 1 missing cumulative volume, 2 incomplete depth, 4 missing source
# time, 8 cumulative reset/time reversal, 16 no previous observation,
# 32 the observed int64-max / 1e6 missing-price sentinel, 64 actual contract changed.


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def price_number(value):
    parsed = number(value)
    if parsed is None or parsed == 0 or parsed == MISSING_PRICE_SENTINEL:
        return None
    return parsed


def source_time(value) -> str | None:
    """The observed API uses HHMMSS, with leading zeroes dropped for integers."""
    if type(value) is not int and not isinstance(value, str):
        return None
    text = str(value).strip()
    if not text.isdigit() or len(text) > 6:
        return None
    text = text.zfill(6)
    try:
        return datetime.strptime(text, "%H%M%S").strftime("%H:%M:%S")
    except ValueError:
        return None


def normalize_quote(symbol: str, quote: dict, received_at: str, previous: dict | None = None, *,
                    source_symbol: str | None = None, mapping_date: str | None = None,
                    trading_date: str | None = None) -> dict:
    source_symbol = source_symbol or symbol
    price = price_number(quote.get("latestPrice"))
    if price is None or price <= 0:
        raise ValueError("缺少有效最新成交价 latestPrice")
    if quote.get("securityId") not in (None, source_symbol):
        raise ValueError("响应 securityId 与请求标的不一致")
    received = datetime.fromisoformat(received_at)
    if received.tzinfo is None:
        raise ValueError("采集时间必须包含时区")
    capture_date = received.astimezone(CHINA).date().isoformat()
    total = number(quote.get("tradedQuantities"))
    market_time = source_time(quote.get("quoteTimestamp"))
    flags = (1 if total is None else 0) | (4 if market_time is None else 0)
    row = {"timestamp": int(received.timestamp()), "capture_date": capture_date, "symbol": symbol,
           "source_symbol": source_symbol, "mapping_date": mapping_date, "trading_date": trading_date,
           "quote_time": market_time, "close": price, "volume": None, "volume_total": total}
    for side, source in (("bid", "b"), ("ask", "s")):
        for level in range(1, 6):
            for field, suffix in (("price", "Price"), ("volume", "Stocks")):
                raw = quote.get(f"{source}{level}{suffix}")
                value = price_number(raw) if field == "price" else number(raw)
                if field == "price" and raw == MISSING_PRICE_SENTINEL:
                    flags |= 32
                row[f"{side}_{field}_{level}"] = value
                if value is None:
                    flags |= 2
    previous_contract = (previous.get("source_symbol") or previous.get("symbol") or symbol) if previous else None
    contract_changed = bool(previous and previous_contract != source_symbol)
    same_session = bool(previous and ((previous.get("trading_date") == trading_date) if trading_date
                                     else previous["capture_date"] == capture_date))
    if contract_changed:
        flags |= 64
    if not same_session:
        flags |= 16
    elif not contract_changed and total is not None and previous.get("volume_total") is not None:
        backwards = bool(market_time and previous.get("quote_time") and market_time < previous["quote_time"]
                         and (not trading_date or previous["capture_date"] == capture_date))
        if total < previous["volume_total"] or backwards:
            flags |= 8
        else:
            row["volume"] = total - previous["volume_total"]
    row["quality_flags"] = flags
    return row
