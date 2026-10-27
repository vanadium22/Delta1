"""Filters for browsing today's inventory, using current market values only."""
from dataclasses import dataclass
from decimal import Decimal

from .calculation import decimal_value
from .inventory import normalize_code


@dataclass(frozen=True)
class InventoryFilters:
    industry: str = ""
    minimum_wan: Decimal | None = None
    maximum_wan: Decimal | None = None
    available_only: bool = False

    def __post_init__(self):
        object.__setattr__(self, "industry", self.industry.strip())
        for field, title in (("minimum_wan", "金额下限"), ("maximum_wan", "金额上限")):
            raw = getattr(self, field)
            value = None if raw is None or str(raw).strip() == "" else decimal_value(raw)
            if raw is not None and str(raw).strip() and (value is None or not 0 <= value <= Decimal("1e10")):
                raise ValueError(f"{title}须为 0 至 100 亿之间的数值（万元），留空表示不限")
            object.__setattr__(self, field, value)
        if self.minimum_wan is not None and self.maximum_wan is not None and self.minimum_wan > self.maximum_wan:
            raise ValueError("金额下限不能大于上限（单位：万元）")

    @property
    def has_amount_range(self):
        return self.minimum_wan is not None or self.maximum_wan is not None

    def matches_stock(self, item):
        return (not self.industry or self.industry.casefold() in (item.get("industry") or "").casefold()) and (
            not self.available_only or item.get("inventory_status") == "available")

    def matches_amount(self, item):
        if not self.has_amount_range:
            return True
        value = decimal_value(item.get("inventory_market_value"))
        return value is not None and (
            self.minimum_wan is None or value >= self.minimum_wan * 10000) and (
            self.maximum_wan is None or value <= self.maximum_wan * 10000)


def inventory_candidates(records, tokens):
    """Match keywords by security, retaining every source row for that code."""
    grouped = {}
    for row in records:
        grouped.setdefault(row["code"], []).append(dict(row))
    if not tokens:
        return grouped
    return {code: rows for code, rows in grouped.items() if any(
        normalize_code(token) == code or token.casefold() in code.casefold() or
        any(token.casefold() in row["name"].casefold() for row in rows)
        for token in tokens)}
