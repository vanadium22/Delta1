"""Inspect Windows lock-file users without changing files or stopping processes.

Restart Manager reports file users, not the owner of a particular byte lock.
Only StartSession/RegisterResources/GetList/EndSession are used; no shutdown,
restart, handle closing, elevation, VPN operation or remote query is requested.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys

from dashboard.connection_diagnostics import error_detail


class UniqueProcess(ctypes.Structure):
    _fields_=[('pid',wintypes.DWORD),('started',wintypes.FILETIME)]


class ProcessInfo(ctypes.Structure):
    _fields_=[('process',UniqueProcess),('app_name',wintypes.WCHAR*256),
              ('service_name',wintypes.WCHAR*64),('app_type',wintypes.UINT),
              ('app_status',wintypes.ULONG),('session_id',wintypes.DWORD),
              ('restartable',wintypes.BOOL)]


def _windows_file_users(path):
    """One resource per session so separate profiles cannot share result lists."""
    result=dict(path=str(path),method='windows_restart_manager',file_users=[])
    stage='lock_users_stat';session=wintypes.DWORD();started=False
    try:
        try:Path(path).stat()
        except FileNotFoundError:return dict(result,state='missing')
        stage='lock_users_start'
        api=ctypes.WinDLL('rstrtmgr.dll')
        signatures={
            'RmStartSession':[ctypes.POINTER(wintypes.DWORD),wintypes.DWORD,wintypes.LPWSTR],
            'RmRegisterResources':[wintypes.DWORD,wintypes.UINT,ctypes.POINTER(wintypes.LPCWSTR),
                                   wintypes.UINT,ctypes.POINTER(UniqueProcess),wintypes.UINT,
                                   ctypes.POINTER(wintypes.LPCWSTR)],
            'RmGetList':[wintypes.DWORD,ctypes.POINTER(wintypes.UINT),ctypes.POINTER(wintypes.UINT),
                         ctypes.POINTER(ProcessInfo),ctypes.POINTER(wintypes.DWORD)],
            'RmEndSession':[wintypes.DWORD],
        }
        for name,arguments in signatures.items():
            function=getattr(api,name);function.argtypes=arguments;function.restype=wintypes.DWORD
        def check(code):
            if code:raise ctypes.WinError(code)
        check(api.RmStartSession(ctypes.byref(session),0,ctypes.create_unicode_buffer(33)))
        started=True;stage='lock_users_register'
        files=(wintypes.LPCWSTR*1)(str(Path(path).resolve()))
        check(api.RmRegisterResources(session,1,files,0,None,0,None))
        stage='lock_users_list';capacity=0
        # File users may change during the query. Retry a bounded number of
        # times on ERROR_MORE_DATA, never present an incomplete list as empty.
        for attempt in range(4):
            needed=wintypes.UINT();count=wintypes.UINT(capacity);reasons=wintypes.DWORD()
            buffer=(ProcessInfo*capacity)() if capacity else None
            code=api.RmGetList(session,ctypes.byref(needed),ctypes.byref(count),buffer,ctypes.byref(reasons))
            if code==234:
                capacity=max(needed.value,capacity+1)
                if capacity>4096:raise ValueError('Process list capacity exceeded')
                continue
            check(code)
            result['file_users']=[dict(pid=row.process.pid,
                started_filetime=(row.process.started.dwHighDateTime<<32)|row.process.started.dwLowDateTime)
                for row in (buffer or [])[:count.value]]
            result['state']='ok'
            break
        else:raise ctypes.WinError(234)
    except Exception as exc:
        result.update(state='unavailable',error=error_detail(exc,stage,path=path))
    finally:
        if started:
            try:
                check(api.RmEndSession(session))
            except Exception as exc:
                result['cleanup_error']=error_detail(exc,'lock_users_end',path=path)
    return result


def file_users(paths):
    """Bound native calls in our own hidden child, without touching task workers."""
    paths=list(dict.fromkeys(str(Path(path).resolve()) for path in paths))
    if os.name!='nt':return [dict(path=p,state='unavailable',reason='not_windows') for p in paths]
    if not paths:return []
    try:
        child=subprocess.run([sys.executable,'-B','-X','utf8','-m','dashboard.lock_processes'],
            input=json.dumps(paths),capture_output=True,text=True,encoding='utf8',timeout=20,
            cwd=Path(__file__).resolve().parents[1],
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if child.returncode:
            return [dict(path=p,state='unavailable',exit_code=child.returncode) for p in paths]
        return json.loads(child.stdout)
    except Exception as exc:
        return [dict(path=p,state='unavailable',error=error_detail(exc,'lock_users_query',path=p)) for p in paths]


def process_summary(pids=()):
    """Return only allowlisted metadata; raw command lines never leave PowerShell."""
    if os.name!='nt':return dict(state='unavailable',reason='not_windows')
    selected=','.join(str(int(pid)) for pid in pids)
    script=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$selectedPids=@(SELECTED_PIDS)
$all=@(Get-CimInstance Win32_Process)
$items=@($all | Where-Object {
    $_.Name -match '^(pythonw?|EXCEL)\.exe$' -or $_.ProcessId -in $selectedPids
} | ForEach-Object {
    $taskModule=$null
    if ($_.CommandLine -match '(?i)(?:^|\s)"?-m"?\s+"?(dashboard\.[A-Za-z0-9_.]+)"?(?:\s|$)') {
        $taskModule=$Matches[1]
    }
    $feedPath=$null;$stopFile=$null;$localRoot=$null
    if ($taskModule -in @('dashboard.current','dashboard.native.editions_current','dashboard.native.app')) {
        if ($_.CommandLine -match '(?i)(?:^|\s)"?--local-root"?\s+(?:"([^"]+)"|(\S+))') {
            $localRoot=if($Matches[1]){$Matches[1]}else{$Matches[2]}
        }
        if ($localRoot -and ($localRoot.Contains('://') -or -not [IO.Path]::IsPathRooted($localRoot))) {$localRoot=$null}
    }
    if ($taskModule -eq 'dashboard.numeric_excel') {
        if ($_.CommandLine -match '(?i)(?:^|\s)"?--feed"?\s+(?:"([^"]+)"|(\S+))') {
            $feedPath=if($Matches[1]){$Matches[1]}else{$Matches[2]}
        }
        if ($_.CommandLine -match '(?i)(?:^|\s)"?--stop-file"?\s+(?:"([^"]+)"|(\S+))') {
            $stopFile=if($Matches[1]){$Matches[1]}else{$Matches[2]}
        }
        if ($feedPath -and ($feedPath.Contains('://') -or -not [IO.Path]::IsPathRooted($feedPath))) {$feedPath=$null}
        if ($stopFile -and ($stopFile.Contains('://') -or -not [IO.Path]::IsPathRooted($stopFile))) {$stopFile=$null}
    }
    [pscustomobject]@{
        pid=[int]$_.ProcessId;parent_pid=[int]$_.ParentProcessId;name=$_.Name
        executable=$_.ExecutablePath;module=$taskModule
        feed_path=$feedPath;stop_file=$stopFile;local_root=$localRoot
        started_filetime=if ($_.CreationDate) {$_.CreationDate.ToFileTimeUtc()} else {$null}
        started_at=if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().ToString('o')} else {$null}
    }
})
[pscustomobject]@{items=$items;active_pids=@($all | ForEach-Object {[int]$_.ProcessId})} | ConvertTo-Json -Depth 4 -Compress
'''.replace('SELECTED_PIDS',selected)
    try:
        child=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
            capture_output=True,timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if child.returncode:return dict(state='unavailable',exit_code=child.returncode)
        return dict(state='ok',**json.loads(child.stdout.decode('utf-8-sig')))
    except Exception as exc:return dict(state='unavailable',error=error_detail(exc,'process_query'))


if __name__=='__main__':
    # Internal worker: paths arrive as JSON rather than interpolated shell text.
    print(json.dumps([_windows_file_users(path) for path in json.load(sys.stdin)],ensure_ascii=True))
