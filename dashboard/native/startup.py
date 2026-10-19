"""Optional window reuse. Failure must never prevent the native UI from opening."""
from dataclasses import dataclass
import getpass
import hashlib
import logging
import os
from pathlib import Path


def user_session_scope():
    identity=f"{os.environ.get('USERDOMAIN','')}\\{getpass.getuser()}"
    session=os.environ.get("XDG_SESSION_ID","")
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        token=wintypes.HANDLE()
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        advapi=ctypes.WinDLL("advapi32",use_last_error=True)
        kernel.GetCurrentProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.LocalFree.argtypes=[ctypes.c_void_p]
        kernel.LocalFree.restype=ctypes.c_void_p
        kernel.ProcessIdToSessionId.argtypes=[wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
        advapi.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
        advapi.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
        advapi.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR)]
        session_id=wintypes.DWORD()
        if kernel.ProcessIdToSessionId(os.getpid(),ctypes.byref(session_id)):
            session=str(session_id.value)
        if advapi.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):
            try:
                size=wintypes.DWORD()
                advapi.GetTokenInformation(token,1,None,0,ctypes.byref(size))
                if size.value:
                    buffer=ctypes.create_string_buffer(size.value)
                    if advapi.GetTokenInformation(token,1,buffer,size,ctypes.byref(size)):
                        sid=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0]
                        result=wintypes.LPWSTR()
                        if advapi.ConvertSidToStringSidW(sid,ctypes.byref(result)):
                            try: identity=result.value
                            finally: kernel.LocalFree(ctypes.cast(result,ctypes.c_void_p))
            finally: kernel.CloseHandle(token)
    return identity+"|"+session


def instance_name(local_root,scope=None,edition="developer"):
    root=os.path.normcase(str(Path(local_root).resolve()))
    key=f"v3|{edition}|{root}|{user_session_scope() if scope is None else scope}"
    return "delta1-native-v2-"+hashlib.sha256(key.encode()).hexdigest()[:24]


@dataclass
class Instance:
    forwarded: bool=False
    server: object=None
    warning: str=""


def start_instance(local_root,*,edition="developer",demo=False,enabled=True,logger=None,server_factory=None,socket_factory=None):
    log=logger or logging.getLogger(__name__)
    if not enabled: return Instance()
    server=None
    try:
        from PySide6.QtNetwork import QLocalServer,QLocalSocket
        server_factory=server_factory or QLocalServer
        socket_factory=socket_factory or QLocalSocket
        name=instance_name(local_root,edition=edition)
        socket=socket_factory()
        try:
            socket.connectToServer(name)
            if socket.waitForConnected(300):
                socket.write(b"delta1-v2:demo\n" if demo else b"delta1-v2:raise\n")
                socket.waitForBytesWritten(500)
                # Only exit when the other UI confirms it handled activation.
                if socket.waitForReadyRead(1800) and bytes(socket.readAll()).strip()==b"delta1-v2:ok":
                    log.info("Activated existing window")
                    return Instance(forwarded=True)
                warning="已有实例未确认窗口激活；继续打开独立窗口"
                log.warning(warning)
                return Instance(warning=warning)
        finally:
            socket.abort()
        server=server_factory()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if server.listen(name):
            log.info("Window reuse server ready: %s",name)
            return Instance(server=server)
        warning="窗口复用通道不可用；继续打开 App。"+server.errorString()
        server.close()
        log.warning(warning)
        return Instance(warning=warning)
    except Exception as exc:
        if server: server.close()
        warning=f"窗口复用不可用；继续打开 App。{type(exc).__name__}: {exc}"
        log.warning(warning)
        return Instance(warning=warning)


def activate_window(window):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    state=window.windowState() & ~Qt.WindowState.WindowMinimized
    window.setWindowState(state)
    window.show()
    # Windows startup flags can hide a GUI process even after QWidget.show().
    if os.name=="nt" and QGuiApplication.platformName()=="windows":
        import ctypes
        from ctypes import wintypes
        user32=ctypes.WinDLL("user32",use_last_error=True)
        user32.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
        user32.SetForegroundWindow.argtypes=[wintypes.HWND]
        handle=wintypes.HWND(int(window.winId()))
        user32.ShowWindow(handle,3 if window.isMaximized() else 1)
        user32.SetForegroundWindow(handle)
    window.raise_()
    window.activateWindow()


def bind_activation(server,window,*,logger=None):
    from PySide6.QtCore import QTimer
    log=logger or logging.getLogger(__name__)
    def accept():
        while server.hasPendingConnections():
            connection=server.nextPendingConnection()
            if connection is None: break
            connection.setProperty("delta1_buffer",b"")
            deadline=QTimer(connection);deadline.setSingleShot(True)
            def expire(connection=connection):
                connection.abort();connection.deleteLater()
            deadline.timeout.connect(expire);deadline.start(2500)
            def handle(connection=connection,deadline=deadline):
                data=bytes(connection.property("delta1_buffer") or b"")+bytes(connection.readAll())
                if len(data)>256:
                    deadline.stop();expire(connection);return
                if b"\n" not in data:
                    connection.setProperty("delta1_buffer",data);return
                deadline.stop()
                command=data.strip()
                if command in {b"delta1-v2:raise",b"delta1-v2:demo"}:
                    if command==b"delta1-v2:demo" and not window.demo: window.toggle_demo()
                    activate_window(window)
                    connection.write(b"delta1-v2:ok\n");connection.flush()
                    connection.disconnectFromServer()
                    log.info("Existing window activation handled")
                else: connection.abort()
                connection.deleteLater()
            connection.readyRead.connect(handle)
            if connection.bytesAvailable(): handle()
    server.newConnection.connect(accept)
    # Keep Python callbacks alive for the life of the server.
    server._delta1_accept=accept
