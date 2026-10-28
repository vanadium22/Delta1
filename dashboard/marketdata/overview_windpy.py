"""Bridge to existing Wind terminal Python. No install or Oracle requirement."""
import json
from datetime import date
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def run_readonly_worker(command,request,stop_file,*,timeout=180):
    """Cancel only our private SDK reader, never the publisher/history writer."""
    if Path(stop_file).exists():raise InterruptedError()
    payload=json.dumps(request,ensure_ascii=False);started=time.monotonic()
    with subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding='utf8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as process:
        try:
            while True:
                if Path(stop_file).exists():raise InterruptedError()
                remaining=timeout-(time.monotonic()-started)
                if remaining<=0:raise subprocess.TimeoutExpired(command,timeout)
                try:
                    stdout,_=process.communicate(input=payload,timeout=min(.2,remaining))
                    return subprocess.CompletedProcess(command,process.returncode,stdout)
                except subprocess.TimeoutExpired:payload=None
        finally:
            if process.poll() is None:
                # This process only reads Wind and writes disposable evidence.
                # The owning publisher checks stop_file before atomic publish.
                process.terminate()
                try:process.communicate(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.communicate(timeout=2)


class TerminalFailure(RuntimeError):
    """Carries only structured, sanitized evidence across the process boundary."""
    def __init__(self,error_type,diagnostics):
        from .wind_terminal_worker import safe_diagnostics
        super().__init__('Wind低频查询未完成；查看失败阶段与ErrorCode')
        self.error_type=error_type if isinstance(error_type,str) and error_type.isidentifier() else 'WindError'
        self.diagnostics=safe_diagnostics(diagnostics)


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


def refresh(config,local_root,old,*,now,stop_file=None,stage='all',requested_day=None):
    from .overview_reference import validate
    from .overview_sessions import latest_completed_session
    day=latest_completed_session(now)
    if requested_day is not None:
        from .trading_calendar import HOLIDAYS,load_year
        selected=date.fromisoformat(requested_day)
        if (selected.isoformat()!=requested_day or requested_day>day or selected.year not in HOLIDAYS or
            selected.weekday()>=5 or requested_day in load_year(selected.year,'.')):
            raise ValueError('Wind只读测试日期须为已核验的已完成交易日')
        day=requested_day
    fields={key:config.get('overview_wind_'+key) for key in ('etf_sector','tracking_field','aum_field','industry_field') if config.get('overview_wind_'+key)}
    if stage not in ('all','connect','indices','etfs','nav'):raise ValueError('低频检查阶段无效')
    request=dict(day=day,fetched_at=now.isoformat(),old=old,config=fields,stage=stage,stop_file=str(stop_file) if stop_file else None)
    worker=Path(__file__).with_name('wind_terminal_worker.py')
    # No -s: preserves the user's WindPy registration and original Wind install.
    with tempfile.TemporaryDirectory(prefix='delta1-wind-evidence-') as scratch:
        progress=Path(scratch)/'progress.json';request['progress_file']=str(progress)
        def failure(kind,phase):
            try:evidence=json.loads(progress.read_text(encoding='utf8'))
            except (OSError,ValueError):evidence=dict(requested_day=day,stage=stage,steps=[])
            evidence.setdefault('steps',[]).append(dict(stage=phase,status='failed'))
            return TerminalFailure(kind,evidence)
        try:
            command=[executable(config,local_root),'-B','-X','utf8',str(worker)]
            if stop_file is not None:result=run_readonly_worker(command,request,stop_file)
            else:result=subprocess.run(command,
                input=json.dumps(request,ensure_ascii=False),capture_output=True,text=True,encoding='utf8',errors='replace',
                timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except InterruptedError as exc:
            exc.diagnostics=failure('InterruptedError','worker_cancelled').diagnostics
            raise
        except (OSError,subprocess.TimeoutExpired) as exc:
            # Never export TimeoutExpired.stdout/stderr or the driver message.
            raise failure(type(exc).__name__,'worker_timeout' if isinstance(exc,subprocess.TimeoutExpired) else 'worker_start') from None
        if result.returncode:raise failure('WorkerExit','worker_exit')
    try:value=json.loads(result.stdout)
    except ValueError:raise TerminalFailure('WorkerProtocol',dict(requested_day=day,stage=stage,steps=[dict(stage='worker_protocol',status='failed')])) from None
    if not isinstance(value,dict):raise TerminalFailure('WorkerProtocol',dict(requested_day=day,stage=stage,steps=[dict(stage='worker_protocol',status='failed')]))
    if not value.get('ok'):
        if value.get('error_type')=='InterruptedError':
            from .wind_terminal_worker import safe_diagnostics
            error=InterruptedError();error.diagnostics=safe_diagnostics(value.get('diagnostics'));raise error
        raise TerminalFailure(value.get('error_type'),value.get('diagnostics'))
    try:value['data']=validate(value['data'])
    except (ValueError,TypeError,KeyError):
        diagnostics=value.get('diagnostics') or {};diagnostics.setdefault('steps',[]).append(dict(stage='reference_validation',status='failed'))
        raise TerminalFailure('ReferenceValidation',diagnostics) from None
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
