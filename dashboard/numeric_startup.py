"""Numeric Excel startup services; optional local DDB VPN login, manual return."""
import argparse
from datetime import datetime, timedelta
import getpass
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from dashboard.numeric_config import prepare_config
from dashboard.numeric_snapshot import save_snapshot


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def summary(local_root):
    from dashboard.marketdata.bars import BarDataset
    from dashboard.session_clock import session_policy
    config = read(Path(local_root)/'native.json')
    dates = {'1d': [], '1m': []}
    for root in config.get('history_roots', []):
        snap = BarDataset(root).snapshot()
        for frequency in dates:
            days = [p['trade_date'] for p in snap['parts'] if p['frequency'] == frequency]
            if days:
                dates[frequency].append(max(days))
    from dashboard.marketdata.trading_calendar import HOLIDAYS, trading_days
    today = datetime.now().astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date()
    # Summary is strictly offline, including unknown calendar years.
    target = None
    if all(y in HOLIDAYS for y in range((today-timedelta(days=20)).year,today.year+1)):
        _, target = trading_days(str(today), str(today), Path(local_root)/'calendar')
    from dashboard.marketdata.history_publication import maintenance_root
    return dict(local_root=str(local_root), history_dates={k:min(v) if v else None for k,v in dates.items()},
        target=target, gate=session_policy(), python=sys.executable,
        history_status=str(maintenance_root(config['history_roots'])/'status.json') if config.get('history_roots') else None,
        history_python=config.get('history_python') or os.environ.get('SWHY_HISTORY_PYTHON') or sys.executable,
        note='截止日期仅为各目录最新分片；完整缺口在补齐阶段核验')


def history(local_root, report, stop_file, *, cycle=None, max_cycles=20, vpn_mode='auto'):
    from dashboard.marketdata.history_maintenance import run_cycle, open_direct
    from dashboard.marketdata import ddb_vpn
    from index_strategy.history.credentials import load_config
    from index_strategy.history.downloader import DEFAULT_CONFIG
    config = read(Path(local_root)/'native.json')
    connection = config.get('history_connection_file') or DEFAULT_CONFIG
    if cycle is None:
        try:
            credentials = load_config(connection)
            valid = credentials.get('host') and credentials.get('username') and credentials.get('password') and 0 < int(credentials.get('port',0)) < 65536
            credentials.clear()
            if not valid:
                raise ValueError()
        except Exception:
            result = dict(state='waiting_credentials', message='DDB未配置。可使用现有数据；配置入口：dashboard/configure_numeric_history.cmd')
            save_snapshot(result, report)
            return result
        if importlib.util.find_spec('dolphindb') is None:
            result = dict(state='waiting_sdk', message='所选历史Python缺少DDB SDK，请配置已有历史解释器。')
            save_snapshot(result, report)
            return result
    vpn_failure = None
    vpn_cancelled = False
    vpn_connected = False
    def connect(path):
        nonlocal vpn_failure, vpn_cancelled, vpn_connected
        try:
            ddb_vpn.check_stop(stop_file)
            if vpn_mode == 'auto' and not vpn_connected:
                save_snapshot(dict(state='connecting_vpn', message='正在检查DDB网络，必要时自动登录VPN；完成前请勿切换网络。'), report)
                connection = load_config(path)
                try:
                    ddb_vpn.ensure_connected(connection,
                        config.get('history_vpn_config') or Path(local_root)/'ddb_vpn.local.json',
                        config.get('history_vpn_trust') or Path(local_root)/'ddb_vpn.trust.local.json',
                        stop_file=stop_file, interpreter=config.get('history_vpn_powershell'))
                finally:
                    connection.clear()
                vpn_connected = True
                save_snapshot(dict(state='history', message='DDB网络已就绪，正在核验数据库登录及历史缺口。'), report)
            ddb_vpn.check_stop(stop_file)
            return open_direct(path)
        except ddb_vpn.VPNError as exc:
            vpn_failure = ddb_vpn.message(exc)
            raise
        except ddb_vpn.VPNCancelled:
            vpn_cancelled = True
            raise
    fn = cycle or run_cycle
    for attempt in range(max_cycles):
        if stop_file and Path(stop_file).exists():
            result = dict(state='stopped', message='历史任务已停止，原发布数据保留')
            break
        # Reset no user controls. A pre-existing paused task must remain paused.
        options = {} if cycle is not None else dict(direct_factory=connect)
        result = fn(local_root, force=attempt == 0, stop_file=stop_file, **options)
        if vpn_cancelled:
            result.update(state='stopped', message='已取消；VPN登录辅助进程和历史任务已结束，请手动检查VPN状态。')
        elif vpn_failure:
            result.update(state='waiting_vpn', message=vpn_failure)
        save_snapshot(result, report)
        if result.get('state') != 'partial' or not result.get('inserted'):
            break
        # A completed batch schedules the next one slightly later. Do not consume
        # all cycles rereading its old status during that cooldown. Longer source
        # backoffs remain a later explicit retry, not a frozen startup dialog.
        retry_at = result.get('next_retry') or time.time()
        if retry_at > time.time()+6:
            break
        while time.time() < retry_at and not (stop_file and Path(stop_file).exists()):
            time.sleep(min(.2, max(0, retry_at-time.time())))
    save_snapshot(result, report)
    return result


def configure(local_root):
    from index_strategy.history import protected_config
    path = Path(local_root)/'native.json'
    config = read(path)
    connection = Path(local_root)/'ddb.connection.local.json'
    print('仅配置本机DDB数据库；VPN账号另行配置。密码不会显示或写入日志。')
    host = input('DDB地址: ').strip()
    port = int(input('端口: ').strip())
    username = input('账号: ').strip()
    password = getpass.getpass('密码: ')
    ssl = input('启用SSL? [Y/n]: ').strip().lower() != 'n'
    interpreter = input('已有DDB Python完整路径（回车用当前解释器）: ').strip() or sys.executable
    if not host or not username or not password or not 0 < port < 65536 or not Path(interpreter).is_file():
        raise ValueError('地址、端口、账号、密码或解释器路径无效')
    protected_config.save_config(connection, dict(host=host, port=port, username=username, password=password, enable_ssl=ssl))
    # Back up only the numeric copy; other App configurations are untouched.
    backup = path.with_name('native.before_history_' + str(time.time_ns()) + '.json')
    backup.write_bytes(path.read_bytes())
    config.update(history_connection_file=str(connection), history_python=str(Path(interpreter).resolve()))
    save_snapshot(config, path)
    print('已保存本机加密凭据和数字版配置。重开数字Excel后选择检查并补齐。')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['summary','history','probe','configure'])
    parser.add_argument('--local-root', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--vpn-mode', choices=['auto','manual'], default='auto')
    args = parser.parse_args(argv)
    local_root = prepare_config(args.local_root)
    try:
        if args.action == 'configure':
            configure(local_root)
            return 0
        if args.action == 'summary':
            result = summary(local_root)
        elif args.action == 'probe':
            from dashboard.session_guard import probe_realtime
            result = probe_realtime(read(local_root/'native.json'))
        else:
            result = history(local_root, args.report, args.stop_file, vpn_mode=args.vpn_mode)
        if args.report:
            save_snapshot(result, args.report)
        return 0
    except Exception as exc:
        result = dict(state='failed', message='启动检查失败：' + type(exc).__name__ + '；可使用现有数据')
        if args.report:
            save_snapshot(result, args.report)
        else:
            print(result['message'])
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
