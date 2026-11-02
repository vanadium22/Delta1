"""Frozen 60-session reverse-percentile study with actual-contract expiry hedges."""
import argparse
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .acquire_daily import audit_daily
from .analytics import attribute_legs
from .api import run_backtest
from .calendar import verified_days
from .hedging import index_hedges
from .io import write_json
from .models import BacktestConfig, BacktestError, DataConfig, check_cancelled, check_market_source, normalize_frame
from .strategy import FactorConfig, generate_strategy, hold_to_expiry_targets
from .strategy.factors import previous_windows
from .strategy.pipeline import _load_market


@dataclass(frozen=True)
class CarryStudyConfig:
    start: str = "2024-01-01"
    end: str = "2026-11-02"
    warmup_start: str = "2023-07-01"
    window_days: int = 60
    thresholds: tuple[float, ...] = (.9, .8)
    initial_capital: float = 10_000_000
    margin_rate: float = .15
    commission_rate: float = .0003
    max_capital_usage: float = .99
    min_annual_days: int = 5
    workers: int = 4
    allow_partial: bool = False
    allowed_tail_sessions: int = 1

    def __post_init__(self):
        if self.start > self.end or self.warmup_start >= self.start:
            raise BacktestError("Carry study needs warmup_start < start <= end")
        if not self.thresholds or any(not 0 < t < 1 for t in self.thresholds):
            raise BacktestError("Carry thresholds must lie strictly in (0, 1)")
        if self.window_days < 2 or not 0 < self.margin_rate <= 1 or self.initial_capital <= 0:
            raise BacktestError("Invalid carry window, margin or capital")


def _factor_table(result, config):
    annual, p = result.continuous_factors["annual_basis"], result.continuous_factors["basis_percentile"]
    windows, locations, _ = previous_windows(annual, config.window_days)
    counts = np.isfinite(windows).sum(axis=2)[locations]
    tables = []
    for j, alias in enumerate(result.panel.mapping):
        table = pd.DataFrame(dict(timestamp=annual.index, root=alias[:2], slot=alias,
            contract=result.panel.mapping[alias].to_numpy(), futures_close=result.panel.close[alias].to_numpy(),
            spot_close=result.panel.spot[alias].to_numpy(), days_to_expiry=result.panel.days_to_expiry[alias].to_numpy(),
            dividend_points=0.0, annual_basis_pct=annual[alias].to_numpy(), percentile=p[alias].to_numpy(),
            score=(2 * p[alias] - 1).to_numpy(), historical_samples=counts[:, j]))
        table["abs_score"] = table.score.abs()
        tables.append(table)
    return pd.concat(tables, ignore_index=True)


def _trades(account_name, account, market, signals, threshold, scope, initial_capital):
    orders = account.actual_orders
    records = []
    opens = orders.loc[orders.symbol.str.endswith(".CFE") & orders.action.str.startswith("open")]
    for symbol, entries in opens.groupby("symbol"):
        if len(entries) != 1:
            raise BacktestError("Hold-to-expiry study unexpectedly resized or re-entered a contract")
        entry = entries.iloc[0]
        future_orders = orders.loc[orders.symbol.eq(symbol)]
        spot_orders = orders.loc[orders.symbol.str.endswith("_spot") & orders.hedge_primary.eq(symbol)]
        hedge_entry = spot_orders.loc[spot_orders.execution_time.eq(entry.execution_time) & spot_orders.action.str.startswith("open")]
        if len(hedge_entry) != 1:
            raise BacktestError("Missing uniquely linked hedge entry")
        hedge_entry = hedge_entry.iloc[0]
        closed = future_orders.loc[future_orders.action.str.startswith("close")]
        exit_order = closed.iloc[-1] if len(closed) else None
        end = exit_order.execution_time if exit_order is not None else account.equity.index[-1]
        final_f = float(exit_order.price) if exit_order is not None else float(market.daily_close.at[end, symbol])
        hedge_exit = spot_orders.loc[spot_orders.execution_time.eq(end) & spot_orders.action.str.startswith("close")]
        final_s = float(hedge_exit.price.iloc[-1]) if len(hedge_exit) else float(market.daily_close.at[end, hedge_entry.symbol])
        decision = signals.decisions.loc[signals.decisions.action.eq("signal_open") & signals.decisions.symbol.eq(symbol)]
        decision = decision.loc[decision.signal_time.eq(entry.signal_time)].iloc[0]
        future_gross = entry.signed_quantity * entry.multiplier * (final_f - entry.price)
        spot_gross = hedge_entry.signed_quantity * (final_s - hedge_entry.price)
        future_fee, spot_fee = float(future_orders.fee.sum()), float(spot_orders.fee.sum())
        net = future_gross + spot_gross - future_fee - spot_fee
        records.append(dict(scope=scope, threshold=threshold, account=account_name, root=symbol[:2], contract=symbol,
            signal_time=entry.signal_time, entry_time=entry.execution_time, end_time=end,
            status="closed" if exit_order is not None else "open_marked_to_latest_close",
            exit_reason=exit_order.reason if exit_order is not None else None,
            percentile_signal=decision.percentile, score_signal=decision.score, slot_signal=decision.slot,
            futures_signed_lots=int(entry.signed_quantity), spot_signed_units=int(hedge_entry.signed_quantity),
            futures_open=float(entry.price), spot_open=float(hedge_entry.price), futures_end=final_f, spot_end=final_s,
            futures_gross_pnl=future_gross, spot_gross_pnl=spot_gross, futures_fees=future_fee, spot_fees=spot_fee,
            futures_net_pnl=future_gross-future_fee, spot_net_pnl=spot_gross-spot_fee, net_pnl=net,
            net_pnl_per_futures_lot=net/entry.quantity, return_on_account_capital=net/initial_capital))
    return records


def run_carry_study(*, data_config=None, market_data=None, config=None, output_dir, render=True,
                    cancel_event=None, progress=None):
    config = config or CarryStudyConfig()
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    factor_config = FactorConfig(roots=("IF", "IH", "IC", "IM"), window_days=config.window_days,
                                min_annual_days=config.min_annual_days, precision="1d", workers=config.workers)
    data = replace(data_config or DataConfig(), dividend_points_path=None, adjusted_close_path=None, dividend_policy="none")
    market = market_data if market_data is not None else _load_market(data, factor_config, cancel_event, progress)
    check_market_source(market.metadata)
    raw_daily = market.daily_close if market.daily_close is not None else market.close
    normalized = normalize_frame(raw_daily, label="carry daily close")
    daily = normalized.groupby(normalized.index.normalize()).tail(1)
    full_calendar = verified_days(config.warmup_start, config.end)
    first_requested = next((i for i, day in enumerate(full_calendar) if day >= config.start), None)
    if first_requested is None or first_requested < config.window_days:
        raise BacktestError("Not enough verified pre-start calendar sessions for the factor window")
    required_warmup = full_calendar[first_requested-config.window_days]
    requested_audit = audit_daily(daily, market.contracts, required_warmup, config.end)
    write_json(root / "requested_coverage.json", requested_audit)
    complete_start = not requested_audit["interior_gaps"]
    tail_ok = len(requested_audit["unavailable_tail"]) <= config.allowed_tail_sessions
    partial = not (complete_start and tail_ok)
    if partial and not config.allow_partial:
        write_json(root / "status.json", dict(status="data_incomplete", requested_start=config.start,
                   requested_end=config.end, price_first=str(daily.index.min().date()), price_last=str(daily.index.max().date()),
                   action="Acquire missing actual-contract/index daily data; no zero-price or synthetic backfill"))
        raise BacktestError(f"Requested {config.start}..{config.end} coverage is incomplete; audit saved at {root / 'requested_coverage.json'}")
    if partial:
        actual_start = max(config.start, str(daily.index.min().date()))
        actual_end = min(config.end, str(daily.index.max().date()))
        used_audit = audit_daily(daily, market.contracts, str(daily.index.min().date()), actual_end)
        if used_audit["interior_gaps"]:
            raise BacktestError("Available-data study still has internal quote/mapping gaps")
        actual_end = used_audit["effective_end"]
        calendar_begin = str(daily.index.min().date())
    else:
        actual_start, actual_end = config.start, requested_audit["effective_end"]
        calendar_begin = max(config.warmup_start, str(daily.index.min().date()))
    daily = daily.loc[daily.index <= pd.Timestamp(actual_end + " 23:59:59", tz="Asia/Shanghai")]
    # This study intentionally uses next-day DAILY close; no minute price is
    # read or labelled as a daily/opening execution.
    market = replace(market, close=daily, daily_close=daily, daily_fallback=None, adjusted_close=None,
                     margin_rate={r:config.margin_rate for r in ("IF", "IH", "IC", "IM")})
    zeros = pd.DataFrame(0.0, index=daily.index.normalize(), columns=daily.columns)
    factors = generate_strategy(market_data=market, dividend_points=zeros, factor_config=factor_config,
                                 calendar=verified_days(calendar_begin, actual_end), output_dir=root / "factors",
                                 cancel_event=cancel_event, progress=progress)
    factor_table = _factor_table(factors, config)
    factor_table.to_parquet(root / "factor_values.parquet", index=False)
    factor_table.to_csv(root / "factor_values.csv", index=False, encoding="utf-8-sig")
    daily.to_parquet(root / "input_daily_close.parquet")
    write_json(root / "input_reference.json", dict(contracts=[{**ref, "instrument_id":symbol} for symbol,ref in market.contracts.items()]))
    summaries, trades, daily_tables, decisions, runs = [], [], [], [], {}
    for threshold in config.thresholds:
        tag = str(threshold).replace(".", "_")
        for selection, mode in (("product_best", "product"), ("contract_independent", "contract_pair")):
            check_cancelled(cancel_event)
            signals = hold_to_expiry_targets(factors.factors["basis_percentile"], factors.panel.mapping, market.contracts,
                start=actual_start, end=actual_end, threshold=threshold, selection=selection, weight=config.max_capital_usage,
                cancel_event=cancel_event)
            run_config = BacktestConfig(initial_capital=config.initial_capital, commission_rate=config.commission_rate,
                max_capital_usage=config.max_capital_usage, minimum_margin_ratio=.0001, margin_call_basis="equity",
                mode=mode, precision="1d", workers=config.workers, d0=0,
                hedges=index_hedges(list(signals.targets.columns)), rebalance_on_change_only=True,
                start=actual_start, end=actual_end, liquidate_at_end=False)
            folder = root / f"{selection}_{tag}"
            result = run_backtest(signals.targets, market_data=market, config=run_config, output_dir=folder,
                                  cancel_event=cancel_event, progress=progress)
            write_json(folder / "job.local.json", dict(instructions_path=result.output_paths["instructions"],
                data=dict(daily_close_path=str(root / "input_daily_close.parquet"), reference_path=str(root / "input_reference.json"),
                          margin_rates={r:config.margin_rate for r in ("IF", "IH", "IC", "IM")}),
                backtest=asdict(run_config), output_dir=str(folder / "rerun")))
            signals.decisions.assign(scope=selection, threshold=threshold).to_parquet(folder / "decisions.parquet", index=False)
            decisions.append(signals.decisions.assign(scope=selection, threshold=threshold))
            for name, account in result.accounts.items():
                attributed, _ = attribute_legs(account, market, initial_capital=config.initial_capital)
                daily_tables.append(attributed.assign(scope=selection, threshold=threshold, account=name).reset_index())
                ledger = _trades(name, account, market, signals, threshold, selection, config.initial_capital)
                trades.extend(ledger)
                pnl = float(account.equity.equity.iloc[-1]-config.initial_capital)
                if not np.isclose(sum(t["net_pnl"] for t in ledger), pnl, atol=.001, rtol=1e-10):
                    raise BacktestError("Trade-level results do not reconcile to account equity")
                summaries.append(dict(scope=selection, threshold=threshold, account=name, root=name[:2],
                    initial_capital=config.initial_capital, start=str(account.equity.index[0].date()), end=str(account.equity.index[-1].date()),
                    net_pnl=pnl, total_return=pnl/config.initial_capital,
                    futures_pnl=float(attributed.futures_pnl.iloc[-1]), spot_pnl=float(attributed.spot_pnl.iloc[-1]),
                    max_drawdown=float(attributed.drawdown.min()), max_drawdown_cny=float(attributed.drawdown_cny.min()),
                    fees=float(account.equity.fees.sum()), entries=len(ledger), closed_trades=sum(t["status"]=="closed" for t in ledger),
                    open_trades=sum(t["status"]!="closed" for t in ledger), actual_orders=len(account.actual_orders),
                    expiry_closes=account.summary["expiry_closes"], status=account.summary["status"]))
            runs[(selection, threshold)] = result
    summary = pd.DataFrame(summaries)
    trades = pd.DataFrame(trades)
    curves = pd.concat(daily_tables, ignore_index=True)
    decisions = pd.concat(decisions, ignore_index=True)
    for name, frame in (("summary", summary), ("trades", trades), ("daily_attribution", curves), ("decisions", decisions)):
        frame.to_parquet(root / f"{name}.parquet", index=False)
        if name != "daily_attribution":
            frame.to_csv(root / f"{name}.csv", index=False, encoding="utf-8-sig")
    metadata = dict(config=asdict(config), actual_start=actual_start, actual_end=actual_end,
        requested_period_verified=not partial and not requested_audit["unavailable_tail"],
        coverage_status="available_data_only" if partial else "latest_published" if requested_audit["unavailable_tail"] else "complete",
        tail_pending=requested_audit["unavailable_tail"],
        dividend_policy="D=0 explicitly requested; no dividends in factors, PnL, or spot cashflows",
        spot_model="synthetic fully-funded index units; IF/IH 300 units, IC/IM 200 units opposite each future lot",
        selection="greatest abs(2*p-1) across today's four slots when flat; reverse; hold actual lots until expiry",
        execution="signal at close; first later jointly valid DAILY close; both legs close at expiry close",
        margin_assumption="explicit fixed rate, not actual historical account margin",
        capital="one initial_capital per product or independent contract account; independent accounts are not a shared portfolio",
        attribution="each leg uses the actual pair lots and charges its own notional commissions",
        market=market.metadata, warnings=["DATA LIMITED: requested period is not fully covered"] if partial else [],
        output_dir=str(root), run_directories={f"{s}:{t}":v.output_paths["output_dir"] for (s,t),v in runs.items()})
    write_json(root / "study.json", metadata)
    if render:
        from .carry_report import render_carry_report
        render_carry_report(root, summary, trades, curves, factor_table, decisions, metadata)
    return dict(metadata=metadata, summary=summary, trades=trades, curves=curves, factors=factor_table, runs=runs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args(argv)
    from .__main__ import load_job
    job = load_job(args.config)
    options = dict(job.get("study", {}))
    if args.allow_partial:
        options["allow_partial"] = True
    try:
        result = run_carry_study(data_config=DataConfig(**job["data"]), config=CarryStudyConfig(**options),
                                 output_dir=args.output, render=not args.no_render)
        print(result["summary"].query("scope == 'product_best'").to_string(index=False))
        print(str(args.output.resolve()))
        return 0
    except BacktestError as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
