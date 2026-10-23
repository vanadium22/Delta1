"""Observe a launcher handle; never terminate another process or inspect windows."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import threading

from dashboard.connection_diagnostics import error_detail


class LauncherLifetime:
    def __init__(self,pid=None,started_filetime=None,*,stop_file=None):
        self.pid=pid;self.expected_start=started_filetime;self.started_filetime=None
        self.stop_file=Path(stop_file) if stop_file is not None else None
        self.stopped=threading.Event();self.closing=threading.Event()
        self.reason=None;self.error=None;self.handle=None;self.thread=None
        self._callbacks=[];self._lock=threading.Lock()

    def attach(self,callback):
        with self._lock:
            self._callbacks.append(callback);stopped=self.stopped.is_set()
        if stopped:callback()

    def _stop(self,reason):
        with self._lock:
            if self.stopped.is_set():return
            self.reason=reason;self.stopped.set();callbacks=list(self._callbacks)
        for callback in callbacks:callback()

    def __enter__(self):
        if self.pid is None:return self
        if self.pid<=0:raise ValueError('launcher PID must be positive')
        if os.name!='nt':raise RuntimeError('launcher handle monitoring requires Windows')
        api=self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        api.OpenProcess.restype=wintypes.HANDLE
        api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        api.WaitForSingleObject.restype=wintypes.DWORD
        api.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        api.GetProcessTimes.restype=wintypes.BOOL
        api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION; no terminate rights.
        self.handle=api.OpenProcess(0x00101000,False,self.pid)
        if not self.handle:
            code=ctypes.get_last_error()
            if code==87:
                self._stop('launcher_exited');return self
            raise ctypes.WinError(code)
        try:
            times=[wintypes.FILETIME() for _ in range(4)]
            if not api.GetProcessTimes(self.handle,*[ctypes.byref(t) for t in times]):
                raise ctypes.WinError(ctypes.get_last_error())
            self.started_filetime=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
            if self.expected_start is not None and self.expected_start!=self.started_filetime:
                self._stop('launcher_identity_changed');return self
            state=api.WaitForSingleObject(self.handle,0)
            if state==0:self._stop('launcher_exited');return self
            if state!=258:raise ctypes.WinError(ctypes.get_last_error())
            self.thread=threading.Thread(target=self._watch,name='numeric-launcher-lifetime',daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.close();raise

    def _watch(self):
        try:
            while not self.closing.is_set():
                if self.stop_file is not None and self.stop_file.exists():
                    self._stop('stop_requested');break
                state=self.api.WaitForSingleObject(self.handle,200)
                if state==258:continue
                if state==0:self._stop('launcher_exited')
                else:
                    self.error=error_detail(ctypes.WinError(ctypes.get_last_error()),'launcher_watch')
                    self._stop('launcher_watch_failed')
                break
        except Exception as exc:
            self.error=error_detail(exc,'launcher_watch');self._stop('launcher_watch_failed')
        finally:
            self.api.CloseHandle(self.handle);self.handle=None

    def close(self):
        self.closing.set()
        if self.thread is not None:self.thread.join(timeout=1)
        elif self.handle:
            self.api.CloseHandle(self.handle);self.handle=None

    def __exit__(self,*args):self.close()
