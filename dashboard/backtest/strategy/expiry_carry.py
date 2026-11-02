"""Select extreme continuous-slot percentiles, then keep actual lots to maturity."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..models import BacktestError, check_cancelled, time_bound


@dataclass
class CarrySignals:
    targets: pd.DataFrame
    decisions: pd.DataFrame
    metadata: dict


def hold_to_expiry_targets(percentiles, mapping, contracts, *, start="2024-01-01", end=None,
                           threshold=.9, selection="product_best", weight=.99, direction=-1,
                           roots=("IF", "IH", "IC", "IM"), cancel_event=None):
    """Only emits complete target changes; use rebalance_on_change_only=True."""
    if not 0 < threshold < 1 or not 0 < weight <= 1 or direction not in (-1, 1):
        raise BacktestError("Invalid carry threshold, weight or direction")
    if selection not in {"product_best", "contract_independent"}:
        raise BacktestError("selection must be product_best or contract_independent")
    if not percentiles.index.equals(mapping.index) or percentiles.index.normalize().duplicated().any():
        raise BacktestError("Expiry carry requires aligned daily percentile and mapping rows")
    if ((percentiles < 0) | (percentiles > 1)).any().any():
        raise BacktestError("Expiry carry expects raw percentiles in [0, 1]")
    left, right = time_bound(start), time_bound(end, end=True)
    selected = np.ones(len(percentiles), dtype=bool)
    if left is not None:
        selected &= percentiles.index >= left
    if right is not None:
        selected &= percentiles.index <= right
    index = percentiles.index[selected]
    if not len(index):
        raise BacktestError("No carry observations in the requested period")
    columns = sorted(s for s, ref in contracts.items() if s[:2] in roots and s.endswith(".CFE")
                     and ref.get("listing_date", "9999") <= str(index[-1].date())
                     and ref.get("expiry_date", "0000") >= str(index[0].date()))
    if not columns:
        raise BacktestError("No dated actual contracts overlap the carry interval")
    desired = dict.fromkeys(columns, 0.0)
    held, records, emitted = {}, [], {}
    for i, stamp in enumerate(index):
        if i % 128 == 0:
            check_cancelled(cancel_event)
        day = str(stamp.date())
        changed = False
        for key, state in list(held.items()):
            if day >= contracts[state["symbol"]]["expiry_date"]:
                desired[state["symbol"]] = 0.0
                records.append(dict(timestamp=stamp, account=key, symbol=state["symbol"], action="expiry_release",
                                    percentile=np.nan, score=np.nan, slot=None, signal_time=state["signal_time"]))
                del held[key]
                changed = True
        row = percentiles.loc[stamp]
        choices = {}
        for alias, symbol in mapping.loc[stamp].items():
            if not isinstance(symbol, str) or symbol not in desired or alias[:2] not in roots:
                continue
            value = row.get(symbol, np.nan)
            score = 2 * value - 1
            if not np.isfinite(score) or contracts[symbol]["expiry_date"] <= day:
                continue
            key = symbol if selection == "contract_independent" else symbol[:2]
            choices.setdefault(key, []).append((abs(score), int(alias[2:4]), symbol, value, score, alias))
        keys = sorted(set(choices) | set(held) | (set(roots) if selection == "product_best" else set()))
        for key in keys:
            if key in held:
                state = held[key]
                value = row.get(state["symbol"], np.nan)
                records.append(dict(timestamp=stamp, account=key, symbol=state["symbol"], action="holding",
                                    percentile=value, score=2 * value - 1, slot=None, signal_time=state["signal_time"]))
                continue
            candidates = sorted(choices.get(key, []), key=lambda v: (-v[0], v[1], v[2]))
            best = candidates[0] if candidates else None
            if best is None or best[0] <= threshold:
                records.append(dict(timestamp=stamp, account=key, symbol=best[2] if best else None, action="flat_no_signal",
                                    percentile=best[3] if best else np.nan, score=best[4] if best else np.nan,
                                    slot=best[5] if best else None, signal_time=pd.NaT))
                continue
            _, _, symbol, value, score, alias = best
            desired[symbol] = direction * float(np.sign(score)) * weight
            held[key] = dict(symbol=symbol, signal_time=stamp)
            records.append(dict(timestamp=stamp, account=key, symbol=symbol, action="signal_open",
                                percentile=value, score=score, slot=alias, signal_time=stamp))
            changed = True
        if changed or i == 0:
            emitted[stamp] = desired.copy()
    targets = pd.DataFrame.from_dict(emitted, orient="index").reindex(columns=columns).fillna(0.0)
    targets.index = pd.DatetimeIndex(targets.index, name="timestamp")
    return CarrySignals(targets, pd.DataFrame(records), dict(window="prior continuous-slot daily percentiles",
        threshold=threshold, score="2*p-1", direction=direction, selection=selection,
        tie_break="greatest absolute score, then lowest slot, then actual symbol", weight=weight,
        exit="both legs at maturity close; ignore intermediate score changes", next_bar_execution=True,
        required_backtest_options=dict(d0=0, rebalance_on_change_only=True)))
