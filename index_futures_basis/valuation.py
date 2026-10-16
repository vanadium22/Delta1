"""Explicit calculation choices; unadjusted never implies missing dividends are zero."""

VALUATIONS = {"adjusted": "分红调整后", "raw": "不调整分红"}


def valuation_mode(value):
    if value not in VALUATIONS:
        raise ValueError("请选择分红调整后或不调整分红")
    return value
