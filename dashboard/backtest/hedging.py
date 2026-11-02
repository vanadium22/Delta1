"""Exact quantity-linked future/index legs; hedge weights are never sized separately."""
import math

from .models import BacktestError, DEFAULT_MULTIPLIERS, HedgeRule


def index_hedges(symbols, multipliers=None):
    symbols = tuple(symbols)
    multiples = {**DEFAULT_MULTIPLIERS, **(multipliers or {})}
    for symbol in symbols:
        if symbol.endswith(".CFE"):
            value = multiples.get(symbol, multiples[symbol[:2]])
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0 or int(value) != value:
                raise BacktestError("Index hedge multipliers must be positive exact integers")
    return tuple(HedgeRule(s, s[:2] + "_spot", -int(multiples.get(s, multiples[s[:2]])))
                 for s in symbols if s.endswith(".CFE"))


def pairs_for(symbols, rules):
    locations = {s: i for i, s in enumerate(symbols)}
    result = []
    for rule in rules:
        if rule.primary not in locations:
            continue
        if rule.hedge not in locations:
            raise BacktestError(f"Missing linked hedge column {rule.hedge} for {rule.primary}")
        result.append((locations[rule.primary], locations[rule.hedge], rule.quantity_ratio))
    return result


def expand_needed(needed, pairs):
    result = needed.copy()
    for primary, hedge, _ in pairs:
        if needed[primary]:
            result[hedge] = True
    return result


def link_quantities(target, pairs):
    if not pairs:
        return target
    result = target.copy()
    for hedge in {h for _, h, _ in pairs}:
        result[hedge] = sum(int(result[p]) * ratio for p, h, ratio in pairs if h == hedge)
    return result
