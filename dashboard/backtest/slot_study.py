"""Sixteen independent fixed-slot future/index accounts and four calendar accounts."""
import argparse
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .analytics import performance_metrics
from .api import run_backtest
from .configuration import factor_spec
from .io import frame_fingerprint, write_json
from .models import BacktestConfig, BacktestError, DataConfig
from .pair_analytics import attribute_calendar_pairs, attribute_index_pairs
from .strategy import load_factors
from .strategy.annual_calendar import annual_calendar_percentile
from .strategy.factors import basis_percentile
from .strategy.mapping import to_actual
from .strategy.pipeline import _load_market
from .structure_study import _audit
from .workflow import cta_stage, factor_stage


def _factors(job,market,output):
    spec=factor_spec(job)
    if spec.name!="term_structure_percentile" or set(spec.slots)!={0,1,2,3}:
        raise BacktestError("Independent-slot study requires all four term-structure factor slots")
    factors=factor_stage(job,market_data=market)
    config=spec.runtime()
    history=basis_percentile(factors.panel,factors.continuous_factors["annual_basis"],config)
    annual,calendar=annual_calendar_percentile(factors.panel,config,dict(window_days=config.window_days,min_samples=2,min_gap_days=1,price_base="near"))
    for name,value,unit in (("basis_percentile",history,"0_to_1"),("annual_calendar_spread",annual,"percentage_points"),
                            ("annual_calendar_spread_percentile",calendar,"0_to_1")):
        factors.continuous_factors[name]=value
        factors.factors[name]=to_actual(value,factors.panel.mapping)
        factors.metadata["factor_units"][name]=unit
        factors.metadata["quality"][name]=dict(valid_cells=int(value.notna().sum().sum()),total_cells=value.size)
    common=dict(roots=spec.roots,slots=spec.slots,precision="1d",workers=spec.workers)
    factors.metadata["factor_declarations"]={"term_structure_percentile":asdict(spec),
        "basis_percentile":dict(name="basis_percentile",**common,parameters=dict(window_days=config.window_days,min_samples=2,min_annual_days=config.min_annual_days)),
        "annual_calendar_spread_percentile":dict(name="annual_calendar_spread_percentile",**common,
            parameters=dict(window_days=config.window_days,min_samples=2,min_gap_days=1,price_base="near"))}
    factors.metadata["factor_fingerprints"]={k:frame_fingerprint(v) for k,v in factors.continuous_factors.items()}
    factors.save(output)
    return load_factors(output)


def run_slot_study(job,output,*,thresholds=(.9,.8),render=True,progress=None):
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    config=BacktestConfig(**job["backtest"])
    if config.mode!="product" or config.weight_mode!="neutral_units" or config.precision!="1d" or config.d0!=0 or not config.rebalance_on_change_only:
        raise BacktestError("Slot study requires independent product accounts, daily neutral_units, d0=0 and on-change execution")
    spec=factor_spec(job)
    if not thresholds or any(not 0<t<1 for t in thresholds):
        raise BacktestError("Thresholds must lie in (0,1)")
    data=DataConfig(**job["data"])
    if progress:
        progress("读取本地冻结快照；研究及回测不再访问 Z")
    market=_load_market(data,spec.runtime(),None,None)
    daily=market.daily_close if market.daily_close is not None else market.close
    days,audit=_audit(daily,market.contracts,spec.roots,synthetic="synthetic" in data.source_id)
    write_json(out/"coverage.local.json",audit)
    if audit["status"]!="complete":
        raise BacktestError("Local snapshot lacks a complete dated four-slot panel")
    warm=spec.parameters["window_days"]
    requested=str(config.start or "2024-01-01")[:10]
    eligible=[d for d in days[warm:] if d>=requested and (not config.end or d<=str(config.end)[:10])]
    if not eligible:
        raise BacktestError("No evaluation dates after the complete warmup")
    start,end=eligible[0],eligible[-1]
    if requested<=days[warm-1]:
        raise BacktestError("Requested start has insufficient preceding warmup; import earlier data")
    if progress:
        progress("一次计算并保存三类原始因子；随后各组仅复用")
    factors=_factors(job,market,out/"factors")
    base_cta=job.get("cta",{}).get("parameters",{})
    cta_parameters=dict(position_weight=base_cta.get("position_weight",.495),direction=base_cta.get("direction",-1),
                        transform=base_cta.get("transform","center_percentile"))
    before={k:frame_fingerprint(v) for k,v in factors.continuous_factors.items()}
    metrics,pair_summaries,all_curves,audits=[],[],{},[]
    cases=[]
    for threshold in thresholds:
        for method,name in (("history","basis_percentile"),("regression","term_structure_percentile")):
            for slot in range(4):
                cases.append((method,name,slot,threshold))
        cases.append(("calendar","annual_calendar_spread_percentile",None,threshold))
    for method,name,slot,threshold in cases:
        key=f"{method}"+(f"_slot{slot:02d}" if slot is not None else "")+"_"+str(threshold).replace(".","_")
        folder=out/key
        folder.mkdir()
        execution={**asdict(config),"start":start,"end":end,"hedges":(),"preserve_pair_lots":False}
        params=dict(threshold=threshold,**cta_parameters)
        cta=dict(name="expiry_spread" if method=="calendar" else "expiry_index",input_factor=name,parameters=params)
        if slot is not None:
            params.update(selection="product_best",slots=[slot])
        case_job=dict(data=asdict(data),factor=factors.metadata["factor_declarations"][name],cta=cta,backtest=execution)
        signals=cta_stage(factors,case_job,output_dir=folder/"cta")
        if progress:
            progress(f"{key}：每组独立本金 {config.initial_capital:,.0f}，不与其他档位净额结算")
        result=run_backtest(signals.targets,market_data=market,config=BacktestConfig(**execution))
        result.metadata.update(cta_stage=signals.metadata,data_config=asdict(data),study_case=key,
            account_layout="one fixed entry slot per account; lock actual contract to expiry; no cross-slot cash/index netting")
        result.save(folder/"backtest")
        write_json(folder/"job.local.json",dict(case_job,instructions_path=signals.output_paths["targets"]))
        details=[]
        curve_key=method+"_"+str(threshold).replace(".","_")
        account_curves=all_curves.setdefault(curve_key,{})
        for root,account in result.accounts.items():
            group=root+(f"{slot:02d}" if slot is not None else "_01_03")
            futures=account.positions.filter(regex=r"\.CFE$")
            limit=2 if method=="calendar" else 1
            if futures.ne(0).sum(axis=1).gt(limit).any():
                raise BacktestError("Independent account held more than its single permitted pair")
            changed=futures.ne(0)&futures.shift().notna()&futures.shift().ne(0)&futures.ne(futures.shift())
            if changed.any().any():
                raise BacktestError("Held actual lots changed before exit")
            method_fn=attribute_calendar_pairs if method=="calendar" else attribute_index_pairs
            detail,summary=method_fn(account,market,initial_capital=config.initial_capital)
            if len(detail):
                detail=detail.assign(group_id=group,method=method,threshold=threshold,slot=slot,case=key)
                details.append(detail)
                fees=account.actual_orders.groupby("symbol").fee.sum()
                summary=summary.assign(group_id=group,method=method,threshold=threshold,slot=slot,case=key)
                summary["future_fees"]=summary.future.map(fees).fillna(0.)
                summary["hedge_fees"]=summary.fees_cumulative-summary.future_fees
                summary["future_gross_pnl"]=summary.future_pnl+summary.future_fees
                summary["hedge_gross_pnl"]=summary.hedge_pnl+summary.hedge_fees
                pair_summaries.append(summary)
            result_metrics=performance_metrics(account.equity.equity,config.initial_capital)
            metrics.append(dict(case=key,group_id=group,root=root,slot=slot,method=method,threshold=threshold,**result_metrics,
                fees=float(account.equity.fees.sum()),orders=len(account.actual_orders),status=account.summary["status"],
                future_pnl=float(summary.future_pnl.sum()) if len(summary) else 0.,hedge_pnl=float(summary.hedge_pnl.sum()) if len(summary) else 0.,
                average_margin_usage=float(account.equity.margin_usage.mean())))
            account_curves[group]=account.equity.equity
            audits.append(dict(case=key,group_id=group,single_pair=True,fixed_lots=True,pnl_margin_fee_reconciled=True,status=account.summary["status"]))
        if details:
            pd.concat(details,ignore_index=True).to_parquet(folder/"pairs_daily.parquet",index=False)
    assert before=={k:frame_fingerprint(v) for k,v in factors.continuous_factors.items()}
    results=pd.DataFrame(metrics)
    pairs=pd.concat(pair_summaries,ignore_index=True) if pair_summaries else pd.DataFrame()
    results.to_csv(out/"account_metrics.csv",index=False,encoding="utf-8-sig")
    pairs.to_csv(out/"actual_pair_legs.csv",index=False,encoding="utf-8-sig")
    for key,value in all_curves.items():
        pd.concat(value,axis=1).sort_index(axis=1).to_parquet(out/(key+"_equity.parquet"))
    protocol=dict(schema_version="fixed_slot_study_v1",data=asdict(data),requested_start=requested,evaluation_start=start,evaluation_end=end,
        price_start=days[0],price_end=days[-1],warmup_sessions=warm,capital_per_account=config.initial_capital,
        index_accounts=4*len(spec.roots),calendar_accounts=len(spec.roots),index_total_capital=4*len(spec.roots)*config.initial_capital,
        calendar_total_capital=len(spec.roots)*config.initial_capital,
        thresholds=list(thresholds),threshold_semantics="abs(2*p-1)>threshold; .9/.8 => 5%/10% tails",
        cta_parameters=cta_parameters,
        holding="each root x fixed entry slot independently selects only that slot while flat; lock actual code until its expiry; then look again in original slot",
        accounting="independent cash, futures and index legs per slot account; no cross-account index netting; each account charged its own actual fees",
        calendar="one 01-minus-03 pair per root; annualize by actual T03-T01; both legs close on first expiry",
        factor_declarations=factors.metadata["factor_declarations"],factor_cells_unchanged=True,full_requested_start=start[:4]==requested[:4],
        execution=dict(config=asdict(config),dividends="explicit D=0",price="next trading day actual daily close",ddb="paused",vpn="untouched"),
        cases=[k["case"] for k in metrics[::len(spec.roots)]],audits=audits)
    write_json(out/"study.local.json",protocol)
    if render:
        from .slot_report import render_slot_report
        render_slot_report(out)
    return dict(output_dir=str(out),metrics=results,protocol=protocol)


def main(argv=None):
    from .__main__ import load_job
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--thresholds",type=float,nargs="+",default=[.9,.8])
    parser.add_argument("--no-render",action="store_true")
    args=parser.parse_args(argv)
    result=run_slot_study(load_job(args.config),args.output,thresholds=tuple(args.thresholds),render=not args.no_render,progress=lambda s:print(s,flush=True))
    print(result["output_dir"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
