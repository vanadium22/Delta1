"""Decompose a netted index book into actual-contract pairs, with exact fee totals."""
import numpy as np
import pandas as pd

from .engine import ParameterBook
from .models import BacktestError, normalize_frame
from .timeline import daily_marks, quote_timeline


def attribute_index_pairs(account, market, *, initial_capital, timezone="Asia/Shanghai"):
    """Virtual index allocations sum to physical units; no fictitious gross fees."""
    index = account.equity.index
    symbols = [s for s in account.positions if s.endswith(".CFE")]
    if not symbols:
        raise BacktestError("Pair attribution requires actual futures")
    days = index.normalize()
    positions = account.positions[symbols]
    multiple = ParameterBook(market.multiplier, symbols, timezone).block(index)
    rates = ParameterBook(market.margin_rate, symbols, timezone).block(index)
    daily = normalize_frame(daily_marks(market.close, market.daily_close), label="pair daily close", timezone=timezone)
    close = daily.reindex(index=index, columns=symbols).to_numpy()
    future_value = np.where(positions.to_numpy() != 0, positions.to_numpy()*close*multiple, 0.)
    units = np.where(positions.to_numpy() != 0, -positions.to_numpy()*multiple, 0.)
    marks = daily.reindex(index=index)
    minute = normalize_frame(market.close, label="pair execution quotes", timezone=timezone)
    quotes, _ = quote_timeline(minute, daily)
    flow = pd.DataFrame(0., index=days, columns=symbols)
    future_flow, future_fees, hedge_fees = flow.copy(), flow.copy(), flow.copy()
    orders = account.actual_orders.copy()
    if len(orders):
        orders["day"] = orders.execution_time.dt.normalize()
        for stamp, event in orders.groupby("execution_time", sort=True):
            for root in sorted({s[:2] for s in event.symbol}):
                futures = event.loc[event.symbol.str.startswith(root) & event.symbol.str.endswith(".CFE")]
                spot = root + "_spot"
                hedge = event.loc[event.symbol.eq(spot)]
                changes, turnover = {}, {}
                for row in futures.itertuples(index=False):
                    future_flow.at[row.day, row.symbol] += row.signed_quantity * row.price * row.multiplier
                    future_fees.at[row.day, row.symbol] += row.fee
                    changes[row.symbol] = changes.get(row.symbol, 0.) - row.signed_quantity * row.multiplier
                    turnover[row.symbol] = turnover.get(row.symbol, 0.) + abs(row.signed_quantity * row.multiplier)
                physical = float(hedge.signed_quantity.sum())
                if not np.isclose(sum(changes.values()), physical, atol=1e-9, rtol=0):
                    raise BacktestError("Actual index changes do not reconcile to pair quantity changes")
                if not changes:
                    if len(hedge):
                        raise BacktestError("Unlinked index order cannot be assigned to futures pairs")
                    continue
                if len(hedge):
                    prices = hedge.price.unique()
                    if len(prices) != 1:
                        raise BacktestError("Pair events need one common index fill price")
                    price = float(prices[0])
                else:
                    use_daily = futures.price_source.eq("daily_close").all()
                    source = daily if use_daily else quotes
                    price = source.at[stamp, spot] if stamp in source.index and spot in source else np.nan
                if not np.isfinite(price) or price <= 0:
                    raise BacktestError(f"Missing actual index quote for virtual pair event {spot} at {stamp}")
                denominator = sum(turnover.values())
                for symbol, change in changes.items():
                    flow.at[stamp.normalize(), symbol] += change * price
                    hedge_fees.at[stamp.normalize(), symbol] += float(hedge.fee.sum()) * turnover[symbol] / denominator
    future_net = future_value - future_flow.cumsum().to_numpy() - future_fees.cumsum().to_numpy()
    hedge_net = np.zeros_like(future_net)
    pair_margin = np.zeros_like(future_net)
    gross_margin = np.zeros_like(future_net)
    for root in sorted({s[:2] for s in symbols}):
        cols = [j for j, symbol in enumerate(symbols) if symbol.startswith(root)]
        spot = root + "_spot"
        prices = marks[spot].to_numpy() if spot in marks else np.full(len(index), np.nan)
        needed = np.any(units[:,cols] != 0, axis=1)
        if (~np.isfinite(prices[needed]) | (prices[needed] <= 0)).any():
            raise BacktestError("Cannot mark virtual index legs without actual same-day prices")
        actual_units = account.positions[spot].to_numpy() if spot in account.positions else np.zeros(len(index))
        if not np.allclose(units[:,cols].sum(axis=1), actual_units, atol=1e-9, rtol=0):
            raise BacktestError("Virtual pair index units do not sum to the actual index holding")
        hedged_value = np.where(units[:,cols] != 0, units[:,cols]*prices[:,None], 0.)
        hedge_net[:,cols] = hedged_value - flow.iloc[:,cols].cumsum().to_numpy() - hedge_fees.iloc[:,cols].cumsum().to_numpy()
        absolute = np.abs(units[:,cols])
        total = absolute.sum(axis=1)
        physical_margin = np.where(actual_units != 0, np.abs(actual_units)*prices, 0.)
        allocation = np.divide(absolute, total[:,None], out=np.zeros_like(absolute), where=total[:,None]>0) * physical_margin[:,None]
        future_margin = np.where(positions.iloc[:,cols].to_numpy() != 0,
                                np.abs(positions.iloc[:,cols].to_numpy())*close[:,cols]*multiple[:,cols]*rates[:,cols], 0.)
        pair_margin[:,cols] = future_margin + allocation
        gross_margin[:,cols] = future_margin + np.where(absolute != 0, absolute*prices[:,None], 0.)
    net = future_net + hedge_net
    if not np.allclose(net.sum(axis=1), account.equity.equity.to_numpy()-initial_capital, atol=max(1e-5,initial_capital*1e-11), rtol=1e-10):
        raise BacktestError("Pair PnL does not reconcile to account equity")
    if not np.allclose(pair_margin.sum(axis=1), account.equity.required_margin, atol=1e-5, rtol=1e-10):
        raise BacktestError("Allocated pair margin does not reconcile to physical margin")
    if not np.allclose((future_fees+hedge_fees).sum(axis=1).to_numpy(), account.equity.fees.to_numpy(), atol=1e-6, rtol=1e-10):
        raise BacktestError("Allocated pair fees do not reconcile to actual fees")
    frames = []
    for j, symbol in enumerate(symbols):
        if not (positions[symbol].ne(0).any() or future_fees[symbol].ne(0).any()):
            continue
        frames.append(pd.DataFrame(dict(timestamp=index, root=symbol[:2], pair_id=symbol+"|"+symbol[:2]+"_spot",
            future=symbol, hedge=symbol[:2]+"_spot", future_lots=positions[symbol].to_numpy(), hedge_units=units[:,j],
            multiplier=multiple[:,j], hedge_multiplier=1., pair_type="future_index", hedge_quantity_unit="index_units",
            future_pnl=future_net[:,j], hedge_pnl=hedge_net[:,j], net_pnl=net[:,j],
            fees_cumulative=(future_fees[symbol]+hedge_fees[symbol]).cumsum().to_numpy(),
            allocated_actual_margin=pair_margin[:,j], gross_pair_margin=gross_margin[:,j],
            return_contribution=net[:,j]/initial_capital)))
    detail = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    summary = detail.groupby("pair_id", sort=True).tail(1).reset_index(drop=True) if len(detail) else detail.copy()
    return detail, summary


def attribute_calendar_pairs(account, market, *, initial_capital, timezone="Asia/Shanghai"):
    """Assign both actual futures legs to the executed pair, including same-day rolls."""
    index, dates = account.equity.index, account.equity.index.normalize()
    daily = normalize_frame(daily_marks(market.close, market.daily_close), label="calendar pair close", timezone=timezone)
    active = None
    pairs = {}
    orders = account.actual_orders
    if len(orders) and orders.symbol.str.endswith("_spot").any():
        raise BacktestError("Calendar pair attribution does not accept index orders")
    for _, group in orders.groupby(["execution_time", "reason", "signal_time"], dropna=False, sort=False):
        if active is None:
            opened = group.loc[group.action.str.startswith("open"), "symbol"].unique()
            if len(opened) != 2:
                raise BacktestError("A calendar pair must open two actual futures together")
            near, far = sorted(opened, key=lambda s:(market.contracts[s]["expiry_date"],s))
            active = near + "|" + far
            if active not in pairs:
                pairs[active] = dict(legs=(near,far), lots={near:0,far:0}, rows=[])
        state = pairs[active]
        if not set(group.symbol) <= set(state["legs"]):
            raise BacktestError("Calendar event mixes an existing pair with unrelated legs")
        for row in group.itertuples(index=False):
            state["rows"].append(row)
            state["lots"][row.symbol] += row.signed_quantity
        if all(v == 0 for v in state["lots"].values()):
            active = None
    frames = []
    reconstructed = pd.DataFrame(0., index=index, columns=account.positions.columns)
    for pair_id, state in pairs.items():
        near, far = state["legs"]
        lots = pd.DataFrame(0., index=dates, columns=[near,far])
        cashflows, fees = lots.copy(), lots.copy()
        for row in state["rows"]:
            day = row.execution_time.normalize()
            lots.at[day,row.symbol] += row.signed_quantity
            cashflows.at[day,row.symbol] += row.signed_quantity*row.price*row.multiplier
            fees.at[day,row.symbol] += row.fee
        positions = lots.cumsum().to_numpy()
        multiples = ParameterBook(market.multiplier,[near,far],timezone).block(index)
        rates = ParameterBook(market.margin_rate,[near,far],timezone).block(index)
        prices = daily.reindex(index=index,columns=[near,far]).to_numpy()
        held_value = np.where(positions != 0, positions*prices*multiples, 0.)
        if not np.isfinite(held_value).all():
            raise BacktestError("Missing actual price for held calendar pair leg")
        net = held_value-cashflows.cumsum().to_numpy()-fees.cumsum().to_numpy()
        margin = np.where(positions != 0,np.abs(positions)*prices*multiples*rates,0.).sum(axis=1)
        reconstructed.loc[:,[near,far]] += positions
        frames.append(pd.DataFrame(dict(timestamp=index,root=near[:2],pair_id=pair_id,future=near,hedge=far,
            future_lots=positions[:,0],hedge_units=positions[:,1],multiplier=multiples[:,0],hedge_multiplier=multiples[:,1],
            pair_type="calendar",hedge_quantity_unit="futures_lots",future_pnl=net[:,0],hedge_pnl=net[:,1],net_pnl=net.sum(axis=1),
            fees_cumulative=fees.cumsum().sum(axis=1).to_numpy(),allocated_actual_margin=margin,gross_pair_margin=margin,
            return_contribution=net.sum(axis=1)/initial_capital)))
    if not frames:
        if not np.allclose(account.equity.equity,initial_capital):
            raise BacktestError("No calendar pair explains non-flat equity")
        return pd.DataFrame(),pd.DataFrame()
    if not np.allclose(reconstructed,account.positions):
        raise BacktestError("Calendar pair inventories do not reconstruct actual holdings")
    detail = pd.concat(frames,ignore_index=True)
    grouped = detail.groupby("timestamp")
    if not np.allclose(grouped.net_pnl.sum().reindex(index),account.equity.equity-initial_capital,atol=max(1e-5,initial_capital*1e-11),rtol=1e-10):
        raise BacktestError("Calendar pair PnL does not reconcile to account equity")
    if not np.allclose(grouped.allocated_actual_margin.sum().reindex(index),account.equity.required_margin,atol=1e-5,rtol=1e-10):
        raise BacktestError("Calendar pair margins do not reconcile")
    return detail,detail.groupby("pair_id",sort=True).tail(1).reset_index(drop=True)
