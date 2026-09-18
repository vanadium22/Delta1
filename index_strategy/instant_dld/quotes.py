"""Normalize the observed SWHY response without inventing an exchange date."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

CHINA = timezone(timedelta(hours=8))
DEPTH_COLUMNS = [f"{side}_{field}_{level}" for side in ("bid", "ask")
                 for level in range(1, 6) for field in ("price", "volume")]
IDENTITY_COLUMNS = ["source_symbol", "mapping_date", "trading_date"]
VOLUME_COLUMNS = ["volume_start", "volume_interval_seconds"]
QUOTE_COLUMNS = ["sequence", "timestamp", "symbol", *IDENTITY_COLUMNS, "quote_time", "close", "volume", "volume_total",
                 *VOLUME_COLUMNS, *DEPTH_COLUMNS, "quality_flags"]
MISSING_PRICE_SENTINEL = (2**63 - 1) / 1_000_000
# Bit flags: 1 missing cumulative volume, 2 incomplete depth, 4 missing source
# time, 8 cumulative reset/time reversal, 16 no previous observation,
# 32 the observed int64-max / 1e6 missing-price sentinel, 64 actual contract changed,
# 128 observation gap beyond the configured polling tolerance.


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


def _observation_interval(row: dict, previous: dict) -> tuple[int | None, float | None]:
    """Use precise receipt times together, otherwise the stored second labels."""
    try:
        current_time = datetime.fromisoformat(row["received_at"])
        previous_time = datetime.fromisoformat(previous["received_at"])
        if current_time.tzinfo is not None and previous_time.tzinfo is not None:
            return int(previous_time.timestamp()), (current_time - previous_time).total_seconds()
    except (KeyError, TypeError, ValueError):
        pass
    current_timestamp = number(row.get("timestamp"))
    previous_timestamp = number(previous.get("timestamp"))
    if current_timestamp is None or previous_timestamp is None:
        return None, None
    return int(previous_timestamp), current_timestamp - previous_timestamp


def update_volume(row: dict, previous: dict | None, *, reset_volume: bool = False,
                  expected_interval: float | None = None) -> None:
    """Recompute an observation delta, never an asserted one-second trade bar.

    Cumulative quantities retain their source units. A configured polling gap
    beyond max(2 * interval, interval + 1 second) invalidates the delta rather
    than assigning all unobserved trading to the latest sample. Receipt times
    bound the observation interval; they are not exchange event timestamps.
    """
    flags = row.get("quality_flags", 0) & ~(1 | 8 | 16 | 64 | 128)
    row.update(volume=None, volume_start=None, volume_interval_seconds=None)
    total = number(row.get("volume_total"))
    if total is None:
        flags |= 1
    symbol = row["symbol"]
    source_symbol = row.get("source_symbol") or symbol
    previous_contract = (previous.get("source_symbol") or previous.get("symbol") or symbol) if previous else None
    contract_changed = bool(previous and previous_contract != source_symbol)
    trading_date, capture_date = row.get("trading_date"), row.get("capture_date")
    same_session = bool(previous and ((previous.get("trading_date") == trading_date) if trading_date
                                     else previous.get("capture_date") == capture_date))
    if contract_changed:
        flags |= 64
    if reset_volume or not same_session:
        flags |= 16
    elif not contract_changed:
        previous_total = number(previous.get("volume_total"))
        market_time = row.get("quote_time")
        backwards = bool(market_time and previous.get("quote_time") and market_time < previous["quote_time"]
                         and (not trading_date or previous.get("capture_date") == capture_date))
        start, seconds = _observation_interval(row, previous)
        interval = number(expected_interval)
        gap = bool(interval and seconds is not None and seconds > max(2 * interval, interval + 1))
        if gap:
            flags |= 128
        if (total is None or previous_total is None or total < previous_total or backwards
                or (seconds is not None and seconds < 0)):
            flags |= 8
        elif not gap:
            row.update(volume=total - previous_total, volume_start=start, volume_interval_seconds=seconds)
    row["quality_flags"] = flags


def normalize_quote(symbol: str, quote: dict, received_at: str, previous: dict | None = None, *,
                    source_symbol: str | None = None, mapping_date: str | None = None,
                    trading_date: str | None = None, reset_volume: bool = False,
                    expected_interval: float | None = None) -> dict:
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
    row = {"timestamp": int(received.timestamp()), "received_at": received_at,
           "capture_date": capture_date, "symbol": symbol,
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
    row["quality_flags"] = flags
    update_volume(row, previous, reset_volume=reset_volume, expected_interval=expected_interval)
    return row
