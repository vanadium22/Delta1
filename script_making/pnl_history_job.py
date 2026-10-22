"""Standalone Work Automation program for the self-only OTC/group history task."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def history_diagnostics(snapshot):
    """Describe an existing snapshot without exposing amounts or reading its sources."""
    if (not isinstance(snapshot, dict) or snapshot.get('kind') != 'otc_group_history'
            or not isinstance(snapshot.get('errors'), dict)
            or not isinstance(snapshot.get('reports'), list)
            or not isinstance(snapshot.get('otc'), list)):
        raise ValueError('请指定独立收益任务的 pnl_history_records 统计记录JSON。')
    errors, points = snapshot['errors'], snapshot['otc']
    if (not all(isinstance(day, str) and isinstance(reason, str) for day, reason in errors.items())
            or not all(isinstance(point, dict) and isinstance(point.get('date'), str) for point in points)):
        raise ValueError('独立收益任务统计记录中的历史诊断结构无效。')
    recent = [{'date': point['date'], 'previous_date': point.get('previous_date'),
               'has_current': point.get('current') is not None,
               'has_change': point.get('change') is not None} for point in points[-2:]]
    complete = not errors and bool(recent) and recent[-1]['has_change']
    diagnostics = {'through': snapshot.get('through'), 'report_count': len(snapshot['reports']),
                   'error_count': len(errors), 'errors': dict(errors), 'recent_otc': recent,
                   'complete': complete}
    if errors:
        day = max(errors)
        reason = f'历史报表有{len(errors)}份解析失败；最近异常 {day}：{errors[day]}；不生成可发送草稿。'
    elif not recent:
        reason = '未取得场外业务合计历史；不生成可发送草稿。'
    elif not recent[-1]['has_change']:
        day = recent[-1]['date']
        if len(points) == 1:
            reason = f'当年仅取得1份报表，{day} 缺少可相减的上期数据；不生成可发送草稿。'
        elif not recent[-1]['has_current']:
            reason = f'{day} 未取得本期场外业务合计缓存；不生成可发送草稿。'
        else:
            reason = f'{day} 未取得可相减的上期数据或区间差额；不生成可发送草稿。'
    else:
        reason = '已有统计记录的历史完整性检查通过；仅诊断，未生成或发送邮件。'
    return diagnostics, reason


def run_once(root, as_of, *, local_only=False):
    from shared_data.io import file_lock
    from script_making.daily_job import sync_once
    from script_making.pnl_history import (VERSION, REQUIRED, build_history, export_history,
                                         load_self_config, mail_manifest)
    from script_making.service import ReportService
    from script_making.storage import ReportError, Settings, atomic_json, sha256, timestamp
    record = {'run_id': uuid4().hex, 'state': 'running', 'send_email': False,
              'started_at': timestamp(), 'as_of': as_of.isoformat(), 'local_only': local_only}
    started = time.monotonic()
    try:
        root = Path(root).resolve()
        config = load_self_config(root)  # Never inherit the main daily report's recipients.
        settings = Settings(root)
        values = settings.get()
        base = settings.data_path(values)
        runs = base / 'statistics/pnl_history_runs'
        class FrozenSettings:
            def __init__(self):
                self.root = root
            def get(self):
                return dict(values)
            def data_path(self, ignored=None):
                return base
        try:
            # Shared with the original daily run: one writer to the same report archive.
            with file_lock(base / 'statistics/.daily_job.lock', timeout=0):
                atomic_json(runs / (record['run_id'] + '.json'), record)
                try:
                    through = None
                    if not local_only:
                        cache = root / 'cache/pnl_history_jobs'
                        cache.mkdir(parents=True, exist_ok=True)
                        with tempfile.TemporaryDirectory(dir=cache) as temporary:
                            frozen = Path(temporary)
                            atomic_json(frozen / 'config.local.json', {**values, 'data_dir': str(base)})
                            try:
                                result = sync_once(frozen, as_of, 'pnl')
                            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                                record.update(state='incomplete', reason='本次盈亏统计同步未完成：' + str(exc))
                                return 2, record
                        record['sync'] = result
                        through = result.get('source_latest')
                        if result.get('errors') or not through:
                            record.update(state='incomplete', reason='本次盈亏统计同步不完整，不使用旧本地来源冒充。')
                            return 2, record
                    service = ReportService(root)
                    service.settings = FrozenSettings()
                    if local_only:
                        through = next((e['date'] for e in service.query_catalog()['dates']
                                        if 'pnl' in e['files'] and e['date'] < as_of.isoformat()), None)
                    if not through or through >= as_of.isoformat():
                        record.update(state='incomplete', reason='没有早于截止日的本次盈亏统计来源。')
                        return 2, record
                    try:
                        snapshot = build_history(service, through, config)
                    except ReportError as exc:
                        record.update(state='incomplete', reason=str(exc))
                        return 2, record
                    path = base / 'statistics/pnl_history_records' / (snapshot['id'] + '.json')
                    atomic_json(path, snapshot)
                    record['statistics_record'] = str(path)
                    if snapshot['errors'] or snapshot['otc'][-1]['change'] is None:
                        diagnostics, reason = history_diagnostics(snapshot)
                        record.update(state='incomplete', diagnostics=diagnostics, reason=reason)
                        return 2, record
                    identity = {k: v for k, v in snapshot.items() if k not in ('id', 'created_at')}
                    fingerprint = hashlib.sha256(json.dumps({'version': VERSION, 'snapshot': identity},
                                                           ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    completed = runs / 'completed' / (fingerprint + '.json')
                    export_root = base / 'statistics/pnl_history_exports'
                    if completed.exists():
                        try:
                            prior = json.loads(completed.read_text(encoding='utf-8'))
                            folder = Path(prior['export_directory'])
                            files = prior['files']
                            if (folder.resolve().is_relative_to(export_root.resolve())
                                    and REQUIRED.issubset(files)
                                    and all(Path(name).name == name and (folder / name).is_file()
                                            and sha256(folder / name) == digest for name, digest in files.items())):
                                mail_manifest(folder)
                                record.update(state='reused', fingerprint=fingerprint, export_directory=str(folder))
                                return 0, record
                        except (OSError, ValueError, KeyError, TypeError):
                            pass
                    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
                    from PySide6.QtWidgets import QApplication
                    from PySide6.QtGui import QFontDatabase
                    app = QApplication.instance() or QApplication([])
                    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
                    if font.is_file():
                        QFontDatabase.addApplicationFont(str(font))
                    folder = export_history(export_root, snapshot)
                    mail_manifest(folder)
                    atomic_json(completed, {'export_directory': str(folder),
                                            'files': {name: sha256(folder / name) for name in REQUIRED}})
                    record.update(state='success', fingerprint=fingerprint, export_directory=str(folder))
                    return 0, record
                except Exception as exc:
                    record.update(state='failed', error_type=type(exc).__name__, reason=str(exc))
                    return 1, record
                finally:
                    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
                    record['finished_at'] = timestamp()
                    atomic_json(runs / (record['run_id'] + '.json'), record)
                    atomic_json(runs / 'latest.json', record)
        except TimeoutError:
            record.update(state='busy', reason='日报或独立收益任务正在使用同一数据目录，本次未重复执行。')
            return 3, record
    except Exception as exc:
        record.update(state='failed', error_type=type(exc).__name__, reason=str(exc))
        return 1, record


def main(argv=None):
    parser = argparse.ArgumentParser(description='本人专用场外业务及各组收益两图；默认只读检查，程序不发邮件')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--diagnose-record', type=Path, metavar='JSON',
                      help='只读诊断已有收益历史统计记录，不同步、不运行任务、不修改设置')
    mode.add_argument('--set-self-email', metavar='EMAIL', help='仅保存本任务的单一本人邮箱，不运行任务')
    parser.add_argument('--as-of', type=date.fromisoformat)
    parser.add_argument('--local-only', action='store_true')
    parser.add_argument('--wa-output', type=Path)
    args = parser.parse_args(argv)
    if (args.local_only or args.wa_output or args.as_of) and not args.run:
        parser.error('--local-only、--as-of、--wa-output 只可与 --run 合用')
    from script_making.pnl_history import CONFIG_NAME, load_self_config, mail_manifest, self_config
    from script_making.storage import atomic_json, today
    try:
        if args.diagnose_record is not None:
            snapshot = json.loads(args.diagnose_record.read_text(encoding='utf-8'))
            diagnostics, reason = history_diagnostics(snapshot)
            result, code = {'state': 'diagnostic_only', 'send_email': False,
                            'statistics_record': str(args.diagnose_record.resolve()),
                            'diagnostics': diagnostics, 'reason': reason}, 0
        elif args.set_self_email is not None:
            config = self_config({'to': args.set_self_email})
            atomic_json(args.root / CONFIG_NAME, config)
            result, code = {'state': 'configured', 'send_email': False}, 0
        elif args.run:
            code, result = run_once(args.root, args.as_of or today(), local_only=args.local_only)
            if code == 0 and args.wa_output:
                atomic_json(args.wa_output, mail_manifest(result['export_directory']))
        else:
            configured = False
            if (args.root / CONFIG_NAME).exists():
                load_self_config(args.root)
                configured = True
            result, code = {'state': 'inspection_only', 'self_email_configured': configured,
                            'config_file': str((args.root / CONFIG_NAME).resolve()),
                            'send_email': False}, 0
        print(json.dumps({k: v for k, v in result.items() if k not in ('sync',)}, ensure_ascii=False, indent=2))
        return code
    except Exception as exc:
        print(json.dumps({'state': 'failed', 'reason': str(exc), 'send_email': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
