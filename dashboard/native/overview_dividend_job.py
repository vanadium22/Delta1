"""At most an AM/PM share check, with persistent bounded retries."""
from datetime import datetime, timedelta, time
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from dashboard.marketdata.dividends import digest
from dashboard.marketdata.bars import _atomic_bytes, _json_bytes
from dashboard.marketdata.overview_dividend_sync import read_json
from dashboard.marketdata.overview_dividends import directory


class DividendJob:
    def __init__(self, local_root):
        self.local_root = Path(local_root)
        self.process = None
        self.closed = False
        self.stop_file = None
        self.scheduling = dict(status='not_evaluated')
        self.active_root = None

    def running(self):
        return self.process is not None and self.process.poll() is None

    def state(self):
        result = dict(self.scheduling, worker_running=self.running())
        if self.active_root:
            saved = read_json(self.active_root/'status.json')
            result['last_result'] = {k:saved.get(k) for k in ('status','inserted','imported_files','unchanged','source_files','errors','finished_at')}
        return result

    def tick(self, config, *, enabled, now=None, force=False):
        now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
        now = now.astimezone(ZoneInfo('Asia/Shanghai'))
        if self.closed or not enabled:
            self.scheduling = dict(status='stopped' if self.closed else 'waiting')
            return
        if self.running():
            self.scheduling = dict(status='running')
            return
        self.active_root = directory(config, self.local_root)
        schedule_path = self.active_root/'schedule.json'
        saved = read_json(schedule_path)
        if self.process is not None:
            outcome = read_json(self.active_root/'status.json')
            saved['complete'] = outcome.get('status') == 'complete'
            saved['retry_after'] = (now+timedelta(minutes=5)).isoformat()
            _atomic_bytes(schedule_path, _json_bytes(saved))
            self.process = None
        if config.get('overview_dividend_sync_enabled', True) is False:
            self.scheduling = dict(status='disabled')
            return
        try:
            morning = time.fromisoformat(config.get('overview_dividend_check_am') or '09:00')
            afternoon = time.fromisoformat(config.get('overview_dividend_check_pm') or '15:30')
            if not morning < afternoon:
                raise ValueError()
        except (ValueError, TypeError):
            self.scheduling = dict(status='invalid_schedule')
            return
        slot = 'pm' if now.time() >= afternoon else 'am' if now.time() >= morning else None
        if slot is None and not force:
            self.scheduling = dict(status='waiting_am')
            return
        slot = slot or 'am'
        profile = digest({k:config.get(k) for k in ('overview_dividend_source_dir','overview_dividend_pattern',
            'overview_dividend_file','dividend_root','overview_dividend_check_am','overview_dividend_check_pm')})
        same = saved.get('day') == now.date().isoformat() and saved.get('slot') == slot and saved.get('profile') == profile
        if same and not force:
            if saved.get('complete') or saved.get('attempts',0) >= 3:
                self.scheduling = dict(status='checked_this_slot' if saved.get('complete') else 'attempted_this_slot', slot=slot)
                return
            if saved.get('retry_after') and now < datetime.fromisoformat(saved['retry_after']):
                self.scheduling = dict(status='retry_wait', slot=slot)
                return
        self.active_root.mkdir(parents=True, exist_ok=True)
        self.stop_file = self.active_root/'stop.request'
        self.stop_file.unlink(missing_ok=True)
        record = dict(day=now.date().isoformat(),slot=slot,profile=profile,attempts=(saved.get('attempts',0) if same else 0)+1,
            complete=False,attempted_at=now.isoformat(),retry_after=(now+timedelta(minutes=5)).isoformat())
        _atomic_bytes(schedule_path, _json_bytes(record))
        try:
            self.process = subprocess.Popen([sys.executable,'-B','-X','utf8','-m','dashboard.marketdata.overview_dividend_sync',
                '--local-root',str(self.local_root)],cwd=str(Path(__file__).resolve().parents[2]),
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.scheduling = dict(status='worker_started',slot=slot)
        except OSError as exc:
            self.scheduling = dict(status='failed_to_start',error_type=type(exc).__name__)

    def stop(self):
        self.closed = True
        if self.running() and self.stop_file:
            _atomic_bytes(self.stop_file, b'stop')
