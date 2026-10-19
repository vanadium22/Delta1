"""Opt-in expiry aliases and concrete-contract fan-out for any collection client.

IC00/01/02/03 (also IF/IH/IM) mean the first through fourth listed expiry.
These are explicitly our local aliases, not an assertion about vendor codes.
The original collector and desktop entry points remain independently usable.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date
import re

from .contracts import ContractMappingError, MainContractResolver
from .realtime_store import RealtimeStore

INDEX_ALIAS = re.compile(r"(IF|IH|IC|IM)(0[0-3])\.CFE\Z")


def index_months(day: date, calendar: list[date]) -> list[str]:
    """Four candidate months, accounting for the exchange expiry holiday rule."""
    first = date(day.year, day.month, 1)
    friday = date(day.year, day.month, 1 + (4 - first.weekday()) % 7 + 14)
    position = bisect_left(calendar, friday)
    if position == len(calendar):
        raise ContractMappingError("交易日历未覆盖本月到期日，请更新日历")
    start = day.year * 12 + day.month - 1 + (day > calendar[position])
    months = [start, start + 1]
    cursor = start + 2
    while len(months) < 4:
        if cursor % 12 + 1 in (3, 6, 9, 12):
            months.append(cursor)
        cursor += 1
    return [f"{value // 12 % 100:02d}{value % 12 + 1:02d}" for value in months]


class ExpiryAliasResolver(MainContractResolver):
    def candidates(self, at=None) -> dict:
        trade_day, _ = self.trading_dates("IC.CFE", at or self.now())
        months = index_months(date.fromisoformat(trade_day), self._calendar)
        return {"trading_date": trade_day, "basis": "交易日历与到期规则候选；接口报价单独核验",
                "contracts": {root: [f"{root}{month}.CFE" for month in months]
                              for root in ("IF", "IH", "IC", "IM")}}

    def resolve(self, symbol, at=None):
        match = INDEX_ALIAS.fullmatch(symbol)
        if match:
            candidates = self.candidates(at)
            return {"source_symbol": candidates["contracts"][match[1]][int(match[2])],
                    "mapping_date": None, "trading_date": candidates["trading_date"]}
        if re.fullmatch(r"[A-Z]+\d{2}\.(SHF|DCE|CZC|INE|GFE)", symbol):
            raise ContractMappingError("商品两位月份别名尚未配置含义，请输入具体合约或 AU.SHF 等主力标识")
        return super().resolve(symbol, at)


class DualIdentityStore(RealtimeStore):
    """Keep aliases and actual contracts in the same quote transaction.

    No extra network request. Original HTTP body and source_response remain intact.
    Alias rows are alternative identities; consumers must not add their volumes
    to their corresponding concrete-contract rows.
    """
    def batch(self, record):
        data = (record.get("response") or {}).get("data", {}) if isinstance(record.get("response"), dict) else {}
        if record.get("status") in {"success", "partial"} and isinstance(data, dict):
            original = list(record["symbols"])
            expanded, mappings = dict(data), dict(record.get("symbol_mapping", {}))
            for alias in original:
                identity = mappings.get(alias, {})
                actual = identity.get("source_symbol", alias)
                if actual != alias and isinstance(data.get(alias), dict) and data[alias]:
                    expanded.setdefault(actual, data[alias])
                    mappings.setdefault(actual, {"source_symbol": actual, "mapping_date": None,
                                                 "trading_date": identity.get("trading_date")})
                    if actual not in record["symbols"]:
                        record["symbols"] = [*record["symbols"], actual]
            record["logical_symbols_before_fanout"] = original
            record["response"] = {**record["response"], "data": expanded}
            record["symbol_mapping"] = mappings
            record["received_symbols"] = [s for s in record["symbols"] if isinstance(expanded.get(s), dict) and expanded[s]]
            record["missing_symbols"] = [s for s in record["symbols"] if s not in record["received_symbols"]]
        super().batch(record)
