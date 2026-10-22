"""Explicit Work Automation acceptance; synthetic files and fake SMTP only."""
import argparse
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))


def verify_images(message, paths, *, regular):
    """Inspect the actual SMTP MIME, including independent downloadable files."""
    expected = {path.name: path for path in paths}
    parts = [p for p in message.walk() if p.get_filename()]
    assert len(parts) == len(expected) * (2 if regular else 1)
    assert message.get_body(('plain',)) and message.get_body(('html',))
    for disposition in (('inline', 'attachment') if regular else ('inline',)):
        selected = [p for p in parts if p.get_content_disposition() == disposition]
        assert len(selected) == len(expected)
        assert {p.get_filename() for p in selected} == set(expected)
        for part in selected:
            assert part.get_payload(decode=True) == expected[part.get_filename()].read_bytes()
            if disposition == 'inline':
                assert part.get('Content-ID')
                assert 'cid:' + str(part['Content-ID'])[1:-1] in message.get_body(('html',)).get_content()
            else:
                assert part.get('Content-ID') is None


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
        sector_book(archive_path(service.settings, 'pnl') / day / f'盈亏统计_{day}_new_adjust.xlsx',
                    day, i - 160, option_value=79)  # Deliberately differs from the five industries.
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
    def execute(batch, task_id=None):
        run = work.enqueue(task_id or saved['id'], batch)
        work.execute_one()
        result = work.run(run['id'])
        assert result['exit_code'] == 0 and result['status'] == 'success', result
        return result
    preview_run = execute('preview')
    manifest = preview_run['result']['mail_manifest']
    assert manifest['mail']['to'] == ['self@example.invalid']
    assert manifest['mail']['cc'] == manifest['mail']['bcc'] == []
    assert len(manifest['mail']['attachments']) == 2
    history_record = json.loads((Path(manifest['mail']['attachments'][0]['path']).parent / '统计记录.json').read_text(encoding='utf-8'))
    assert [g['name'] for g in history_record['groups']] == [
        '境内权益互换台', '境内个股期权台', '用于验证长名称换行的其他业务汇总组']
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
    assert '13 + 14' in pages[0] and '15 + 16' in pages[0]
    assert '<b>境内个股期权台</b>' not in pages[0]
    assert not snap['errors']
    daily_folder = export_bundle(output / 'daily-export', snap, pages, config)
    msg = BytesParser(policy=policy.default).parsebytes((daily_folder / '邮件草稿.eml').read_bytes())
    assert msg['To'] == 'team@example.invalid' and msg['Cc'] == 'manager@example.invalid'
    assert {p.get_filename() for p in msg.walk() if p.get_filename()} == {'pnl1.png', 'risk.png', 'swap_stocks.png'}
    verify_images(msg, [daily_folder / name for name in ('pnl1.png', 'risk.png', 'swap_stocks.png')], regular=True)
    # The new stock task uses the same stock subset as the daily attachment,
    # with separately configured recipients and the existing Work Automation API.
    from script_making.independent_mail_widgets import IndependentMailDialog
    from script_making.stock_task_registration import task_definition, register_with_client
    from script_making.statistics_widgets import StatisticsPage
    from mail_app.server import Server
    from mail_app.client import MailClient
    stock_rows = [[f'{600001 + i}.SH', f'合成股票{i + 1}的长名称用于检查完整明细',
                   (i + 1) * 1000 * (-1 if i % 2 else 1), (i + 1) * 30,
                   (i + 1) * 100, (i + 1) * 750000 * (-1 if i % 2 else 1)] for i in range(25)]
    stock_rows.extend([['512200.SH', '其他ETF', 1, 2, 3, 9000000],
                       ['000300.SH', '指数', 1, 2, 3, 9000000]])
    risk_book(service.path_for('swap', '2026-10-14'), '2026-10-14', stock_rows)
    stock_daily = build_snapshot(service, {'pnl': '2026-10-19', 'previous': '2026-10-18',
                                          'swap': '2026-10-14', 'strategy': '2026-10-19'}, config)
    dialog = IndependentMailDialog(service.settings.root)
    dialog.entries['to'].setText('stock@example.invalid')
    dialog.entries['cc'].setText('risk@example.invalid')
    dialog.note.setPlainText('合成隔离验收；仅供本组合观察。')
    dialog.save()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.show(); app.processEvents()
    dialog.grab().save(str(output / 'independent-mail-settings.png'))
    dialog.close()
    with patch('script_making.statistics_widgets.QTimer.singleShot'):
        page = StatisticsPage(service)
    page.resize(1120, 720); page.show(); app.processEvents()
    page.grab().save(str(output / 'statistics-controls.png'))
    page.close()
    stock_spec = task_definition(service.settings.root)
    stock_spec['arguments'] += ['--local-only', '--as-of', '2026-10-21']
    stock_spec['result_mail'] = 'preview'
    server = Server(('127.0.0.1', 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()  # No Engine.start or schedule worker: isolated API only.
    try:
        client = MailClient(f'http://127.0.0.1:{server.server_port}', store.local / 'api_token.txt')
        registered = register_with_client(client, stock_spec)
        assert registered['state'] == 'registered'
        assert register_with_client(client, stock_spec)['state'] == 'already_registered'
    finally:
        server.shutdown(); thread.join(); server.server_close()
    stock_id = registered['task']['id']
    assert registered['task']['schedule'] == {'type': 'daily', 'time': '09:20'}
    stock_preview = execute('stock-preview', stock_id)
    stock_manifest = stock_preview['result']['mail_manifest']
    stock_folder = Path(stock_manifest['mail']['attachments'][0]['path']).parent
    stock_snapshot = json.loads((stock_folder / '统计记录.json').read_text(encoding='utf-8'))
    assert stock_snapshot['swap_stocks'] == stock_daily['swap_stocks']
    assert stock_snapshot['swap_stocks']['count'] == 25
    assert len(store.history('outbox')) == 1
    stock_spec['result_mail'] = 'queue'
    work.save(stock_spec)
    execute('stock-send', stock_id)
    stock_smtp = FakeSMTP()
    with patch('mail_app.mail.smtp_connection', connection(stock_smtp)):
        transmit(store, store.claim_mail())
    assert len(stock_smtp.sent) == 1
    stock_sent, _, stock_recipients = stock_smtp.sent[0]
    assert stock_recipients == ['stock@example.invalid', 'risk@example.invalid']
    verify_images(stock_sent, [stock_folder / 'swap_stocks.png'], regular=True)
    assert stock_manifest['mail']['attachments'][0]['also_attach'] is True
    assert '带符号Delta总敞口金额' in stock_sent.get_body(('plain',)).get_content()
    assert stock_sent.get_body(('html',))
    (output / 'stock-fake-smtp.eml').write_bytes(stock_sent.as_bytes())
    work = WorkTasks(Store(store.root))
    execute('stock-new-batch-after-restart', stock_id)
    assert len(store.history('outbox')) == 2 and store.claim_mail() is None
    # The existing saved daily entry carries three CIDs and three attachments.
    daily_task = work.save({'name': '合成日报三图CID验收',
                           'program': str(args.work_root / 'integrations/daily_report/entry.py'),
                           'interpreter': str(args.task_python), 'cwd': str(PROJECT), 'enabled': False,
                           'arguments': ['--project', str(PROJECT), '--root', str(service.settings.root),
                                         '--run', '--local-only', '--as-of', '2026-10-21'],
                           'schedule': {'type': 'manual'}, 'result_mail': 'queue'})
    daily_run = execute('daily-three-cid', daily_task['id'])
    daily_manifest = daily_run['result']['mail_manifest']
    assert len(daily_manifest['mail']['attachments']) == 3
    daily_smtp = FakeSMTP()
    with patch('mail_app.mail.smtp_connection', connection(daily_smtp)):
        transmit(store, store.claim_mail())
    assert len(daily_smtp.sent) == 1
    daily_sent, _, daily_recipients = daily_smtp.sent[0]
    assert daily_recipients == ['team@example.invalid', 'manager@example.invalid']
    verify_images(daily_sent, [Path(a['path']) for a in daily_manifest['mail']['attachments']], regular=True)
    assert all(a['also_attach'] is True for a in daily_manifest['mail']['attachments'])
    (output / 'daily-three-cid-fake-smtp.eml').write_bytes(daily_sent.as_bytes())
    execute('daily-three-cid-new-batch', daily_task['id'])
    assert len(store.history('outbox')) == 3 and store.claim_mail() is None
    current = {task['id']: task for task in work.tasks()}
    for original in existing:
        assert current[original['id']] == original
    assert sha256(service.settings.root / 'statistics.local.json') == original_config_hash
    result = {'ok': True, 'history_export': str(history_folder), 'daily_export': str(daily_folder),
              'evidence': str(output), 'stock_export': str(stock_folder),
              'checks': ['292-report full-year histories', 'actual selected Conda/Windows Job',
              'exact two CID images and plain/HTML through fake SMTP', 'self-only recipient',
              'preview before send', 'restart/new-batch sends once', 'original daily/FOF definitions unchanged',
              'main report recipients and three-image contract unchanged',
              'stock GUI mail settings used by next CLI', '09:20 task registration via real isolated HTTP API',
              'stock subset equals daily attachment data', 'one CID stock image plus separate attachment and explanatory plain/HTML',
              'stock restart/new-batch sends once', 'saved daily adapter to SMTP preserves three CIDs plus three regular attachments',
              'daily three-CID new-batch sends once']}
    atomic_json(output / 'acceptance.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
