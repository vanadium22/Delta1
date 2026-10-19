"""Windows current-user DPAPI configuration; never returns secrets in diagnostics."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import uuid


class CredentialError(RuntimeError):
    pass


def _crypt(data, decrypt=False):
    if os.name != 'nt':
        raise CredentialError('Credentials require the original Windows user on this machine')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    api = ctypes.WinDLL('crypt32', use_last_error=True)
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise CredentialError('Windows credential protection failed; re-enter credentials on this machine')
    kernel = ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes = [ctypes.c_void_p]
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.memset(target.data, 0, target.size)
        kernel.LocalFree(target.data)


def private_acl(path):
    if os.name != 'nt':
        os.chmod(path, 0o600);return
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    adv.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    # Owner rights and SYSTEM only; disable inherited access to this file.
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;;FA;;;OW)(A;;FA;;;SY)', 1, ctypes.byref(descriptor), None):
        raise CredentialError('Could not create private credential permissions')
    kernel = ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes = [ctypes.c_void_p]
    try:
        if not adv.SetFileSecurityW(str(Path(path).resolve()), 0x80000004, descriptor):
            raise CredentialError('Could not restrict credential file permissions')
    finally:
        kernel.LocalFree(descriptor)


def load_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        blob = value.pop('protected_credentials', None)
        if blob:
            if blob.get('scheme') != 'windows-dpapi-current-user-v1':
                raise CredentialError('Unsupported credential protection')
            decoded = json.loads(_crypt(base64.b64decode(blob['data'], validate=True), True))
            if not isinstance(decoded, dict) or not set(decoded) <= {'username', 'id', 'password'}:
                raise CredentialError('Invalid protected credential fields')
            value.update(decoded)
        return value
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('Local credentials could not be read') from None


def save_config(path, value):
    path = Path(path);value = dict(value)
    secrets = {k: value.pop(k) for k in ('username', 'id', 'password') if k in value}
    if not secrets.get('password'):
        raise CredentialError('Password is required')
    blob = _crypt(json.dumps(secrets, ensure_ascii=False).encode('utf8'))
    if json.loads(_crypt(blob, True)) != secrets:
        raise CredentialError('Credential readback verification failed')
    value['protected_credentials'] = dict(scheme='windows-dpapi-current-user-v1', data=base64.b64encode(blob).decode('ascii'))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.touch(exist_ok=False);private_acl(temp)
        with temp.open('w', encoding='utf8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2);handle.flush();os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {'protected': True, 'scheme': 'windows-dpapi-current-user-v1'}


def migrate(path):
    return save_config(path, load_config(path))


if __name__ == '__main__':
    import argparse
    import getpass
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--kind',choices=['ddb','vpn'],default='ddb')
    parser.add_argument('--migrate',action='store_true')
    args=parser.parse_args()
    try:
        if args.migrate:migrate(args.config)
        else:
            try:config=load_config(args.config)
            except CredentialError:
                config=json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config.exists() else {}
                config.pop('protected_credentials',None)
            if args.kind=='ddb':
                config['host']=input('DDB host: ').strip();config['port']=int(input('DDB port: '))
                config['username']=input('DDB account: ').strip();config.setdefault('enable_ssl',True)
            else:
                config['url']=input('VPN HTTPS gateway: ').strip();config['id']=input('VPN account: ').strip()
            config['password']=getpass.getpass('Password (hidden): ')
            save_config(args.config,config)
        print('Credentials protected and verified. No network login performed.')
    except Exception:
        raise SystemExit('Credential configuration failed; no secret diagnostic output.') from None
