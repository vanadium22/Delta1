"""Calendar-day maturity inputs. No guessed expiry dates or price forward filling."""
import numpy as np
import pandas as pd

from .models import BacktestError, normalize_frame


def remaining_days(index, symbols, contracts, supplied=None, *, timezone="Asia/Shanghai"):
    days = index.normalize()
    result = pd.DataFrame(np.nan, index=index, columns=symbols)
    for symbol in symbols:
        expiry = contracts.get(symbol, {}).get("expiry_date")
        if expiry and not symbol.endswith("_spot"):
            end = pd.Timestamp(expiry).normalize()
            if end.tzinfo is not None:
                end = end.tz_convert(timezone).tz_localize(None)
            result[symbol] = (end - days.tz_localize(None)).days.astype(float)
    if supplied is not None:
        source = normalize_frame(supplied, label="days_to_expiry", timezone=timezone, date_at="00:00")
        source.index = source.index.normalize()
        if source.index.duplicated().any():
            raise BacktestError("days_to_expiry must have one row per calendar day")
        values = source.reindex(index=days, columns=symbols)
        values.index = index
        if ((values % 1 != 0) & values.notna()).any().any():
            raise BacktestError("days_to_expiry must contain integer calendar days")
        conflict = result.notna() & values.notna() & result.ne(values)
        if conflict.any().any():
            raise BacktestError("days_to_expiry conflicts with the contract expiry_date")
        result = values.combine_first(result)
    return result


def require_days(values, needed, symbols, now):
    missing = needed & ~np.isfinite(values)
    if missing.any():
        names = [symbols[j] for j in np.flatnonzero(missing)]
        raise BacktestError(f"Missing expiry_date/days_to_expiry for {names} at {now}; "
                            "supply reference_path or days_to_expiry_path, or explicitly repair references from DDB")
