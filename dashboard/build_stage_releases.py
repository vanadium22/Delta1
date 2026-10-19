"""Build all delivery scopes from the current shared source and one demo snapshot."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path: sys.path.insert(0,str(ROOT.parent))
from dashboard.build_public_repository import build_repository,build_archive,export_git_bundle,source_files
from dashboard.release_profiles import profile
from dashboard.native.publication import SCHEMA,decode_state,PRODUCTS
from dashboard.native.trading_axis import TradingTimeMap,session_at

THREAD_ID="01a0f78e-6886-76a2-83d9-970f6893b518"
OUTPUT_ROOT=ROOT/"outputs"/THREAD_ID
CHINA=timezone(timedelta(hours=8))


def run(command,**kwargs):
    result=subprocess.run([str(x) for x in command],capture_output=True,text=True,encoding="utf-8",
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),**kwargs)
    if result.returncode: raise RuntimeError((result.stderr or result.stdout)[-6000:])
    return result.stdout


def prepare_excel(bundle):
    """Project only basic, synchronized 1m observations into the workbook input."""
    if bundle.get("demo") is not True or bundle.get("schema_version")!=SCHEMA:
        raise ValueError("A current, explicitly synthetic snapshot is required")
    states={p:decode_state(bundle["views"][p+":1m"]) for p in PRODUCTS}
    rows=[];latest={};summary={};index={}
    for product,state in states.items():
        keys=["event_time","trade_date","session_id"]
        merged=None
        for key in ("near","spot","far"):
            frame=state[key][keys+["close"]].rename(columns={"close":key})
            merged=frame if merged is None else merged.merge(frame,on=keys)
        merged=merged.sort_values("event_time")
        first=len(rows)
        for _,row in merged.iterrows():
            stamp=row.event_time.timestamp()
            if session_at(stamp) is None: continue
            index[(product,stamp)]=len(rows)
            rows.append({"product":product,"local_time":row.event_time.tz_convert(CHINA).strftime("%Y-%m-%dT%H:%M:%S"),
                "near":float(row.near),"spot":float(row.spot),"far":float(row.far),
                "contracts":str(state["roles"]["$near"])+" / "+str(state["roles"]["$far"])})
        if len(rows)==first: raise ValueError("Insufficient synchronized workbook inputs: "+product)
        latest[product]=len(rows)-1
        summary[product]={"basis_bp":state["values"]["basis_bp"],"spread":state["values"]["spread"],
                          "calendar_bp":state["analytics"]["calendar_bp"]}
    times=sorted({stamp for _,stamp in index})
    axis=TradingTimeMap(times,"1m")
    chart=[];previous=None
    for stamp in times:
        if previous is not None:
            a,b=session_at(previous),session_at(stamp)
            if a[:2]!=b[:2]: chart.append({"label":"午休" if a[0]==b[0] else b[0].strftime("%m-%d"),"indices":[None]*4})
            else:
                missing=previous+60
                while missing<stamp:
                    chart.append({"label":datetime.fromtimestamp(missing,CHINA).strftime("%m-%d %H:%M"),"indices":[None]*4})
                    missing+=60
        chart.append({"label":None,"indices":[index.get((p,stamp)) for p in PRODUCTS],"x":axis.coordinate(stamp)})
        previous=stamp
    return {"snapshot_id":bundle["snapshot_id"],"rows":rows,"latest":latest,"summary":summary,"chart":chart}


def workbook_runtime():
    dependencies=Path(os.environ.get("DELTA1_ARTIFACT_DEPENDENCIES",str(Path(os.environ.get("USERPROFILE",Path.home()))/".cache/codex-runtimes/codex-primary-runtime/dependencies")))
    node=dependencies/"node/bin/node.exe"
    modules=dependencies/"node/node_modules"
    if not node.is_file() or not (modules/"@oai/artifact-tool/package.json").is_file():
        raise RuntimeError("Workbook runtime unavailable: set DELTA1_ARTIFACT_DEPENDENCIES to the bundled dependency directory")
    work=ROOT/"runtime/artifact_tools"/THREAD_ID
    work.mkdir(parents=True,exist_ok=True)
    junction=work/"node_modules"
    if not junction.exists():
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        run(["powershell","-NoProfile","-NonInteractive","-Command",
            "$null = New-Item -ItemType Junction -Path "+quote(junction)+" -Target "+quote(modules)],timeout=15)
    if junction.resolve()!=modules.resolve(): raise ValueError("Unexpected workbook dependency junction")
    return node,work,dependencies


def export_workbook(payload,path):
    node,work,dependencies=workbook_runtime()
    marker=work/"operation_started.json"
    if not marker.exists():
        script=dependencies.parent/"plugins/openai-primary-runtime/plugins/spreadsheets/skills/spreadsheets/container_tools/mark_artifact_operation_started.mjs"
        run([node,script,"--operation-kind","create","--expected-output-count","1","--output-format","xlsx"],timeout=30)
        marker.write_text(json.dumps({"started_at":datetime.now(timezone.utc).isoformat()}),encoding="utf-8")
    builder=work/"excel_sample.mjs"
    builder.write_bytes((ROOT/"excel_sample.mjs").read_bytes())
    inputs=work/"workbook_input.json"
    inputs.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    run([node,builder,inputs,path],timeout=180)
    if not path.is_file(): raise RuntimeError("Workbook export did not create a file")


def generate_demo(path,formulas=None):
    from dashboard.native.developer_model import DeveloperModel
    with tempfile.TemporaryDirectory() as tmp:
        model=DeveloperModel(tmp,path.parent)
        try:
            if formulas is not None: model.formulas=deepcopy(formulas)
            else:
                formula_file=ROOT/"localsetting/native_formulas.json"
                if formula_file.is_file():
                    from dashboard.native.factors import definition
                    model.formulas=[definition(x) for x in json.loads(formula_file.read_text(encoding="utf-8"))]
            state=model.snapshot({"demo":True,"product":"IC","frequency":"1m","save":False})
            if state.get("publish_error"): raise RuntimeError(state["publish_error"])
        finally: model.close()


def build_all(*,demo_path=None,output_root=None,formulas=None,capture=True,resume=None):
    root=Path(output_root or OUTPUT_ROOT).resolve();root.mkdir(parents=True,exist_ok=True)
    clock=Path(resume).name if resume else datetime.now(CHINA).strftime("%Y%m%d_%H%M%S_%f")
    batch=(root/clock).resolve()
    if resume:
        if Path(resume).resolve()!=batch or (batch/"release_manifest.json").exists():
            raise ValueError("Resume must identify an incomplete batch inside output_root")
        progress=json.loads((batch/"build_progress.json").read_text(encoding="utf-8"))
        demo_path=ROOT/"runtime/stage_inputs"/clock/"demo.json"
        if hashlib.sha256(demo_path.read_bytes()).hexdigest()!=progress["input_sha256"]:
            raise ValueError("The original batch input has changed")
    else:
        batch.mkdir();progress={}
    if demo_path is None:
        demo_path=ROOT/"runtime/stage_inputs"/clock/"demo.json"
        generate_demo(demo_path,formulas)
    demo_path=Path(demo_path).resolve()
    bundle=json.loads(demo_path.read_text(encoding="utf-8"))
    payload=prepare_excel(bundle)
    # Preserve the exact full input internally for repeatable releases, never hand it to lower scopes.
    inputs=ROOT/"runtime/stage_inputs"/clock/"demo.json"
    inputs.parent.mkdir(parents=True,exist_ok=True)
    if inputs!=demo_path: inputs.write_bytes(demo_path.read_bytes())
    report={"created_at":datetime.now(CHINA).isoformat(),"snapshot_id":bundle["snapshot_id"],
        "input_sha256":hashlib.sha256(inputs.read_bytes()).hexdigest(),"artifacts":{}}
    progress["input_sha256"]=report["input_sha256"]
    progress_path=batch/"build_progress.json"
    progress_path.write_text(json.dumps(progress,indent=2),encoding="utf-8")
    sample=batch/"指标样稿";sample.mkdir(exist_ok=True)
    workbook=sample/"Delta1_股指期货指标样稿.xlsx"
    builder_hash=hashlib.sha256((ROOT/"excel_sample.mjs").read_bytes()).hexdigest()
    reuse=workbook.is_file() and progress.get("workbook_builder")==builder_hash and progress.get("workbook_sha256")==hashlib.sha256(workbook.read_bytes()).hexdigest()
    if not reuse: export_workbook(payload,workbook)
    progress.update(workbook_builder=builder_hash,workbook_sha256=hashlib.sha256(workbook.read_bytes()).hexdigest())
    progress_path.write_text(json.dumps(progress,indent=2),encoding="utf-8")
    report["artifacts"]["20"]={"name":"指标样稿","workbook":str(workbook),"sha256":hashlib.sha256(workbook.read_bytes()).hexdigest()}
    for stage in ("50","80","100"):
        settings=profile(stage);folder=batch/settings["RELEASE_NAME"];folder.mkdir(exist_ok=True)
        repository=build_repository(demo_path=inputs,stage=stage)
        receipt=json.loads((repository/"release.json").read_text(encoding="utf-8"))
        bundle_path=export_git_bundle(repository,folder/"Delta1-market-dashboard.bundle")
        archive=build_archive(folder/"Delta1-market-dashboard.zip",demo_path=inputs,stage=stage)
        item={"name":settings["RELEASE_NAME"],"repository":str(repository),"git":str(bundle_path),"zip":str(archive),"build_id":receipt["build_id"],"screenshots":[]}
        if capture:
            env={**os.environ,"PYTHONPATH":str(ROOT.parent/".deps/dashboard_native"),"QT_QPA_PLATFORM":"offscreen"}
            for page in range(len(settings["MODULE_TITLES"])):
                image=folder/f"{page+1:02d}_{settings['MODULE_TITLES'][page]}.png"
                run([sys.executable,"-B","-s","-X","utf8","-m","dashboard","--demo","--capture",image,
                    "--capture-page",str(page)],cwd=repository,env=env,timeout=40)
                item["screenshots"].append(str(image))
        report["artifacts"][stage]=item
    (batch/"release_manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    latest=root/"latest.json";temporary=root/"latest.tmp"
    temporary.write_text(json.dumps({"manifest":str(batch/"release_manifest.json"),**report},ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temporary,latest)
    return batch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-file");parser.add_argument("--output-root");parser.add_argument("--no-capture",action="store_true")
    parser.add_argument("--resume",help="Continue an incomplete batch without replacing its input")
    args=parser.parse_args()
    path=build_all(demo_path=args.demo_file,output_root=args.output_root,capture=not args.no_capture,resume=args.resume)
    print(json.dumps({"release":str(path)},ensure_ascii=False))


if __name__=="__main__": main()
