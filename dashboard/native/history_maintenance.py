"""Cooperative owner of one bounded history worker. Never terminates a writer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from dashboard.marketdata.history_publication import maintenance_root


def read(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return {}


class HistoryMaintenance:
    def __init__(self,model):
        self.model=model;self.process=None;self.root=None;self.stop_file=None
        self.error=None;self.closing=False;self.authorized=False;self.started=0

    def state(self):
        value=read(self.root/'status.json') if self.root else {}
        return {**value,**(self.error or {})}

    def start(self,*,deep=False,force=False):
        if self.process is not None or not self.authorized or self.closing:return False
        roots=self.model.config.get('history_roots') or []
        if not roots:
            self.error=dict(state='waiting_configuration',message='请在数据设置中指定已有历史目录');return False
        self.root=maintenance_root(roots);self.root.mkdir(parents=True,exist_ok=True)
        self.stop_file=self.root/('app-stop-'+uuid.uuid4().hex)
        from dashboard.marketdata.bars import _atomic_bytes,_json_bytes
        _atomic_bytes(self.model.local_root/'history_control.json',_json_bytes(dict(paused=False)))
        from dashboard.app_config import history_python
        interpreter=history_python(self.model.config)
        # A saved explicit interpreter is authoritative. Do not silently upgrade it.
        if str(interpreter).lower().endswith('pythonw.exe'):interpreter=str(Path(interpreter).with_name('python.exe'))
        cmd=[str(interpreter),'-B','-s','-X','utf8','-m','dashboard.marketdata.history_maintenance',
             '--once','--local-root',str(self.model.local_root),'--stop-file',str(self.stop_file)]
        if force:cmd+=['--force']
        cmd+=['--vpn-mode',self.model.config.get('history_vpn_mode','auto')]
        if self.model.config.get('reference_file'):cmd+=['--reference-file',self.model.config['reference_file']]
        if os.name=='nt':cmd+=['--owner-pid',str(os.getpid())]
        if not deep:cmd+=['--incremental']
        cmd+=['--include-completed-today','--overview-daily']
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
        try:
            self.process=subprocess.Popen(cmd,cwd=Path(__file__).resolve().parents[2],stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
            self.started=time.monotonic();self.error=None;return True
        except OSError as exc:
            self.error=dict(state='waiting_sdk',message='历史解释器无法启动；请核对内联设置',error_type=type(exc).__name__)
            return False

    def tick(self):
        if self.process is None:return None
        if self.process.poll() is None:return None
        code=self.process.returncode;self.process=None
        if self.stop_file:self.stop_file.unlink(missing_ok=True)
        if code not in (0,2):
            self.error=dict(state='busy' if code==3 else 'failed',
                message='共享网络/历史任务正在使用或本地权限受限' if code==3 else '历史任务未完成；核对解释器、SDK及已有配置',exit_code=code)
        return code

    def pause(self):
        self.authorized=False
        if self.stop_file:self.stop_file.touch(exist_ok=True)

    def retry(self):
        return self.start()

    def stop(self):
        self.closing=True;self.pause()


# Kept as a non-modal view for existing development integrations.
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel
class MaintenancePage(QWidget):
    def __init__(self,controller):
        super().__init__();self.controller=controller;layout=QVBoxLayout(self)
        self.head=QLabel();self.head.setWordWrap(True);layout.addWidget(self.head)
    def refresh(self):
        from dashboard.history_status import progress_text
        state=self.controller.state();self.head.setText(state.get('message','')+'\n'+progress_text(state))
