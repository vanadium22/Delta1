"""Weekly reference review and daily dated ETF NAV, each bounded and owned."""
from datetime import date,datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from dashboard.marketdata.bars import _atomic_bytes, _json_bytes
from dashboard.marketdata.overview_reference import load, path_for, publish
from dashboard.marketdata.wind_terminal_worker import PROTOCOL


def repair_needs(data,target):
    """A valid weekly review can still need a bounded repair, separate from NAV."""
    from dashboard.marketdata.overview_reference import ROOTS,finite
    reasons=[]
    for root,expected in dict(IF=300,IH=50,IC=500,IM=1000).items():
        group=data.get('indices',{}).get(root,{})
        rows=group.get('rows',[])
        if len(rows)!=expected:reasons.append(root+':membership')
        if group.get('weights_complete') is False or not rows or any(not finite(r.get('weight_pct')) for r in rows):reasons.append(root+':weights')
        if any(not r.get('industry') for r in rows):reasons.append(root+':industry')
        try:age=(date.fromisoformat(target)-date.fromisoformat(group.get('as_of',''))).days
        except (ValueError,TypeError):age=999
        if age<0 or age>14:reasons.append(root+':weight_date')
        fund=data.get('etfs',{}).get(root,{})
        if fund.get('complete') is not True or not fund.get('rows'):reasons.append(root+':etf_ranking')
    return reasons


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
        from dashboard.marketdata.overview_sessions import latest_completed_session
        from dashboard.marketdata.overview_reference import ranking,ROOTS
        try:target=latest_completed_session(now)
        except ValueError:record('waiting_calendar','完成交易日日历待核验');return
        chosen={r['symbol'] for root in ROOTS for r in ranking(current['data'],root,today=now.date().isoformat())[0]}
        saved_nav=current['data'].get('etf_nav',{}).get('rows',{})
        nav_due=bool(chosen) and (config.get('overview_reference_backend') or 'windpy')=='windpy' and any(saved_nav.get(s,{}).get('as_of')!=target for s in chosen)
        week = '-'.join(map(str, now.isocalendar()[:2]))
        profile=hashlib.sha256(json.dumps([PROTOCOL,{k:config.get(k) for k in
            ('overview_reference_backend','overview_wind_python','overview_wind_config','overview_wind_aum_field',
             'overview_wind_aum_multiplier','overview_wind_etf_sector','overview_wind_tracking_field','overview_wind_industry_field')}],sort_keys=True).encode()).hexdigest()
        attempt={}
        try:
            attempt = json.loads((self.directory/'attempt.json').read_text(encoding='utf8'))
        except (OSError, ValueError):
            pass
        weekly_tried=attempt.get('week')==week and attempt.get('profile')==profile
        repairs=repair_needs(current['data'],target)
        daily_repair_due=bool(repairs) and (attempt.get('day')!=target or attempt.get('checked_day')!=now.date().isoformat())
        stage='all'
        if not force and not daily_repair_due and (not current['due'] and not repairs or weekly_tried):
            if not nav_due:
                record('attempted_this_week' if weekly_tried and (current['due'] or current['data'].get('errors')) else 'up_to_date',
                    '该完成日今日已尝试；缺项明日有界复核，结果见Wind状态' if repairs else '本周资料及最近完成日净值已核验');return
            stage='nav';profile=hashlib.sha256((profile+target).encode()).hexdigest()
            try:nav_attempt=json.loads((self.directory/'nav-attempt.json').read_text(encoding='utf8'))
            except (OSError,ValueError):nav_attempt={}
            if nav_attempt.get('day')==target and nav_attempt.get('checked_day')==now.date().isoformat() and nav_attempt.get('profile')==profile:
                record('nav_attempted_today','该完成日净值已尝试；保留原数据日期');return
        self.directory.mkdir(parents=True, exist_ok=True)
        # A persistent stop file is never deleted while an old worker is alive.
        if self.stop_file.exists():
            self.stop_file.unlink()
        _atomic_bytes(self.directory/('attempt.json' if stage=='all' else 'nav-attempt.json'),
            _json_bytes(dict(week=week,day=target,checked_day=now.date().isoformat(),stage=stage,profile=profile,attempted_at=now.isoformat())))
        try:
            self.process = subprocess.Popen([sys.executable, '-B', '-s', '-X', 'utf8', '-m', __name__,
                '--local-root', str(self.local_root),'--stage',stage], cwd=str(Path(__file__).resolve().parents[2]),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            record('worker_started','已启动隐藏低频资料任务，等待结果')
            self.scheduling['repair_needs']=repairs
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
    parser.add_argument('--stage',choices=('all','nav'),default='all')
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
            result=refresh(config,args.local_root,prior['data'],now=now,stop_file=directory/'stop.request',stage=args.stage)
            value=result['data'];status['diagnostics']=result['diagnostics']
        elif backend=='oracle':
            if args.stage!='all':raise ValueError('独立净值任务仅使用WindPy')
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
