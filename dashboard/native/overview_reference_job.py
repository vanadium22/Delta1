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
        self.scheduling = dict(status='not_evaluated', reason='尚未评估低频资料任务')

    def running(self):
        return self.process is not None and self.process.poll() is None

    def state(self):
        return dict(self.scheduling,worker_running=self.running(),
                    worker_exit_code=self.process.poll() if self.process is not None else None)

    def tick(self, config, *, enabled, now=None, blocked_reason=None, force=False):
        now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
        def record(status,reason):
            self.scheduling=dict(status=status,reason=reason,checked_at=now.isoformat())
        if self.closed:
            record('stopped','正在关闭，保留已有资料');return
        if not enabled:
            record('waiting',blocked_reason or '只读或后台流程尚未就绪');return
        if self.running():
            record('running','低频资料任务运行中');return
        if config.get('overview_wind_enabled', True) is False:
            record('disabled','配置已关闭Wind低频更新')
            return
        current = load(config, self.local_root, now=now)
        if not current['due'] and not current['data'].get('errors'):
            record('up_to_date','本周资料已核验')
            return
        week = '-'.join(map(str, now.isocalendar()[:2]))
        profile=hashlib.sha256(json.dumps(['wind-terminal-v3-evidence',{k:config.get(k) for k in
            ('overview_reference_backend','overview_wind_python','overview_wind_config','overview_wind_aum_field',
             'overview_wind_aum_multiplier','overview_wind_etf_sector','overview_wind_tracking_field','overview_wind_industry_field')}],sort_keys=True).encode()).hexdigest()
        try:
            attempt = json.loads((self.directory/'attempt.json').read_text(encoding='utf8'))
            if not force and attempt.get('week') == week and attempt.get('profile') == profile:
                record('attempted_this_week','本周已尝试；结果以Wind任务状态文件为准')
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
            record('worker_started','已启动隐藏低频资料任务，等待结果')
        except OSError as exc:
            record('failed_to_start','低频任务子进程未能启动')
            _atomic_bytes(self.directory/'status.json', _json_bytes(dict(status='unavailable', error_type=type(exc).__name__)))

    def stop(self):
        self.closed = True
        if self.running():
            _atomic_bytes(self.stop_file, b'stop')


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--local-root', required=True, type=Path)
    args = parser.parse_args(argv); directory = args.local_root/'overview_reference'
    status = dict(started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),diagnostics={})
    try:
        config = json.loads((args.local_root/'native.json').read_text(encoding='utf8'))
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        prior = load(config, args.local_root, now=now)
        backend=config.get('overview_reference_backend') or 'windpy'
        status['provider']=backend
        if backend=='windpy':
            from dashboard.marketdata.overview_windpy import refresh
            result=refresh(config,args.local_root,prior['data'],now=now,stop_file=directory/'stop.request')
            value=result['data'];status['diagnostics']=result['diagnostics']
        elif backend=='oracle':
            from dashboard.marketdata.overview_wind import refresh
            value=refresh(config,args.local_root,prior['data'],now=now,stop=lambda:(directory/'stop.request').exists(),diagnostics=status['diagnostics'])
        else:raise ValueError('未识别低频资料接口')
        if (directory/'stop.request').exists():
            raise InterruptedError()
        publish(path_for(config, args.local_root), value)
        status.update(status='published', warnings=value.get('errors', []), fetched_at=value['fetched_at'])
    except Exception as exc:
        from dashboard.marketdata.wind_terminal_worker import safe_diagnostics
        status['diagnostics']=safe_diagnostics(getattr(exc,'diagnostics',status['diagnostics']))
        status.update(status='cancelled' if isinstance(exc, InterruptedError) else 'unavailable',
                      error_type=getattr(exc,'error_type',None) or type(exc).__name__, reason='Wind终端低频资料未完成，保留已有资料；查看失败阶段与ErrorCode，原因尚待核验，不切换VPN')
    status['finished_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    _atomic_bytes(directory/'status.json', _json_bytes(status))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
