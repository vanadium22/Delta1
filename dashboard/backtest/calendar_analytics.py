"""Round trips and disjoint drawdown episodes reconciled to original engine ledgers."""
import numpy as np
import pandas as pd

from .analytics import performance_metrics
from .models import BacktestError

TRIP_COLUMNS = ("scenario", "trade_id", "root", "channel", "near", "far", "entry_signal_time", "entry_time",
    "exit_signal_time", "exit_time", "valuation_time", "direction", "actual_lots", "entry_p", "entry_execution_p",
    "exit_p", "exit_execution_p", "entry_near_t", "entry_far_t", "exit_near_t", "exit_far_t", "holding_calendar_days",
    "exit_reason", "status", "entry_margin", "entry_history_start", "entry_history_end", "exit_history_start", "exit_history_end",
    "near_entry_price", "near_exit_price", "near_signed_lots", "near_gross_pnl", "near_fees", "near_net_pnl", "near_entry_margin",
    "far_entry_price", "far_exit_price", "far_signed_lots", "far_gross_pnl", "far_fees", "far_net_pnl", "far_entry_margin",
    "gross_pnl", "fees", "net_pnl", "net_return", "annualized_net_pnl", "annualized_return", "annualization_status")
LEG_COLUMNS = ("scenario", "trade_id", "leg", "symbol", "signed_lots", "multiplier", "margin_rate", "entry_time", "exit_time",
    "entry_price", "exit_or_mark_price", "entry_fee", "exit_fee", "gross_pnl", "net_pnl", "status")
PATH_COLUMNS = ("timestamp", "scenario", "trade_id", "root", "channel", "near", "far", "near_gross_pnl", "near_net_pnl",
    "far_gross_pnl", "far_net_pnl", "net_pnl", "return_on_entry_margin", "entry_margin")
DRAWDOWN_COLUMNS = ("scenario", "peak_date", "trough_date", "recovery_date", "end_date", "peak_equity", "trough_equity",
    "drawdown", "duration_calendar_days", "peak_to_trough_days", "recovered", "peak_is_initial_anchor", "rank")


def _check_equal(actual, expected, label, *, atol=1e-5):
    if not np.allclose(actual, expected, rtol=1e-10, atol=atol, equal_nan=False):
        raise BacktestError(f"Calendar reconciliation failed: {label}")


def annual_trade_returns(net, margin, days):
    ratio = net / margin
    if days <= 0 or ratio <= -1:
        return ratio, np.nan, np.nan, "holding_days_zero" if days <= 0 else "return_le_minus_one"
    return ratio, net*365/days, float(np.expm1(np.log1p(ratio)*365/days)), "applicable"


def round_trips(account, factors, signals, *, scenario, root, channel, initial_capital, commission_rate,
                entry_timing="next_observation"):
    table = factors.diagnostics["calendar_pairs"]
    table = table.loc[table.root.eq(root) & table.channel.eq(channel)]
    lookup = {(r.timestamp, r.near, r.far): r for r in table.itertuples(index=False)}
    day_lookup = {(r.timestamp.normalize(), r.near, r.far): r for r in table.itertuples(index=False)}
    decisions = signals.decisions
    opening = {} if decisions.empty else {r.timestamp: r for r in
        decisions.loc[decisions.root.eq(root) & decisions.action.eq("signal_open")].itertuples(index=False)}
    orders = account.actual_orders
    active, states = None, []
    for stamp, group in orders.groupby("execution_time", sort=False):
        for is_open in (False, True):
            part = group.loc[group.action.str.startswith("open" if is_open else "close")]
            if part.empty:
                continue
            if len(part) != 2 or part.symbol.nunique() != 2 or part.reason.nunique() != 1:
                raise BacktestError("A calendar event must contain exactly two same-reason actual legs")
            _check_equal(part.signed_quantity.sum(), 0, "equal opposite lots", atol=0)
            _check_equal(part.fee, part.notional*commission_rate, "full-notional commission")
            _check_equal(part.notional, part.quantity*part.price*part.multiplier, "actual notional")
            if is_open:
                if active is not None or part.position_before.ne(0).any():
                    raise BacktestError("Overlapping calendar round trips or resized held lots")
                valid_entry = (part.signal_time.eq(part.execution_time) if entry_timing == "signal_close"
                               else part.signal_time.lt(part.execution_time))
                if part.signal_time.nunique() != 1 or not valid_entry.all():
                    raise BacktestError("Entry execution differs from its declared signal timing")
                signal = opening.get(part.signal_time.iloc[0])
                if signal is None or {signal.near, signal.far} != set(part.symbol):
                    raise BacktestError("Executed pair differs from the locked entry signal")
                active = dict(open=part.set_index("symbol"), close=None, signal=signal, entry_time=stamp)
                states.append(active)
            else:
                if active is None or set(part.symbol) != set(active["open"].index) or part.position_after.ne(0).any():
                    raise BacktestError("Closing event does not match the entire locked pair")
                _check_equal(part.set_index("symbol").loc[active["open"].index].signed_quantity,
                             -active["open"].signed_quantity, "closed original lots", atol=0)
                if part.reason.iloc[0] == "target_rebalance" and not (part.signal_time < part.execution_time).all():
                    raise BacktestError("Threshold exit must follow its signal")
                if part.reason.iloc[0] == "expiry_d0":
                    expiry = min(factors.contracts[s]["expiry_date"] for s in part.symbol)
                    if str(stamp.date()) != expiry or not part.price_source.eq("daily_close").all():
                        raise BacktestError("Expiry must close both legs at actual expiry-day close")
                active["close"] = part.set_index("symbol")
                active = None
    index = account.equity.index
    reconstructed = np.zeros(len(index))
    reconstructed_fees = np.zeros(len(index))
    reconstructed_margin = np.zeros(len(index))
    reconstructed_positions = pd.DataFrame(0, index=index, columns=account.positions.columns)
    trips, legs, paths = [], [], []
    for state in states:
        signal, opened, closed = state["signal"], state["open"], state["close"]
        near, far, start = signal.near, signal.far, state["entry_time"]
        end = closed.execution_time.iloc[0] if closed is not None else index[-1]
        held_days = (end.normalize()-start.normalize()).days
        entry_factor = lookup[(signal.timestamp, near, far)]
        fill_factor = day_lookup[(start.normalize(), near, far)]
        exit_factor = day_lookup[(end.normalize(), near, far)]
        exit_signal = closed.signal_time.iloc[0] if closed is not None else pd.NaT
        exit_signal_factor = lookup.get((exit_signal, near, far))
        reason = closed.reason.iloc[0] if closed is not None else "open_at_end"
        if reason == "target_rebalance":
            reason = "threshold"
        trade_id = scenario+"_"+signal.trade_id.rsplit("_",1)[-1]
        margin = float((opened.notional*opened.margin_rate).sum())
        active_index = index[(index.normalize() >= start.normalize()) & (index.normalize() <= end.normalize())]
        positions = index.get_indexer(active_index)
        trace = pd.DataFrame(dict(timestamp=active_index, scenario=scenario, trade_id=trade_id, root=root,
            channel=channel, near=near, far=far))
        sums = dict(gross_pnl=0., fees=0., net_pnl=0.)
        row = dict(scenario=scenario, trade_id=trade_id, root=root, channel=channel, near=near, far=far,
            entry_signal_time=signal.timestamp, entry_time=start, exit_signal_time=exit_signal,
            exit_time=end if closed is not None else pd.NaT, valuation_time=end,
            direction="long_spread" if signal.direction > 0 else "short_spread", actual_lots=int(opened.loc[near].quantity),
            entry_p=entry_factor.percentile, entry_execution_p=fill_factor.percentile if start==fill_factor.timestamp else np.nan,
            exit_p=exit_signal_factor.percentile if exit_signal_factor is not None else exit_factor.percentile,
            exit_execution_p=exit_factor.percentile if end==exit_factor.timestamp else np.nan,
            entry_near_t=fill_factor.near_t, entry_far_t=fill_factor.far_t,
            exit_near_t=exit_factor.near_t, exit_far_t=exit_factor.far_t,
            holding_calendar_days=held_days, exit_reason=reason, status="closed" if closed is not None else "open",
            entry_margin=margin, entry_history_start=entry_factor.history_start, entry_history_end=entry_factor.history_end,
            exit_history_start=(exit_signal_factor or exit_factor).history_start,
            exit_history_end=(exit_signal_factor or exit_factor).history_end)
        trade_fees = np.zeros(len(active_index))
        trade_margin = np.zeros(len(active_index))
        for label, symbol in (("near", near), ("far", far)):
            order = opened.loc[symbol]
            closing = closed.loc[symbol] if closed is not None else None
            quotes = np.array([getattr(lookup[(t, near, far)], label+"_price") for t in active_index])
            if not np.isfinite(quotes).all():
                raise BacktestError("Missing held-pair quote; cannot fill prices")
            if closing is not None:
                if end==exit_factor.timestamp:
                    _check_equal(quotes[-1], closing.price, "exit quote versus saved actual pair")
                quotes[-1]=closing.price
            if start==fill_factor.timestamp and (closing is None or end>start):
                _check_equal(quotes[0], order.price, "entry quote versus saved actual pair")
            qty = int(order.signed_quantity)
            gross = qty*order.multiplier*(quotes-order.price)
            fees = np.full(len(active_index), order.fee)
            trade_fees[0] += order.fee
            if closing is not None:
                fees[-1] += closing.fee
                trade_fees[-1] += closing.fee
            net = gross-fees
            trace[label+"_gross_pnl"], trace[label+"_net_pnl"] = gross, net
            leg_margin = np.abs(qty)*order.multiplier*quotes*order.margin_rate
            if closed is not None:
                leg_margin[-1] = 0.
            trade_margin += leg_margin
            held_mask = (index >= start) & (index < end if closed is not None else index <= end)
            reconstructed_positions.loc[held_mask, symbol] += qty
            row.update({label+"_entry_price":order.price, label+"_exit_price":quotes[-1], label+"_signed_lots":qty,
                label+"_gross_pnl":float(gross[-1]), label+"_fees":float(fees[-1]), label+"_net_pnl":float(net[-1]),
                label+"_entry_margin":float(order.notional*order.margin_rate)})
            legs.append(dict(scenario=scenario,trade_id=trade_id,leg=label,symbol=symbol,signed_lots=qty,
                multiplier=order.multiplier,margin_rate=order.margin_rate,entry_time=start,exit_time=row["exit_time"],
                entry_price=order.price,exit_or_mark_price=quotes[-1],entry_fee=order.fee,
                exit_fee=closing.fee if closing is not None else 0.,gross_pnl=gross[-1],net_pnl=net[-1],status=row["status"]))
            sums["gross_pnl"] += float(gross[-1])
            sums["fees"] += float(fees[-1])
            sums["net_pnl"] += float(net[-1])
        trace["net_pnl"] = trace.near_net_pnl+trace.far_net_pnl
        trace["return_on_entry_margin"] = trace.net_pnl/margin
        trace["entry_margin"] = margin
        reconstructed[positions] += trace.net_pnl.to_numpy()
        if closed is not None:
            reconstructed[index.normalize() > end.normalize()] += sums["net_pnl"]
        reconstructed_fees[positions] += trade_fees
        reconstructed_margin[positions] += trade_margin
        ratio, amount, annual, applicability = annual_trade_returns(sums["net_pnl"], margin, held_days)
        row.update(**sums, net_return=ratio,
            annualized_net_pnl=amount if closed is not None else np.nan,
            annualized_return=annual if closed is not None else np.nan,
            annualization_status=applicability if closed is not None else "open_not_annualized")
        trips.append(row)
        paths.append(trace)
    _check_equal(reconstructed, account.equity.equity-initial_capital, "round-trip daily equity")
    _check_equal(reconstructed_fees, account.equity.fees, "round-trip daily fees")
    _check_equal(reconstructed_margin, account.equity.required_margin, "round-trip daily margin")
    _check_equal(reconstructed_positions, account.positions, "locked actual pair and lots", atol=0)
    trip_frame = pd.DataFrame(trips) if trips else pd.DataFrame(columns=TRIP_COLUMNS)
    stats = performance_metrics(account.equity.equity, initial_capital)
    closed = trip_frame.loc[trip_frame.status.eq("closed")] if len(trip_frame) else trip_frame
    wins = closed.loc[closed.net_pnl > 0] if len(closed) else closed
    losses = closed.loc[closed.net_pnl < 0] if len(closed) else closed
    flats = closed.loc[closed.net_pnl.eq(0)] if len(closed) else closed
    avg_win = float(wins.net_pnl.mean()) if len(wins) else np.nan
    avg_loss = float(losses.net_pnl.mean()) if len(losses) else np.nan
    stats.update(closed_trades=len(closed),winning_trades=len(wins),losing_trades=len(losses),flat_trades=len(flats),
        net_win_rate=len(wins)/len(closed) if len(closed) else np.nan,
        average_win_cny=avg_win,average_loss_cny=avg_loss,
        average_win_return=float(wins.net_return.mean()) if len(wins) else np.nan,
        average_loss_return=float(losses.net_return.mean()) if len(losses) else np.nan,
        payoff_ratio=avg_win/abs(avg_loss) if len(wins) and len(losses) else np.nan,
        payoff_ratio_return=(wins.net_return.mean()/abs(losses.net_return.mean())) if len(wins) and len(losses) else np.nan,
        open_trades=len(trip_frame)-len(closed),
        open_net_pnl=float(trip_frame.loc[trip_frame.status.eq("open"),"net_pnl"].sum()) if len(trip_frame) else 0.,
        closed_net_pnl=float(closed.net_pnl.sum()) if len(closed) else 0.,
        fees=float(orders.fee.sum()),engine_status=account.summary["status"],
        annualization_na_trades=int(closed.annualization_status.ne("applicable").sum()) if len(closed) else 0)
    return (trip_frame, pd.DataFrame(legs) if legs else pd.DataFrame(columns=LEG_COLUMNS),
        pd.concat(paths,ignore_index=True) if paths else pd.DataFrame(columns=PATH_COLUMNS), stats)


def drawdown_episodes(equity, initial_capital, *, scenario):
    """Top three complete peak-to-recovery underwater episodes; never overlapping.

    A pre-first-close initial equity anchor is explicit if the first close is
    already underwater. New equal highs choose the last high before the decline.
    """
    dates, values = equity.index, equity.to_numpy()
    peak_values = np.maximum.accumulate(np.r_[initial_capital, values])[1:]
    drawdown = values/peak_values-1
    anchor = dates[0].normalize()
    peak_time, peak, trough_time, trough, active = anchor, initial_capital, None, None, False
    rows = []
    def append(recovery, end):
        rows.append(dict(scenario=scenario,peak_date=peak_time,trough_date=trough_time,recovery_date=recovery,
            end_date=end,peak_equity=float(peak),trough_equity=float(trough),drawdown=float(trough/peak-1),
            duration_calendar_days=(end.normalize()-peak_time.normalize()).days,
            peak_to_trough_days=(trough_time.normalize()-peak_time.normalize()).days,
            recovered=not pd.isna(recovery),peak_is_initial_anchor=peak_time==anchor))
    for stamp, value in zip(dates,values):
        if value >= peak:
            if active:
                append(stamp,stamp)
            peak_time,peak,active=stamp,value,False
        else:
            if not active or value < trough:
                trough_time,trough=stamp,value
            active=True
    if active:
        append(pd.NaT,dates[-1])
    rows=sorted(rows,key=lambda r:(r["drawdown"],r["peak_date"]))[:3]
    for rank,row in enumerate(rows,1):
        row["rank"]=rank
        _check_equal(equity.loc[row["trough_date"]],row["trough_equity"],"drawdown trough")
        j=dates.get_loc(row["trough_date"])
        _check_equal(drawdown[j],row["drawdown"],"drawdown amplitude")
        if not row["peak_is_initial_anchor"]:
            _check_equal(equity.loc[row["peak_date"]],row["peak_equity"],"drawdown peak")
        if row["recovered"] and equity.loc[row["recovery_date"]] < row["peak_equity"]:
            raise BacktestError("Drawdown recovery point is still underwater")
    ordered=sorted(rows,key=lambda r:r["peak_date"])
    for left,right in zip(ordered,ordered[1:]):
        if left["end_date"] > right["peak_date"]:
            raise BacktestError("Drawdown episodes overlap")
    if rows:
        _check_equal(rows[0]["drawdown"],drawdown.min(),"maximum drawdown")
    curve=pd.DataFrame(dict(timestamp=dates,scenario=scenario,equity=values,
        cumulative_net_return=values/initial_capital-1,drawdown=drawdown,peak_equity=peak_values))
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=DRAWDOWN_COLUMNS),curve
