"""Explicit synthetic references used by cash/price accounting tests."""
from dashboard.backtest.models import MarketData
from dashboard.backtest.io import write_json


def fixture_contracts():
    expiries = {"2609": "2026-09-18", "2610": "2026-10-16", "2611": "2026-11-20",
                "2612": "2026-12-18", "2703": "2027-03-19"}
    return {root + code + ".CFE": dict(instrument_id=root + code + ".CFE", listing_date="2025-01-01",
                                     expiry_date=expiry, known_at="2025-01-01T00:00:00+08:00")
            for root in ("IF", "IH", "IC", "IM") for code, expiry in expiries.items()}


def synthetic_market(*args, **kwargs):
    kwargs.setdefault("contracts", fixture_contracts())
    return MarketData(*args, **kwargs)


def write_reference(root):
    path = root / "reference.json"
    write_json(path, dict(schema_version="cn_index_reference_v1", contracts=list(fixture_contracts().values()), aliases=[]))
    return path
