"""Deterministic synthetic daily data, visibly separate from actual research."""
import math
import pandas as pd


def third_friday(month):
    start = pd.Timestamp(month).replace(day=1)
    return start + pd.Timedelta(days=(4 - start.weekday()) % 7 + 14)


def snapshot():
    dates = pd.bdate_range("2025-07-01", "2026-10-08")
    rows = []
    for i, day in enumerate(dates):
        front = day.replace(day=1)
        if day > third_friday(front):
            front += pd.DateOffset(months=1)
        next_month = front + pd.DateOffset(months=1)
        quarters = []
        probe = next_month + pd.DateOffset(months=1)
        while len(quarters) < 2:
            if probe.month in (3, 6, 9, 12):
                quarters.append(probe)
            probe += pd.DateOffset(months=1)
        for ri, (root, base) in enumerate([("IF", 4000), ("IC", 6200), ("IM", 6500)]):
            spot = base + i * .8 + 80 * math.sin(i / 27 + ri)
            for slot, month in enumerate([front, next_month, *quarters], 1):
                expiry = third_friday(month)
                days = (expiry - day).days
                rate = -.065 - .012 * ri + .015 * math.sin(i / 19 + slot)
                basis = spot * rate * days / 365 + 3 * math.sin(i / 5)
                rows.append({"trade_date": str(day.date()), "root": root, "slot": slot,
                    "instrument_id": root + month.strftime("%y%m") + ".CFE", "expiry_date": str(expiry.date()),
                    "futures_close": round(spot + basis, 3), "spot_close": round(spot, 3),
                    "open_interest": 40000 + ri * 5000 + (month.year * 12 + month.month) % 13 * 700 + i * 20})
    return {"records": rows, "calendar": [str(d.date()) for d in dates], "actual_end": str(dates[-1].date()),
            "source": "合成演示（工作日历并非真实交易所日历）"}


def dividends(end):
    return pd.DataFrame([{"trade_date": pd.Timestamp(end), "code": f"{root}0{slot}.CFE", "dividend_points": slot * 3.5}
                         for root in ("IF", "IC", "IM") for slot in range(4)])
