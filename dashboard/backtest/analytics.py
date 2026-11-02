"""Daily leg attribution reconciled to account equity, including actual fill prices."""
import numpy as np
import pandas as pd

from .engine import ParameterBook
from .models import BacktestError, normalize_frame
from .timeline import daily_marks


def performance_metrics(equity, initial_capital):
    """Actual calendar-time CAGR; interval PnL/return and realized path drawdown."""
    if equity.empty or not equity.index.is_monotonic_increasing or initial_capital <= 0:
        raise BacktestError("Performance metrics require ordered equity and positive initial capital")
    values = equity.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise BacktestError("Performance metrics cannot fill missing equity")
    elapsed = (equity.index[-1] - equity.index[0]).total_seconds() / 86400
    ratio = float(values[-1] / initial_capital)
    annual = float(np.expm1(np.log(ratio) * 365 / elapsed)) if ratio > 0 and elapsed > 0 else (-1. if ratio == 0 and elapsed > 0 else None)
    peaks = np.maximum.accumulate(np.r_[initial_capital, values])[1:]
    return dict(initial_capital=float(initial_capital), final_equity=float(values[-1]), net_pnl=float(values[-1]-initial_capital),
                total_return=ratio-1, annualized_return=annual, elapsed_calendar_days=float(elapsed),
                annualization="compound 365 / actual elapsed calendar days", max_drawdown=float((values/peaks-1).min()),
                max_drawdown_cny=float((values-peaks).min()))


def attribute_legs(account, market, *, initial_capital, timezone="Asia/Shanghai"):
    index, symbols = account.equity.index, list(account.positions.columns)
    source = market.daily_close if market.daily_close is not None else market.close
    source = normalize_frame(source, label="attribution close", timezone=timezone)
    close = daily_marks(source).reindex(index=index, columns=symbols)
    book = ParameterBook(market.multiplier, symbols, timezone)
    multiples = book.block(index)
    positions = account.positions.reindex(index=index, columns=symbols).to_numpy()
    market_value = np.where(positions != 0, positions * close.to_numpy() * multiples, 0.0)
    if not np.isfinite(market_value).all():
        raise BacktestError("Cannot attribute a held leg without its actual daily close")
    cashflows = pd.DataFrame(0.0, index=index.normalize(), columns=symbols)
    fees = cashflows.copy()
    orders = account.actual_orders.copy()
    if len(orders):
        orders["day"] = orders.execution_time.dt.normalize()
        orders["signed_notional"] = orders.signed_quantity * orders.price * orders.multiplier
        for field, output in (("signed_notional", cashflows), ("fee", fees)):
            daily = orders.groupby(["day", "symbol"])[field].sum().unstack(fill_value=0)
            output.loc[:, :] = daily.reindex(index=output.index, columns=symbols, fill_value=0).to_numpy()
    net = pd.DataFrame(market_value - cashflows.cumsum().to_numpy() - fees.cumsum().to_numpy(), index=index, columns=symbols)
    future_cols = [s for s in symbols if s.endswith(".CFE")]
    spot_cols = [s for s in symbols if s.endswith("_spot")]
    result = pd.DataFrame(dict(futures_pnl=net[future_cols].sum(axis=1), spot_pnl=net[spot_cols].sum(axis=1)), index=index)
    result["net_pnl"] = result.futures_pnl + result.spot_pnl
    expected = account.equity.equity - initial_capital
    if not np.allclose(result.net_pnl, expected, atol=max(1e-5, initial_capital * 1e-11), rtol=1e-10):
        raise BacktestError("Leg attribution does not reconcile to account equity")
    result["equity"] = account.equity.equity
    peaks = np.maximum.accumulate(np.r_[initial_capital, result.equity.to_numpy()])[1:]
    result["drawdown"] = result.equity / peaks - 1
    result["drawdown_cny"] = result.equity - peaks
    result["fees_cumulative"] = account.equity.fees.cumsum()
    return result, net
