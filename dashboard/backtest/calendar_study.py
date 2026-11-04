"""Independent calendar reversal matrices, using the original three workflow stages."""
import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .calendar_analytics import drawdown_episodes, round_trips
from .configuration import CTASpec, factor_spec
from .factor_cache import validate_factor_artifact
from .io import frame_fingerprint, write_json
from .models import BacktestConfig, BacktestError, DataConfig
from .strategy import load_factors
from .strategy.calendar_pairs import calendar_pair_factors
from .strategy.models import ContinuousPanel
from .workflow import backtest_stage, cta_stage, factor_stage


def fingerprints(factors):
    return {group+"/"+name:frame_fingerprint(value) for group, frames in
        (("continuous",factors.continuous_factors),("actual",factors.factors),("diagnostics",factors.diagnostics))
        for name,value in frames.items()}


def _hashes(paths):
    return {str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(set(map(str,paths)))}


def _coverage(factors, config, window):
    index=factors.panel.close.index
    common=pd.Series(True,index=index)
    rows=[]
    channels=factors.metadata["method"]["channels"]
    for root in sorted({s[:2] for s in factors.panel.mapping}):
        for channel in channels:
            near,far=(root+s+".CFE" for s in channel.split("-"))
            valid=factors.panel.close[[near,far]].gt(0).all(axis=1) & factors.panel.days_to_expiry[[near,far]].ge(0).all(axis=1)
            valid &= factors.panel.days_to_expiry[far].gt(factors.panel.days_to_expiry[near])
            common &= valid
            last=index[valid][-1] if valid.any() else None
            rows.append(dict(root=root,channel=channel,last_common_quote=str(last.date()) if last is not None else None,
                             valid_sessions=int(valid.sum()),missing_sessions=int((~valid).sum())))
    if not common.any():
        raise BacktestError("No common futures-pair coverage")
    end=index[common][-1]
    if config.end:
        end=min(end,pd.Timestamp(str(config.end)[:10],tz="Asia/Shanghai")+pd.Timedelta(hours=23,minutes=59))
    start=pd.Timestamp(str(config.start or "2024-01-01")[:10],tz="Asia/Shanghai")
    eligible=index[(index>=start)&(index<=end)]
    if eligible.empty or (index<eligible[0]).sum()<window:
        raise BacktestError("Requested evaluation start lacks its complete prior warmup")
    aliases=[root+channel[:2]+".CFE" for root in sorted({s[:2] for s in factors.panel.mapping}) for channel in channels]
    active=factors.continuous_factors["calendar_pair_percentile"].loc[eligible,aliases]
    if active.isna().any().any():
        raise BacktestError("Evaluation has missing calendar factors/quotes; inspect data rather than fill or shorten history")
    return str(eligible[0].date()),str(eligible[-1].date()),dict(price_start=str(index[0].date()),
        snapshot_end=str(index[-1].date()),common_pair_end=str(index[common][-1].date()),
        requested_start=str(start.date()),warmup_sessions=int((index<eligible[0]).sum()),window_days=window,pairs=rows,
        scope="futures legs only; no spot coverage dependency",end_policy=f"last simultaneous valid observation across all {len(rows)} root/channel pairs")


def verify_prefixes(factors):
    panel=factors.panel
    checks=[]
    for stop in sorted({max(3,int(len(panel.close)*f)) for f in (.4,.7,.9)}):
        sliced={k:getattr(panel,k).iloc[:stop] for k in ("close","spot","dividend_points","days_to_expiry","mapping")}
        prefix=ContinuousPanel(**sliced)
        values,diagnostics,_=calendar_pair_factors(prefix,factors.contracts,factors.metadata["method"]["window_days"],
                                                  channels=factors.metadata["method"]["channels"])
        for key,value in values.items():
            pd.testing.assert_frame_equal(value,factors.continuous_factors[key].iloc[:stop])
        expected=factors.diagnostics["calendar_pairs"]
        expected=expected.loc[expected.timestamp<=panel.close.index[stop-1]].reset_index(drop=True)
        pd.testing.assert_frame_equal(diagnostics["calendar_pairs"],expected)
        checks.append(dict(through=str(panel.close.index[stop-1]),rows=len(expected),equal=True))
    table=factors.diagnostics["calendar_pairs"]
    dated=table.loc[table.history_end.notna()]
    if not (dated.history_end.dt.normalize()<dated.timestamp.dt.normalize()).all():
        raise BacktestError("Calendar factor history includes current or future day")
    return checks


def run_calendar_study(job, output, *, verify=True, render=True, progress=print,
                       q_opens=(.8,.9), exit_rules=("expiry","close0.6","close0.4")):
    spec=factor_spec(job)
    if spec.name!="calendar_pair_percentile" or set(spec.roots)!={"IF","IH","IC","IM"}:
        raise BacktestError("Calendar study requires calendar_pair_percentile for IF/IH/IC/IM")
    channels=spec.parameters["channels"]
    exits={"expiry":("expiry",.6),"close0.6":("threshold",.6),"close0.4":("threshold",.4)}
    if not q_opens or len(set(q_opens))!=len(q_opens) or not exit_rules or len(set(exit_rules))!=len(exit_rules) or any(r not in exits for r in exit_rules):
        raise BacktestError("Matrix thresholds and exits must be nonempty and unique; exits: expiry, close0.6, close0.4")
    for q in q_opens:
        for rule in exit_rules:
            mode,close=exits[rule]
            CTASpec(name="calendar_reversal",parameters=dict(q_open=q,exit_mode=mode,q_close=close))
    scenario_count=len(channels)*len(spec.roots)*len(q_opens)*len(exit_rules)
    legacy_matrix=(tuple(channels)==("01-03","02-03") and tuple(q_opens)==(.8,.9)
                   and tuple(exit_rules)==("expiry","close0.6","close0.4"))
    cfg=BacktestConfig(**job["backtest"])
    if cfg.mode!="product" or cfg.weight_mode!="neutral_units" or cfg.precision!="1d" or cfg.d0!=0 or not cfg.rebalance_on_change_only or not cfg.preserve_pair_lots or cfg.liquidate_at_end:
        raise BacktestError("Calendar study requires product, daily, neutral_units, d0=0, on-change and preserved lots; leave end holdings open")
    data=DataConfig(**job["data"])
    if data.dividend_mode!="ignore":
        raise BacktestError("Calendar study explicitly ignores dividends")
    rates={data.margin_rates.get(r) for r in spec.roots}
    if data.margin_rate_path or None in rates or len(rates)!=1:
        raise BacktestError("Calendar study requires one explicit fixed margin rate for every root and both legs")
    margin_rate=rates.pop()
    if render and (not legacy_matrix or margin_rate!=.2):
        raise BacktestError("The legacy renderer requires the original 48 schemes and 20% margin; use --no-render for a custom matrix")
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    progress("计算/校验原始因子与实际 pair 退出分位")
    if job.get("factor_input"):
        factors=load_factors(job["factor_input"])
        validate_factor_artifact(factors,spec,data)
    else:
        factor_stage(job,output_dir=out/"factors")
        factors=load_factors(out/"factors")
    before=fingerprints(factors)
    paths=[v["path"] for v in factors.metadata["market"].get("files",{}).values() if v.get("path")]
    paths += [str(p) for p in Path(factors.output_paths["output_dir"]).rglob("*") if p.is_file()]
    source_hashes=_hashes(paths)
    start,end,coverage=_coverage(factors,cfg,spec.parameters["window_days"])
    write_json(out/"coverage.local.json",coverage)
    (out/"csv").mkdir()
    factors.diagnostics["calendar_pairs"].to_csv(out/"csv/factor_actual_pairs.csv",index=False,encoding="utf-8-sig")
    for name,value in factors.continuous_factors.items():
        value.to_csv(out/"csv"/(name+".csv"),encoding="utf-8-sig")
    factors.panel.mapping.to_csv(out/"csv/continuous_actual_mapping.csv",encoding="utf-8-sig")
    metrics,all_trips,all_legs,all_paths,drawdowns,curves,verification=[],[],[],[],[],[],[]
    cases=[]
    case_id=0
    for channel in channels:
        for q_open in q_opens:
            for rule in exit_rules:
                exit_mode,q_close=exits[rule]
                case_id+=1
                exit_label="expiry" if exit_mode=="expiry" else f"close{q_close:.1f}"
                case=f"{channel}_open{q_open:.15g}_{exit_label}"
                folder=out/"cases"/case
                folder.mkdir(parents=True)
                case_job=deepcopy(job)
                case_job.pop("factor_input",None)
                case_job.pop("output_dir",None)
                case_job["backtest"].update(start=start,end=end)
                base_weight=job.get("cta",{}).get("parameters",{}).get("position_weight",.495)
                case_job["cta"]=dict(name="calendar_reversal",input_factor=spec.name,parameters=dict(
                    channel=channel,root="all",q_open=q_open,exit_mode=exit_mode,q_close=q_close,position_weight=base_weight))
                progress(f"{case_id}/{scenario_count//len(spec.roots)} {case}：4 个独立账户，调用原回测阶段")
                signals=cta_stage(factors,case_job,output_dir=folder/"cta")
                reloaded=cta_stage(factors.output_paths["output_dir"],case_job)
                pd.testing.assert_frame_equal(signals.targets,reloaded.targets)
                pd.testing.assert_frame_equal(signals.decisions,reloaded.decisions)
                if fingerprints(factors)!=before:
                    raise BacktestError("CTA changed a raw factor or actual-pair diagnostic")
                result=backtest_stage(signals,case_job,output_dir=folder/"backtest")
                write_json(folder/"job.local.json",case_job)
                signals.decisions.to_csv(folder/"decisions.csv",index=False,encoding="utf-8-sig")
                cases.append(case)
                for root,account in result.accounts.items():
                    scenario=root+"_"+case
                    trip,legs,path,stats=round_trips(account,factors,signals,scenario=scenario,root=root,channel=channel,
                        initial_capital=cfg.initial_capital,commission_rate=cfg.commission_rate)
                    episodes,curve=drawdown_episodes(account.equity.equity,cfg.initial_capital,scenario=scenario)
                    metrics.append(dict(scenario=scenario,case=case,root=root,channel=channel,q_open=q_open,
                        exit_mode=exit_mode,q_close=q_close if exit_mode=="threshold" else np.nan,**stats))
                    all_trips.append(trip)
                    all_legs.append(legs)
                    all_paths.append(path)
                    drawdowns.append(episodes)
                    curves.append(curve)
                    if verify:
                        single=deepcopy(case_job)
                        single["cta"]["parameters"]["root"]=root
                        alone=backtest_stage(cta_stage(factors.output_paths["output_dir"],single),single).accounts[root]
                        for name in ("equity","positions","actual_orders","target_weights","schedule"):
                            pd.testing.assert_frame_equal(getattr(account,name),getattr(alone,name))
                    verification.append(dict(scenario=scenario,standalone_equal=verify,factor_reload_weights_equal=True,
                        raw_factor_unchanged=True,locked_pair_and_lots=True,two_leg_pnl_fees_margin_equity=True,
                        drawdown_dates_equal=True,closed_sample=int(stats["closed_trades"])))
    summary=pd.DataFrame(metrics)
    if len(summary)!=scenario_count or summary.scenario.nunique()!=scenario_count:
        raise BacktestError("Calendar scheme matrix is incomplete")
    outputs={"account_metrics":summary,"round_trips":pd.concat(all_trips,ignore_index=True),
        "trade_legs":pd.concat(all_legs,ignore_index=True),"trades_daily":pd.concat(all_paths,ignore_index=True),
        "drawdown_top3":pd.concat(drawdowns,ignore_index=True),"equity_drawdown":pd.concat(curves,ignore_index=True),
        "verification":pd.DataFrame(verification)}
    for name,frame in outputs.items():
        frame.to_csv(out/"csv"/(name+".csv"),index=False,encoding="utf-8-sig")
        frame.to_parquet(out/(name+".parquet"),index=False)
    progress("验证前缀重放、全量因子与源文件 SHA 不变")
    prefixes=verify_prefixes(factors) if verify else []
    if fingerprints(factors)!=before or _hashes(paths)!=source_hashes:
        raise BacktestError("Original factor or source snapshot changed during research")
    write_json(out/"input_sha256.local.json",source_hashes)
    protocol=dict(schema_version="calendar_reversal_48_v1" if legacy_matrix and margin_rate==.2 else "calendar_reversal_matrix_v2",research_date=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),data=asdict(data),factor=asdict(spec),
        evaluation_start=start,evaluation_end=end,coverage=coverage,capital_per_account=cfg.initial_capital,
        scenario_count=scenario_count,cases=cases,channels=list(channels),q_opens=list(q_opens),exit_rules=list(exit_rules),margin_rate=margin_rate,commission_rate=cfg.commission_rate,
        backtest=asdict(replace(cfg,start=start,end=end)),factor_artifact=factors.output_paths["output_dir"],
        factor_computations=0 if job.get("factor_input") else 1,all_inputs_sha_unchanged=True,
        threshold_semantics="raw p > q_open short, p < 1-q_open long; strict; no centered labels",
        exit_benchmark=factors.metadata["method"]["exit_benchmark"],
        execution="next common valid observation; daily data fills actual next close; original engine expiry same-day close",
        dividends="explicitly ignored",accounting=f"{scenario_count} independent capital accounts; no shared cash/netting; equal opposite integer lots",
        trade_return="net PnL / frozen actual entry margin; zero-day or r<=-1 annualization not applicable",
        win_rate="net winning closed trips / all closed trips per scheme; flat trades separate; open trips excluded",
        drawdown="top 3 non-overlapping high-watermark to recovery episodes; unrecovered to sample end; fewer than 3 if insufficient episodes",
        statistical_scope="descriptive historical parameter comparison; no holdout or multiple-testing correction; no predictive claim",
        availability_limit="algorithmic prefix invariance verified; dated reference metadata is not a complete point-in-time publication archive",
        standalone_verified=scenario_count if verify else 0,prefix_checks=prefixes,ddb="paused",vpn="untouched",z_source="not accessed")
    write_json(out/"study.local.json",protocol)
    if render:
        from .calendar_report import render_calendar_report
        render_calendar_report(out)
    return dict(output_dir=str(out),metrics=summary,protocol=protocol)


def main(argv=None):
    from .__main__ import load_job
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--no-verify",action="store_true",help="skip independent reruns and prefix verification; exploratory runs only")
    parser.add_argument("--no-render",action="store_true")
    parser.add_argument("--q-open",type=float,nargs="+",default=[.8,.9],help="raw opening p thresholds; default .8 .9")
    parser.add_argument("--exits",nargs="+",choices=("expiry","close0.6","close0.4"),default=["expiry","close0.6","close0.4"])
    args=parser.parse_args(argv)
    run_calendar_study(load_job(args.config),args.output,verify=not args.no_verify,render=not args.no_render,q_opens=args.q_open,exit_rules=args.exits,
                       progress=lambda s:print(s,flush=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
