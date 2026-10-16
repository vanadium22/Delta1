"""Read available local observations without inventing prices, mappings or sessions."""
import numpy as np
import pandas as pd

from .analytics import ROOTS


def local_panel(store, start, end):
    calendar = store.calendar(start, end)
    mapping, expiries, quotes = store.mappings(start, end), store.expiries(), store.quotes(start, end)
    observed = {day for _, day, _ in quotes}
    known_days = {day for day, opened in calendar.items() if opened} | {day for day, _, _ in mapping}
    first = min(observed | known_days, default=str(end))
    # Unknown dates are explicit gaps, not asserted trading days. They prevent a
    # line or a purported full-window distribution from bridging an unknown period.
    unknown = {str(day.date()) for day in pd.date_range(first, end) if str(day.date()) not in calendar}
    days = sorted(known_days | observed | unknown | {str(end)})
    records = []
    for day in days:
        for root, spot in ROOTS.items():
            for slot in range(1, 5):
                code = mapping.get((day, root, slot), "")
                expiry = pd.to_datetime(expiries.get(code), errors="coerce")
                if pd.notna(expiry) and expiry < pd.Timestamp(day):
                    expiry = pd.NaT
                records.append({"trade_date": pd.Timestamp(day), "root": root, "slot": slot,
                    "instrument_id": code, "expiry_date": expiry,
                    "futures_close": quotes.get((code, day, "close"), np.nan),
                    "open_interest": quotes.get((code, day, "oi"), np.nan),
                    "spot_close": quotes.get((spot, day, "close"), np.nan),
                    "calendar_known": bool(calendar.get(day, False))})
    p = pd.DataFrame(records)
    p["expiry_date"] = pd.to_datetime(p.expiry_date)
    p["days_to_expiry"] = (p.expiry_date - p.trade_date).dt.days
    p["continuous_code"] = p.root + (p.slot - 1).astype(str).str.zfill(2) + ".CFE"
    # Conflicting mappings must not create a plausible-looking term structure.
    for _, g in p.groupby(["trade_date", "root"]):
        valid = g[g.instrument_id.ne("")]
        duplicate = valid.instrument_id.duplicated(keep=False)
        if duplicate.any():
            p.loc[valid.index[duplicate], ["futures_close", "open_interest"]] = np.nan
            p.loc[valid.index[duplicate], "instrument_id"] = ""
            p.loc[valid.index[duplicate], "expiry_date"] = pd.NaT
        dates = g.expiry_date.dropna()
        if dates.diff().dropna().le(pd.Timedelta(0)).any():
            p.loc[g.index, "expiry_date"] = pd.NaT
    p["days_to_expiry"] = (p.expiry_date - p.trade_date).dt.days
    missing = {column: int(p[column].isna().sum()) for column in
               ("futures_close", "spot_close", "open_interest", "expiry_date")}
    missing["instrument_id"] = int(p.instrument_id.eq("").sum())
    info = {"source_database": str(store.path), "unknown_calendar_dates": len(unknown),
            "missing_fields": missing, "first_local_date": first,
            "latest_local_date": max(observed, default=None), "row_count": len(p)}
    return p, info
