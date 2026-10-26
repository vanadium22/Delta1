"""Bridge to existing Wind terminal Python. No install or Oracle requirement."""
import json
from pathlib import Path
import subprocess
import sys


def executable(config,local_root):
    selected=config.get('overview_wind_python') or config.get('wind_python')
    if not selected:
        repository=Path(__file__).resolve().parents[2]
        for relative in ('index_futures_basis/config.local.json','securities_lending/config.local.json'):
            try:
                value=json.loads((repository/relative).read_text(encoding='utf-8-sig'))
                candidate=value.get('wind_python')
                if candidate and Path(candidate).is_file():selected=candidate;break
            except (OSError,ValueError,TypeError):pass
    path=Path(selected or sys.executable)
    if path.name.lower()=='pythonw.exe':path=path.with_name('python.exe')
    return str(path)


def refresh(config,local_root,old,*,now,stop_file=None):
    from .overview_reference import validate
    from .overview_sessions import latest_completed_session
    day=latest_completed_session(now)
    fields={key:config.get('overview_wind_'+key) for key in ('etf_sector','tracking_field','aum_field','industry_field') if config.get('overview_wind_'+key)}
    request=dict(day=day,fetched_at=now.isoformat(),old=old,config=fields,stop_file=str(stop_file) if stop_file else None)
    worker=Path(__file__).with_name('wind_terminal_worker.py')
    # No -s: preserves the user's WindPy registration and original Wind install.
    result=subprocess.run([executable(config,local_root),'-B','-X','utf8',str(worker)],
        input=json.dumps(request,ensure_ascii=False),capture_output=True,text=True,encoding='utf8',errors='replace',
        timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Wind终端子进程未正常退出')
    try:value=json.loads(result.stdout)
    except ValueError:raise RuntimeError('Wind终端返回格式不完整') from None
    if not value.get('ok'):
        error=RuntimeError(value.get('reason') or 'Wind终端参考查询失败')
        error.error_type=value.get('error_type');raise error
    value['data']=validate(value['data'])
    return value


def setup(config,local_root):
    selected=executable(config,local_root)
    result=dict(provider='WindPy',python=selected,python_exists=Path(selected).is_file(),credentials_read=False,connection_attempted=False)
    if not result['python_exists']:return dict(result,status='python_missing',module_available=False)
    try:
        process=subprocess.run([selected,'-B','-X','utf8',str(Path(__file__).with_name('wind_terminal_worker.py')),'--check'],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=10,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        value=json.loads(process.stdout)
        return dict(result,**{k:value[k] for k in ('module_available','user_site_enabled') if k in value},status='inspected_module_only')
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return dict(result,status='unavailable',error_type=type(exc).__name__)
