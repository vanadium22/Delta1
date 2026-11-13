"""Validate and save a new local VPN profile without replacing older ones."""
import json
from pathlib import Path
import re
import uuid

from .marketdata.bars import _atomic_bytes,_json_bytes
from .marketdata.ddb_vpn import normalize_gateway,VPNError
from index_strategy.history.protected_config import save_config

DEFAULT_GATEWAY='https://210.22.83.97:10443'
DEFAULT_FINGERPRINT='7D8F3700892DBD417706E195EEB865103E56B70FC7820F5129C8385B4C2E9EAD'


def display_defaults(config_path,trust_path,*,allow_default=True):
    """Use existing trust first; only initialize a completely new profile."""
    current=metadata(config_path,trust_path)
    if current:return current
    if not allow_default or Path(config_path).exists() or Path(trust_path).exists():return {}
    return dict(gateway=DEFAULT_GATEWAY,fingerprint=DEFAULT_FINGERPRINT)


def metadata(config_path,trust_path):
    """Return only the gateway and matching certificate fingerprint."""
    try:
        config=json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        trust=json.loads(Path(trust_path).read_text(encoding='utf-8-sig'))
        gateway=normalize_gateway(config['url']);fingerprint=str(trust['certificate_sha256']).replace(':','').replace(' ','').upper()
        if gateway!=normalize_gateway(trust['endpoint']) or not re.fullmatch(r'[A-F0-9]{64}',fingerprint):return {}
        return dict(gateway=gateway,fingerprint=fingerprint)
    except (OSError,ValueError,TypeError,KeyError,VPNError):return {}


def prepare(local_root,gateway,fingerprint,username,password):
    gateway=normalize_gateway(gateway)
    fingerprint=str(fingerprint).replace(':','').replace(' ','').strip().upper()
    if not re.fullmatch(r'[A-F0-9]{64}',fingerprint):raise ValueError('invalid_fingerprint')
    if not username or not password:raise ValueError('missing_credentials')
    root=Path(local_root)/'vpn_profiles';identifier=uuid.uuid4().hex
    connection=root/('ddb-vpn-'+identifier+'.local.json')
    trust=root/('ddb-vpn-'+identifier+'.trust.local.json')
    save_config(connection,dict(url=gateway,id=username,password=password))
    _atomic_bytes(trust,_json_bytes(dict(endpoint=gateway,certificate_sha256=fingerprint)))
    return dict(history_vpn_config=str(connection.resolve()),history_vpn_trust=str(trust.resolve()))
