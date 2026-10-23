"""Resolve existing local profiles without rewriting data paths or credentials."""
import json
from pathlib import Path

MODULE_ROOT=Path(__file__).resolve().parent


def prepare_config(local_root=None, *, module_root=MODULE_ROOT):
    if local_root is not None:return Path(local_root).resolve()
    base=Path(module_root)/'localsetting'
    target=base/'app'
    if (target/'native.json').is_file():return target
    source=base/'numeric_excel'
    if not (source/'native.json').is_file():
        return base if (base/'native.json').is_file() else target
    target.mkdir(parents=True,exist_ok=True)
    for name in ('native.json','native_formulas.json','indicator_preferences.json'):
        original=source/name
        if not original.is_file():continue
        raw=original.read_text(encoding='utf-8-sig');value=json.loads(raw)
        if name=='native.json':
            for key,filename in (('history_vpn_config','ddb_vpn.local.json'),('history_vpn_trust','ddb_vpn.trust.local.json')):
                if not value.get(key) and (source/filename).is_file():value[key]=str((source/filename).resolve())
            if value!=json.loads(raw):raw=json.dumps(value,ensure_ascii=False,indent=2)
        try:
            with (target/name).open('x',encoding='utf8') as f:f.write(raw)
        except FileExistsError:pass
    return target


def connection_path(config):
    if config.get('history_connection_file'):return Path(config['history_connection_file'])
    from index_strategy.history.downloader import DEFAULT_CONFIG
    default=Path(DEFAULT_CONFIG)
    if default.is_file():return default
    candidates=[]
    for parent in MODULE_ROOT.parents:
        for relative in ('dolphindb_data/config/connection.local.json','project/dolphindb_data/config/connection.local.json'):
            path=parent/relative
            if path.is_file() and path not in candidates:candidates.append(path)
    # A unique known legacy installation is a reference, never a credential copy.
    return candidates[0] if len(candidates)==1 else default


def history_python(config):
    import os,sys,importlib.util
    explicit=config.get('history_python') or os.environ.get('SWHY_HISTORY_PYTHON')
    if explicit:return explicit
    if importlib.util.find_spec('dolphindb') is not None:return sys.executable
    legacy=connection_path(config).parent.parent/'.venv/Scripts/python.exe'
    return str(legacy) if legacy.is_file() else sys.executable


def credential_state(config,local_root=None):
    """Read/decrypt locally; export only availability and scheme, never secrets."""
    from index_strategy.history.credentials import load_config
    path=connection_path(config)
    result=dict(reference=str(path),configured=path.is_file(),available=False,
                stage='credential_reference',vpn_changed=False)
    try:
        raw=json.loads(path.read_text(encoding='utf-8-sig'))
        result['protection']=(raw.get('protected_credentials') or {}).get('scheme','existing_provider_policy')
        value=load_config(path)
        result.update(available=bool(value.get('password') and value.get('host') and value.get('port') and value.get('username')),
                      stage='credential_decryption')
        value.clear();raw.clear()
    except Exception as exc:result['error_type']=type(exc).__name__
    # VPN credentials remain a separate reference and are never used to log in.
    vpn=config.get('history_vpn_config') or config.get('ddb_vpn_config') or (Path(local_root)/'ddb_vpn.local.json' if local_root else None)
    info=dict(reference=str(vpn) if vpn else None,used=False,policy='manual_network_only',available=False)
    if vpn and Path(vpn).is_file():
        try:
            raw=json.loads(Path(vpn).read_text(encoding='utf-8-sig'))
            info['protection']=(raw.get('protected_credentials') or {}).get('scheme','existing_provider_policy')
            value=load_config(vpn);info['available']=bool(value.get('password'));value.clear();raw.clear()
        except Exception as exc:info['error_type']=type(exc).__name__
    result['vpn']=info
    return result
