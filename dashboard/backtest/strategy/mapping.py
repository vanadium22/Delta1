"""Dated 00..03 calculation panels with concrete-only factors and trade targets."""
import re

import numpy as np
import pandas as pd

from dashboard.native.continuous import slot_map
from ..models import BacktestError, normalize_frame


def is_slot(symbol):
    return bool(re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE", str(symbol).upper()))


def slot_mapping(index, contracts, roots, slots=(0, 1, 2, 3)):
    columns = [f"{root}0{slot}.CFE" for root in roots for slot in slots]
    result = pd.DataFrame(None, index=index, columns=columns, dtype=object)
    groups = pd.Series(np.arange(len(index)), index=index).groupby(index.normalize())
    errors = []
    for day, positions in groups:
        for root in roots:
            mapping, error = slot_map(contracts, root, day)
            if error:
                errors.append(dict(day=str(day.date()), root=root, reason=error))
                continue
            cols = [f"{root}0{s}.CFE" for s in slots]
            result.iloc[positions.to_numpy(), result.columns.get_indexer(cols)] = [mapping[c] for c in cols]
    return result, errors


def to_actual(frame, mapping, *, fill=np.nan, columns=None):
    if not frame.index.equals(mapping.index) or not frame.columns.isin(mapping.columns).all():
        raise BacktestError("Continuous values must align exactly with their dated slot mapping")
    mapping = mapping.loc[:, frame.columns]
    symbols = sorted({s for s in mapping.to_numpy().ravel() if isinstance(s, str)}) if columns is None else list(columns)
    result = pd.DataFrame(fill, index=frame.index, columns=symbols, dtype=float)
    for col in frame.columns:
        for symbol in mapping[col].dropna().unique():
            rows = mapping[col].eq(symbol)
            result.loc[rows, symbol] = frame.loc[rows, col]
    return result


def expand_slot_targets(instructions, contracts, **normalization):
    source = normalize_frame(instructions, label="continuous instructions", allow_continuous=True, **normalization)
    aliases = [s for s in source if is_slot(s)]
    if not aliases:
        return source, None
    roots = sorted({s[:2] for s in aliases})
    if any(s.endswith(".CFE") and not is_slot(s) and s[:2] in roots for s in source):
        raise BacktestError("Do not mix concrete and continuous futures targets for the same product")
    mapping, _ = slot_mapping(source.index, contracts, roots)
    for alias in aliases:
        if (mapping[alias].isna() & source[alias].ne(0)).any():
            raise BacktestError(f"Missing four-contract slot mapping for nonzero {alias} target")
    real = to_actual(source[aliases], mapping, fill=0.0)
    for symbol in source.columns.difference(aliases, sort=False):
        real[symbol] = source[symbol]
    if real.empty:
        raise BacktestError("No concrete contracts can be mapped from the continuous targets")
    return real, source
