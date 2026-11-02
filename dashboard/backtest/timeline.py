"""Signal precision and actual-quote calendars, independent of account cash."""
import numpy as np
import pandas as pd


def input_precision(instructions):
    days = instructions.index.normalize()
    if days.duplicated().any():
        return "1m"
    at_close = instructions.index == days + pd.Timedelta(hours=15)
    return "1d" if at_close.all() else "1m"


def effective_instructions(instructions, precision):
    if precision == "auto":
        return instructions, input_precision(instructions)
    # Daily precision observes the day's final target at that day's close,
    # then executes only on a later actual quote. No same-day early entry.
    result = instructions.groupby(instructions.index.normalize(), sort=True).tail(1).copy()
    result.index = (result.index.normalize() + pd.Timedelta(hours=15)).rename("timestamp")
    return result, "1d"


def daily_marks(close, supplied=None):
    if supplied is None:
        # A directly supplied matrix defines its own last observable daily close.
        return close.groupby(close.index.normalize(), sort=True).tail(1)
    return supplied


def quote_timeline(close, daily, supplied_fallback=None):
    times = close.index.union(daily.index).sort_values()
    original = close.reindex(index=times)
    day = daily.reindex(index=times, columns=close.columns)
    fallback = original.isna() & day.notna()
    merged = original.where(original.notna(), day)
    if supplied_fallback is not None:
        fallback |= supplied_fallback.reindex(index=times, columns=close.columns, fill_value=False)
    return merged, fallback


def next_joint_quote(valid, start, needed, cache):
    key = tuple(np.flatnonzero(needed))
    if not key:
        return start if start < len(valid) else None
    if key not in cache:
        cache[key] = np.flatnonzero(valid[:, key].all(axis=1))
    locations = cache[key]
    found = locations.searchsorted(start)
    return int(locations[found]) if found < len(locations) else None
