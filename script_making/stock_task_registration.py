"""Construct one task, or explicitly register it through the existing local API."""
import hashlib
import os
from pathlib import Path
import re
import sys


def task_definition(root, clock='09:20'):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
        raise ValueError('运行时间必须为HH:MM。')
    program = Path(__file__).with_name('swap_stocks_job.py').resolve()
    root = Path(root).resolve()
    args = ['--run'] if root == program.parent else ['--root', str(root), '--run']
    return {'id': 'swap_stocks_' + hashlib.sha256(os.path.normcase(str(program)).encode()).hexdigest()[:20],
            'name': '收益互换纯个股敞口', 'program': str(program), 'cwd': str(program.parent.parent),
            'interpreter': str(Path(sys.executable).with_name('python.exe') if Path(sys.executable).name.lower() == 'pythonw.exe' else Path(sys.executable)),
            'arguments': args, 'enabled': True, 'schedule': {'type': 'daily', 'time': clock},
            'result_mail': 'queue'}


def register(work_root, task, port=8766):
    if not 1 <= port <= 65535:
        raise ValueError('工作台端口无效。')
    work_root = Path(work_root).resolve(strict=True)
    if not (work_root / 'mail_app/client.py').is_file():
        raise ValueError('请填写已有Work Automation仓库目录。')
    sys.path.insert(0, str(work_root))
    from mail_app.client import MailClient
    client = MailClient(f'http://127.0.0.1:{port}', token_file=work_root / 'local/api_token.txt')
    return register_with_client(client, task)


def register_with_client(client, task):
    tasks = client.request('/api/work/tasks')
    if not isinstance(tasks, list):
        raise ValueError('工作台任务列表读取失败。')
    key = lambda p: os.path.normcase(str(Path(p).resolve()))
    existing = [item for item in tasks if item.get('id') == task['id'] or key(item.get('program', '')) == key(task['program'])]
    if existing:
        if len(existing) != 1 or key(existing[0].get('program', '')) != key(task['program']):
            raise ValueError('纯个股任务身份冲突，请在工作台核对；未修改任何登记。')
        return {'state': 'already_registered', 'task': existing[0], 'send_email': False}
    if any(item.get('name') == task['name'] for item in tasks):
        raise ValueError('已有同名但程序不同的任务，请在工作台核对；未覆盖。')
    result = client.request('/api/work/tasks', task)
    return {'state': 'registered', 'task': result, 'send_email': False,
            'note': '已登记每天自动发送；登记本身不运行，后续由现有工作台计划触发。'}
