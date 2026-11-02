"""Annualized carry, rolling conditional quantiles and per-contract pair books."""
import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .analytics import performance_metrics
from .api import run_backtest
from .calendar import verified_days
from .configuration import factor_spec
from .io import frame_fingerprint, write_json
from .models import BacktestConfig, BacktestError, DataConfig, check_market_source
from .pair_analytics import attribute_calendar_pairs, attribute_index_pairs
from .strategy import load_factors
from .strategy.mapping import slot_mapping
from .strategy.pipeline import _load_market
from .workflow import cta_stage, factor_stage


LABELS = {"best":"年化基差·四档择优", "history_pairs":"年化基差·各合约pair",
          "quantile_pairs":"期限结构分位回归·各pair", "calendar":"年化跨期01−03"}


def _audit(daily, contracts, roots, *, synthetic=False):
    first,last=str(daily.index[0].date()),str(daily.index[-1].date())
    days=list(daily.index.strftime("%Y-%m-%d")) if synthetic else verified_days(first,last)
    index=pd.DatetimeIndex(days,tz="Asia/Shanghai")+pd.Timedelta(hours=15)
    mapping,gaps=slot_mapping(index,contracts,roots)
    missing=[]
    aligned=daily.reindex(index)
    for stamp in index:
        symbols=mapping.loc[stamp].dropna().tolist()
        required=[root+"_spot" for root in roots]+symbols
        absent=[s for s in required if s not in aligned or not np.isfinite(aligned.at[stamp,s]) or aligned.at[stamp,s]<=0]
        if absent or len(symbols)!=4*len(roots):
            missing.append(dict(date=str(stamp.date()),missing=absent,mapping_count=len(symbols)))
    return days,dict(start=first,end=last,expected_dates=len(days),observed_dates=len(daily),missing=missing,
                     mapping_gaps=gaps,synthetic=synthetic,status="complete" if not missing and len(days)==len(daily) else "incomplete")


def _view(factors, name, declarations):
    return replace(factors,metadata={**factors.metadata,"factor_name":name,"factor":declarations[name]})


def run_structure_study(job, output_dir, *, thresholds=(.9,.8), capital_sensitivity=(), factor_artifact=None,
                        synthetic=False, render=True, progress=None):
    out=Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True,exist_ok=False)
    spec=factor_spec(job)
    if spec.name!="term_structure_percentile":
        raise BacktestError("Structure study requires factor.name=term_structure_percentile")
    if not thresholds or any(not 0<t<1 for t in thresholds):
        raise BacktestError("Structure study thresholds must lie in (0,1)")
    data=DataConfig(**job.get("data",{}))
    is_synthetic="synthetic" in data.source_id
    if is_synthetic!=synthetic:
        raise BacktestError("Synthetic input must be explicitly marked with --synthetic; real studies cannot use that mode")
    base=BacktestConfig(**job.get("backtest",{}))
    if base.mode!="product" or base.precision!="1d" or base.weight_mode!="neutral_units" or base.d0!=0 or not base.rebalance_on_change_only:
        raise BacktestError("Structure study requires product accounts, daily execution, neutral_units, d0=0 and rebalance_on_change_only")
    if progress:
        progress("读取明确配置的本地日线和冻结版本")
    market=_load_market(data,spec.runtime(),None,None)
    check_market_source(market.metadata)
    daily=market.daily_close if market.daily_close is not None else market.close
    days,audit=_audit(daily,market.contracts,spec.roots,synthetic=synthetic)
    write_json(out/"coverage.local.json",audit)
    if audit["status"]!="complete":
        raise BacktestError("Available source interval has price/calendar/mapping gaps; see coverage.local.json")
    window=spec.parameters["window_days"]
    if len(days)<=window+1:
        raise BacktestError("Not enough dates after the declared warmup")
    start,end=days[window],days[-1]
    if base.start and str(base.start)[:10]>start:
        start=str(base.start)[:10]
    if base.end and str(base.end)[:10]<end:
        end=str(base.end)[:10]
    if start>end:
        raise BacktestError("No study dates remain after warmup/start/end")
    options={**asdict(base),"start":start,"end":end,"hedges":()}
    declarations={"term_structure_percentile":asdict(spec),
        "basis_percentile":dict(name="basis_percentile",roots=spec.roots,slots=spec.slots,precision="1d",workers=spec.workers,
            parameters=dict(window_days=window,min_samples=2,min_annual_days=spec.parameters["min_annual_days"])),
        "annual_calendar_spread_percentile":dict(name="annual_calendar_spread_percentile",roots=spec.roots,slots=spec.slots,
            precision="1d",workers=spec.workers,parameters=dict(window_days=window,min_samples=2,min_gap_days=1,price_base="near"))}
    if factor_artifact:
        factors=load_factors(factor_artifact)
        if factors.metadata.get("factor_declarations")!=declarations:
            # JSON round trips turn tuples into lists; compare canonical JSON instead.
            import json
            if json.dumps(factors.metadata.get("factor_declarations"),sort_keys=True)!=json.dumps(declarations,sort_keys=True):
                raise BacktestError("Saved factor declarations do not match this study")
        old=factors.metadata.get("market",{}).get("datasets",[])
        if [(d["root"],d["version"]) for d in old] != [(d["root"],d["version"]) for d in market.metadata.get("datasets",[])]:
            raise BacktestError("Saved factors and current execution dataset versions differ")
        if factors.metadata.get("dividend_mode")!=data.dividend_mode:
            raise BacktestError("Saved factors and current dividend assumption differ")
        used=market.metadata.get("files",{})
        for name,entry in factors.metadata.get("market",{}).get("files",{}).items():
            if name in {"margin_rate_path","multiplier_path","dashboard_config_path"}:
                continue
            if entry.get("sha256") and entry["sha256"]!=used.get(name,{}).get("sha256"):
                raise BacktestError(f"Saved factor input differs from execution input: {name}")
    else:
        if progress:
            progress("逐品种仅用前序日期拟合期限结构条件分位回归")
        factors=factor_stage(job,market_data=market)
        factors.metadata=deepcopy(factors.metadata)
        for name in ("basis_percentile","annual_calendar_spread_percentile"):
            calculated=factor_stage(dict(data=asdict(data),factor=declarations[name]),market_data=market)
            for key,value in calculated.factors.items():
                if key in factors.factors:
                    pd.testing.assert_frame_equal(factors.factors[key],value)
                factors.factors[key]=value
                factors.continuous_factors[key]=calculated.continuous_factors[key]
            factors.metadata["quality"].update(calculated.metadata["quality"])
            factors.metadata["factor_units"].update(calculated.metadata["factor_units"])
        factors.metadata["factor_declarations"]=declarations
        factors.metadata["factor_fingerprints"]={k:frame_fingerprint(v) for k,v in factors.continuous_factors.items()}
        factors.save(out/"factors")
        factors=load_factors(out/"factors")
    for name in declarations:
        if not factors.continuous_factors[name].notna().any().any():
            raise BacktestError(f"No valid observations for {name}; inspect factor diagnostics")
    fingerprints={k:frame_fingerprint(v) for k,v in factors.continuous_factors.items()}
    cases=[]
    for threshold in thresholds:
        for family,name,cta_name,weight in (("best","basis_percentile","expiry_index",.495),
            ("history_pairs","basis_percentile","expiry_index_structure",.12375),
            ("quantile_pairs","term_structure_percentile","expiry_index_structure",.12375),
            ("calendar","annual_calendar_spread_percentile","expiry_spread",.495)):
            cases.append((family,name,cta_name,weight,threshold,base.initial_capital,False))
        for capital in capital_sensitivity:
            if not np.isfinite(capital) or capital<=0:
                raise BacktestError("Capital sensitivity must be positive")
            for family,name in (("history_pairs","basis_percentile"),("quantile_pairs","term_structure_percentile")):
                cases.append((family,name,"expiry_index_structure",.12375,threshold,float(capital),True))
    records,products,curves,pair_details,pair_summaries,results,audits=[],[],{},{},{},{},[]
    for family,name,cta_name,weight,threshold,capital,sensitivity in cases:
        key=f"{family}_{str(threshold).replace('.','_')}"+(f"_capital_{int(capital)}" if sensitivity else "")
        folder=out/key
        folder.mkdir()
        if progress:
            progress(f"回测 {key}，每品种资金 {capital:,.0f} 元")
        params=dict(threshold=threshold,position_weight=weight,direction=-1,transform="center_percentile")
        if cta_name=="expiry_index":
            params.update(selection="product_best",slots=spec.slots)
        elif cta_name=="expiry_index_structure":
            params.update(slots=spec.slots)
        cta=dict(name=cta_name,input_factor=name,parameters=params)
        execution={**options,"initial_capital":capital,"preserve_pair_lots":cta_name=="expiry_index_structure"}
        case_job=dict(data=asdict(data),factor=declarations[name],cta=cta,backtest=execution)
        signals=cta_stage(_view(factors,name,declarations),case_job,output_dir=folder/"cta")
        assert signals.metadata["factor_fingerprint"]==fingerprints[name]
        for field,value in signals.metadata["required_backtest_options"].items():
            if execution[field]!=value:
                raise BacktestError(f"Execution mismatch {field}")
        result=run_backtest(signals.targets,market_data=market,config=BacktestConfig(**execution))
        result.metadata.update(cta_stage=signals.metadata,data_config=asdict(data),study_case=key)
        result.save(folder/"backtest")
        write_json(folder/"job.local.json",dict(case_job,instructions_path=signals.output_paths["targets"]))
        account_curves,pairs,latest=[],[],[]
        for root,account in result.accounts.items():
            metrics=performance_metrics(account.equity.equity,capital)
            products.append(dict(case=key,root=root,family=family,threshold=threshold,sensitivity=sensitivity,
                **metrics,fees=float(account.equity.fees.sum()),orders=len(account.actual_orders),status=account.summary["status"],
                average_margin_usage=float(account.equity.margin_usage.mean())))
            account_curves.append(account.equity.equity.rename(root))
            method=attribute_calendar_pairs if family=="calendar" else attribute_index_pairs
            detail,summary=method(account,market,initial_capital=capital)
            if len(detail):
                pairs.append(detail)
                latest.append(summary)
            audits.append(dict(case=key,root=root,pair_pnl_margin_fee_reconciled=True,status=account.summary["status"]))
        equity=pd.concat(account_curves,axis=1)
        if equity.isna().any().any():
            raise BacktestError("Accounts with different stopped intervals require explicit aggregation policy")
        total=equity.sum(axis=1)
        metrics=performance_metrics(total,capital*len(result.accounts))
        records.append(dict(case=key,family=family,label=LABELS[family],factor=name,threshold=threshold,sensitivity=sensitivity,
            capital_per_product=capital,**metrics,total_fees=float(result.actual_orders.fee.sum()),actual_orders=len(result.actual_orders),
            average_margin_usage=float(sum(a.equity.required_margin for a in result.accounts.values()).div(total).mean())))
        pair_details[key]=pd.concat(pairs,ignore_index=True) if pairs else pd.DataFrame()
        pair_summaries[key]=pd.concat(latest,ignore_index=True) if latest else pd.DataFrame()
        if len(pair_details[key]):
            pair_details[key].to_parquet(folder/"pairs_daily.parquet",index=False)
            pair_summaries[key].to_csv(folder/"pairs_summary.csv",index=False,encoding="utf-8-sig")
        curves[key]=equity
        results[key]=result
        total.to_frame("equity").to_parquet(folder/"total_equity.parquet")
        annual="不适用" if metrics["annualized_return"] is None else f"{100*metrics['annualized_return']:+.4f}%"
        print(f"{key}: 年化 {annual}，区间 {100*metrics['total_return']:+.4f}%",flush=True)
    assert fingerprints=={k:frame_fingerprint(v) for k,v in factors.continuous_factors.items()}
    summary=pd.DataFrame(records)
    by_product=pd.DataFrame(products)
    summary.to_csv(out/"summary.csv",index=False,encoding="utf-8-sig")
    by_product.to_csv(out/"by_product.csv",index=False,encoding="utf-8-sig")
    protocol=dict(source="synthetic" if synthetic else "pure local frozen registered history",data=asdict(data),datasets=market.metadata.get("datasets",[]),
        price_start=days[0],price_end=days[-1],evaluation_start=start,evaluation_end=end,warmup_sessions=window,
        annual_spot="100*(F-S+D)/S*365/T",annual_calendar="100*(F01-F03+D01-D03)/F01*365/(T03-T01)",
        quantile_regression=asdict(spec),training="previous dates only; current date excluded",thresholds=thresholds,
        capital_per_product=base.initial_capital,capital_sensitivity=capital_sensitivity,
        execution=options,index_netting="physical index units and costs netted; virtual pair fees allocated from actual fees only",
        all_factor_cells_unchanged=True,full_2024_to_present=False,ddb="paused; no acquisition",vpn="untouched",audits=audits,
        factor_artifact=factors.output_paths["output_dir"],method_sources=[
            "https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs-ds.html",
            "https://www.statsmodels.org/stable/generated/statsmodels.regression.quantile_regression.QuantReg.html"])
    write_json(out/"study.local.json",protocol)
    if render:
        from .structure_report import render_structure_report
        render_structure_report(out,summary,by_product,curves,pair_details,pair_summaries,results,factors,protocol)
    return dict(output_dir=str(out),summary=summary,by_product=by_product,protocol=protocol)


def main(argv=None):
    from .__main__ import load_job
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--thresholds",type=float,nargs="+",default=[.9,.8])
    parser.add_argument("--capital-sensitivity",type=float,nargs="*",default=[])
    parser.add_argument("--factor-artifact",type=Path)
    parser.add_argument("--synthetic",action="store_true")
    parser.add_argument("--no-render",action="store_true",help="save complete numerical results; render separately without recomputing factors")
    args=parser.parse_args(argv)
    result=run_structure_study(load_job(args.config),args.output,thresholds=tuple(args.thresholds),
        capital_sensitivity=tuple(args.capital_sensitivity),factor_artifact=args.factor_artifact,synthetic=args.synthetic,
        render=not args.no_render,progress=lambda s:print(s,flush=True))
    print(result["output_dir"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
