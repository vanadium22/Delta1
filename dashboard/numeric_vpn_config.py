"""Configure local VPN credentials separately from the DDB database account."""
import argparse
import getpass
import json
from pathlib import Path
import re
import time

from dashboard.numeric_config import prepare_config
from dashboard.numeric_snapshot import save_snapshot
from dashboard.marketdata.ddb_vpn import normalize_gateway, validate_profile, powershell, VPNError
from index_strategy.history.protected_config import save_config


def configure(local_root, *, reuse_config=None, trust_file=None, gateway=None, fingerprint=None, pwsh=None):
    root = Path(local_root)
    native = root/'native.json'
    config = json.loads(native.read_text(encoding='utf-8-sig'))
    if reuse_config:
        if not trust_file:
            raise ValueError('trust_file_required')
        connection, trust = Path(reuse_config).resolve(), Path(trust_file).resolve()
        validate_profile(connection, trust)
    else:
        gateway = normalize_gateway(gateway or input('VPN HTTPS网关（含端口）: '))
        fingerprint = (fingerprint or input('已核验网关证书SHA256指纹: ')).replace(':','').replace(' ','').strip().upper()
        if not re.fullmatch(r'[A-F0-9]{64}', fingerprint):
            raise ValueError('fingerprint_required')
        username = input('VPN账号（不是DDB数据库账号）: ').strip()
        password = getpass.getpass('VPN密码: ')
        if not username or not password:
            raise ValueError('credentials_required')
        connection, trust = root/'ddb_vpn.local.json', root/'ddb_vpn.trust.local.json'
        save_config(connection, dict(url=gateway, id=username, password=password))
        save_snapshot(dict(endpoint=gateway, certificate_sha256=fingerprint), trust)
    selected = pwsh or config.get('history_vpn_powershell')
    try:
        selected = powershell(selected)
    except VPNError:
        entered = input('已有PowerShell 7的pwsh.exe路径（回车以后配置，仍可手动登录）: ').strip()
        selected = powershell(entered) if entered else None
    backup = native.with_name('native.before_vpn_' + str(time.time_ns()) + '.json')
    backup.write_bytes(native.read_bytes())
    config.update(history_vpn_config=str(connection), history_vpn_trust=str(trust))
    if selected:
        config['history_vpn_powershell'] = selected
    else:
        config.pop('history_vpn_powershell', None)
    save_snapshot(config, native)
    print('VPN配置已保存；数据库账号、数据路径和其他App配置保留。')
    if not selected:
        print('尚未找到PowerShell 7：自动登录前需配置已有pwsh.exe；当前可手动连接后补齐。')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root', type=Path)
    parser.add_argument('--reuse-config', type=Path)
    parser.add_argument('--trust-file', type=Path)
    parser.add_argument('--gateway')
    parser.add_argument('--certificate-sha256')
    parser.add_argument('--powershell')
    args = parser.parse_args(argv)
    try:
        configure(prepare_config(args.local_root), reuse_config=args.reuse_config, trust_file=args.trust_file,
                  gateway=args.gateway, fingerprint=args.certificate_sha256, pwsh=args.powershell)
        return 0
    except Exception:
        print('VPN配置未完成，请检查网关、证书指纹、已有文件或PowerShell路径；不输出凭据。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
