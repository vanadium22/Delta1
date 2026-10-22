"""Explicit Work Automation acceptance; synthetic files and fake SMTP only."""
import argparse
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root', required=True, type=Path)
    parser.add_argument('--task-python', required=True, type=Path)
    args = parser.parse_args()
    sys.path[:0] = [str(args.work_root.resolve()), str(args.work_root.resolve() / 'tests')]
    from mail_app.store import Store
    from mail_app.work import WorkTasks
    from mail_app.mail import transmit
    from test_workflows import FakeSMTP, connection
    from script_making.service import ReportService
    from script_making.downloads import archive_path
    from script_making.storage import atomic_json, filename, sha256
    from script_making.statistics import build_snapshot, save_config
    from script_making.statistics_export import export_bundle, render_pages
    from script_making.tests.test_pnl_history import sector_book
    from script_making.tests.test_statistics import risk_book
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    output = PROJECT / 'script_making/cache' / ('pnl-history-qa-' + uuid4().hex)
    output.mkdir(parents=True)
    service = ReportService(output / 'module')
    service.update_settings({'data_dir': str(output / 'synthetic-data'), 'source_root': '', 'pnl_source': '', 'strategy_source': ''})
    for i in range(292):
        day = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        sector_book(archive_path(service.settings, 'pnl') / day / f'盈亏统计_{day}_new_adjust.xlsx', day, i - 160)
    for kind, day in (('swap', '2026-10-14'), ('strategy', '2026-10-19')):
        path = (service.settings.data_path() / day / filename('swap', day) if kind == 'swap' else
                archive_path(service.settings, kind) / day / f'D1策略台日报_{day}.xlsx')
        risk_book(path, day)
    config = save_config(service.settings.root, {'to': 'team@example.invalid', 'cc': 'manager@example.invalid'})
    atomic_json(service.settings.root / 'pnl_history.local.json', {'to': 'self@example.invalid'})
    original_config_hash = sha256(service.settings.root / 'statistics.local.json')
    store = Store(output / 'workbench')
    work = WorkTasks(store)
    noop = output / 'noop.py'
    noop.write_text("print('synthetic task; never executed')\n", encoding='utf-8')
    existing = []
    for name, clock in (('原日报', '09:20'), ('FOF', '15:00')):
        saved = work.save({'name': name, 'program': str(noop), 'interpreter': str(args.task_python),
                           'enabled': True, 'schedule': {'type': 'daily', 'time': clock}})
        existing.append(saved)
    spec = {'name': '本人场外与各组收益（合成隔离）', 'program': str(PROJECT / 'script_making/pnl_history_job.py'),
            'interpreter': str(args.task_python), 'cwd': str(PROJECT), 'enabled': False,
            'arguments': ['--root', str(service.settings.root), '--run', '--local-only', '--as-of', '2026-10-21'],
            'schedule': {'type': 'manual'}, 'result_mail': 'preview'}
    saved = work.save(spec)
    spec['id'] = saved['id']
    def execute(batch):
        run = work.enqueue(saved['id'], batch)
        work.execute_one()
        result = work.run(run['id'])
        assert result['exit_code'] == 0 and result['status'] == 'success', result
        return result
    preview_run = execute('preview')
    manifest = preview_run['result']['mail_manifest']
    assert manifest['mail']['to'] == ['self@example.invalid']
    assert manifest['mail']['cc'] == manifest['mail']['bcc'] == []
    assert len(manifest['mail']['attachments']) == 2
    assert store.history('outbox') == []
    history_folder = Path(manifest['mail']['attachments'][0]['path']).parent
    spec['result_mail'] = 'queue'
    work.save(spec)
    execute('send-to-fake')
    fake = FakeSMTP()
    with patch('mail_app.mail.smtp_connection', connection(fake)):
        transmit(store, store.claim_mail())
    assert len(fake.sent) == 1
    sent, _, recipients = fake.sent[0]
    assert recipients == ['self@example.invalid']
    assert not sent.get('Cc') and not sent.get('Bcc')
    assert sent.get_body(('plain',)) and sent.get_body(('html',))
    images = [p for p in sent.walk() if p.get_filename()]
    assert {p.get_filename() for p in images} == {'otc_pnl.png', 'groups_pnl.png'}
    for part in images:
        assert part.get_payload(decode=True) == (history_folder / part.get_filename()).read_bytes()
        assert part.get('Content-ID') and part.get_content_disposition() == 'inline'
    (output / 'fake-smtp.eml').write_bytes(sent.as_bytes())
    store = Store(store.root)
    work = WorkTasks(store)
    execute('restart-new-batch')
    assert len(store.history('outbox')) == 1 and store.claim_mail() is None
    current = {t['id']: t for t in work.tasks()}
    for original in existing:
        assert current[original['id']] == original
    assert sha256(service.settings.root / 'statistics.local.json') == original_config_hash
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    snap = build_snapshot(service, {'pnl': '2026-10-19', 'previous': '2026-10-18',
                                   'swap': '2026-10-14', 'strategy': '2026-10-19'}, config)
    pages = render_pages(snap)
    daily_folder = export_bundle(output / 'daily-export', snap, pages, config)
    msg = BytesParser(policy=policy.default).parsebytes((daily_folder / '邮件草稿.eml').read_bytes())
    assert msg['To'] == 'team@example.invalid' and msg['Cc'] == 'manager@example.invalid'
    assert {p.get_filename() for p in msg.walk() if p.get_filename()} == {'pnl1.png', 'risk.png', 'swap_stocks.png'}
    result = {'ok': True, 'history_export': str(history_folder), 'daily_export': str(daily_folder),
              'evidence': str(output), 'checks': ['292-report full-year histories', 'actual selected Conda/Windows Job',
              'exact two CID images and plain/HTML through fake SMTP', 'self-only recipient',
              'preview before send', 'restart/new-batch sends once', 'original daily/FOF definitions unchanged',
              'main report recipients and three-image contract unchanged']}
    atomic_json(output / 'acceptance.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
