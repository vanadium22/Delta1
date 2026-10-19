"""Explicit two-network startup. Never changes or stores VPN configuration."""
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from .history_maintenance import HistoryMaintenance, MaintenancePage, read


class LaunchWizard(QDialog):
    def __init__(self, model, parent=None, *, maintenance=None, probe=None, public=False):
        super().__init__(parent)
        self.demo = False
        self.model = model
        self.controller = maintenance or HistoryMaintenance(model)
        self.controller.authorized = False
        self.probe = probe
        self.public = public
        self.phase = 'choice'
        self.realtime = False
        self.task = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle('Delta1 · 双 VPN 启动向导')
        from .card_style import CARD_STYLE
        self.setStyleSheet(CARD_STYLE)
        self.resize(780, 240)
        layout = QVBoxLayout(self)
        self.note = QLabel(); self.note.setWordWrap(True); self.note.setStyleSheet('font-size:17px;padding:16px;'); layout.addWidget(self.note)
        self.page = MaintenancePage(self.controller); layout.addWidget(self.page)
        # The first choice must precede any credential save/retry action.
        self.page.hide()
        self.buttons = QHBoxLayout(); layout.addLayout(self.buttons)
        self.timer = QTimer(self); self.timer.setInterval(250); self.timer.timeout.connect(self.tick); self.timer.start()
        self.show_choice()

    def actions(self, text, choices):
        self.note.setText(text)
        self.resize(1000,700) if self.phase=='history' and not self.public else self.resize(780,240)
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for title, callback in choices:
            button = QPushButton(title); button.setMinimumHeight(42); button.clicked.connect(callback); self.buttons.addWidget(button)

    def show_choice(self):
        self.phase = 'choice'
        self.actions('启动前请选择。历史只补至上一交易日；选择之前不会采集实时行情。', [
            ('检查并补齐历史', self.ddb_prompt), ('跳过，使用现有历史', self.company_prompt), ('取消', self.reject)])

    def ddb_prompt(self):
        self.phase = 'ddb_prompt'
        self.actions('请在客户端登录 DDB VPN，再点击确认。程序只检查已有路由，使用本机加密数据库配置；不会切换 VPN。', [
            ('已登录，检查并补齐', self.start_history), ('跳过', self.company_prompt), ('取消', self.reject)])

    def start_history(self):
        self.phase = 'history'; self.page.setVisible(not self.public)
        self.controller.authorized = True
        self.controller.retry()
        self.actions('正在检查 / 补齐。可在下方查看进度、剩余缺口及重试时间。结束前不要切换 VPN。', [
            ('立即重试', self.controller.retry), ('停止补库并继续', lambda: self.drain('company')), ('取消启动', self.reject)])

    def drain(self, target):
        self.phase = 'draining_' + target
        self.controller.authorized = False
        self.controller.stop()
        self.page.setEnabled(False)
        self.actions('正在等待下载、校验、发布及 DDB 进程真正退出。此时不要切换 VPN。', [])

    def company_prompt(self):
        if self.controller.process is not None:
            self.drain('company'); return
        self.phase = 'company'; self.page.hide()
        self.actions('历史进程已退出。请断开 DDB VPN，并在客户端登录公司内网 VPN。确认后执行一次有限查询；也可离线查看已发布历史。', [
            ('已切换，验证连接', self.start_probe), ('离线进入', self.offline), ('取消', self.reject)])

    def start_probe(self):
        if self.task is not None or self.controller.process is not None: return
        from .app import Task
        from dashboard.session_guard import probe_realtime
        self.phase = 'probing'
        self.actions('正在有限验证公司行情连接；不会启动持续采集。', [('取消（等待查询退出）', self.reject)])
        self.task = Task(lambda: (self.probe or probe_realtime)(self.model.config))
        self.task.signals.completed.connect(self.probed)
        self.task.signals.failed.connect(lambda _: self.probed(dict(ok=False, message='连接验证失败，可重试或离线进入')))
        self.pool.start(self.task)

    def probed(self, result):
        self.task = None
        if self.phase == 'cancel_probe': self.finish_cancel(); return
        if result['ok']:
            self.realtime = True; self.timer.stop(); self.accept()
        else:
            self.phase = 'company'
            self.actions(result['message'], [('重试', self.start_probe), ('离线进入', self.offline), ('取消', self.reject)])

    def offline(self):
        if self.controller.process is not None or self.task is not None: return
        self.realtime = False; self.timer.stop(); self.accept()

    def tick(self):
        c = self.controller
        # Inspect exit before tick can schedule another bounded cycle.
        if self.phase == 'history' and c.process is not None and c.process.poll() == 0:
            raw = read(c.root / 'status.json') if c.root else {}
            if raw.get('state') == 'complete' and raw.get('missing_bars') == 0:
                self.drain('company')
        c.tick()
        if self.phase == 'history':
            if self.public:
                s=c.state()
                self.note.setText(f"{s.get('message','检查中')} · 剩余 {s.get('missing_bars','待扫描')} 条 · 目标 {s.get('target','上一交易日')}。账号设置和详细缺口请使用开发版。")
            else:self.page.refresh()
        if self.phase.startswith('draining_') and c.process is None:
            if self.phase == 'draining_cancel': self.finish_cancel()
            else: self.company_prompt()

    def finish_cancel(self):
        self.timer.stop(); super().reject()

    def reject(self):
        if self.task is not None:
            self.phase = 'cancel_probe'; self.actions('等待有限查询关闭会话后退出…', []); return
        if self.controller.process is not None: self.drain('cancel')
        else: self.finish_cancel()

    def closeEvent(self, event):
        event.ignore(); self.reject()
