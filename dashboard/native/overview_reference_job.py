"""One hidden, bounded reference worker per calendar week, with safe draining."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from dashboard.marketdata.bars import _atomic_bytes, _json_bytes
from dashboard.marketdata.overview_reference import load, path_for, publish


class ReferenceJob:
    def __init__(self, local_root):
        self.local_root = Path(local_root); self.directory = self.local_root/'overview_reference'
        self.process = None; self.closed = False
        self.stop_file = self.directory/'stop.request'

    def running(self):
        return self.process is not None and self.process.poll() is None

    def tick(self, config, *, enabled, now=None):
        if self.closed or not enabled or self.running() or config.get('overview_wind_enabled', True) is False:
            return
        now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
        current = load(config, self.local_root, now=now)
        if not current['due'] and not current['data'].get('errors'):
            return
        week = '-'.join(map(str, now.isocalendar()[:2]))
        profile=hashlib.sha256(json.dumps({k:config.get(k) for k in
            ('overview_wind_config','overview_wind_aum_field','overview_wind_aum_multiplier')},sort_keys=True).encode()).hexdigest()
        try:
            attempt = json.loads((self.directory/'attempt.json').read_text(encoding='utf8'))
            if attempt.get('week') == week and attempt.get('profile') == profile:
                return
        except (OSError, ValueError):
            pass
        self.directory.mkdir(parents=True, exist_ok=True)
        # A persistent stop file is never deleted while an old worker is alive.
        if self.stop_file.exists():
            self.stop_file.unlink()
        _atomic_bytes(self.directory/'attempt.json', _json_bytes(dict(week=week, profile=profile, attempted_at=now.isoformat())))
        try:
            self.process = subprocess.Popen([sys.executable, '-B', '-s', '-X', 'utf8', '-m', __name__,
                '--local-root', str(self.local_root)], cwd=str(Path(__file__).resolve().parents[2]),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            _atomic_bytes(self.directory/'status.json', _json_bytes(dict(status='unavailable', error_type=type(exc).__name__)))

    def stop(self):
        self.closed = True
        if self.running():
            _atomic_bytes(self.stop_file, b'stop')


def main(argv=None):
    import argparse
    from dashboard.marketdata.overview_wind import refresh
    parser = argparse.ArgumentParser(); parser.add_argument('--local-root', required=True, type=Path)
    args = parser.parse_args(argv); directory = args.local_root/'overview_reference'
    status = dict(started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),diagnostics={})
    try:
        config = json.loads((args.local_root/'native.json').read_text(encoding='utf8'))
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        prior = load(config, args.local_root, now=now)
        value = refresh(config, args.local_root, prior['data'], now=now, stop=lambda: (directory/'stop.request').exists(),diagnostics=status['diagnostics'])
        if (directory/'stop.request').exists():
            raise InterruptedError()
        publish(path_for(config, args.local_root), value)
        status.update(status='published', warnings=value.get('errors', []), fetched_at=value['fetched_at'])
    except Exception as exc:
        status.update(status='cancelled' if isinstance(exc, InterruptedError) else 'unavailable',
                      error_type=type(exc).__name__, reason='Wind低频资料未完成，保留已有资料；不切换VPN')
    status['finished_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    _atomic_bytes(directory/'status.json', _json_bytes(status))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
