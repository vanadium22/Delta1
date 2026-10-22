"""Work Automation entry: a standalone filtered stock-exposure mail draft."""
from datetime import date
import argparse
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


def run_once(root, as_of, *, local_only=False):
    from shared_data.io import file_lock
    from script_making.daily_job import sync_once
    from script_making.service import ReportService
    from script_making.statistics import load_config, risk_statistics, stock_subset
    from script_making.stock_mail import VERSION, REQUIRED, export, load_profile, mail_manifest
    from script_making.storage import Settings, ReportError, atomic_json, sha256, timestamp
    record = {'run_id': uuid4().hex, 'state': 'running', 'as_of': as_of.isoformat(),
              'started_at': timestamp(), 'send_email': False, 'local_only': local_only}
    started = time.monotonic()
    try:
        root = Path(root).resolve()
        mail = load_profile(root, require_to=True)
        settings = Settings(root)
        values, filters = settings.get(), load_config(root)
        filters = {key: filters[key] for key in ('metric', 'threshold', 'exclusions')}
        base = settings.data_path(values)
        class FrozenSettings:
            def __init__(self):
                self.root = root
            def get(self):
                return dict(values)
            def data_path(self, ignored=None):
                return base
        runs = base / 'statistics/swap_stock_runs'
        with file_lock(base / 'statistics/.daily_job.lock', timeout=0):
            try:
                day = None
                if not local_only:
                    cache = root / 'cache/swap_stock_jobs'
                    cache.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(dir=cache) as temporary:
                        frozen = Path(temporary)
                        atomic_json(frozen / 'config.local.json', {**values, 'data_dir': str(base)})
                        try:
                            synced = sync_once(frozen, as_of, 'pair')
                        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                            raise ReportError('本次收益互换来源同步未完成：' + str(exc)) from exc
                    record['sync'] = synced
                    if synced.get('errors'):
                        raise ReportError('本次来源同步不完整，不使用旧本地数据代替。')
                    day = synced.get('date')
                service = ReportService(root)
                service.settings = FrozenSettings()
                catalog = service.query_catalog()
                if local_only:
                    day = next((entry['date'] for entry in catalog['dates']
                                if 'swap' in entry['files'] and entry['date'] < as_of.isoformat()), None)
                if not day or day >= as_of.isoformat():
                    raise ReportError('没有早于截止日的本次收益互换来源。')
                entry = next((entry for entry in catalog['dates'] if entry['date'] == day and 'swap' in entry['files']), None)
                if entry is None:
                    raise ReportError('本次收益互换来源日期未取得，不退回旧日期。')
                path = Path(entry['files']['swap']['path'])
                digest = sha256(path)
                risk = risk_statistics(path, day, 'swap', filters)
                snapshot = {'id': uuid4().hex, 'created_at': timestamp(), 'kind': 'swap_stock_exposure',
                            'config': filters, 'sources': {'swap': {'date': day, 'path': str(path), 'sha256': digest}},
                            'swap_stocks': stock_subset(risk), 'errors': {}}
                if sha256(path) != digest:
                    raise ReportError('读取期间来源发生变化，请重新生成。')
                statistics_record = base / 'statistics/swap_stock_records' / (snapshot['id'] + '.json')
                atomic_json(statistics_record, snapshot)
                record.update(statistics_record=str(statistics_record), report_date=day)
                identity = {key: value for key, value in snapshot.items() if key not in ('id', 'created_at')}
                fingerprint = hashlib.sha256(json.dumps({'version': VERSION, 'snapshot': identity, 'mail': mail},
                                                       ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                index = runs / 'completed' / (fingerprint + '.json')
                exports = base / 'statistics/swap_stock_exports'
                if index.is_file():
                    try:
                        prior = json.loads(index.read_text(encoding='utf-8'))
                        folder, files = Path(prior['export_directory']), prior['files']
                        if (folder.resolve().is_relative_to(exports.resolve()) and REQUIRED.issubset(files)
                                and all(Path(name).name == name and sha256(folder / name) == digest for name, digest in files.items())):
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
                folder = export(exports, snapshot, mail)
                mail_manifest(folder)
                atomic_json(index, {'export_directory': str(folder), 'files': {name: sha256(folder / name) for name in REQUIRED}})
                record.update(state='success', fingerprint=fingerprint, export_directory=str(folder))
                return 0, record
            except ReportError as exc:
                record.update(state='incomplete', reason=str(exc))
                return 2, record
            except Exception as exc:
                record.update(state='failed', reason=str(exc), error_type=type(exc).__name__)
                return 1, record
            finally:
                record.update(finished_at=timestamp(), elapsed_seconds=round(time.monotonic() - started, 3))
                atomic_json(runs / (record['run_id'] + '.json'), record)
                atomic_json(runs / 'latest.json', record)
    except TimeoutError:
        record.update(state='busy', reason='日报或其他独立任务正在使用同一目录。')
        return 3, record
    except Exception as exc:
        record.update(state='failed', reason=str(exc), error_type=type(exc).__name__)
        return 1, record


def main(argv=None):
    parser = argparse.ArgumentParser(description='纯个股敞口独立邮件任务；程序只生成，不发信')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--run', action='store_true')
    modes.add_argument('--inspect', action='store_true')
    modes.add_argument('--task-definition', action='store_true')
    modes.add_argument('--register-task', action='store_true')
    parser.add_argument('--work-root', type=Path)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--time', default='09:20')
    parser.add_argument('--as-of', type=date.fromisoformat)
    parser.add_argument('--local-only', action='store_true')
    parser.add_argument('--wa-output', type=Path)
    args = parser.parse_args(argv)
    if (args.as_of or args.local_only or args.wa_output) and not args.run:
        parser.error('--as-of、--local-only、--wa-output 只可与 --run 合用')
    if args.register_task and not args.work_root:
        parser.error('--register-task 需要 --work-root')
    from script_making.stock_mail import load_profile, mail_manifest
    from script_making.storage import atomic_json, today
    try:
        if args.run:
            code, result = run_once(args.root, args.as_of or today(), local_only=args.local_only)
            if code == 0 and args.wa_output:
                atomic_json(args.wa_output, mail_manifest(result['export_directory']))
        elif args.task_definition or args.register_task:
            from script_making.stock_task_registration import task_definition, register
            task = task_definition(args.root, args.time)
            if args.register_task:
                load_profile(args.root, require_to=True)
                result = register(args.work_root, task, args.port)
            else:
                result = {'state': 'task_definition_only', 'task': task, 'send_email': False}
            code = 0
        else:
            result, code = {'state': 'inspection_only', 'mail_configured': bool(load_profile(args.root)['to']), 'send_email': False}, 0
        print(json.dumps({k: v for k, v in result.items() if k != 'sync'}, ensure_ascii=False, indent=2))
        return code
    except Exception as exc:
        print(json.dumps({'state': 'failed', 'reason': str(exc), 'send_email': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
