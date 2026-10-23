"""Sangfor login adapter reused from the local history tool.

An existing route is reused. This adapter never logs out or switches to the
realtime VPN; the user does that after the history process has exited.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import time
from urllib.parse import urlsplit


class VPNError(ConnectionError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class VPNCancelled(Exception):
    pass


def check_stop(stop_file):
    # App workers also observe the exact owning process while a login is pending.
    requested=stop_file() if callable(stop_file) else bool(stop_file and Path(stop_file).exists())
    if requested:
        raise VPNCancelled()


def normalize_gateway(value):
    if not isinstance(value, str):
        raise VPNError('configuration')
    value = value.strip()
    markdown = re.fullmatch(r'\[[^\]]+\]\((https://[^)]+)\)', value)
    parts = urlsplit(markdown[1] if markdown else value)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ('', '/')):
        raise VPNError('configuration')
    try:
        port = parts.port or 443
    except ValueError:
        raise VPNError('configuration') from None
    if not 1 <= port <= 65535:
        raise VPNError('configuration')
    host = parts.hostname.lower()
    return f"https://{'['+host+']' if ':' in host else host}:{port}"


def validate_profile(config_path, trust_path):
    try:
        config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        trust = json.loads(Path(trust_path).read_text(encoding='utf-8-sig'))
        gateway = normalize_gateway(config['url'])
        if (normalize_gateway(trust['endpoint']) != gateway
                or not re.fullmatch(r'[a-fA-F0-9]{64}', trust['certificate_sha256'])
                or config.get('protected_credentials', {}).get('scheme') != 'windows-dpapi-current-user-v1'):
            raise ValueError()
        return gateway, trust['certificate_sha256'].upper()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise VPNError('configuration') from None


def powershell(override=None):
    profile = os.environ.get('USERPROFILE', '')
    candidates = [override, os.environ.get('SWHY_SSLVPN_POWERSHELL'), shutil.which('pwsh'),
        Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'PowerShell/7/pwsh.exe',
        Path(profile)/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise VPNError('powershell7')


def reachable(host, port, tls=True):
    """Reachability only; no database credentials are sent."""
    try:
        with socket.create_connection((host, port), timeout=1.8) as stream:
            if not tls:
                return True
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            try:
                with context.wrap_socket(stream, server_hostname=host):
                    return True
            except ssl.SSLCertVerificationError:
                # A TLS certificate response proves a service answered, not identity.
                return True
    except OSError:
        return False


@contextmanager
def login_lock(path, stop_file=None, timeout=150):
    if os.name != 'nt':
        raise VPNError('windows')
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic()+timeout
        while True:
            check_stop(stop_file)
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise VPNError('busy') from None
                time.sleep(.2)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def child_lifetime(process):
    """Kill only the owned helper if its Python parent is terminated.

    Native VPN agents started by that helper are deliberately outside the job:
    their system tunnel remains available for the user's manual network switch.
    """
    if os.name != 'nt':
        yield
        return
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
            ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
            ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
            ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', ctypes.c_ulonglong*6),
            ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
            ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    try:
        limits = Extended()
        limits.basic.flags = 0x2000 | 0x1000  # KILL_ON_JOB_CLOSE | SILENT_BREAKAWAY_OK
        if (not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle)))):
            raise VPNError('helper_guard')
        yield
    finally:
        if job:
            kernel.CloseHandle(job)


def invoke(host, port, config_path, trust_path, *, stop_file=None, interpreter=None, timeout=150):
    validate_profile(config_path, trust_path)
    check_stop(stop_file)
    command = [powershell(interpreter), '-NoProfile', '-NonInteractive', '-File',
        str(Path(__file__).with_suffix('.ps1')), '-DdbHost', host, '-DdbPort', str(port),
        '-ConfigPath', str(Path(config_path).resolve()), '-TrustPath', str(Path(trust_path).resolve())]
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        with child_lifetime(process):
            # The PS entry point waits for this token before any network/client action.
            # Thus it cannot log in before lifetime protection is attached.
            process.stdin.write('ready\n')
            process.stdin.close()
            process.stdin = None
            deadline = time.monotonic()+timeout
            while True:
                check_stop(stop_file)
                if time.monotonic() >= deadline:
                    raise VPNError('timeout')
                try:
                    output, _ = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
            result = None
            for line in reversed(output.splitlines()):
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and 'state' in value:
                        result = value
                        break
                except ValueError:
                    pass
            if not result:
                raise VPNError('helper')
            if process.returncode or result.get('state') != 'connected' or result.get('tcp_verified') is not True:
                reason = result.get('reason')
                code = ('interactive' if reason in ('interactive_auth_required','authentication_or_additional_factor_required')
                        else 'client' if reason == 'native_agent_not_installed' else 'login')
                raise VPNError(code)
            # Only controlled fields leave this layer; never provider response text.
            return dict(state='connected', mode='native_login' if result.get('mode') == 'native_login' else 'existing_tunnel',
                        tcp_verified=True, tls_pin_verified=result.get('tls_pin_verified') is True)
    except VPNError:
        raise
    except OSError:
        raise VPNError('helper') from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate()


def ensure_connected(connection, config_path, trust_path, *, stop_file=None, interpreter=None):
    host, port = connection.get('host'), connection.get('port')
    if not isinstance(host, str) or not host.strip() or type(port) is not int or not 0 < port < 65536:
        raise VPNError('ddb_target')
    check_stop(stop_file)
    tls = connection.get('enable_ssl', True)
    if reachable(host, port, tls):
        check_stop(stop_file)
        return dict(state='connected', mode='existing_tunnel', tcp_verified=True)
    # The existing native helper verifies SSL DDB reachability.
    if not tls:
        raise VPNError('manual_required')
    with login_lock(Path(config_path).parent/'sslvpn.login.lock', stop_file):
        if reachable(host, port, tls):
            check_stop(stop_file)
            return dict(state='connected', mode='existing_tunnel', tcp_verified=True)
        result = invoke(host, port, config_path, trust_path, stop_file=stop_file, interpreter=interpreter)
        check_stop(stop_file)
        if not reachable(host, port, tls):
            raise VPNError('unreachable')
        return result


MESSAGES = {
    'configuration': 'VPN本机配置或网关证书指纹未就绪；运行 configure_numeric_vpn.cmd，或手动登录后重试。',
    'powershell7': '自动登录需要已有PowerShell 7；配置pwsh.exe路径，或手动登录后重试。',
    'interactive': 'VPN需要核对账号密码或完成验证码/二次认证，请在VPN客户端手动登录后重试。',
    'client': '未找到深信服客户端；请使用公司已安装的VPN客户端手动登录。',
    'busy': '另一VPN登录仍在进行，请稍后重试。',
    'timeout': 'VPN登录超时，登录辅助进程已停止；请检查客户端状态后手动连接。',
    'unreachable': '登录后DDB网络仍不可达，请检查VPN客户端及网络。',
}


def message(error):
    return MESSAGES.get(error.code, 'VPN自动登录未完成，请手动连接后重试；未切换实时行情VPN。')
