"""Parameter batches built exclusively from the existing factor/CTA/backtest stages."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
from itertools import product
import json
from pathlib import Path

import pandas as pd

from .analytics import performance_metrics
from .configuration import EXECUTION_DATA_FIELDS, cta_spec, data_declaration, factor_data_declaration, factor_spec
from .factor_cache import validate_factor_artifact
from .io import frame_fingerprint, json_default, write_json
from .models import BacktestConfig, BacktestError, DataConfig, check_cancelled
from .strategy import load_factors
from .workflow import backtest_stage, cta_stage, factor_stage


SECTIONS={"data","factor","cta","backtest"}


def _key(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=json_default,separators=(",",":")).encode()).hexdigest()[:20]


def _merge(base,patch):
    result=deepcopy(base)
    for key,value in patch.items():
        if key=="factor" and isinstance(value,dict) and value.get("name",result.get(key,{}).get("name"))!=result.get(key,{}).get("name"):
            result.setdefault(key,{})["parameters"]={}
        if isinstance(value,dict) and isinstance(result.get(key),dict):
            result[key]=_merge(result[key],value)
        else:
            result[key]=deepcopy(value)
    return result


def _set(job,path,value):
    names=path.split(".")
    if len(names)<2 or names[0] not in SECTIONS or any(not n or n.startswith("_") for n in names):
        raise BacktestError(f"Tuning path must name a data/factor/cta/backtest field: {path}")
    node=job
    for name in names[:-1]:
        node=node.setdefault(name,{})
        if not isinstance(node,dict):
            raise BacktestError(f"Tuning path traverses a non-object: {path}")
    node[names[-1]]=deepcopy(value)


def expand_tuning(job,*,base_dir=None):
    settings=job.get("tuning",{})
    if not isinstance(settings,dict) or set(settings)-{"grid","cases","max_runs"}:
        raise BacktestError("tuning supports grid, cases and max_runs only")
    grid=settings.get("grid",{})
    cases=settings.get("cases",[dict(name="base")])
    limit=settings.get("max_runs",128)
    if type(limit) is not int or limit<1 or not isinstance(grid,dict) or not isinstance(cases,list) or not cases:
        raise BacktestError("Invalid tuning grid/cases/max_runs")
    if any(not isinstance(path,str) or not isinstance(values,list) or not values for path,values in grid.items()):
        raise BacktestError("Each tuning grid field requires a nonempty list of candidate values")
    count=len(cases)
    for values in grid.values():
        count*=len(values)
    if count>limit:
        raise BacktestError(f"Tuning expands to {count} runs > max_runs={limit}; reduce the grid or explicitly increase max_runs")
    base_dir=Path(base_dir or Path.cwd()).resolve()
    base=deepcopy(job)
    base.pop("tuning",None)
    # Preserve root-relative file declarations when the grid changes data_root.
    base["data"]=data_declaration(DataConfig(**base.get("data",{})))
    output=[]
    for case in cases:
        if not isinstance(case,dict) or set(case)-SECTIONS-{"name"} or not isinstance(case.get("name","base"),str):
            raise BacktestError("A tuning case supports name and four configuration sections only")
        overrides={k:v for k,v in case.items() if k!="name"}
        if any(not isinstance(v,dict) for v in overrides.values()):
            raise BacktestError("Tuning case configuration sections must be objects")
        for values in product(*grid.values()):
            variant=_merge(base,overrides)
            changes=dict(zip(grid,values))
            for path,value in changes.items():
                _set(variant,path,value)
            if variant["data"].get("data_root"):
                variant["data"]["data_root"]=str((base_dir/Path(variant["data"]["data_root"])).resolve())
            data=DataConfig(**variant["data"])
            factor= factor_spec(variant)
            cta=cta_spec(variant)
            execution=BacktestConfig(**variant.get("backtest",{}))
            variant.update(data=asdict(data),factor=asdict(factor),cta=asdict(cta),backtest=asdict(execution))
            output.append(dict(id=f"v{len(output)+1:04d}",name=case.get("name","base"),changes=changes,job=variant))
    return output


def _source_identity(metadata):
    return dict(datasets=[(d["root"],d["version"]) for d in metadata.get("datasets",[])],
        files={k:(v.get("path"),v.get("sha256")) for k,v in metadata.get("files",{}).items() if k not in EXECUTION_DATA_FIELDS})


def _factor_fingerprints(factors):
    return {group+"/"+name:frame_fingerprint(frame) for group,frames in
        (("continuous",factors.continuous_factors),("actual",factors.factors)) for name,frame in frames.items()}


def run_tuning(job,output,*,base_dir=None,cancel_event=None,progress=None):
    variants=expand_tuning(job,base_dir=base_dir)
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    write_json(out/"plan.local.json",variants)
    factor_cache,cta_cache,markets,sources={},{},{},{}
    rows=[]
    manifest=dict(status="running",planned_runs=len(variants),completed_runs=0,factors={},ctas={},variants=[])
    write_json(out/"tuning.local.json",manifest)
    external=load_factors(job["factor_input"]) if job.get("factor_input") else None
    for entry in variants:
        check_cancelled(cancel_event)
        variant=entry["job"]
        spec,cta,data=factor_spec(variant),cta_spec(variant),DataConfig(**variant["data"])
        fkey=_key(dict(data=factor_data_declaration(data),factor=asdict(spec)))
        factor_hit=fkey in factor_cache
        if not factor_hit:
            if external is not None:
                validate_factor_artifact(external,spec,data)
                factors=external
                computed=False
            else:
                mkey=_key(dict(data=factor_data_declaration(data),roots=spec.roots,precision=spec.precision))
                if progress:
                    progress(f"计算因子 {spec.name} {spec.parameters}")
                factors=factor_stage(variant,market_data=markets.get(mkey),output_dir=out/"factors"/fkey,
                    cancel_event=cancel_event,progress=None)
                markets[mkey]=factors.market_data
                computed=True
            dkey=_key(dict(data=factor_data_declaration(data),precision=spec.precision))
            identity=_source_identity(factors.metadata.get("market",{}))
            if dkey in sources and sources[dkey]!=identity:
                raise BacktestError("Input dataset changed between tuning factors; pin versions or freeze a local snapshot")
            sources[dkey]=identity
            fingerprint=_factor_fingerprints(factors)
            factor_cache[fkey]=(factors,fingerprint)
            manifest["factors"][fkey]=dict(path=factors.output_paths["output_dir"],computed=computed,factor=asdict(spec),fingerprints=fingerprint)
        factors,before=factor_cache[fkey]
        ckey=_key(dict(factor=fkey,cta=asdict(cta),start=variant["backtest"]["start"],end=variant["backtest"]["end"]))
        cta_hit=ckey in cta_cache
        if not cta_hit:
            signals=cta_stage(factors,variant,output_dir=out/"cta"/ckey,cancel_event=cancel_event)
            cta_cache[ckey]=signals
            manifest["ctas"][ckey]=dict(path=signals.output_paths["output_dir"],cta=asdict(cta),factor=fkey)
        signals=cta_cache[ckey]
        if before!=_factor_fingerprints(factors):
            raise BacktestError("CTA mutated a cached raw factor")
        directory=out/"variants"/entry["id"]
        directory.mkdir(parents=True)
        effective={**variant,"factor_input":factors.output_paths["output_dir"],"instructions_path":signals.output_paths["targets"],
            "output_dir":str(directory/"backtest")}
        write_json(directory/"job.local.json",effective)
        if progress:
            progress(f"{entry['id']} {entry['name']}：因子{'复用' if factor_hit or external is not None else '已计算'}，CTA{'复用' if cta_hit else '已生成'}")
        result=backtest_stage(signals.output_paths["output_dir"],effective,output_dir=directory/"backtest",
            cancel_event=cancel_event,progress=None)
        for account,value in result.accounts.items():
            metrics=performance_metrics(value.equity.equity,variant["backtest"]["initial_capital"])
            rows.append(dict(variant=entry["id"],case=entry["name"],account=account,factor_name=spec.name,cta_name=cta.name,
                factor_key=fkey,cta_key=ckey,factor_reused=factor_hit or external is not None,cta_reused=cta_hit,
                **metrics,fees=float(value.equity.fees.sum()),orders=len(value.actual_orders),status=value.summary["status"],
                changes=json.dumps(entry["changes"],ensure_ascii=False,default=json_default)))
        if before!=_factor_fingerprints(factors):
            raise BacktestError("CTA/execution mutated a cached raw factor")
        manifest["completed_runs"]+=1
        manifest["variants"].append(dict(id=entry["id"],name=entry["name"],factor=fkey,cta=ckey,output_dir=str(directory/"backtest")))
        write_json(out/"tuning.local.json",manifest)
    summary=pd.DataFrame(rows)
    summary.to_csv(out/"summary.csv",index=False,encoding="utf-8-sig")
    manifest.update(status="complete",factor_computations=sum(v["computed"] for v in manifest["factors"].values()),
        unique_factors=len(factor_cache),unique_ctas=len(cta_cache),raw_factor_cells_unchanged=True,summary=str(out/"summary.csv"))
    write_json(out/"tuning.local.json",manifest)
    return dict(output_dir=str(out),summary=summary,manifest=manifest)
