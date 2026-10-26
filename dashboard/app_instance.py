"""Cooperative App replacement. Never terminates a process or deletes a lock.

New Apps hold a scope lease until their window and workers have drained. A new
launch requests the previous owner's stop marker and waits for that lease.
Legacy windows are closed only after matching their report, actual module,
executable, data scope and original process creation time.
"""
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from dashboard.connection_diagnostics import error_detail
from dashboard.marketdata.bars import _writer_lock, _atomic_bytes, _json_bytes
from dashboard.process_lifetime import LauncherLifetime


APP_MODULES = {'dashboard.current', 'dashboard.native.editions_current', 'dashboard.native.app'}


def normalized(path):
    return os.path.normcase(str(Path(path).resolve())) if path else None


def data_scope(config, local_root=None):
    roots = sorted({normalized(p) for p in config.get('history_roots', []) if p})
    realtime = normalized(config.get('realtime_root'))
    primary = ['history', roots] if roots else ['realtime', realtime] if realtime else ['profile', normalized(local_root)]
    return dict(key=hashlib.sha256(_json_bytes(primary)).hexdigest()[:24], history_roots=roots,
                realtime_root=realtime, local_root=normalized(local_root))


def same_data(a, b):
    return bool((a.get('history_roots') and a['history_roots'] == b.get('history_roots')) or
                (a.get('realtime_root') and a['realtime_root'] == b.get('realtime_root')) or
                (a.get('local_root') and a['local_root'] == b.get('local_root')))


def read(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):return {}


def current_start():
    if os.name != 'nt':return None
    with LauncherLifetime(os.getpid()) as process:return process.started_filetime


def close_legacy_windows(pid):
    """Post a normal WM_CLOSE to identified Delta1 windows; never activate them."""
    if os.name != 'nt':return []
    api = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    api.PostMessageW.restype = wintypes.BOOL
    windows = []
    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD();api.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(512);api.GetWindowTextW(hwnd, title, len(title))
            if title.value.lower().startswith('delta1'):
                if api.PostMessageW(hwnd, 0x0010, 0, 0):windows.append(int(hwnd))
        return True
    api.EnumWindows(visit, 0)
    return windows


def legacy_candidates(session_roots, scope, snapshot, *, now=None):
    """PID reuse after the original report file was created is never eligible."""
    if snapshot.get('state') != 'ok':return []
    processes = {p['pid']:p for p in snapshot.get('items', [])}
    now = now or datetime.now(timezone.utc);result = []
    for root in session_roots:
        for path in Path(root).glob('*/status.json'):
            try:
                if not re.fullmatch('[0-9a-f]{32}', path.parent.name):continue
                report = read(path);pid = report.get('pid');process = processes.get(pid, {})
                if pid == os.getpid() or process.get('module') not in APP_MODULES:continue
                if not process.get('executable') or not report.get('python'):continue
                if normalized(process.get('executable')) != normalized(report.get('python')):continue
                if not same_data(scope, data_scope(report.get('paths') or {}, report.get('local_root'))):continue
                seen = datetime.fromisoformat(report['observed_at'].replace('Z', '+00:00'))
                if seen.tzinfo is None or (now-seen).total_seconds() < -3:continue
                stat = path.stat()
                birth_ns = getattr(stat, 'st_birthtime_ns', stat.st_ctime_ns if os.name == 'nt' else 0)
                born = birth_ns//100 + 116444736000000000 if birth_ns else 0
                started = process.get('started_filetime')
                observed_filetime=int(seen.timestamp()*10_000_000)+116444736000000000
                if not isinstance(started, int) or not 0 < started <= min(born,observed_filetime):continue
                # Explicit command-line profiles must agree with the run report.
                profile = process.get('local_root')
                if profile and normalized(profile) != normalized(report.get('local_root')):continue
                result.append(dict(pid=pid, started_filetime=started, report=str(path), closing=bool(report.get('closing'))))
            except (OSError, ValueError, KeyError, TypeError):continue
    return list({r['pid']:r for r in result}.values())


class InstanceLease:
    def __init__(self, runtime_root, config, local_root, *, timeout=45, discover_legacy=True):
        self.runtime_root = Path(runtime_root).resolve();self.scope = data_scope(config, local_root)
        self.root = self.runtime_root/'app_instances'/self.scope['key']
        self.local_root = Path(local_root).resolve();self.timeout = timeout;self.discover_legacy = discover_legacy
        self.token = uuid.uuid4().hex;self.stop_file = self.root/(self.token+'.stop')
        self.active = None;self.owned = False
        self.report = dict(schema='app-handover-v1', scope=self.scope['key'], pid=os.getpid(),
                           state='starting', previous=[], forced_termination=False, vpn_changed=False)

    def summary(self):return dict(self.report, owned=self.owned, stop_file=str(self.stop_file))

    def stop_requested(self):return self.owned and self.stop_file.is_file()

    def _claim(self, name):
        stack = ExitStack()
        try:stack.enter_context(_writer_lock(self.root/name));return stack
        except OSError as exc:
            self.report['coordination_lock_error']=error_detail(exc,'app_coordination_lock')
            stack.close()
            if getattr(exc,'lock_operation',None) in ('create_directory','open_file'):raise
            return None

    def _request_owner(self, owner):
        if owner.get('schema') != 'app-owner-v1' or owner.get('scope') != self.scope['key']:return False
        token = owner.get('token', '')
        if not re.fullmatch('[0-9a-f]{32}', token):return False
        pid, started = owner.get('pid'), owner.get('started_filetime')
        if type(pid) is not int or pid <= 0 or pid == os.getpid() or type(started) is not int:return False
        try:
            with LauncherLifetime(pid, started) as process:
                if process.stopped.is_set():return False
                marker = self.root/(token+'.stop')
                with marker.open('a', encoding='ascii'):pass
                self.report['previous'].append(dict(pid=pid, action='cooperative_stop_requested'))
                return True
        except OSError as exc:
            self.report['owner_error'] = error_detail(exc, 'app_owner_check');return False

    def _close_legacy(self, deadline):
        from dashboard.lock_processes import process_summary
        roots = [self.runtime_root/'app_sessions']
        # Existing explicit local profiles may live in an older checkout.
        dashboard = self.local_root.parent.parent if self.local_root.name in ('app','numeric_excel') else self.local_root.parent
        old = dashboard/'runtime/app_sessions'
        if old not in roots:roots.append(old)
        reports = [p for r in roots for p in r.glob('*/status.json')
                   if read(p).get('pid') != os.getpid()
                   and same_data(self.scope,data_scope(read(p).get('paths') or {},read(p).get('local_root')))]
        if not reports:return True
        snapshot = process_summary()
        if snapshot.get('state') != 'ok':
            self.report['legacy_inspection'] = snapshot;return True
        rows = legacy_candidates(roots, self.scope, snapshot)
        with ExitStack() as stack:
            watches = []
            for row in rows:
                watch = stack.enter_context(LauncherLifetime(row['pid']))
                if watch.stopped.is_set():continue
                # CIM creation timestamps can lose sub-microsecond FILETIME
                # precision. The actual retained process handle remains the
                # authority; a different creation identity is never closed.
                if abs(watch.started_filetime-row['started_filetime'])>10000:continue
                # Query again immediately before sending WM_CLOSE.
                fresh = process_summary([row['pid']])
                if not any(r['pid'] == row['pid'] and r['started_filetime'] == row['started_filetime']
                           for r in legacy_candidates(roots, self.scope, fresh)):continue
                windows = close_legacy_windows(row['pid'])
                action = dict(pid=row['pid'], action='normal_window_close_requested', windows=len(windows))
                self.report['previous'].append(action)
                if not windows and not row['closing']:
                    action['action'] = 'no_verified_window';return False
                watches.append(watch)
            while any(not w.stopped.is_set() for w in watches):
                if time.monotonic() >= deadline:return False
                time.sleep(.1)
        return True

    def acquire(self):
        deadline = time.monotonic()+self.timeout;startup = None
        try:
            while startup is None and time.monotonic() < deadline:
                startup = self._claim('startup')
                if startup is None:time.sleep(.1)
            if startup is None:raise TimeoutError('startup coordination busy')
            with startup:
                requested = False
                while self.active is None and time.monotonic() < deadline:
                    self.active = self._claim('active')
                    if self.active is not None:break
                    if not requested:requested = self._request_owner(read(self.root/'owner.json'))
                    time.sleep(.1)
                if self.active is None:raise TimeoutError('previous App did not drain')
                if self.discover_legacy and not self._close_legacy(deadline):
                    raise TimeoutError('legacy App did not drain')
                owner = dict(schema='app-owner-v1', scope=self.scope['key'], token=self.token,
                             pid=os.getpid(), started_filetime=current_start(), local_root=str(self.local_root),
                             created_at=datetime.now(timezone.utc).isoformat())
                _atomic_bytes(self.root/'owner.json', _json_bytes(owner))
                self.owned = True;self.report['state'] = 'ready'
        except Exception as exc:
            if self.active:self.active.close();self.active = None
            self.report.update(state='waiting_previous_app', error=error_detail(exc, 'app_handover'))
        return self.summary()

    def close(self):
        self.owned = False
        if self.active:self.active.close();self.active = None
        self.report['state'] = 'closed'
