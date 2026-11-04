"""Daily raw-p calendar factors and a quote-aware CTA that only reads saved factors."""
import numpy as np
import pandas as pd

from ..models import BacktestError, check_cancelled, time_bound


def _annual(near, far, tn, tf):
    if not all(np.isfinite(x) for x in (near, far, tn, tf)) or min(near, far) <= 0 or tn < 0 or tf <= tn:
        return np.nan
    return 36500 * (near - far) / near / (tf - tn)


def _rank(value, history, window):
    if len(history) != window or not np.isfinite(history).all() or not np.isfinite(value):
        return np.nan
    return float((np.count_nonzero(history < value) + .5 * np.count_nonzero(history == value)) / window)


def calendar_pair_factors(panel, contracts, window, *, channels=("01-03", "02-03"), cancel_event=None):
    """Only pairs encountered by the current date are tracked; current date never trains p.

    A held pair can leave its original continuous slots. Its contemporaneous raw
    quotes/T are recovered from all four dated slots, never from a new entry pair.
    Missing observations invalidate the fixed window, rather than shortening it.
    """
    index = panel.close.index
    if index.normalize().duplicated().any():
        raise BacktestError("Calendar pair factors need unique daily observations")
    annual = pd.DataFrame(np.nan, index=index, columns=panel.close.columns)
    percentile = annual.copy()
    records = []
    for root in sorted({s[:2] for s in panel.mapping}):
        aliases = [f"{root}0{s}.CFE" for s in range(4)]
        if not set(aliases) <= set(panel.mapping):
            raise BacktestError("Held calendar pairs require the full 00..03 mapping")
        close = panel.close[aliases].to_numpy()
        days = panel.days_to_expiry[aliases].to_numpy()
        mapping = panel.mapping[aliases].to_numpy()
        for channel in channels:
            slot, far_slot = (int(s) for s in channel.split("-"))
            alias = aliases[slot]
            series = np.array([_annual(c[slot], c[far_slot], d[slot], d[far_slot]) for c, d in zip(close, days)])
            annual[alias] = series
            seen = set()
            for i, stamp in enumerate(index):
                check_cancelled(cancel_event)
                near, far = mapping[i, slot], mapping[i, far_slot]
                if isinstance(near, str) and isinstance(far, str) and near != far:
                    seen.add((near, far))
                history = series[max(0, i-window):i]
                percentile.at[stamp, alias] = _rank(series[i], history, window)
                quotes = {s: (close[i, j], days[i, j]) for j, s in enumerate(mapping[i]) if isinstance(s, str)}
                for a, b in sorted(seen):
                    expiry = min(contracts[s]["expiry_date"] for s in (a, b))
                    if str(stamp.date()) > expiry:
                        continue
                    pa, ta = quotes.get(a, (np.nan, np.nan))
                    pb, tb = quotes.get(b, (np.nan, np.nan))
                    value = _annual(pa, pb, ta, tb)
                    records.append(dict(timestamp=stamp, root=root, channel=channel, near=a, far=b,
                        near_price=pa, far_price=pb, near_t=ta, far_t=tb, annual_spread=value,
                        percentile=_rank(value, history, window), quote_valid=bool(np.isfinite(value)),
                        is_entry_pair=(a, b) == (near, far),
                        history_start=index[max(0, i-window)] if i else pd.NaT,
                        history_end=index[i-1] if i else pd.NaT,
                        history_count=len(history), history_valid=int(np.isfinite(history).sum())))
    diagnostic = pd.DataFrame(records)
    return {"calendar_pair_annual": annual, "calendar_pair_percentile": percentile}, {"calendar_pairs": diagnostic}, dict(
        formula="100*(Fnear-Ffar)/Fnear*365/(Tfar-Tnear); dividends explicitly ignored",
        history="previous complete window_days trading sessions; excludes entire current day; ties half weight",
        exit_benchmark="held actual pair today compared with rolling prior continuous entry-channel history",
        quote_availability="saved factor-stage observation only; no fills or lot sizing in CTA",
        channels=list(channels), window_days=window)


def calendar_reversal_targets(factors, spec, *, start=None, end=None, cancel_event=None):
    """No market access or factor calculation. Pending state waits for a saved valid observation.

    Engine alone decides actual fills, lot counts, fees, risk and expiry close.
    Observed execution eligibility prevents an unfilled close being replaced by
    a new entry. Earliest new entry signal is the close's eligible execution day.
    """
    if spec.input_factor != "calendar_pair_percentile" or "calendar_pairs" not in factors.diagnostics:
        raise BacktestError("Calendar reversal requires saved actual-pair factor diagnostics")
    params = spec.parameters
    channel = params["channel"]
    slot, far_slot = (int(s) for s in channel.split("-"))
    if channel not in factors.metadata.get("method", {}).get("channels", ("01-03", "02-03")):
        raise BacktestError("CTA channel is absent from saved factors; recalculate the declared factor channels first")
    roots = sorted({s[:2] for s in factors.panel.mapping})
    if params["root"] != "all":
        roots = [params["root"]]
    if not set(roots) <= {s[:2] for s in factors.panel.mapping}:
        raise BacktestError("Requested CTA root is absent from factors")
    p = factors.continuous_factors[spec.input_factor]
    if ((p < 0) | (p > 1)).any().any():
        raise BacktestError("Calendar CTA requires untransformed p in [0,1]")
    index = p.index
    left, right = time_bound(start), time_bound(end, end=True)
    selected = np.ones(len(index), dtype=bool)
    if left is not None:
        selected &= index >= left
    if right is not None:
        selected &= index <= right
    index = index[selected]
    if index.empty:
        raise BacktestError("No calendar CTA dates in requested range")
    table = factors.diagnostics["calendar_pairs"]
    table = table.loc[table.channel.eq(channel) & table.root.isin(roots)]
    lookup = {(r.timestamp, r.near, r.far): r for r in table.itertuples(index=False)}
    symbols = sorted(s for s in factors.contracts if s[:2] in roots)
    desired, held, records, emitted = dict.fromkeys(symbols, 0.), {}, [], {}
    serial = dict.fromkeys(roots, 0)
    for i, stamp in enumerate(index):
        check_cancelled(cancel_event)
        changed = False
        day = str(stamp.date())
        for root in roots:
            state = held.get(root)
            if state:
                near, far = state["near"], state["far"]
                row = lookup.get((stamp, near, far))
                value = row.percentile if row else np.nan
                action = None
                if day >= state["expiry"]:
                    action = "expiry_release"
                elif stamp > state["pending_since"] and row and row.quote_valid:
                    if state["phase"] == "pending_close":
                        action = "close_observed"
                    elif state["phase"] == "pending_open":
                        state["phase"] = "held"
                        records.append(dict(timestamp=stamp, root=root, channel=channel, action="open_observed",
                            trade_id=state["trade_id"], near=near, far=far, percentile=value, direction=state["direction"]))
                if action:
                    desired[near] = desired[far] = 0.
                    records.append(dict(timestamp=stamp, root=root, channel=channel, action=action,
                        trade_id=state["trade_id"], near=near, far=far, percentile=value, direction=state["direction"]))
                    del held[root]
                    changed = True
                elif state["phase"] == "held" and params["exit_mode"] == "threshold" and np.isfinite(value):
                    exits = value <= params["q_close"] if state["direction"] < 0 else value >= 1-params["q_close"]
                    if exits:
                        desired[near] = desired[far] = 0.
                        state.update(phase="pending_close", pending_since=stamp)
                        records.append(dict(timestamp=stamp, root=root, channel=channel, action="signal_close",
                            trade_id=state["trade_id"], near=near, far=far, percentile=value, direction=state["direction"]))
                        changed = True
            if root in held:
                continue
            aliases = f"{root}0{slot}.CFE", f"{root}0{far_slot}.CFE"
            near, far = (factors.panel.mapping.at[stamp, s] for s in aliases)
            row = lookup.get((stamp, near, far))
            value = row.percentile if row else np.nan
            expiry = min(factors.contracts[s]["expiry_date"] for s in (near, far)) if row else ""
            if not np.isfinite(value) or expiry <= day:
                continue
            # Decimal thresholds are compared in raw p space, never via 2*p-1.
            lower = round(1-params["q_open"], 14)
            direction = -1 if value > params["q_open"] else 1 if value < lower else 0
            if not direction:
                continue
            serial[root] += 1
            trade_id = f"{root}_{channel}_{serial[root]:04d}"
            held[root] = dict(near=near, far=far, expiry=expiry, direction=direction,
                phase="pending_open", pending_since=stamp, trade_id=trade_id)
            desired[near], desired[far] = direction*params["position_weight"], -direction*params["position_weight"]
            records.append(dict(timestamp=stamp, root=root, channel=channel, action="signal_open", trade_id=trade_id,
                near=near, far=far, percentile=value, direction=direction))
            changed = True
        if changed or i == 0:
            emitted[stamp] = desired.copy()
    targets = pd.DataFrame.from_dict(emitted, orient="index")
    targets.index = pd.DatetimeIndex(targets.index, name="timestamp")
    return targets, pd.DataFrame(records)
