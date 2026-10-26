"""Headless, bounded company diagnostics. Never start a collector or change VPN."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

from dashboard.connection_diagnostics import error_detail


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def local_checks(local_root):
    """Read selected metadata only; no config preparation, credentials or migration."""
    root=Path(local_root).resolve();path=root/'native.json'
    result=dict(local_root=str(root),config_file=str(path))
    try:config=read_json(path)
    except Exception as exc:
        result['error']=error_detail(exc,'config_read',path=path)
        return result,None
    from dashboard.marketdata.history_publication import maintenance_root
    try:
        roots=config.get('history_roots',[])
        result['history_roots']=roots
        ref=config.get('reference_file')
        result['reference_file']=ref
        if ref:
            try:
                with Path(ref).open('rb') as source:source.read(1)
                result['reference_readable']=True
            except OSError as exc:result['reference_error']=error_detail(exc,'reference_read',path=ref)
        if roots:
            maintenance=maintenance_root(roots)
            result['maintenance_root']=str(maintenance)
            for filename in ('status.json','pending.json','publication.json'):
                selected=maintenance/filename
                if not selected.is_file():continue
                value=read_json(selected)
                if filename=='status.json':
                    allowed=('state','updated_at','today','target','scan_id','scan_complete','scan_groups','scan_total',
                             'pending_scan_id','pending_target','pending_symbol_days','missing_bars','queries','inserted',
                             'last_published_at','last_complete_at','error_type','versions')
                    result['history_status']={key:value.get(key) for key in allowed}
                elif filename=='pending.json':
                    result['pending_summary']={key:value.get(key) for key in ('target','scan_id','versions','generated_at')}
                    result['pending_summary']['jobs']=len(value.get('jobs',[]))
                else:
                    result['published_summary']={key:value.get(key) for key in ('target','published_at','datasets')}
            lock=maintenance/'network_session/writer.lock'
            result['network_lock']={'path':str(lock),'exists':lock.exists()}
            if lock.exists():
                before=lock.stat()
                for mode,key in (('rb','read_byte'),('r+b','open_write_access_without_writing')):
                    try:
                        with lock.open(mode) as handle:
                            if mode=='rb':handle.read(1)
                        result['network_lock'][key]={'ok':True}
                    except OSError as exc:result['network_lock'][key]={'ok':False,'error':error_detail(exc,'network_lock',path=lock)}
                after=lock.stat()
                result['network_lock']['content_metadata_unchanged']=(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    except Exception as exc:result['local_check_error']=error_detail(exc,'config_read')
    return result,config


def windows_routes(addresses):
    if os.name!='nt':return {'skipped':'not_windows'}
    # Addresses are validated numbers, never shell text from a remote response.
    safe=[str(ipaddress.ip_address(item)) for item in addresses]
    commands=['$ErrorActionPreference="Stop"', '$routes=@()']
    for item in safe:
        commands.append("$routes+=@(Find-NetRoute -RemoteIPAddress '"+item+"' | Select-Object IPAddress,DestinationPrefix,NextHop,InterfaceAlias,RouteMetric)")
    commands.append('$adapters=@(Get-NetAdapter | Select-Object Name,InterfaceDescription,Status)')
    commands.append('[pscustomobject]@{routes=$routes;adapters=$adapters} | ConvertTo-Json -Depth 5 -Compress')
    try:
        process=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
             '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);'+ ';'.join(commands)],
             capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if process.returncode!=0:return {'state':'unavailable','exit_code':process.returncode}
        return json.loads(process.stdout.decode('utf-8-sig'))
    except Exception as exc:return {'error':error_detail(exc,'route')}


def network_checks():
    from index_strategy.instant_dld.client import DEFAULT_URL
    endpoint=urlsplit(DEFAULT_URL)
    result=dict(hostname=endpoint.hostname,port=endpoint.port or 443,tcp=[])
    try:
        addresses=list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(endpoint.hostname,result['port'],type=socket.SOCK_STREAM)))
        result['resolved_addresses']=addresses
    except OSError as exc:
        result['error']=error_detail(exc,'dns');return result
    for address in addresses[:2]:
        started=time.monotonic()
        try:
            with socket.create_connection((address,result['port']),timeout=3):pass
            result['tcp'].append(dict(address=address,ok=True,seconds=round(time.monotonic()-started,3)))
        except OSError as exc:
            result['tcp'].append(dict(address=address,ok=False,error=error_detail(exc,'tcp'),seconds=round(time.monotonic()-started,3)))
    result['windows']=windows_routes(addresses[:2])
    return result


def cached_route_checks(app_pids=()):
    """Inspect cached DNS / existing App sockets and routes; never make a request."""
    if os.name!='nt':return dict(state='unavailable',reason='not_windows',network_requested=False)
    from index_strategy.instant_dld.client import DEFAULT_URL
    endpoint=urlsplit(DEFAULT_URL);host=endpoint.hostname
    pids=sorted({pid for pid in app_pids if type(pid) is int and pid>0})
    # Hostname is a fixed application constant, supplied as data, not shell code.
    script=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=[Console]::In.ReadToEnd() | ConvertFrom-Json
$hostName=$request.hostname
$ownerPids=@($request.app_pids | ForEach-Object {[int]$_})
$port=[int]$request.port
$checks=@{}
$cache=@()
try {
    $cache=@(Get-DnsClientCache | Where-Object {$_.Entry -eq $hostName -and $_.Data -match '^[0-9a-fA-F:.]+$'} | Select-Object -ExpandProperty Data -Unique)
    $checks.dns_cache='ok'
} catch {$checks.dns_cache=$_.Exception.GetType().Name}
$connections=@()
if ($ownerPids.Count -gt 0) {
    try {
        $connections=@(Get-NetTCPConnection -OwningProcess $ownerPids -RemotePort $port -State Established |
            Where-Object {$_.OwningProcess -in $ownerPids -and $_.RemotePort -eq $port -and $_.RemoteAddress -match '^[0-9a-fA-F:.]+$'} |
            Select-Object OwningProcess,LocalAddress,RemoteAddress,RemotePort,State)
        $checks.existing_app_connections='ok'
    } catch {$checks.existing_app_connections=$_.Exception.GetType().Name}
} else {$checks.existing_app_connections='no_verified_app_lock_user'}
$addresses=@(@($cache)+@($connections | Select-Object -ExpandProperty RemoteAddress) | Select-Object -Unique)
$routes=@()
foreach ($address in $addresses) {
    try {
        $evidence=if ($address -in @($connections.RemoteAddress)) {'established_app_tcp'} else {'cached_dns'}
        $routes+=@(Find-NetRoute -RemoteIPAddress $address | Select-Object IPAddress,DestinationPrefix,NextHop,InterfaceAlias,RouteMetric,
            @{Name='RemoteAddress';Expression={$address}},@{Name='Evidence';Expression={$evidence}})
    } catch {$checks.route_lookup=$_.Exception.GetType().Name}
}
$adapters=@()
try {$adapters=@(Get-NetAdapter | Select-Object Name,InterfaceDescription,Status)} catch {$checks.adapters=$_.Exception.GetType().Name}
[pscustomobject]@{cached_addresses=$cache;existing_app_connections=$connections;routes=$routes;adapters=$adapters;checks=$checks;network_requested=$false;vpn_changed=$false} | ConvertTo-Json -Depth 6 -Compress
'''
    try:
        child=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
            input=json.dumps(dict(hostname=host,port=endpoint.port or 443,app_pids=pids)),text=True,encoding='utf8',capture_output=True,timeout=12,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if child.returncode:return dict(state='unavailable',exit_code=child.returncode,network_requested=False)
        value=json.loads(child.stdout.lstrip('\ufeff'));value['state']='ok' if value.get('routes') else 'cache_or_route_unavailable'
        value['interpretation']='路由来自DNS缓存目标IP或已核验看板锁使用者在行情端口的现有TCP连接；不发新请求，无法据此确认公司网关内部是否使用VPN'
        return value
    except Exception as exc:return dict(state='unavailable',network_requested=False,error=error_detail(exc,'route'))


def verified_app_lock_pids(users, processes):
    from dashboard.app_instance import APP_MODULES
    if processes.get('state')!='ok':return []
    identities={u['pid']:u.get('started_filetime') for row in users if row.get('state')=='ok' for u in row.get('file_users',[])}
    result=[]
    for process in processes.get('items',[]):
        pid=process.get('pid');started=process.get('started_filetime');expected=identities.get(pid)
        if process.get('module') in APP_MODULES and type(started) is int and type(expected) is int and abs(started-expected)<=10000:
            result.append(pid)
    return sorted(set(result))


def collect(local_roots, *, connect=False, lock_owners=False, routes=False):
    result=dict(schema='company-connection-diagnostic-v1',observed_at=datetime.now(timezone.utc).isoformat(),
                python=sys.executable,python_version=sys.version.split()[0],prefix=sys.prefix,
                pid=os.getpid(),profiles=[],continuous_collection_started=False,vpn_changed=False)
    from dashboard.session_clock import session_policy
    gate=session_policy();result['session']=gate
    configs=[];route_pids=[]
    for root in local_roots:
        profile,config=local_checks(root)
        if config is not None:configs.append(config)
        if config is not None and connect:
            from dashboard.session_guard import probe_realtime
            profile['probe']=probe_realtime(config)
        result['profiles'].append(profile)
    if lock_owners:
        from dashboard.lock_processes import file_users,process_summary
        paths=[p['network_lock']['path'] for p in result['profiles'] if 'network_lock' in p]
        users=file_users(paths)
        by_path={os.path.normcase(item['path']):item for item in users}
        for profile in result['profiles']:
            lock=profile.get('network_lock')
            if lock is not None:lock['file_users_query']=by_path.get(os.path.normcase(str(Path(lock['path']).resolve())))
        result['processes']=process_summary([user['pid'] for item in users for user in item.get('file_users',[])])
        route_pids=verified_app_lock_pids(users,result['processes'])
    if routes:result['cached_route_inspection']=cached_route_checks(route_pids)
    denied=any(p.get('probe',{}).get('error',{}).get('stage')=='network_lock' for p in result['profiles'])
    if not connect:result['network']={'skipped':'connect_not_requested'}
    elif not session_policy()['allowed']:result['network']={'skipped':'outside_session'}
    elif denied:result['network']={'skipped':'network_lock_not_acquired'}
    elif not configs:result['network']={'skipped':'no_readable_config'}
    else:
        from dashboard.session_guard import network_lease
        from dashboard.marketdata.history_publication import maintenance_root
        unique={str(maintenance_root(c['history_roots'])) if c.get('history_roots') else '':c for c in configs}
        try:
            # DNS/TCP obey the same exclusion as quote verification. Recheck
            # after earlier probes so another history job cannot race this step.
            with ExitStack() as stack:
                for key in sorted(unique):stack.enter_context(network_lease(unique[key]))
                result['network']=network_checks() if session_policy()['allowed'] else {'skipped':'outside_session'}
        except OSError as exc:result['network']={'error':error_detail(exc,'network_lock')}
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path)
    parser.add_argument('--all-profiles',action='store_true',help='Read existing Excel and App configs without creating either')
    parser.add_argument('--connect',action='store_true',help='One bounded quote check per existing profile and DNS/TCP checks during session')
    parser.add_argument('--lock-owners',action='store_true',help='Query lock-file users and safe process metadata; does not imply --connect')
    parser.add_argument('--routes',action='store_true',help='Inspect DNS cache, existing verified App connections and routes; no network request or VPN change')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    module=Path(__file__).resolve().parent
    if args.local_root and args.all_profiles:parser.error('--local-root and --all-profiles are exclusive')
    choices=[module/'localsetting/app',module/'localsetting/numeric_excel',module/'localsetting']
    roots=([args.local_root] if args.local_root else [p for p in choices if (p/'native.json').is_file()])
    if not args.all_profiles:roots=roots[:1]
    report=dict(schema='company-connection-diagnostic-v1',python=sys.executable,profiles=[],vpn_changed=False)
    code=0
    try:
        if not roots:raise FileNotFoundError('No existing profile')
        report=collect(roots,connect=args.connect,lock_owners=args.lock_owners,routes=args.routes)
    except Exception as exc:
        report['error']=error_detail(exc,'imports' if isinstance(exc,ImportError) else 'config_read');code=1
    if args.output:
        try:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            # Never overwrite a prior company diagnosis.
            with args.output.open('x',encoding='utf8') as out:json.dump(report,out,ensure_ascii=False,allow_nan=False,indent=2)
        except Exception as exc:
            report['report_error']=error_detail(exc,'report',path=args.output);code=1
    print(json.dumps(report,ensure_ascii=True,allow_nan=False))
    return code


if __name__=='__main__':raise SystemExit(main())
