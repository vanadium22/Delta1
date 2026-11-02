"""Deterministic next-bar fills with gross margin budgets and explicit ledgers."""
from __future__ import annotations

from dataclasses import asdict
import heapq
import os

import numpy as np
import pandas as pd

from .models import (AccountResult, BacktestConfig, BacktestError, BacktestResult,
                     MarketData, check_cancelled, normalize_frame, time_bound)
from .parallel import process_map, worker_cancel_event, worker_count
from .timeline import daily_marks, effective_instructions, input_precision, next_joint_quote, quote_timeline


ORDER_COLUMNS = ["signal_time", "execution_time", "symbol", "action", "side", "quantity",
                 "signed_quantity", "price", "multiplier", "margin_rate", "notional", "fee",
                 "position_before", "position_after", "reason", "price_source", "execution_precision"]


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


class ParameterBook:
    """Constant parameters broadcast without allocating a full time-by-symbol table."""
    def __init__(self, value, symbols, timezone):
        self.symbols = symbols
        self.spot = np.array([s.endswith("_spot") for s in symbols])
        self.source = None
        if isinstance(value, pd.DataFrame):
            self.source = normalize_frame(value, label="reference parameter", timezone=timezone, date_at="00:00")
            self.source = self.source.reindex(columns=symbols)
            self.source.loc[:, self.spot] = 1.0
            self.values = self.source.to_numpy()
        else:
            self.values = np.array([1.0 if s.endswith("_spot") else value.get(s, value.get(s[:2], np.nan))
                                    for s in symbols], dtype=float)

    def at(self, stamp):
        if self.source is None:
            return self.values
        pos = self.source.index.searchsorted(stamp, side="right") - 1
        return self.values[pos] if pos >= 0 else np.where(self.spot, 1.0, np.nan)

    def block(self, times):
        if self.source is None:
            return np.broadcast_to(self.values, (len(times), len(self.symbols)))
        locations = self.source.index.get_indexer(times, method="pad")
        result = self.values[np.maximum(locations, 0)].copy()
        result[locations < 0] = np.where(self.spot, 1.0, np.nan)
        return result


def _schedule(instructions, times, *, daily_only=False):
    pending, rows = {}, []
    locations = times.searchsorted(instructions.index, side="right")
    if daily_only:
        locations = np.maximum(locations, times.searchsorted(instructions.index.normalize() + pd.Timedelta(days=1)))
    values = instructions.to_numpy(dtype=float)
    for i, (signal_time, loc) in enumerate(zip(instructions.index, locations)):
        record = dict(signal_time=signal_time, execution_time=pd.NaT, status="no_next_bar")
        if loc < len(times):
            loc = int(loc)
            record.update(execution_time=times[loc], status="scheduled")
            if loc in pending:
                rows[pending[loc][2]]["status"] = "superseded"
            pending[loc] = (signal_time, values[i], len(rows))
        rows.append(record)
    return pending, rows


def _run_account(name, instructions, market, config, *, cancel_event=None, progress=None):
    symbols = list(instructions.columns)
    daily = daily_marks(market.close, market.daily_close).reindex(columns=symbols)
    close, fallback = quote_timeline(market.close.reindex(columns=symbols), daily, market.daily_fallback)
    if market.daily_fallback is None and not market.close.index.normalize().duplicated().any():
        at_close = market.close.index == market.close.index.normalize() + pd.Timedelta(hours=15)
        fallback.loc[market.close.index[at_close]] = market.close.loc[at_close, symbols].notna()
    times = close.index
    prices = close.to_numpy(dtype=float)
    fallback = fallback.to_numpy(dtype=bool)
    valid = np.isfinite(prices) & (prices > 0)
    multiple_book = ParameterBook(market.multiplier, symbols, config.timezone)
    rate_book = ParameterBook(market.margin_rate, symbols, config.timezone)
    spot = np.array([s.endswith("_spot") for s in symbols])
    positions = np.zeros(len(symbols), dtype=np.int64)
    last_price = np.full(len(symbols), np.nan)
    last_multiple = np.full(len(symbols), np.nan)
    cash = float(config.initial_capital)
    pending, schedule = _schedule(instructions, times, daily_only=config.precision == "1d" or input_precision(instructions) == "1d")
    day_rows = {int(times.get_loc(t)): i for i, t in enumerate(daily.index)}
    events = list(set(pending) | set(day_rows))
    heapq.heapify(events)
    queued = set(events)
    joint_cache = {}
    ledger, history, holding_rows, target_rows, target_times = [], [], [], [], []
    status, blown_at, latest_signal = "completed", None, None
    previous_equity, fees_today, total_fees = config.initial_capital, 0.0, 0.0
    scanned, checks, gaps, evaluated = -1, 0, 0, 0
    trigger_margin, trigger_available = np.nan, np.nan
    trigger_time = pd.NaT

    def values(price, multiple, rate):
        held = positions != 0
        spot_held = held & spot
        equity = cash + float((positions[spot_held] * price[spot_held] * multiple[spot_held]).sum())
        notional = np.abs(positions[held]) * price[held] * multiple[held]
        required = float((notional * rate[held]).sum())
        return equity, required, equity - required, float(notional.sum())

    def failed(equity, required, available):
        base = equity if config.margin_call_basis == "equity" else available
        return equity <= 0 or (required > 0 and base < required * config.minimum_margin_ratio)

    def mark(price, multiple, rate, now):
        nonlocal cash, evaluated
        held = positions != 0
        _require(price, held, symbols, now, "close")
        _require(multiple, held, symbols, now, "multiplier")
        _require(rate, held, symbols, now, "margin_rate", upper=1)
        for j in np.flatnonzero(held):
            expiry = market.contracts.get(symbols[j], {}).get("expiry_date")
            if expiry and str(now.date()) > expiry:
                raise BacktestError(f"{symbols[j]} still held after expiry at {now}; no guessed settlement")
        if (held & np.isfinite(last_multiple) & (multiple != last_multiple)).any():
            raise BacktestError(f"Contract multiplier changed while held at {now}")
        future = held & ~spot
        cash += float((positions[future] * (price[future] - last_price[future]) * multiple[future]).sum())
        last_price[held], last_multiple[held] = price[held], multiple[held]
        evaluated += 1
        return values(price, multiple, rate)

    def execute(target, now, price, multiple, rate, signal_time, reason, source):
        nonlocal cash, fees_today, total_fees
        for j, signed, action in _legs(positions.copy(), target):
            signed = int(signed)
            quantity = abs(signed)
            notional = float(quantity * price[j] * multiple[j])
            fee = notional * config.commission_rate
            if spot[j]:
                cash -= signed * price[j] * multiple[j]
            cash -= fee
            before = int(positions[j])
            positions[j] += signed
            kind = source if isinstance(source, str) else "daily_fallback" if source[j] else "minute_close"
            ledger.append(dict(signal_time=signal_time, execution_time=now, symbol=symbols[j], action=action,
                               side="buy" if signed > 0 else "sell", quantity=quantity, signed_quantity=signed,
                               price=float(price[j]), multiplier=float(multiple[j]), margin_rate=float(rate[j]),
                               notional=notional, fee=fee, position_before=before, position_after=int(positions[j]),
                               reason=reason, price_source=kind, execution_precision="1m" if kind == "minute_close" else "1d"))
            fees_today += fee
            total_fees += fee
        held = positions != 0
        last_price[held], last_multiple[held] = price[held], multiple[held]

    def liquidate(now, price, multiple, rate, source):
        nonlocal status, blown_at, trigger_margin, trigger_available, trigger_time
        equity, required, available, _ = values(price, multiple, rate)
        trigger_margin, trigger_available, trigger_time = required, available, now
        execute(np.zeros_like(positions), now, price, multiple, rate, pd.NaT, "margin_call", source)
        status, blown_at = "blown_up", now

    def risk_scan(start, stop):
        nonlocal checks, gaps
        held = np.flatnonzero(positions != 0)
        if not len(held):
            return None
        for offset in range(start, stop, 4096):
            check_cancelled(cancel_event)
            end = min(stop, offset + 4096)
            price = prices[offset:end, :][:, held]
            eligible = valid[offset:end, :][:, held].all(axis=1)
            gaps += int((~eligible).sum())
            if not eligible.any():
                continue
            block_times = times[offset:end]
            multiples = multiple_book.block(block_times)[:, held]
            rates = rate_book.block(block_times)[:, held]
            bad_multiple = eligible[:, None] & (~np.isfinite(multiples) | (multiples <= 0))
            bad_rate = eligible[:, None] & (~np.isfinite(rates) | (rates <= 0) | (rates > 1))
            if bad_multiple.any() or bad_rate.any():
                bad = bad_multiple if bad_multiple.any() else bad_rate
                i, j = np.argwhere(bad)[0]
                field = "multiplier" if bad_multiple.any() else "margin_rate"
                raise BacktestError(f"Missing or invalid {field} for {symbols[held[j]]} at {block_times[i]}")
            if (eligible[:, None] & (multiples != last_multiple[held])).any():
                raise BacktestError("Contract multiplier changed while held during automatic risk scan")
            future = held[~spot[held]]
            base_cash = cash - float((positions[future] * last_price[future] * last_multiple[future]).sum())
            active_prices = price[eligible]
            active_multiple, active_rates = multiples[eligible], rates[eligible]
            equity = base_cash + np.einsum("ij,ij->i", active_prices, positions[held] * active_multiple)
            required = np.einsum("ij,ij->i", active_prices, np.abs(positions[held]) * active_multiple * active_rates)
            base = equity if config.margin_call_basis == "equity" else equity - required
            bad = (equity <= 0) | (base < required * config.minimum_margin_ratio)
            valid_locations = np.flatnonzero(eligible)
            failures = np.flatnonzero(bad)
            checks += int(failures[0] + 1) if len(failures) else len(valid_locations)
            if len(failures):
                return offset + int(valid_locations[failures[0]])
        return None

    def append_day(stamp, price, multiple, rate):
        nonlocal previous_equity, fees_today
        equity, required, available, notional = values(price, multiple, rate)
        history.append(dict(timestamp=stamp, equity=equity, nav=equity / config.initial_capital, cash=cash,
                            required_margin=required, available_equity=available, gross_notional=notional,
                            margin_usage=required / equity if equity > 0 else np.nan, fees=fees_today,
                            pnl=equity - previous_equity, signal_time=pd.NaT, weight_scale=np.nan,
                            status="blown_up" if blown_at is not None else "active", trigger_margin=trigger_margin,
                            trigger_available_equity=trigger_available, trigger_time=trigger_time))
        holding_rows.append(positions.copy())
        previous_equity, fees_today = equity, 0.0

    def append_failure_day():
        closes = daily.index[daily.index.normalize() == blown_at.normalize()]
        stamp = closes[-1] if len(closes) else blown_at
        # Liquidated accounts have no price exposure; this is the day's final
        # cash balance, with the exact intraday trigger retained separately.
        append_day(stamp, np.zeros(len(symbols)), np.ones(len(symbols)), np.ones(len(symbols)))

    while events:
        check_cancelled(cancel_event)
        loc = heapq.heappop(events)
        queued.discard(loc)
        now = times[loc]
        if progress and (loc % 1024 == 0 or loc in day_rows):
            progress(dict(stage="simulating", account=name, done=loc, total=len(times), timestamp=str(now)))
        if config.precision == "auto":
            failure = risk_scan(scanned + 1, loc + 1)
            scanned = loc
            if failure is not None:
                stamp, price = times[failure], prices[failure]
                multiple, rate = multiple_book.at(stamp), rate_book.at(stamp)
                mark(price, multiple, rate, stamp)
                liquidate(stamp, price, multiple, rate, fallback[failure])
                append_failure_day()
                break
        closing_values = None
        if loc in day_rows and config.precision == "1d":
            day_price = daily.iloc[day_rows[loc]].to_numpy(dtype=float)
            day_multiple, day_rate = multiple_book.at(now), rate_book.at(now)
            closing_values = mark(day_price, day_multiple, day_rate, now)
            checks += 1
            if failed(*closing_values[:3]):
                liquidate(now, day_price, day_multiple, day_rate, "daily_close")
                append_day(now, day_price, day_multiple, day_rate)
                break
        candidate = pending.pop(loc, None)
        if candidate is not None:
            signal_time, weights, record = candidate
            if latest_signal is not None and signal_time < latest_signal:
                schedule[record]["status"] = "superseded"
                candidate = None
            else:
                latest_signal = signal_time
                needed = (positions != 0) | (weights != 0)
                future_loc = loc if valid[loc, needed].all() else next_joint_quote(valid, loc, needed, joint_cache)
                if future_loc is None:
                    raise BacktestError(f"No next valid execution close for {[s for s, n in zip(symbols, needed) if n]} after {signal_time}")
                if future_loc != loc:
                    schedule[record]["execution_time"] = times[future_loc]
                    previous = pending.get(future_loc)
                    if previous is None or previous[0] < signal_time:
                        if previous is not None:
                            schedule[previous[2]]["status"] = "superseded"
                        pending[future_loc] = candidate
                    else:
                        schedule[record]["status"] = "superseded"
                    if future_loc not in queued:
                        queued.add(future_loc)
                        heapq.heappush(events, future_loc)
                    candidate = None
        if candidate is not None:
            signal_time, weights, record = candidate
            price = prices[loc]
            multiple, rate = multiple_book.at(now), rate_book.at(now)
            equity, required, available, _ = mark(price, multiple, rate, now)
            needed = (positions != 0) | (weights != 0)
            _require(multiple, needed, symbols, now, "multiplier")
            _require(rate, needed, symbols, now, "margin_rate", upper=1)
            for j in np.flatnonzero(weights != 0):
                ref = market.contracts.get(symbols[j], {})
                if ((ref.get("listing_date") and str(now.date()) < ref["listing_date"]) or
                        (ref.get("expiry_date") and str(now.date()) > ref["expiry_date"])):
                    raise BacktestError(f"Order outside {symbols[j]} listing/expiry interval at {now}")
            if equity <= 0 and np.any(weights != 0):
                schedule[record]["status"] = "insufficient_equity"
            else:
                if not np.any(weights):
                    target, effective = np.zeros_like(positions), weights
                else:
                    target, effective, _ = _targets(weights, equity, price, multiple, rate, positions, config)
                execute(target, now, price, multiple, rate, signal_time, "target_rebalance", fallback[loc])
                schedule[record]["status"] = "executed"
                target_rows.append(effective)
                target_times.append(now)
                equity, required, available, _ = values(price, multiple, rate)
                if config.precision == "auto" and failed(equity, required, available):
                    liquidate(now, price, multiple, rate, fallback[loc])
                    append_failure_day()
                    break
        if loc in day_rows:
            price = daily.iloc[day_rows[loc]].to_numpy(dtype=float)
            multiple, rate = multiple_book.at(now), rate_book.at(now)
            if closing_values is not None and candidate is None:
                equity, required, available, _ = closing_values
            else:
                equity, required, available, _ = mark(price, multiple, rate, now)
            if failed(equity, required, available):
                liquidate(now, price, multiple, rate, "daily_close")
            elif config.liquidate_at_end and now == daily.index[-1]:
                execute(np.zeros_like(positions), now, price, multiple, rate, pd.NaT, "end_of_backtest", "daily_close")
                if values(price, multiple, rate)[0] <= 0:
                    liquidate(now, price, multiple, rate, "daily_close")
            append_day(now, price, multiple, rate)
            if blown_at is not None:
                break
    for row in schedule:
        if row["status"] == "scheduled":
            row["status"] = "stopped_by_margin_call"
    if not history:
        raise BacktestError("No daily close is available for the requested interval")
    curve = pd.DataFrame(history).set_index("timestamp")
    nav = np.r_[1.0, curve.nav.to_numpy()]
    drawdown = nav / np.maximum.accumulate(nav) - 1
    summary = dict(status=status, initial_capital=config.initial_capital, final_equity=float(curve.equity.iloc[-1]),
                   total_return=float(curve.nav.iloc[-1] - 1), max_drawdown=float(drawdown.min()),
                   total_fees=total_fees, order_count=len(ledger), bars=len(curve), start=str(curve.index[0]),
                   end=str(curve.index[-1]), blown_at=str(blown_at) if blown_at is not None else None,
                   unexecuted_signals=sum(r["status"] != "executed" for r in schedule),
                   evaluated_events=evaluated, quote_rows=len(times), risk_checks=checks, risk_quote_gaps=gaps,
                   daily_fallback_orders=sum(r["price_source"] == "daily_fallback" for r in ledger), worker_pid=os.getpid())
    return AccountResult(curve, pd.DataFrame(holding_rows, index=curve.index, columns=symbols),
                         pd.DataFrame(ledger, columns=ORDER_COLUMNS),
                         pd.DataFrame(target_rows, index=pd.DatetimeIndex(target_times, name="timestamp"), columns=symbols),
                         pd.DataFrame(schedule), summary)


def _run_account_worker(payload):
    name, instructions, market, config = payload
    return _run_account(name, instructions, market, config, cancel_event=worker_cancel_event())


def _subset(value, symbols):
    return value.reindex(columns=symbols) if isinstance(value, pd.DataFrame) else value


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
    supplied_daily = (normalize_frame(market.daily_close, label="daily close", timezone=config.timezone)
                      if market.daily_close is not None else None)
    if supplied_daily is not None and supplied_daily.index.normalize().duplicated().any():
        raise BacktestError("daily_close must contain at most one close timestamp per trading day")
    left, right = time_bound(config.start, timezone=config.timezone), time_bound(config.end, end=True, timezone=config.timezone)
    if left is None:
        left = targets.index.min()
    targets = targets.loc[(targets.index >= left) & (True if right is None else targets.index <= right)]
    close = close.loc[(close.index >= left) & (True if right is None else close.index <= right)]
    if supplied_daily is not None:
        supplied_daily = supplied_daily.loc[(supplied_daily.index >= left) & (True if right is None else supplied_daily.index <= right)]
    if targets.empty or close.empty:
        raise BacktestError("No instructions or prices remain in the requested interval")
    input_rows = len(targets)
    targets, resolved = effective_instructions(targets, config.precision)
    active = set(targets.columns[targets.abs().gt(0).any(axis=0)])
    missing = sorted(active - set(close.columns))
    if missing:
        raise BacktestError(f"Instruction symbols missing from close data: {missing}")
    close = close.reindex(columns=close.columns.union(targets.columns))
    if supplied_daily is not None:
        supplied_daily = supplied_daily.reindex(columns=close.columns)
    groups = {"portfolio": list(targets.columns)}
    if config.mode == "symbol":
        groups = {s: [s] for s in targets.columns}
    elif config.mode == "product":
        groups = {root: [s for s in targets.columns if s.startswith(root)] for root in sorted({s[:2] for s in targets.columns})}
    jobs = []
    for name, symbols in groups.items():
        partial = MarketData(close.loc[:, symbols], _subset(market.multiplier, symbols), _subset(market.margin_rate, symbols),
                             contracts=market.contracts, daily_close=_subset(supplied_daily, symbols) if supplied_daily is not None else None,
                             daily_fallback=_subset(market.daily_fallback, symbols) if market.daily_fallback is not None else None)
        jobs.append((name, targets.loc[:, symbols], partial, config))
    # A vectorized risk scan is much cheaper than a target rebalance. Account
    # workers are selected by effective signal work, rather than raw row count.
    work_units = (len(targets) * 4 + len(close) // 50) * len(targets.columns)
    count = worker_count(len(jobs), config.workers, work_units)
    if count > 1:
        results, parallel = process_map(_run_account_worker, jobs, workers=count,
                                       cancel_event=cancel_event, progress=progress, stage="simulating_parallel")
    else:
        results = []
        for i, (name, frame, partial, parameters) in enumerate(jobs):
            def report(info, group=i):
                if progress:
                    progress({**info, "account_index": group, "accounts": len(groups)})
            results.append(_run_account(name, frame, partial, parameters, cancel_event=cancel_event, progress=report))
        parallel = dict(workers=1, worker_pids=[os.getpid()])
    accounts = dict(zip(groups, results))
    market_info = {**market.metadata, "warnings": list(market.metadata.get("warnings", []))}
    gaps = sum(a.summary["risk_quote_gaps"] for a in results)
    if gaps:
        market_info["warnings"].append(f"{gaps} held-position quote gaps; automatic risk falls back to the next real quote/daily close")
    return BacktestResult(accounts, dict(config=asdict(config), market_data=market_info,
                                        precision=dict(requested=config.precision, resolved=resolved, equity_output="daily_close",
                                                       input_rows=input_rows, effective_signal_rows=len(targets),
                                                       risk="every_observed_quote" if config.precision == "auto" else "daily_close"),
                                        performance=dict(account_processes=parallel, input_quote_rows=len(close),
                                                         evaluated_events=sum(a.summary["evaluated_events"] for a in results)),
                                        execution="first jointly valid quote strictly after signal; minute then actual daily-close fallback",
                                        sizing="literal signed equity fractions as gross margin; integer truncation",
                                        spot_model="fully funded synthetic index units; multiplier=1, margin=1; shorts allowed",
                                        pnl="futures variation plus spot market value minus notional commissions; daily close output",
                                        margin_call="equity < required_margin * minimum_margin_ratio" if config.margin_call_basis == "equity" else
                                        "(equity - required_margin) < required_margin * minimum_margin_ratio"))
