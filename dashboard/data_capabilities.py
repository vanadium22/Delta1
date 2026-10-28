"""Offline inventory or explicitly requested, bounded read-only ETF capability test."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from .marketdata.overview_reference import load,ranking,ROOTS,path_for
from .marketdata.overview_sessions import latest_completed_session
from .marketdata.overview_windpy import executable,run_readonly_worker
from .marketdata.wind_terminal_worker import safe_diagnostics
from .marketdata.etf_capability_worker import specification


def fingerprint(path):
    try:return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:return None


def collect(local_root,stage='local',*,fields_file=None,now=None):
    if stage not in ('local','etf'):raise ValueError('explicit_stage_required')
    root=Path(local_root);config=json.loads((root/'native.json').read_text(encoding='utf-8-sig'))
    now=now or datetime.now(ZoneInfo('Asia/Shanghai'));day=latest_completed_session(now)
    from .native.market_overview import previous_session
    data=load(config,root,now=now)['data']
    tracked=[root/'native.json',path_for(config,root),*(root/'overview_reference'/s for s in ('attempt.json','nav-attempt.json','status.json','stop.request'))]
    before={str(p):fingerprint(p) for p in tracked}
    chosen=sorted({f['symbol'] for r in ROOTS for f in ranking(data,r,today=now.date().isoformat())[0]})
    if not chosen:chosen=['510300.SH','510050.SH','510500.SH','512100.SH']
    report=dict(schema='overview-data-capabilities-v1',stage=stage,at=now.isoformat(),requested_day=day,
        codes=chosen,python=executable(config,root),published=False,network_requested=stage=='etf',
        vpn_changed=False,credentials_exported=False,configuration_sha256=before[str(root/'native.json')])
    try:
        raw=json.loads(Path(fields_file).read_text(encoding='utf-8-sig')) if fields_file else {}
        fields=specification(raw)
        report['configured_capabilities']=sorted(fields)
        report['reference']={r:dict(members=len((g:=data.get('indices',{}).get(r,{})).get('rows',[])),
            expected={'IF':300,'IH':50,'IC':500,'IM':1000}[r],weights_complete=g.get('weights_complete'),weight_date=g.get('as_of'),
            missing_weights=sum(m.get('weight_pct') is None for m in g.get('rows',[])),
            missing_industries=sum(not m.get('industry') for m in g.get('rows',[]))) for r in ROOTS}
        if stage=='local':
            report.update(status='inventory_only',checks={kind:dict(status='not_tested' if kind in fields else 'mapping_required') for kind in ('iopv','shares','pcf')})
        else:
            request=dict(day=day,previous_day=previous_session(day),codes=chosen,fields=raw,stage='etf_capabilities')
            with tempfile.TemporaryDirectory(prefix='delta1-etf-probe-') as tmp:
                request['progress_file']=str(Path(tmp)/'progress.json')
                command=[executable(config,root),'-B','-X','utf8',str(Path(__file__).with_name('marketdata')/'etf_capability_worker.py')]
                try:
                    process=run_readonly_worker(command,request,Path(tmp)/'stop.request',timeout=90)
                except Exception:
                    try:report['diagnostics']=safe_diagnostics(json.loads(Path(request['progress_file']).read_text(encoding='utf8')))
                    except (OSError,ValueError):pass
                    raise
                value=json.loads(process.stdout)
            report['diagnostics']=safe_diagnostics(value.get('diagnostics'))
            report['checks']=value.get('checks',{})
            if not value.get('ok'):report.update(status='unavailable',error_type=value.get('error_type','ProbeError'))
            else:report['status']='tested_with_open_requirements'
    except Exception as exc:report.update(status='unavailable',error_type=type(exc).__name__)
    report['profile_files_unchanged']=all(fingerprint(p)==before[str(p)] for p in tracked)
    report['note']='四项能力分别报告；返回非空仍需核验业务时点、份额单位/拆分及PCF状态定义。无正式缓存发布，无实时订阅，不改VPN。'
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path,required=True);parser.add_argument('--stage',choices=('local','etf'),default='local')
    parser.add_argument('--fields-file',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    output=args.output or Path(__file__).parent/'runtime/data_capabilities'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')/'capabilities.json'
    report=collect(args.local_root,args.stage,fields_file=args.fields_file)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf8') as stream:json.dump(report,stream,ensure_ascii=False,allow_nan=False,indent=2)
    print(str(output));return 0 if args.stage=='local' and report['profile_files_unchanged'] and report['status']=='inventory_only' else 2


if __name__=='__main__':raise SystemExit(main())
