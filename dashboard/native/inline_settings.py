"""In-window settings; existing references and secret storage policy are retained."""
from copy import deepcopy
import json
from pathlib import Path

from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QLineEdit,QPlainTextEdit,QLabel,QPushButton


class InlineSettings(QWidget):
    def __init__(self,pipeline):
        super().__init__();self.pipeline=pipeline;self.fields={}
        layout=QVBoxLayout(self);toggle=QPushButton('展开 / 收起本机数据、Wind 与 DDB 设置');layout.addWidget(toggle)
        self.body=QWidget();layout.addWidget(self.body);form=QFormLayout(self.body);self.body.hide()
        toggle.clicked.connect(lambda:self.body.setVisible(not self.body.isVisible()))
        config=pipeline.model.config
        self.paths=QPlainTextEdit('\n'.join(config.get('history_roots',[])));self.paths.setMaximumHeight(60)
        form.addRow('已有标准历史目录（每行一个）',self.paths)
        from dashboard.app_config import connection_path,vpn_profile
        vpn=vpn_profile(config,pipeline.model.local_root)
        for key,title in [('reference_file','合约参考文件'),('realtime_root','已有实时目录'),('dividend_root','分红目录'),
                          ('overview_dividend_file','概览分红Excel（与旧表合并历史）'),
                          ('overview_dividend_source_dir','分红公盘目录（空白关闭公盘读取）'),
                          ('overview_dividend_pattern','分红文件规则'),('overview_dividend_check_am','上午检查时刻（上海）'),('overview_dividend_check_pm','下午检查时刻（上海）'),
                          ('history_python','历史 Python（空白自动选择）'),('history_connection_file','DDB 配置引用'),
                          ('overview_wind_python','WindPy Python（空白复用已有终端环境）'),
                          ('history_vpn_config','已有 DDB VPN 配置'),('history_vpn_trust','已有 VPN 证书信任文件'),
                          ('history_vpn_powershell','VPN PowerShell 7（空白自动选择）')]:
            value=str(connection_path(config)) if key=='history_connection_file' else str(config.get(key) or '')
            if key in ('history_vpn_config','history_vpn_trust','history_vpn_powershell'):
                value=str(vpn[{'history_vpn_config':'config','history_vpn_trust':'trust','history_vpn_powershell':'powershell'}[key]] or '')
            from dashboard.marketdata.overview_dividends import DEFAULT_SOURCE
            defaults=dict(overview_dividend_source_dir=DEFAULT_SOURCE,overview_dividend_pattern='指数基差情况_*.xlsx',overview_dividend_check_am='09:00',overview_dividend_check_pm='15:30')
            if key in defaults and key not in config:value=defaults[key]
            field=QLineEdit(value);self.fields[key]=field;form.addRow(title,field)
        save=QPushButton('保存路径（保留原库与其他设置）');form.addRow(save);save.clicked.connect(self.save_paths)
        self.notice=QLabel('已保存数据库与VPN凭据分别复用；有缺口时按需自动连接DDB VPN。实时VPN由你手动连接，盘中会提示。')
        self.notice.setWordWrap(True);form.addRow(self.notice)
        for key,title in [('host','DDB 地址'),('port','端口'),('username','数据库账号'),('password','新密码（留空保留已有）')]:
            field=QLineEdit();self.fields[key]=field;form.addRow(title,field)
            if key=='password':field.setEchoMode(QLineEdit.EchoMode.Password)
        load=QPushButton('读取已有数据库设置');form.addRow(load);load.clicked.connect(self.load_credentials)
        save=QPushButton('保存本机数据库凭据');form.addRow(save);save.clicked.connect(self.save_credentials)

    def idle(self):
        p=self.pipeline
        reference=getattr(p,'overview_reference',None)
        dividends=getattr(p,'overview_dividends',None)
        if dividends is not None and dividends.running():
            p.readonly();self.notice.setText('已请求停止分红任务；等待本地发布结束后再次保存。');return False
        if p.history.process is not None or p.collection.running() or p.task is not None or p.window.busy or reference is not None and reference.running():
            p.readonly();self.notice.setText('已请求安全停止；等待后台结束后再次保存。');return False
        return True

    def save_paths(self):
        if not self.idle():return
        p=self.pipeline;candidate=deepcopy(p.model.config)
        candidate.update({k:self.fields[k].text().strip() for k in ('reference_file','realtime_root','dividend_root','overview_dividend_file','overview_dividend_source_dir','overview_dividend_pattern','overview_dividend_check_am','overview_dividend_check_pm','history_python','history_connection_file',
                         'history_vpn_config','history_vpn_trust','history_vpn_powershell','overview_wind_python')})
        candidate['history_roots']=[s.strip() for s in self.paths.toPlainText().splitlines() if s.strip()]
        p.window.busy=True
        def work():p.model.save_config(candidate);return {}
        def done(result):
            p.window.busy=False
            self.notice.setText('保存失败：'+result.get('error_type','') if result.get('failed') else '路径已保存；可点击增量更新或验证实时。')
            p.window.refresh()
        p.submit(work,done)

    def load_credentials(self):
        from index_strategy.history.credentials import load_config
        try:
            value=load_config(Path(self.fields['history_connection_file'].text().strip()))
            for key in ('host','port','username'):self.fields[key].setText(str(value.get(key,'')))
            available=bool(value.get('password'));value.clear()
            self.notice.setText('当前用户可读取已有数据库凭据；密码不会回显。' if available else '配置可读，但缺数据库密码。')
        except Exception as exc:self.notice.setText('本机凭据不可读取：'+type(exc).__name__+'；确认配置引用和当前 Windows 用户。')

    def save_credentials(self):
        if not self.idle():return
        from index_strategy.history.credentials import provider
        module=provider();path=Path(self.fields['history_connection_file'].text().strip())
        try:
            try:value=module.load_config(path)
            except Exception:
                value=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
                value.pop('protected_credentials',None)
            value.update(host=self.fields['host'].text().strip(),port=int(self.fields['port'].text()),
                         username=self.fields['username'].text().strip(),
                         password=self.fields['password'].text() or value.get('password',''))
            value.setdefault('enable_ssl',True)
            if not value['host'] or not value['username'] or not 0<value['port']<65536:raise ValueError()
            module.save_config(path,value);value.clear();self.fields['password'].clear()
            self.notice.setText('已按原凭据提供器保存并核验；未连接 VPN。点击增量更新重试。')
        except Exception as exc:
            self.fields['password'].clear();self.notice.setText('保存失败：'+type(exc).__name__+'；核对输入与本机保护权限。')
