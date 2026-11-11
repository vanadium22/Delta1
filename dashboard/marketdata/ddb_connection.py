"""App endpoint policy, separate from the existing protected credentials."""
import json
from pathlib import Path
import re

# Confirmed by the user on 2026-11-11. These contain no account information.
APP_HOST='192.168.198.77'
APP_PORT=8904


def validate_endpoint(host,port):
    host=str(host).strip()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',host):
        raise ValueError('invalid_ddb_host')
    if isinstance(port,bool):raise ValueError('invalid_ddb_port')
    port=int(str(port).strip())
    if not 1<=port<=65535:raise ValueError('invalid_ddb_port')
    return dict(host=host,port=port)


def app_endpoint(config):
    """Explicit App endpoint wins; otherwise use the published current server."""
    if config.get('history_ddb_host') or config.get('history_ddb_port'):
        return {**validate_endpoint(config.get('history_ddb_host',''),config.get('history_ddb_port','')),
                'source':'app_setting'}
    return dict(host=APP_HOST,port=APP_PORT,source='confirmed_2026-11-11')


def connection_summary(config,path=None):
    from dashboard.app_config import connection_path
    path=Path(path) if path is not None else connection_path(config)
    result=dict(credentials_reference=str(path),configured=path.is_file(),network_tested=False)
    try:
        result.update(app_endpoint(config))
    except (TypeError,ValueError):
        result.update(source='invalid_app_setting',error_type='InvalidEndpoint')
    try:
        saved=json.loads(path.read_text(encoding='utf-8-sig'))
        original=validate_endpoint(saved.get('host',''),saved.get('port',''))
        result.update(saved_host=original['host'],saved_port=original['port'],
            saved_endpoint_matches=all(result.get(k)==original[k] for k in ('host','port')))
    except (OSError,ValueError,TypeError,AttributeError):pass
    return result


def with_endpoint(connection,endpoint):
    """Return a transient connection; never rewrite or re-encrypt the provider."""
    return {**connection,**validate_endpoint(endpoint['host'],endpoint['port'])}
