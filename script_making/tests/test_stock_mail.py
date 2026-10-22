"""Isolated stock task, GUI mailbox settings and explicit task registration."""
from contextlib import redirect_stdout
from datetime import date
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import io
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QDialog
from shared_data.io import file_lock
from script_making.independent_mail_widgets import IndependentMailDialog
from script_making.pnl_history import load_self_config
from script_making.statistics import save_config
from script_making.stock_mail import CONFIG, IMAGE_CID, load_profile, mail_manifest, profile
from script_making.stock_task_registration import register_with_client, task_definition
from script_making.storage import ReportError, atomic_json, sha256
from script_making.swap_stocks_job import main, run_once
from script_making.tests import test_statistics as samples


class StockMailTests(unittest.TestCase):
    setUpClass = classmethod(samples.StatisticsTests.setUpClass.__func__)
    setUp = samples.StatisticsTests.setUp
    tearDown = samples.StatisticsTests.tearDown
    snapshot = samples.StatisticsTests.snapshot

    def configure(self):
        save_config(self.service.settings.root, {**self.config, 'to': 'daily@example.invalid', 'cc': 'daily-copy@example.invalid'})
        atomic_json(self.service.settings.root / CONFIG, profile({'to': 'stock@example.invalid', 'cc': 'risk@example.invalid'}))

    def test_frontend_profiles_are_separate_and_next_run_uses_saved_addresses(self):
        self.configure()
        root = self.service.settings.root
        atomic_json(root / 'pnl_history.local.json', {'to': 'self@example.invalid'})
        original = sha256(root / 'statistics.local.json')
        dialog = IndependentMailDialog(root)
        dialog.entries['to'].setText('new-stock@example.invalid')
        dialog.entries['cc'].setText('new-risk@example.invalid')
        dialog.note.setPlainText('仅供本组合观察。')
        dialog.self_email.setText('new-self@example.invalid')
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(load_profile(root)['to'], 'new-stock@example.invalid')
        self.assertEqual(load_self_config(root)['to'], 'new-self@example.invalid')
        self.assertEqual(sha256(root / 'statistics.local.json'), original)
        code, result = run_once(root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 0, result)
        mail = mail_manifest(result['export_directory'])['mail']
        self.assertEqual(mail['to'], ['new-stock@example.invalid'])
        self.assertEqual(mail['cc'], ['new-risk@example.invalid'])
        self.assertIn('仅供本组合观察', mail['body'])
        self.assertEqual(sha256(root / 'statistics.local.json'), original)
        before = sha256(root / CONFIG)
        invalid = IndependentMailDialog(root)
        invalid.entries['to'].setText('other@example.invalid')
        invalid.self_email.setText('a@example.invalid,b@example.invalid')
        invalid.save()
        self.assertEqual(sha256(root / CONFIG), before)
        dialog.close(); invalid.close()

    def test_identical_stock_subset_to_main_report_and_inline_image_plus_attachment(self):
        self.configure()
        expected = self.snapshot()['swap_stocks']
        code, first = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 0, first)
        folder = Path(first['export_directory'])
        snapshot = json.loads((folder / '统计记录.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['swap_stocks'], expected)
        self.assertEqual(set(snapshot['config']), {'metric', 'threshold', 'exclusions'})
        msg = BytesParser(policy=policy.default).parsebytes((folder / '邮件草稿.eml').read_bytes())
        parts = [part for part in msg.walk() if part.get_filename()]
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].get_filename(), 'swap_stocks.png')
        self.assertEqual(msg.get_content_type(), 'multipart/mixed')
        self.assertEqual(parts[0].get_content_disposition(), 'inline')
        self.assertEqual(str(parts[0].get('Content-ID')), f'<{IMAGE_CID}>')
        self.assertEqual(parts[1].get_filename(), 'swap_stocks.png')
        self.assertEqual(parts[1].get_content_disposition(), 'attachment')
        self.assertIsNone(parts[1].get('Content-ID'))
        self.assertEqual(parts[1].get_payload(decode=True), (folder / 'swap_stocks.png').read_bytes())
        self.assertIn(f'src="cid:{IMAGE_CID}"', msg.get_body(('html',)).get_content())
        self.assertEqual(parts[0].get_payload(decode=True), (folder / 'swap_stocks.png').read_bytes())
        mail = mail_manifest(folder)['mail']
        self.assertEqual(set(mail['attachments'][0]), {'path', 'size', 'sha256', 'content_id', 'content_type', 'also_attach'})
        self.assertIs(mail['attachments'][0]['also_attach'], True)
        self.assertIn('带符号Delta总敞口金额', mail['body'])
        self.assertIn('不同标的的Delta数量不相加', mail['body'])
        self.assertIsNotNone(msg.get_body(('html',)))
        code, reused = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 0)
        self.assertEqual(reused['state'], 'reused')
        self.assertEqual(reused['export_directory'], str(folder))
        atomic_json(self.service.settings.root / CONFIG, profile({'to': 'changed@example.invalid'}))
        code, changed = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 0)
        self.assertNotEqual(changed['export_directory'], str(folder))
        self.assertTrue((folder / '邮件草稿.eml').is_file())

    def test_negative_boundary_excludes_etfs_and_empty_success_is_distinct_from_read_failure(self):
        self.configure()
        samples.risk_book(self.swap_path, '2026-10-14', [
            ['600001.SH', '股票', -2, -3, -4, -500000],
            ['512200.SH', '其他ETF', 2, 3, 4, 900000],
            ['159001.SZ', '永久剔除', 2, 3, 4, 900000],
            ['000300.SH', '指数', 2, 3, 4, 900000],
            ['IF2612.CFE', '股指期货', 2, 3, 4, 900000]])
        code, result = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 0, result)
        group = json.loads(Path(result['statistics_record']).read_text(encoding='utf-8'))['swap_stocks']
        self.assertEqual(group['count'], 1)
        self.assertEqual(group['net'], '-500000')
        samples.risk_book(self.swap_path, '2026-10-14', [])
        code, empty = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 0, empty)
        self.assertIn('本次没有达到筛选条件的股票', mail_manifest(empty['export_directory'])['mail']['body'])
        self.swap_path.write_bytes(b'broken')
        output, stdout = self.root / 'no-result.json', io.StringIO()
        with redirect_stdout(stdout):
            code = main(['--root', str(self.service.settings.root), '--run', '--local-only',
                         '--as-of', '2026-10-21', '--wa-output', str(output)])
        self.assertIn(code, (1, 2))
        self.assertNotIn('export_directory', json.loads(stdout.getvalue()))
        self.assertFalse(output.exists())
        self.assertTrue((Path(empty['export_directory']) / '邮件草稿.eml').is_file())

    def test_legacy_attachment_cache_is_preserved_but_not_reused_and_bad_cid_is_rejected(self):
        self.configure()
        root, day = self.service.settings.root, date(2026, 10, 21)
        code, first = run_once(root, day, local_only=True)
        self.assertEqual(code, 0, first)
        old = Path(first['export_directory'])
        snapshot = json.loads((old / '统计记录.json').read_text(encoding='utf-8'))
        legacy = EmailMessage(policy=policy.SMTP)
        legacy['To'], legacy['Cc'], legacy['Subject'] = 'stock@example.invalid', 'risk@example.invalid', '旧普通附件'
        legacy.set_content('旧版纯文本')
        legacy.add_alternative('<html><body>旧版普通附件</body></html>', subtype='html')
        legacy.add_attachment((old / 'swap_stocks.png').read_bytes(), maintype='image', subtype='png', filename='swap_stocks.png')
        (old / '邮件草稿.eml').write_bytes(legacy.as_bytes())
        old_digest = sha256(old / '邮件草稿.eml')
        identity = {k: v for k, v in snapshot.items() if k not in ('id', 'created_at')}
        old_key = hashlib.sha256(json.dumps({'version': 1, 'snapshot': identity, 'mail': load_profile(root)},
                                           ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        completed = self.service.settings.data_path() / 'statistics/swap_stock_runs/completed'
        index = completed / (first['fingerprint'] + '.json')
        prior = json.loads(index.read_text(encoding='utf-8'))
        prior['files']['邮件草稿.eml'] = old_digest
        atomic_json(completed / (old_key + '.json'), prior)
        index.unlink()
        code, upgraded = run_once(root, day, local_only=True)
        self.assertEqual(code, 0, upgraded)
        self.assertNotEqual(upgraded['fingerprint'], old_key)
        self.assertEqual(upgraded['state'], 'success')
        self.assertNotEqual(upgraded['export_directory'], str(old))
        self.assertEqual(sha256(old / '邮件草稿.eml'), old_digest)
        self.assertTrue((completed / (old_key + '.json')).is_file())
        fresh = Path(upgraded['export_directory'])
        mail_manifest(fresh)
        message = BytesParser(policy=policy.default).parsebytes((fresh / '邮件草稿.eml').read_bytes())
        part = next(p for p in message.walk() if p.get_filename())
        part.replace_header('Content-ID', '<wrong@id>')
        (fresh / '邮件草稿.eml').write_bytes(message.as_bytes())
        with self.assertRaises(ReportError):
            mail_manifest(fresh)

    def test_only_pair_sync_frozen_settings_no_stale_fallback_and_source_change(self):
        self.configure()
        def sync(root, as_of, kind):
            self.assertEqual(kind, 'pair')
            values = json.loads((root / 'config.local.json').read_text(encoding='utf-8'))
            self.assertEqual(Path(values['data_dir']), self.service.settings.data_path())
            return {'date': '2026-10-14', 'errors': []}
        with patch('script_making.daily_job.sync_once', side_effect=sync):
            code, record = run_once(self.service.settings.root, date(2026, 10, 21))
        self.assertEqual(code, 0, record)
        with patch('script_making.daily_job.sync_once', return_value={'date': '2026-10-20', 'errors': []}):
            code, record = run_once(self.service.settings.root, date(2026, 10, 21))
        self.assertEqual(code, 2)
        self.assertNotIn('export_directory', record)
        with patch('script_making.daily_job.sync_once', side_effect=OSError('synthetic offline')):
            self.assertEqual(run_once(self.service.settings.root, date(2026, 10, 21))[0], 2)
        digest = sha256(self.swap_path)
        with patch('script_making.storage.sha256', side_effect=[digest, 'changed']):
            code, record = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 2)
        self.assertNotIn('export_directory', record)

    def test_busy_and_unconfigured_do_not_create_sendable_results(self):
        self.assertEqual(run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)[0], 1)
        self.configure()
        ready, release = threading.Event(), threading.Event()
        def hold():
            with file_lock(self.service.settings.data_path() / 'statistics/.daily_job.lock'):
                ready.set(); release.wait(10)
        thread = threading.Thread(target=hold)
        thread.start(); self.assertTrue(ready.wait(5))
        try:
            self.assertEqual(run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)[0], 3)
        finally:
            release.set(); thread.join()

    def test_direct_cli_and_read_only_task_definition(self):
        self.configure()
        output = self.root / 'work-result.json'
        program = Path(__file__).resolve().parents[1] / 'swap_stocks_job.py'
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(program), '--root',
                                 str(self.service.settings.root), '--run', '--local-only', '--as-of',
                                 '2026-10-21', '--wa-output', str(output)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(json.loads(output.read_text(encoding='utf-8'))['mail']['attachments']), 1)
        fresh = self.root / 'never-created'
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(['--root', str(fresh), '--task-definition']), 0)
        task = json.loads(stdout.getvalue())['task']
        self.assertEqual(task['schedule'], {'type': 'daily', 'time': '09:20'})
        self.assertEqual(task['result_mail'], 'queue')
        self.assertTrue(task['enabled'])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--root', str(fresh), '--inspect']), 0)
        self.assertFalse(fresh.exists())

    def test_registration_is_explicit_idempotent_and_preserves_existing_tasks(self):
        task = task_definition(self.service.settings.root)
        class Client:
            def __init__(self):
                self.tasks = [{'id': 'original', 'name': '日报', 'program': str(self.root / 'daily.py')}]
                self.posts = 0
            root = self.root
            def request(self, path, payload=None):
                self.assert_path = path
                if payload is not None:
                    self.posts += 1
                    self.tasks.append(dict(payload))
                    return dict(payload)
                return self.tasks
        client = Client()
        original = dict(client.tasks[0])
        self.assertEqual(register_with_client(client, task)['state'], 'registered')
        client.tasks[-1]['schedule']['time'] = '09:55'
        client.tasks[-1]['enabled'] = False
        self.assertEqual(register_with_client(client, task)['state'], 'already_registered')
        self.assertEqual(client.posts, 1)
        self.assertEqual(client.tasks[0], original)
        self.assertFalse(client.tasks[-1]['enabled'])
        self.assertEqual(client.tasks[-1]['schedule']['time'], '09:55')
