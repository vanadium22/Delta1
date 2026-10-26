"""Safe connection evidence: no exception text, headers, responses or credentials."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import sys
import uuid

STAGES = {'imports':'加载诊断依赖','session_clock':'检查接入时段', 'reference_read':'读取合约参考',
          'network_lock':'取得网络互斥锁', 'network_lock_release':'释放网络互斥锁',
          'client_init':'初始化行情客户端', 'http_request':'请求行情接口',
          'response_validation':'校验接口响应', 'client_close':'关闭行情会话',
          'config_read':'读取本机配置', 'report':'保存诊断报告', 'dns':'解析行情地址',
          'tcp':'连接行情端口', 'route':'读取本机路由'}


def error_detail(exc, stage, *, path=None):
    detail = {'stage':stage, 'type':type(exc).__name__}
    if isinstance(exc,ImportError) and exc.name:detail['module']=exc.name
    chain = []; current = exc
    while current is not None and len(chain) < 5 and all(id(current) != item[0] for item in chain):
        item = {'type':type(current).__name__}
        for key in ('errno','winerror'):
            value = getattr(current,key,None)
            if isinstance(value,int):item[key] = value
        chain.append((id(current),item))
        current = current.__cause__ or current.__context__
    detail['causes'] = [item for _,item in chain]
    detail.update({key:value for key,value in chain[0][1].items() if key != 'type'})
    operation=getattr(exc,'lock_operation',None)
    if operation in ('create_directory','open_file','acquire_byte_lock'):detail['lock_operation']=operation
    # Paths are useful only for local file operations. Never serialize a URL
    # from a transport error as a supposed filename.
    for key in ('filename','filename2'):
        value = getattr(exc,key,None)
        if value is not None and '://' not in str(value) and (Path(str(value)).is_absolute() or PureWindowsPath(str(value)).is_absolute()):
            detail[key] = str(value)
    if path is not None:detail['path'] = str(path)
    frames=[];tb=exc.__traceback__
    while tb is not None:
        frames.append({'file':tb.tb_frame.f_code.co_filename,'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno})
        tb=tb.tb_next
    detail['frames']=frames[-8:]
    return detail


def failure_message(detail):
    stage=detail['stage'];kind=detail.get('type','未知异常')
    message='验证未完成：'+STAGES.get(stage,stage)+'（'+kind+'）'
    for key,label in (('errno','系统错误码'),('winerror','Windows错误码')):
        if detail.get(key) is not None:message+=' · '+label+' '+str(detail[key])
    if stage=='network_lock':
        operation=detail.get('lock_operation')
        message+='；网络锁未取得，尚未请求行情。'
        if operation in ('create_directory','open_file'):
            message+='创建目录/打开锁文件被拒绝；请核对目录写权限或安全软件，不能据此认定旧窗口占锁。'
        elif operation=='acquire_byte_lock':
            message+='申请互斥字节锁被拒绝，常见于其他历史/实时任务仍在运行；启动已尝试正常关闭同范围旧看板。'
        else:
            message+='可能是其他任务占用或文件访问被拒绝，需要核对锁操作阶段与持有者。'
        message+='不会删除锁文件或强制结束写入进程。'
    elif stage=='http_request':
        message+='；已进入接口请求，请核对VPN资源、路由或安全软件。'
    path=detail.get('path') or detail.get('filename2') or detail.get('filename')
    if path:message+='\n路径：'+path
    return message


def probe_evidence():
    return dict(schema='connection-check-v1',started_at=datetime.now(timezone.utc).isoformat(),
                python=sys.executable,pid=os.getpid(),stage='session_clock',http_attempted=False)


def save_probe_report(result, directory):
    if directory is None:return result
    path=Path(directory)/('connection-'+uuid.uuid4().hex+'.json')
    result['diagnostic_file']=str(path)
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        # Unique files prevent an earlier success from replacing this attempt.
        with path.open('x',encoding='utf8') as out:
            json.dump(result,out,ensure_ascii=False,allow_nan=False,indent=2)
        if not result.get('ok') and not result.get('offline'):
            result['message']+='\n诊断JSON：'+str(path)
    except OSError as exc:
        result['report_error']=error_detail(exc,'report',path=path)
        result['message']+='\n诊断保存失败；'+failure_message(result['report_error'])
    return result
