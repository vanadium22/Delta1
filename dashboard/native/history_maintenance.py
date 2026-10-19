"""Qt monitor and lifecycle owner for an isolated, low-priority history process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,
    QTableWidgetItem,QHeaderView,QPlainTextEdit,QDialog,QFormLayout,QLineEdit,QDialogButtonBox)

from dashboard.marketdata.bars import _atomic_bytes,_json_bytes
from dashboard.marketdata.history_publication import maintenance_root


def read(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf8'))
    except (OSError,ValueError):return {} if default is None else default


class HistoryMaintenance:
    def __init__(self,model):
        self.model=model;self.process=None;self.started=0;self.next_launch=0;self.closing=False
        self.root=None;self.stop_file=None;self.last_day=None;self.error=None;self.force=False;self.closing_since=None
        self.control=model.local_root/'history_control.json'

    def state(self):
        value=read(self.root/'status.json') if self.root else {}
        notes=[]
        if self.model.config.get('history_quality_notes'):notes.extend(read(self.model.config['history_quality_notes']).get('entries',[]))
        if self.root:notes.extend(read(self.root/'quality_notes.json').get('entries',[]))
        value['source_notes']=list({(n['symbol'],n['frequency'],n['day']):n for n in notes}.values())
        if self.error:value={**value,**self.error}
        if read(self.control).get('paused'):value.update(state='paused',message='历史维护已暂停，实时采集继续')
        return value

    def pause(self):
        _atomic_bytes(self.control,_json_bytes({'paused':True}))
        if self.stop_file:self.stop_file.touch(exist_ok=True)

    def retry(self):
        _atomic_bytes(self.control,_json_bytes({'paused':False}))
        self.force=True;self.next_launch=0;self.error=None
        self.tick()

    def stop(self):
        if not self.closing:self.closing_since=time.monotonic()
        self.closing=True
        if self.stop_file:self.stop_file.touch(exist_ok=True)

    def tick(self):
        if self.process is not None:
            if self.process.poll() is None:
                state=read(self.root/'status.json') if self.root else {}
                try:
                    from datetime import datetime
                    heartbeat=datetime.fromisoformat(state['updated_at']).timestamp()
                except (KeyError,ValueError):heartbeat=0
                stalled=time.monotonic()-self.started>180 and time.time()-heartbeat>180
                if stalled or self.closing and time.monotonic()-self.closing_since>20:
                    # Query/SDK stalls cannot stall the GUI or kill the real-time process.
                    self.process.terminate();self.next_launch=time.time()+300
                    self.error=dict(state='failed',message='历史进程超时，保留已发布版本；5分钟后重试')
                return
            code=self.process.returncode;self.process=None
            if self.stop_file:self.stop_file.unlink(missing_ok=True)
            if code not in (0,2,3):
                self.error=dict(state='failed',message='历史进程未正常完成；请检查 SDK 环境和本机配置')
                self.next_launch=time.time()+300
        if self.closing or read(self.control).get('paused') or not self.model.config.get('history_maintenance_enabled',True):return
        roots=self.model.config.get('history_roots',[])
        if not roots:return
        root=maintenance_root(roots)
        if self.root!=root:self.root=root;self.next_launch=0;self.last_day=None
        state=read(root/'status.json')
        from datetime import datetime,timezone,timedelta
        day=str(datetime.now(timezone(timedelta(hours=8))).date())
        first=self.last_day is None
        if not first and not self.force and self.last_day==day:
            if state.get('state')=='waiting_credentials':return
            if time.time()<max(self.next_launch,state.get('next_retry') or 0):return
        elif time.time()<self.next_launch:return
        from index_strategy.history.downloader import PUBLIC_ROOT
        interpreter=Path(self.model.config.get('history_python') or os.environ.get('SWHY_HISTORY_PYTHON') or
                         PUBLIC_ROOT/'dolphindb_data/.venv/Scripts/python.exe')
        if not interpreter.is_file() and not (self.model.config.get('history_python') or os.environ.get('SWHY_HISTORY_PYTHON')):
            import importlib.util
            if importlib.util.find_spec('dolphindb') is not None:interpreter=Path(sys.executable)
        if not interpreter.is_file():
            self.error=dict(state='waiting_sdk',message='未找到历史 Python 环境；配置 history_python 或 SWHY_HISTORY_PYTHON')
            self.next_launch=time.time()+300;return
        root.mkdir(parents=True,exist_ok=True)
        self.stop_file=root/('stop-'+uuid.uuid4().hex)
        command=[str(interpreter),'-B','-s','-X','utf8','-m','dashboard.marketdata.history_maintenance',
                 '--once','--local-root',str(self.model.local_root),'--stop-file',str(self.stop_file)]
        if self.force:command.append('--force')
        flags=(getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)) if os.name=='nt' else 0
        try:
            self.process=subprocess.Popen(command,cwd=Path(__file__).resolve().parents[2],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
            self.started=time.monotonic();self.last_day=day;self.next_launch=time.time()+5;self.force=False;self.error=None
        except OSError:
            self.error=dict(state='failed',message='无法启动历史进程；5分钟后重试');self.next_launch=time.time()+300


def make_table(headers):
    table=QTableWidget(0,len(headers));table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);table.setAlternatingRowColors(True)
    return table


def fill(table,rows):
    table.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,value in enumerate(row):table.setItem(i,j,QTableWidgetItem('—' if value is None else str(value)))


class MaintenancePage(QWidget):
    def __init__(self,controller):
        super().__init__();self.controller=controller;self.signature=None;self.jobs=[];self.page=0
        layout=QVBoxLayout(self);actions=QHBoxLayout()
        for title,callback in [('立即检查 / 重试',controller.retry),('暂停历史维护',controller.pause),('设置历史账号',self.credentials)]:
            button=QPushButton(title);button.clicked.connect(callback);actions.addWidget(button)
        actions.addStretch();layout.addLayout(actions)
        note=QLabel('启动自动检查 · 只下载至上一交易日 · DDB 独立进程 · 不登录、切换或退出 VPN');note.setWordWrap(True);layout.addWidget(note)
        self.head=QLabel('等待首次缺口检查');self.head.setWordWrap(True);layout.addWidget(self.head)
        self.progress=QLabel();self.progress.setWordWrap(True);layout.addWidget(self.progress)
        self.coverage=make_table(['具体代码','频率','检查起点','目标日期','最新有效日','连续完整至','缺失天数']);layout.addWidget(self.coverage,2)
        paging=QHBoxLayout();self.filter=QLineEdit();self.filter.setPlaceholderText('筛选缺口代码 / 日期，例如 IF2703 或 2026-10-16')
        self.filter.textChanged.connect(self.filter_changed);paging.addWidget(self.filter,1)
        for title,offset in [('上一页',-1),('下一页',1)]:
            action=QPushButton(title);action.clicked.connect(lambda _,n=offset:self.turn_page(n));paging.addWidget(action)
        self.page_label=QLabel();paging.addWidget(self.page_label);layout.addLayout(paging)
        self.gaps=make_table(['具体代码','频率','交易日','已有 / 应有','缺失条数','状态','尝试次数','下次重试']);layout.addWidget(self.gaps,2)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(105);layout.addWidget(self.details)

    def refresh(self):
        c=self.controller;s=c.state()
        signature=(s.get('updated_at'),s.get('state'),s.get('message'),str(c.root),len(s.get('source_notes',[])))
        if signature==self.signature:return
        self.signature=signature
        pending=read(c.root/'pending.json') if c.root else {}
        def when(value):
            from datetime import datetime
            return datetime.fromtimestamp(value).strftime('%m-%d %H:%M:%S') if value else '—'
        notes=s.get('source_notes',[])
        self.head.setText(s.get('message','等待首次缺口检查')+(f' · {len(notes)} 项历史来源差异：保留原值，仅补缺失分钟' if notes else ''))
        self.progress.setText(f"下载上限：{s.get('target','待确定')}  |  剩余 {s.get('pending_symbol_days','待扫描')} 个代码/频率/交易日，{s.get('missing_bars','待扫描')} 条\n"
            f"本轮查询 {s.get('queries',0)} 次，已发布 {s.get('inserted',0)} 条  |  下次重试：{when(s.get('next_retry'))}\n"
            f"最近发布：{s.get('last_published_at','—')}  |  最近全部完整：{s.get('last_complete_at','—')}")
        fill(self.coverage,[[r.get(k) for k in ('symbol','frequency','start','target','latest','complete_through','missing_days')] for r in pending.get('coverage',[])])
        self.jobs=pending.get('jobs',[]);self.render_gaps()
        self.details.setPlainText('看板实际读取目录：\n'+'\n'.join(s.get('roots',c.model.config.get('history_roots',[])))+
            '\n发布版本：'+json.dumps(s.get('versions',{}),ensure_ascii=False)+
            (f'\n完整缺口清单：{c.root / "pending.json"}' if c.root else '')+
            ('\n来源差异：'+', '.join(n['symbol']+' '+n['day'] for n in notes) if notes else '')+
            '\n账号和密码使用 Windows 当前用户 DPAPI 加密；复制项目到公司电脑后需在该机重新录入。')

    def filter_changed(self):
        self.page=0;self.render_gaps()

    def turn_page(self,offset):
        self.page+=offset;self.render_gaps()

    def render_gaps(self):
        from datetime import datetime
        text=self.filter.text().strip().upper()
        jobs=[j for j in self.jobs if text in (j['symbol']+' '+j['frequency']+' '+j['day']).upper()]
        pages=max(1,(len(jobs)+199)//200);self.page=max(0,min(self.page,pages-1))
        self.page_label.setText(f'{self.page+1} / {pages} 页 · {len(jobs)} 项')
        names={'source_lag':'源数据未齐','downloaded':'待再次核验','conflict_requires_review':'来源冲突，保留原值','validation_failed':'校验未通过','source_query_failed':'查询失败'}
        when=lambda v:datetime.fromtimestamp(v).strftime('%m-%d %H:%M:%S') if v else '—'
        fill(self.gaps,[[j['symbol'],j['frequency'],j['day'],f"{j['observed']} / {j['expected']}",j['missing'],names.get(j.get('reason'),'等待下载'),j.get('attempts',0),when(j.get('retry_at'))] for j in jobs[self.page*200:(self.page+1)*200]])

    def credentials(self):
        from index_strategy.history.credentials import provider
        from index_strategy.history.downloader import DEFAULT_CONFIG
        c=self.controller;module=provider();path=Path(c.model.config.get('history_connection_file') or DEFAULT_CONFIG)
        try:value=module.load_config(path)
        except Exception:value={}
        dialog=QDialog(self);dialog.setWindowTitle('本机历史数据库凭据');form=QFormLayout(dialog);fields={}
        for key,title in [('host','DDB 地址'),('port','端口'),('username','账号'),('password','密码（空白保留已有）')]:
            field=QLineEdit('' if key=='password' else str(value.get(key,'')))
            if key=='password':field.setEchoMode(QLineEdit.EchoMode.Password)
            fields[key]=field;form.addRow(title,field)
        hint=QLabel('仅保存当前 Windows 用户可解密的凭据；此操作不会登录 VPN。');hint.setWordWrap(True);form.addRow(hint)
        error=QLabel();error.setWordWrap(True);form.addRow(error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)
        def save():
            try:
                candidate={**value,'host':fields['host'].text().strip(),'port':int(fields['port'].text()),'username':fields['username'].text().strip(),
                    'password':fields['password'].text() or value.get('password',''),'enable_ssl':value.get('enable_ssl',True)}
                if not candidate['host'] or not candidate['username'] or not 1<=candidate['port']<=65535:raise ValueError()
                module.save_config(path,candidate);fields['password'].clear();dialog.accept();c.retry()
            except Exception:error.setText('保存失败：检查地址、端口、账号、密码及本机凭据权限。')
        buttons.accepted.connect(save);dialog.exec();fields['password'].clear();value.clear()
