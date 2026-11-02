"""Deterministic next-bar fills with gross margin budgets and explicit ledgers."""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from .data import parameter_frame
from .models import (AccountResult, BacktestConfig, BacktestError, BacktestResult,
                     MarketData, check_cancelled, normalize_frame, time_bound)


ORDER_COLUMNS = ["signal_time", "execution_time", "symbol", "action", "side", "quantity",
                 "signed_quantity", "price", "multiplier", "margin_rate", "notional", "fee",
                 "position_before", "position_after", "reason"]


def _require(values, needed, symbols, now, field, *, upper=None):
    invalid = needed & (~np.isfinite(values) | (values <= 0))
    if upper is not None:
        invalid |= needed & (values > upper)
    if invalid.any():
        names = [symbols[i] for i in np.flatnonzero(invalid)]
        raise BacktestError(f"Missing or invalid {field} for {names} at {now}; no price filling or silent order skipping")


def _targets(weights, equity, prices, multipliers, rates, current, config):
    """Preserve literal margin weights; cap only excess gross exposure and fees."""
    gross = float(np.abs(weights).sum())
    if not np.isfinite(gross):
        raise BacktestError("Gross target weight is not finite")
    weight_scale = min(1.0, config.max_capital_usage / gross) if gross else 1.0
    effective = weights * weight_scale
    nonzero = effective != 0
    target = np.zeros_like(current)
    unit_margin = np.zeros(len(current))
    unit_notional = np.zeros(len(current))
    needed = nonzero | (current != 0)
    unit_notional[needed] = prices[needed] * multipliers[needed]
    unit_margin[needed] = unit_notional[needed] * rates[needed]
    raw_lots = np.zeros(len(current))
    raw_lots[nonzero] = equity * effective[nonzero] / unit_margin[nonzero]
    if not np.isfinite(raw_lots).all() or np.abs(raw_lots).max(initial=0) > 2**53:
        raise BacktestError("Target size exceeds supported exact integer range")
    target[:] = np.trunc(raw_lots).astype(np.int64)

    def fits(candidate):
        fee = float((np.abs(candidate - current) * unit_notional).sum() * config.commission_rate)
        margin = float((np.abs(candidate) * unit_margin).sum())
        return margin <= config.max_capital_usage * (equity - fee) + max(1e-8, equity * 1e-12)

    # Reserve fees against the post-trade equity, rather than spending the cash buffer.
    if not fits(target):
        flat = np.zeros_like(target)
        if not fits(flat):
            raise BacktestError("Insufficient equity to pay the fees needed to flatten this account")
        left, right = 0.0, 1.0
        best = flat
        for _ in range(60):
            middle = (left + right) / 2
            candidate = np.trunc(target * middle).astype(np.int64)
            if fits(candidate):
                left, best = middle, candidate
            else:
                right = middle
        target = best
    return target, effective, weight_scale


def _legs(current, target):
    closes, opens = [], []
    for j, (old, new) in enumerate(zip(current, target)):
        interim = old
        if old > 0 and new < old:
            quantity = min(old, old - new)
            closes.append((j, -quantity, "close_long"))
            interim -= quantity
        elif old < 0 and new > old:
            quantity = min(-old, new - old)
            closes.append((j, quantity, "close_short"))
            interim += quantity
        remaining = new - interim
        if remaining:
            opens.append((j, remaining, "open_long" if remaining > 0 else "open_short"))
    return closes + opens


def _schedule(instructions, times):
    pending, rows = {}, []
    for signal_time, row in instructions.iterrows():
        loc = int(times.searchsorted(signal_time, side="right"))
        record = dict(signal_time=signal_time, execution_time=pd.NaT, status="no_next_bar")
        if loc < len(times):
            record.update(execution_time=times[loc], status="scheduled")
            if loc in pending:
                rows[pending[loc][2]]["status"] = "superseded"
            pending[loc] = (signal_time, row.to_numpy(dtype=float), len(rows))
        rows.append(record)
    return pending, rows


def _run_account(name, instructions, close, multiplier, margin, contracts, config, *, cancel_event=None, progress=None):
    symbols = list(instructions.columns)
    times = close.index
    prices = close.loc[:, symbols].to_numpy(dtype=float)
    multipliers = multiplier.loc[:, symbols].to_numpy(dtype=float)
    rates = margin.loc[:, symbols].to_numpy(dtype=float)
    spot = np.array([s.endswith("_spot") for s in symbols])
    positions = np.zeros(len(symbols), dtype=np.int64)
    last_price = np.full(len(symbols), np.nan)
    last_multiplier = np.full(len(symbols), np.nan)
    cash = float(config.initial_capital)
    pending, schedule_rows = _schedule(instructions, times)
    ledger, history, holding_rows, weights_rows = [], [], [], []
    status, blown_at = "completed", None
    previous_equity = config.initial_capital
    total_fees = 0.0

    def execute(target, now, price, multiple, rate, signal_time, reason):
        nonlocal cash, total_fees
        bar_fee = 0.0
        for j, signed_quantity, action in _legs(positions.copy(), target):
            signed_quantity = int(signed_quantity)
            quantity = abs(signed_quantity)
            notional = float(quantity * price[j] * multiple[j])
            fee = notional * config.commission_rate
            if spot[j]:
                cash -= signed_quantity * price[j] * multiple[j]
            cash -= fee
            before = int(positions[j])
            positions[j] += signed_quantity
            ledger.append(dict(signal_time=signal_time, execution_time=now, symbol=symbols[j], action=action,
                               side="buy" if signed_quantity > 0 else "sell", quantity=quantity,
                               signed_quantity=signed_quantity, price=float(price[j]), multiplier=float(multiple[j]),
                               margin_rate=float(rate[j]), notional=notional, fee=fee,
                               position_before=before, position_after=int(positions[j]), reason=reason))
            bar_fee += fee
            total_fees += fee
        return bar_fee

    def account_values(price, multiple, rate):
        held = positions != 0
        spot_held = held & spot
        equity = cash + float((positions[spot_held] * price[spot_held] * multiple[spot_held]).sum())
        notional = np.abs(positions[held]) * price[held] * multiple[held]
        required = float((notional * rate[held]).sum())
        return equity, required, equity - required, float(notional.sum())

    def failed(equity, required, available):
        base = available if config.margin_call_basis == "available_equity" else equity
        return equity <= 0 or (required > 0 and base < required * config.minimum_margin_ratio)

    for i, now in enumerate(times):
        check_cancelled(cancel_event)
        if progress and (i % 256 == 0 or i == len(times) - 1):
            progress(dict(stage="simulating", account=name, done=i, total=len(times), timestamp=str(now)))
        price, multiple, rate = prices[i], multipliers[i], rates[i]
        held = positions != 0
        _require(price, held, symbols, now, "close")
        _require(multiple, held, symbols, now, "multiplier")
        _require(rate, held, symbols, now, "margin_rate", upper=1)
        for j in np.flatnonzero(held):
            ref = contracts.get(symbols[j], {})
            if ref.get("expiry_date") and str(now.date()) > ref["expiry_date"]:
                raise BacktestError(f"{symbols[j]} still held after expiry at {now}; supply a preceding close instruction; no guessed settlement")
        if (held & np.isfinite(last_multiplier) & (multiple != last_multiplier)).any():
            raise BacktestError(f"Contract multiplier changed while held at {now}; concrete-contract redefinition is not supported")
        future_held = held & ~spot
        cash += float((positions[future_held] * (price[future_held] - last_price[future_held]) * multiple[future_held]).sum())
        equity, required, available, gross_notional = account_values(price, multiple, rate)
        fees, signal_time, scale = 0.0, pd.NaT, np.nan
        effective = np.full(len(symbols), np.nan)
        trigger_margin, trigger_available = np.nan, np.nan
        is_blown = failed(equity, required, available)
        if not is_blown and i in pending:
            signal_time, weights, record_number = pending[i]
            needed = held | (weights != 0)
            _require(price, needed, symbols, now, "execution close")
            _require(multiple, needed, symbols, now, "multiplier")
            _require(rate, needed, symbols, now, "margin_rate (supply margin_rates or margin_rate_path)", upper=1)
            for j in np.flatnonzero(weights != 0):
                ref = contracts.get(symbols[j], {})
                if ((ref.get("listing_date") and str(now.date()) < ref["listing_date"]) or
                        (ref.get("expiry_date") and str(now.date()) > ref["expiry_date"])):
                    raise BacktestError(f"Order outside {symbols[j]} listing/expiry interval at {now}")
            target, effective, scale = _targets(weights, equity, price, multiple, rate, positions, config)
            fees += execute(target, now, price, multiple, rate, signal_time, "target_rebalance")
            schedule_rows[record_number]["status"] = "executed"
            equity, required, available, gross_notional = account_values(price, multiple, rate)
            is_blown = failed(equity, required, available)
        if is_blown:
            trigger_margin, trigger_available = required, available
            fees += execute(np.zeros_like(positions), now, price, multiple, rate, pd.NaT, "margin_call")
            equity, required, available, gross_notional = account_values(price, multiple, rate)
            status, blown_at = "blown_up", now
        elif config.liquidate_at_end and i == len(times) - 1:
            fees += execute(np.zeros_like(positions), now, price, multiple, rate, pd.NaT, "end_of_backtest")
            equity, required, available, gross_notional = account_values(price, multiple, rate)
            if equity <= 0:
                status, blown_at = "blown_up", now
        history.append(dict(timestamp=now, equity=equity, nav=equity / config.initial_capital,
                            cash=cash, required_margin=required, available_equity=available,
                            gross_notional=gross_notional, margin_usage=required / equity if equity > 0 else np.nan,
                            fees=fees, pnl=equity - previous_equity, signal_time=signal_time,
                            weight_scale=scale, status=status if blown_at is not None else "active",
                            trigger_margin=trigger_margin, trigger_available_equity=trigger_available))
        holding_rows.append(positions.copy())
        weights_rows.append(effective)
        previous_equity = equity
        last_price = price.copy()
        last_multiplier = multiple.copy()
        if blown_at is not None:
            break
    for row in schedule_rows:
        if row["status"] == "scheduled":
            row["status"] = "stopped_by_margin_call"
    curve = pd.DataFrame(history).set_index("timestamp")
    nav_with_initial = np.r_[1.0, curve.nav.to_numpy()]
    drawdown = nav_with_initial / np.maximum.accumulate(nav_with_initial) - 1
    summary = dict(status=status, initial_capital=config.initial_capital, final_equity=float(curve.equity.iloc[-1]),
                   total_return=float(curve.nav.iloc[-1] - 1), max_drawdown=float(drawdown.min()),
                   total_fees=total_fees, order_count=len(ledger), bars=len(curve),
                   start=str(curve.index[0]), end=str(curve.index[-1]),
                   blown_at=str(blown_at) if blown_at is not None else None,
                   unexecuted_signals=sum(r["status"] != "executed" for r in schedule_rows))
    return AccountResult(curve, pd.DataFrame(holding_rows, index=curve.index, columns=symbols),
                         pd.DataFrame(ledger, columns=ORDER_COLUMNS),
                         pd.DataFrame(weights_rows, index=curve.index, columns=symbols),
                         pd.DataFrame(schedule_rows), summary)


def run_engine(instructions: pd.DataFrame, market: MarketData,
               config: BacktestConfig | None = None, *, cancel_event=None, progress=None) -> BacktestResult:
    config = config or BacktestConfig()
    check_cancelled(cancel_event)
    targets = normalize_frame(instructions, label="instructions", timezone=config.timezone,
                              date_at=config.date_at, unit=config.timestamp_unit)
    if targets.isna().any().any():
        if config.nan_policy == "error":
            raise BacktestError("Instructions contain NaN; enter explicit zero targets or opt into nan_policy='zero'")
        targets = targets.fillna(0.0)
    close = normalize_frame(market.close, label="close", timezone=config.timezone, date_at=config.date_at)
    missing = sorted(set(targets.columns) - set(close.columns))
    if missing:
        raise BacktestError(f"Instruction symbols missing from close data: {missing}")
    left = time_bound(config.start, timezone=config.timezone)
    right = time_bound(config.end, end=True, timezone=config.timezone)
    if left is None:
        left = targets.index.min()
    targets = targets.loc[(targets.index >= left) & (True if right is None else targets.index <= right)]
    close = close.loc[(close.index >= left) & (True if right is None else close.index <= right)]
    if targets.empty or close.empty:
        raise BacktestError("No instructions or prices remain in the requested interval")
    multiplier = parameter_frame(market.multiplier, close, kind="multiplier", timezone=config.timezone)
    margin = parameter_frame(market.margin_rate, close, kind="margin_rate", timezone=config.timezone)
    groups = {"portfolio": list(targets.columns)}
    if config.mode == "symbol":
        groups = {s: [s] for s in targets.columns}
    elif config.mode == "product":
        groups = {root: [s for s in targets.columns if s.startswith(root)] for root in sorted({s[:2] for s in targets.columns})}
    accounts = {}
    for group_index, (name, symbols) in enumerate(groups.items()):
        def report(payload, index=group_index):
            if progress:
                progress({**payload, "account_index": index, "accounts": len(groups)})
        accounts[name] = _run_account(name, targets.loc[:, symbols], close, multiplier, margin,
                                     market.contracts, config, cancel_event=cancel_event, progress=report)
    return BacktestResult(accounts, dict(config=asdict(config), market_data=market.metadata,
                                        execution="first market timestamp strictly after signal; raw close; full fills",
                                        sizing="literal signed equity fractions reserved as gross margin; integer truncation",
                                        spot_model="fully funded synthetic index units; multiplier=1, margin=1; shorts allowed",
                                        pnl="futures variation plus spot market value minus notional commissions",
                                        margin_call="(equity - required_margin) < required_margin * minimum_margin_ratio"
                                        if config.margin_call_basis == "available_equity" else
                                        "equity < required_margin * minimum_margin_ratio"))
