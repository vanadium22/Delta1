"""Inspect numeric Excel runs; opt in to cooperative stopping of verified orphans."""
import argparse
from contextlib import ExitStack
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import time

from dashboard.connection_diagnostics import error_detail
from dashboard.lock_processes import process_summary
from dashboard.process_lifetime import LauncherLifetime


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def inspect_runs(runtime_root,snapshot,*,now=None):
    root=Path(runtime_root).resolve();now=now or datetime.now(timezone.utc)
    if snapshot.get('state')!='ok':return []
    active=set(snapshot['active_pids']);processes={p['pid']:p for p in snapshot['items']}
    result=[]
    for path in root.glob('*/run.json'):
        row=dict(run_file=str(path),eligible=False)
        try:
            run=read_json(path);pid=run.get('producer_pid');process=processes.get(pid)
            if not process or process.get('module')!='dashboard.numeric_excel':continue
            job=path.parent.resolve();job.relative_to(root)
            row.update(run_id=run.get('run_id'),pid=pid,launcher_pid=run.get('launcher_pid'),
                excel_pid=run.get('excel_pid'),output=run.get('output'),heartbeat_at=run.get('heartbeat_at'))
            if not re.fullmatch('[0-9a-f]{32}',job.name) or run.get('run_id')!=job.name:
                row['reason']='invalid_run_identity'
            elif any(type(run.get(key)) is not int or run[key]<=0 for key in ('launcher_pid','excel_pid')):
                row['reason']='missing_owner_metadata'
            elif run['launcher_pid'] in active or run['excel_pid'] in active:
                row['reason']='owner_process_present'
            elif not process.get('feed_path') or not process.get('stop_file') or not run.get('feed'):
                row['reason']='missing_runtime_paths'
            elif (Path(process['feed_path']).resolve()!=Path(run['feed']).resolve() or
                  Path(run['feed']).resolve().parent!=job or
                  Path(process['stop_file']).resolve()!=job/'stop' or
                  (job/'stop').resolve().parent!=job):
                row['reason']='runtime_path_mismatch'
            else:
                heartbeat=datetime.fromisoformat(run['heartbeat_at'].replace('Z','+00:00'))
                if heartbeat.tzinfo is None:raise ValueError('heartbeat timezone missing')
                row['heartbeat_age_seconds']=round((now-heartbeat).total_seconds(),1)
                if row['heartbeat_age_seconds']<120:row['reason']='heartbeat_not_stale'
                else:
                    row.update(eligible=True,reason='launcher_and_excel_absent',
                        stop_file=str(job/'stop'),started_filetime=process['started_filetime'])
        except Exception as exc:row['error']=error_detail(exc,'run_inspection',path=path)
        result.append(row)
    return result


def recover(runtime_root,*,stop_orphans=False,wait_seconds=30):
    result=dict(schema='numeric-recovery-v1',observed_at=datetime.now(timezone.utc).isoformat(),
        stop_requested=stop_orphans,forced_termination=False,vpn_changed=False,network_requested=False)
    snapshot=process_summary();result['process_query_state']=snapshot['state']
    if snapshot['state']!='ok':
        result['process_query']=snapshot;result['ok']=False;return result
    rows=result['runs']=inspect_runs(runtime_root,snapshot)
    watches=[]
    with ExitStack() as stack:
        for row in rows:
            if not row['eligible'] or not stop_orphans:continue
            try:
                watch=stack.enter_context(LauncherLifetime(row['pid']))
                # CIM timestamps may lose sub-microsecond FILETIME precision.
                if watch.stopped.is_set():
                    row['action']='already_exited' if watch.reason=='launcher_exited' else 'monitor_failed'
                    if watch.error:row['watch_error']=watch.error
                    continue
                if abs(watch.started_filetime-row['started_filetime'])>10000:
                    row['action']='identity_changed';continue
                # Refresh owner presence and the actual argv immediately before
                # writing. Query failure or a newly present owner cancels action.
                fresh=process_summary([row['pid']])
                check=next((r for r in inspect_runs(runtime_root,fresh) if r.get('run_id')==row['run_id']),None)
                if not check or not check['eligible'] or abs(check['started_filetime']-row['started_filetime'])>10000:
                    row['action']='recheck_blocked';continue
                marker=Path(row['stop_file'])
                try:
                    with marker.open('x',encoding='ascii') as out:out.write('stop')
                    row['action']='stop_requested'
                except FileExistsError:
                    if not marker.is_file():raise
                    row['action']='stop_already_requested'
                watches.append((row,watch))
            except Exception as exc:
                row['action']='failed';row['error']=error_detail(exc,'cooperative_stop',path=row.get('stop_file'))
        deadline=time.monotonic()+wait_seconds
        while any(not watch.stopped.is_set() for row,watch in watches) and time.monotonic()<deadline:
            time.sleep(min(.2,max(0,deadline-time.monotonic())))
        for row,watch in watches:
            row['exit_observed']=watch.stopped.is_set() and watch.reason=='launcher_exited'
            if watch.error:row['watch_error']=watch.error
    result['ok']=all(not r.get('eligible') or not stop_orphans or
        r.get('action')=='already_exited' or r.get('exit_observed') for r in rows)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop-orphans',action='store_true',help='Write only each verified orphan run\'s stop marker; never kill')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parent/'runtime/numeric_live'
    try:report=recover(root,stop_orphans=args.stop_orphans)
    except Exception as exc:report=dict(ok=False,error=error_detail(exc,'run_recovery'))
    try:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf8') as out:json.dump(report,out,ensure_ascii=False,indent=2)
    except Exception as exc:
        print(json.dumps(error_detail(exc,'report',path=args.output),ensure_ascii=True));return 1
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['ok'] else 2


if __name__=='__main__':raise SystemExit(main())
