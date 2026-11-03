"""Explicit read-only source import; write a new audited snapshot under local data."""
import argparse
import hashlib
import io
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import verified_days
from .configuration import factor_spec
from .io import write_json
from .models import BacktestError, DataConfig, DEFAULT_MULTIPLIERS, normalize_symbol
from .strategy.pipeline import _load_market
from .structure_study import _audit


SOURCE_ID="local_ddb_plus_authorized_readonly_z_v2"
ROOTS=tuple(DEFAULT_MULTIPLIERS)


def read_source(path, evidence, *, roots_only=True, cache=None):
    path=Path(path)
    before=path.stat()
    with path.open("rb") as handle:
        raw=handle.read()
    value=pd.read_pickle(io.BytesIO(raw))
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise BacktestError(f"Source changed while reading: {path}")
    if not isinstance(value,pd.DataFrame):
        raise BacktestError("Source must be a trusted user-owned dataframe")
    evidence.append(dict(path=str(path.resolve()),bytes=len(raw),mtime_ns=after.st_mtime_ns,sha256=hashlib.sha256(raw).hexdigest(),read_only=True))
    frame=value[[r+".CFE" for r in ROOTS]].copy() if roots_only else value.copy()
    frame.index=pd.DatetimeIndex(frame.index)
    if frame.index.has_duplicates or frame.index.tz is not None or frame.index.isna().any():
        raise BacktestError("Source daily dates must be unique, naive date labels")
    frame=frame.sort_index()
    if cache is not None:
        cache[str(path.resolve())]=(frame,roots_only)
    return frame


def import_snapshot(source, output, primary_job, *, start="2023-07-01",end="2026-10-14",authorize_readonly_z=False,progress=None):
    if authorize_readonly_z is not True:
        raise BacktestError("Explicit authorize_readonly_z=True is required")
    source,out=Path(source).resolve(),Path(output).resolve()
    local_data=Path(__file__).resolve().parents[2]/"data"
    if not out.is_relative_to(local_data) or out.is_relative_to(source) or out.drive.upper()=="Z:":
        raise BacktestError("Import destination must be a new local repository data directory, never the read-only source")
    if out.exists():
        raise BacktestError("Import output already exists; choose a new immutable snapshot")
    dates=pd.DatetimeIndex(verified_days(start,end))
    evidence=[]
    snapshots={}
    panels={}
    for slot in range(4):
        if progress:
            progress(f"只读读取 Z 来源日线、实际代码、到期及自然日：档位 {slot:02d}")
        base=source/f"raw/day/next/+{slot}"
        panels[slot]={f:read_source(base/(f+".pkl"),evidence,cache=snapshots) for f in ("close","month_contract_code","last_tradedate","contract_remain_days")}
    spot=read_source(source/"raw/day/main/spot_price.pkl",evidence,cache=snapshots)
    calendar=read_source(source/"normalization/Date.pkl",evidence,roots_only=False,cache=snapshots).index
    if not dates.difference(calendar).empty:
        raise BacktestError("Read-only source calendar disagrees with verified study dates")
    native=_load_market(DataConfig(**primary_job["data"]),factor_spec(primary_job).runtime(),None,None)
    primary=native.daily_close if native.daily_close is not None else native.close
    primary=primary.copy()
    primary.index=primary.index.tz_localize(None).normalize()
    rows,refs=[],{}
    for slot,panel in panels.items():
        for root in ROOTS:
            col=root+".CFE"
            full=pd.DataFrame(dict(code=panel["month_contract_code"][col],expiry=panel["last_tradedate"][col]))
            full=full.dropna(subset=["code","expiry"])
            full["expiry"]=pd.to_datetime(full.expiry.astype(np.int64).astype(str),format="%Y%m%d")
            for code,group in full.groupby("code",sort=False):
                if not isinstance(code,str) or not code.startswith(root):
                    raise BacktestError("Actual mapping/root identity mismatch")
                expiry=group.expiry.unique()
                if len(expiry)!=1:
                    raise BacktestError(f"Conflicting source expiry: {code}")
                expiry=pd.Timestamp(expiry[0])
                first=group.index.min()
                if expiry<dates[0] or first>dates[-1]:
                    continue
                if normalize_symbol(code)!=code:
                    raise BacktestError("Imported identities must be canonical actual contracts")
                if code in refs and refs[code]["expiry_date"]!=str(expiry.date()):
                    raise BacktestError(f"Conflicting expiry across source slots: {code}")
                old=refs.get(code)
                if old is None or str(first.date())<old["listing_date"]:
                    refs[code]=dict(instrument_id=code,root=root,listing_date=str(first.date()),expiry_date=str(expiry.date()),
                        multiplier=DEFAULT_MULTIPLIERS[root],listing_source="first same-day four-slot membership; previous trading-day exclusion verified",
                        expiry_source="read-only last_tradedate; consistent across dated source rows")
            part=pd.DataFrame(dict(code=panel["month_contract_code"][col].reindex(dates),close=panel["close"][col].reindex(dates),
                expiry=panel["last_tradedate"][col].reindex(dates),remaining=panel["contract_remain_days"][col].reindex(dates)))
            part=part.loc[part.close.notna()].copy()
            if part[["code","expiry","remaining"]].isna().any().any() or not (np.isfinite(part.close)&part.close.gt(0)).all():
                raise BacktestError(f"Missing actual mapping/expiry or invalid raw close: {root}{slot:02d}")
            expiry=pd.to_datetime(part.expiry.astype(np.int64).astype(str),format="%Y%m%d")
            t=(pd.DatetimeIndex(expiry)-part.index).days
            if not np.array_equal(t,part.remaining.to_numpy()):
                raise BacktestError(f"Source remaining natural days disagree with actual expiry: {root}{slot:02d}")
            part["source_file"]=f"raw/day/next/+{slot}/close.pkl"
            part["date"]=part.index
            rows.append(part[["date","code","close","source_file"]])
    for code,ref in refs.items():
        first=pd.Timestamp(ref["listing_date"])
        position=calendar.get_indexer([first])[0]
        if position<=0:
            raise BacktestError(f"No source-calendar evidence before first listing membership: {code}")
        previous=calendar[position-1]
        sets={}
        for day in (previous,first):
            values=[p["month_contract_code"].at[day,code[:2]+".CFE"] for p in panels.values()]
            if any(not isinstance(v,str) for v in values) or len(set(values))!=4:
                raise BacktestError(f"Incomplete four-slot listing evidence: {code} {day}")
            sets[day]=set(values)
        if code in sets[previous] or code not in sets[first]:
            raise BacktestError(f"Cannot certify first listing membership: {code}")
        ref["listing_previous_complete_day"]=str(previous.date())
        prior=native.contracts.get(code)
        if prior and (prior["listing_date"],prior["expiry_date"])!=(ref["listing_date"],ref["expiry_date"]):
            raise BacktestError(f"Source and existing dated reference conflict: {code}")
    long=pd.concat(rows,ignore_index=True)
    if long.groupby(["date","code"]).close.nunique().gt(1).any():
        raise BacktestError("Same-day actual contract has conflicting raw prices across source slots")
    long=long.drop_duplicates(["date","code"])
    imported=long.pivot(index="date",columns="code",values="close").reindex(dates)
    for root in ROOTS:
        imported[root+"_spot"]=spot[root+".CFE"].reindex(dates)
    primary=primary.reindex(index=dates,columns=imported.columns)
    both=primary.notna()&imported.notna()
    conflicts=(primary-imported).abs().gt(1e-6)&both
    conflict_rows=[]
    for i,j in np.argwhere(conflicts.to_numpy()):
        conflict_rows.append(dict(date=dates[i],symbol=imported.columns[j],existing_price=primary.iat[i,j],source_price=imported.iat[i,j],policy="existing registered price retained"))
    prices=primary.combine_first(imported)  # same-cell declared source priority, never a time fill
    prices.index=(prices.index.tz_localize("Asia/Shanghai")+pd.Timedelta(hours=15)).rename("timestamp")
    _,audit=_audit(prices,refs,ROOTS)
    if audit["status"]!="complete":
        raise BacktestError(f"Joint local snapshot is incomplete: {audit['missing'][:8]}")
    # Canonical listing/expiry mapping must reproduce every dated source slot.
    from .strategy.mapping import slot_mapping
    mapped,_=slot_mapping(prices.index,refs,ROOTS)
    for slot in range(4):
        for root in ROOTS:
            observed=panels[slot]["month_contract_code"][root+".CFE"].reindex(dates).to_numpy()
            if not np.array_equal(mapped[f"{root}0{slot}.CFE"].to_numpy(),observed):
                raise BacktestError(f"Derived reference does not reproduce source dated mapping: {root}{slot:02d}")
    out.mkdir(parents=True,exist_ok=False)
    prices.to_parquet(out/"daily_close.parquet")
    pd.DataFrame(refs.values()).sort_values("instrument_id").to_parquet(out/"contracts.parquet",index=False)
    t=pd.DataFrame({s:(pd.Timestamp(r["expiry_date"],tz="Asia/Shanghai")-prices.index.normalize()).days for s,r in refs.items()},index=prices.index,dtype=float)
    t.to_parquet(out/"days_to_expiry.parquet")
    pd.DataFrame(dict(date=dates.strftime("%Y-%m-%d"))).to_csv(out/"calendar.csv",index=False)
    pd.DataFrame(conflict_rows,columns=["date","symbol","existing_price","source_price","policy"]).to_parquet(out/"overlap_conflicts.parquet",index=False)
    provenance=[]
    for i,j in np.argwhere(prices.notna().to_numpy()):
        provenance.append(dict(timestamp=prices.index[i],symbol=prices.columns[j],source="existing_registered" if pd.notna(primary.iat[i,j]) else "authorized_readonly_z"))
    pd.DataFrame(provenance).to_parquet(out/"cell_sources.parquet",index=False)
    unchanged=[]
    for record in evidence:
        stat=Path(record["path"]).stat()
        stable=(stat.st_size,stat.st_mtime_ns)==(record["bytes"],record["mtime_ns"])
        unchanged.append(stable)
        if not stable:
            old,roots_only=snapshots[record["path"]]
            recheck=[]
            current=read_source(record["path"],recheck,roots_only=roots_only)
            try:
                pd.testing.assert_frame_equal(old.loc[:end],current.loc[:end],check_exact=True,check_freq=False)
            except AssertionError as exc:
                write_json(out/"unpublished_source_change.local.json",dict(files=evidence,changed=record["path"],published=False))
                raise BacktestError("Selected historical source values changed; unpublished local output retained for audit") from exc
            record.update(changed_after_read=True,selected_history_unchanged=True,rechecked_sha256=recheck[0]["sha256"])
    files=["daily_close.parquet","contracts.parquet","days_to_expiry.parquet","calendar.csv","overlap_conflicts.parquet","cell_sources.parquet"]
    manifest=dict(schema_version="delta1_readonly_import_v1",source_id=SOURCE_ID,source_read_only=True,authorization="user explicitly authorized read-only Z import on 2026-11-03",
        start=str(dates[0].date()),end=str(dates[-1].date()),sources=evidence,source_fingerprints_unchanged=all(unchanged),selected_historical_cells_unchanged=True,
        primary=dict(data=primary_job["data"],datasets=native.metadata.get("datasets",[])),source_priority="existing registered cells win; readonly source fills missing cells only; no temporal fill",
        overlap_cells=int(both.sum().sum()),conflict_cells=int(conflicts.sum().sum()),reference_policy="full same-day four-slot membership plus verified prior trading-day exclusion, actual source last_tradedate; existing reference must agree",
        availability_contract="Z project_declared_time_v1: complete daily row usable after T close; existing registered source availability still unknown",
        coverage=audit,outputs={f:dict(sha256=hashlib.sha256((out/f).read_bytes()).hexdigest(),bytes=(out/f).stat().st_size) for f in files})
    write_json(out/"import_manifest.local.json",manifest)
    data=dict(data_root=str(out),dataset_id="audited_daily_2023_2026",data_version=out.name,source_id=SOURCE_ID,
        daily_close_path="daily_close.parquet",reference_path="contracts.parquet",days_to_expiry_path="days_to_expiry.parquet",
        calendar_path="calendar.csv",source_manifest_path="import_manifest.local.json",allow_readonly_z_import=True,
        dividend_mode="ignore",margin_rates={r:1. for r in ROOTS},daily_label_time="15:00")
    write_json(out/"data.local.json",data)
    return dict(output_dir=str(out),data=data,manifest=manifest)


def main(argv=None):
    from .__main__ import load_job
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--primary-config",type=Path,required=True)
    parser.add_argument("--start",default="2023-07-01")
    parser.add_argument("--end",default="2026-10-14")
    parser.add_argument("--authorize-readonly-z",action="store_true",required=True)
    args=parser.parse_args(argv)
    result=import_snapshot(args.source,args.output,load_job(args.primary_config),start=args.start,end=args.end,
        authorize_readonly_z=args.authorize_readonly_z,progress=lambda s:print(s,flush=True))
    print(result["output_dir"])
    print(f"Overlap {result['manifest']['overlap_cells']}; retained conflicts {result['manifest']['conflict_cells']}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
