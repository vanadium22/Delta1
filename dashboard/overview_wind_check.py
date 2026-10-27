"""Explicit staged Wind reads; never publish reference data or change VPN/settings.

This is separate from the offline -Overview diagnostic. Only a required --stage
can enter WindPy, using the configured existing Python and user site.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from dashboard.marketdata.overview_reference import ROOTS,ranking
from dashboard.marketdata.overview_windpy import refresh,executable
from dashboard.marketdata.wind_terminal_worker import safe_diagnostics


def fingerprint(path):
    try:return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:return None


def collect(local_root,stage,*,now=None,day=None):
    if stage not in ('connect','indices','etfs'):raise ValueError('需明确选择Wind只读测试阶段')
    root=Path(local_root);path=root/'native.json';config=json.loads(path.read_text(encoding='utf-8-sig'))
    from dashboard.marketdata.overview_reference import path_for
    inputs=[path,path_for(config,root),*(root/'overview_reference'/name for name in ('status.json','attempt.json','stop.request'))]
    before={str(p):fingerprint(p) for p in inputs}
    stamp=now or datetime.now(ZoneInfo('Asia/Shanghai'))
    report=dict(schema='overview-wind-check-v1',stage=stage,at=stamp.isoformat(),python=executable(config,root),
        local_root=str(root.resolve()),configuration_sha256=before[str(path)],network_requested=True,wind_requested=True,
        vpn_changed=False,app_started=False,published=False,credentials_exported=False)
    try:
        result=refresh(config,root,{},now=stamp,stage=stage,requested_day=day)
        report['diagnostics']=safe_diagnostics(result.get('diagnostics'))
        data=result['data'];day=report['diagnostics'].get('requested_day')
        if stage=='indices':
            report['indices']={r:dict(members=len((g:=data.get('indices',{}).get(r,{})).get('rows',[])),
                as_of=g.get('as_of'),expected={'IF':300,'IH':50,'IC':500,'IM':1000}[r],
                classified=sum(bool(m.get('industry')) for m in g.get('rows',[])),
                anchor_closes=sum(m.get('anchor_date')==day and m.get('anchor_close',0)>0 for m in g.get('rows',[]))) for r in ROOTS}
            complete=all(g['members']==g['expected']==g['classified']==g['anchor_closes'] for g in report['indices'].values())
        elif stage=='etfs':
            groups={r:ranking(data,r,today=stamp.date().isoformat()) for r in ROOTS}
            report['etfs']={r:dict(as_of=meta.get('as_of'),universe_count=meta.get('universe_count'),
                top3=[dict(symbol=f['symbol'],rank=f['rank'],aum_date=f['aum_date']) for f in rows]) for r,(rows,meta) in groups.items()}
            complete=all(len(g['top3'])==3 for g in report['etfs'].values())
        else:complete=True
        report['status']='complete' if complete else 'partial'
    except Exception as exc:
        report.update(status='unavailable',error_type=getattr(exc,'error_type',None) or type(exc).__name__,
            diagnostics=safe_diagnostics(getattr(exc,'diagnostics',{})))
    report['profile_files_unchanged']=all(fingerprint(p)==before[str(p)] for p in inputs)
    report['note']='显式Wind只读测试，不发布资料或连接HTTP/DDB，不操作VPN；ErrorCode和阶段是证据，不能单独推断登录、权限或网络原因'
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path,required=True)
    parser.add_argument('--stage',choices=('connect','indices','etfs'),required=True)
    parser.add_argument('--day',help='Optional completed trading day, YYYY-MM-DD, for reproducible read-only tests')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    report=collect(args.local_root,args.stage,day=args.day)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as out:json.dump(report,out,ensure_ascii=False,allow_nan=False,indent=2)
    print(str(args.output))
    return 0 if report['status']=='complete' and report['profile_files_unchanged'] else 2


if __name__=='__main__':raise SystemExit(main())
