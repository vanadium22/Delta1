"""Scrollable settings; endpoint changes do not rewrite protected credentials."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QLineEdit,QPlainTextEdit,
    QLabel,QPushButton,QGroupBox,QSizePolicy,QLayout)


class InlineSettings(QWidget):
    def __init__(self,pipeline):
        super().__init__();self.pipeline=pipeline;self.fields={}
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Maximum)
        layout=QVBoxLayout(self);layout.setSpacing(14);layout.setContentsMargins(0,0,0,0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        config=pipeline.model.config
        from dashboard.app_config import connection_path,vpn_profile
        from dashboard.marketdata.ddb_connection import app_endpoint
        try:endpoint=app_endpoint(config)
        except (ValueError,TypeError):endpoint={}
        database=self.group(layout,'DDB 数据地址')
        for key,title in [('host','生效地址'),('port','端口')]:
            field=self.field(key,str(endpoint.get(key,'')));database.addRow(title,field)
        self.endpoint_save=QPushButton('保存地址和端口（沿用原账号密码）')
        database.addRow(self.endpoint_save);self.endpoint_save.clicked.connect(self.save_endpoint)
        info=QLabel('当前发布地址 192.168.198.77:8904；原数据库配置只用于复用账号、密码和连接选项。')
        info.setWordWrap(True);database.addRow(info)
        self.notice=QLabel('价格日、DDB补齐目标和Y盘分红日分别显示；更新地址无需重新输入账号密码。')
        self.notice.setWordWrap(True);layout.addWidget(self.notice)
        toggle=QPushButton('展开 / 收起路径、分红、Wind、VPN与账号设置');layout.addWidget(toggle)
        self.body=QWidget();layout.addWidget(self.body);advanced=QVBoxLayout(self.body)
        advanced.setContentsMargins(0,0,0,0);advanced.setSpacing(16)
        advanced.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.body.hide();toggle.clicked.connect(lambda:self.body.setVisible(not self.body.isVisible()))
        local=self.group(advanced,'本地数据与解释器')
        self.paths=QPlainTextEdit('\n'.join(config.get('history_roots',[])));self.paths.setFixedHeight(84)
        local.addRow('标准历史目录（每行一个）',self.paths)
        forms={
            'reference_file':local,'realtime_root':local,'history_python':local,'history_connection_file':local,
        }
        dividends=self.group(advanced,'Y盘分红')
        for key in ('dividend_root','overview_dividend_file','overview_dividend_source_dir','overview_dividend_pattern',
                    'overview_dividend_check_am','overview_dividend_check_pm'):forms[key]=dividends
        forms['overview_wind_python']=self.group(advanced,'Wind终端')
        vpn_form=self.group(advanced,'DDB数据VPN')
        for key in ('history_vpn_config','history_vpn_trust','history_vpn_powershell'):forms[key]=vpn_form
        vpn=vpn_profile(config,pipeline.model.local_root)
        for key,title in [('reference_file','合约参考文件'),('realtime_root','已有实时目录'),('dividend_root','分红目录'),
                          ('overview_dividend_file','概览分红Excel'),
                          ('overview_dividend_source_dir','公盘目录（空白关闭公盘读取）'),
                          ('overview_dividend_pattern','文件规则'),('overview_dividend_check_am','上午检查时刻（上海）'),
                          ('overview_dividend_check_pm','下午检查时刻（上海）'),
                          ('history_python','历史Python（空白自动选择）'),('history_connection_file','原DDB凭据配置引用'),
                          ('overview_wind_python','WindPy Python（空白复用终端环境）'),
                          ('history_vpn_config','已有DDB VPN配置'),('history_vpn_trust','VPN证书信任文件'),
                          ('history_vpn_powershell','PowerShell 7（空白自动选择）')]:
            value=str(connection_path(config)) if key=='history_connection_file' else str(config.get(key) or '')
            if key in ('history_vpn_config','history_vpn_trust','history_vpn_powershell'):
                value=str(vpn[{'history_vpn_config':'config','history_vpn_trust':'trust','history_vpn_powershell':'powershell'}[key]] or '')
            from dashboard.marketdata.overview_dividends import DEFAULT_SOURCE,source_directory
            defaults=dict(overview_dividend_source_dir=DEFAULT_SOURCE,overview_dividend_pattern='指数基差情况_*.xlsx',
                          overview_dividend_check_am='09:00',overview_dividend_check_pm='15:30')
            if key in defaults and key not in config:value=defaults[key]
            if key=='overview_dividend_source_dir':value=str(source_directory(config) or '')
            label=QLabel(title);label.setWordWrap(True);label.setMinimumWidth(250);label.setMaximumWidth(290)
            forms[key].addRow(label,self.field(key,value))
        save=QPushButton('保存路径（保留原库与其他设置）');advanced.addWidget(save);save.clicked.connect(self.save_paths)
        account=self.group(advanced,'数据库账号（仅需要修改时填写）')
        account.addRow('账号',self.field('username',''));account.addRow('新密码（空白沿用原密码）',self.field('password',''))
        self.fields['password'].setEchoMode(QLineEdit.EchoMode.Password)
        load=QPushButton('读取已有账号（密码不回显）');account.addRow(load);load.clicked.connect(self.load_credentials)
        save=QPushButton('保存本机数据库凭据');account.addRow(save);save.clicked.connect(self.save_credentials)

    def field(self,key,value):
        field=QLineEdit(value);field.setMinimumHeight(40);field.setMinimumWidth(160)
        field.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.fields[key]=field;return field

    @staticmethod
    def group(layout,title):
        box=QGroupBox(title);form=QFormLayout(box);form.setSpacing(12);form.setContentsMargins(16,24,16,16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows);layout.addWidget(box)
        return form

    def idle(self):
        p=self.pipeline
        if getattr(p,'closing',False):return False
        reference=getattr(p,'overview_reference',None)
        dividends=getattr(p,'overview_dividends',None)
        if dividends is not None and dividends.running():
            p.readonly();self.notice.setText('已请求停止分红任务；等待本地发布结束后再次保存。');return False
        if p.history.process is not None or p.collection.running() or p.task is not None or p.window.busy or reference is not None and reference.running():
            p.readonly();self.notice.setText('已请求安全停止；等待后台结束后再次保存。');return False
        return True

    def save_config(self,candidate,message,before=None):
        p=self.pipeline;p.window.busy=True
        def work():
            if before is not None:before()
            p.model.save_config(candidate);return {}
        def done(result):
            p.window.busy=False
            self.notice.setText('保存失败：'+result.get('error_type','') if result.get('failed') else message)
            p.window.refresh()
        if not p.submit(work,done):
            p.window.busy=False;self.notice.setText('后台尚未就绪，请等待当前任务结束。')

    def save_endpoint(self):
        if not self.idle():return
        from dashboard.marketdata.ddb_connection import validate_endpoint
        try:endpoint=validate_endpoint(self.fields['host'].text(),self.fields['port'].text())
        except (ValueError,TypeError):
            self.notice.setText('地址或端口无效；地址只填主机/IP，端口为1–65535。');return
        candidate=deepcopy(self.pipeline.model.config)
        candidate.update(history_ddb_host=endpoint['host'],history_ddb_port=endpoint['port'])
        self.save_config(candidate,'DDB地址已保存，原账号密码未改；点击“DDB一键补齐”重试昨日数据。')

    def save_paths(self):
        if not self.idle():return
        candidate=deepcopy(self.pipeline.model.config)
        candidate.update({k:self.fields[k].text().strip() for k in ('reference_file','realtime_root','dividend_root','overview_dividend_file','overview_dividend_source_dir','overview_dividend_pattern','overview_dividend_check_am','overview_dividend_check_pm','history_python','history_connection_file',
                         'history_vpn_config','history_vpn_trust','history_vpn_powershell','overview_wind_python')})
        candidate['history_roots']=[s.strip() for s in self.paths.toPlainText().splitlines() if s.strip()]
        self.save_config(candidate,'路径已保存；可点击“DDB一键补齐”或验证实时。')

    def load_credentials(self):
        from index_strategy.history.credentials import load_config
        try:
            value=load_config(Path(self.fields['history_connection_file'].text().strip()))
            self.fields['username'].setText(str(value.get('username','')))
            available=bool(value.get('password'));value.clear()
            self.notice.setText('当前用户可读取已有数据库账号密码；生效地址以本页地址/端口为准，密码不回显。' if available else '配置可读，但缺数据库密码。')
        except Exception as exc:self.notice.setText('本机凭据不可读取：'+type(exc).__name__+'；确认引用和当前Windows用户。')

    def save_credentials(self):
        if not self.idle():return
        from index_strategy.history.credentials import provider
        from dashboard.marketdata.ddb_connection import validate_endpoint
        try:endpoint=validate_endpoint(self.fields['host'].text(),self.fields['port'].text())
        except (ValueError,TypeError):
            self.notice.setText('请核对DDB地址和端口。');return
        path=Path(self.fields['history_connection_file'].text().strip());module=provider()
        username=self.fields['username'].text().strip();password=self.fields['password'].text()
        self.fields['password'].clear()
        if not username:
            self.notice.setText('请先读取已有账号或填写数据库账号。');return
        candidate=deepcopy(self.pipeline.model.config)
        candidate.update(history_ddb_host=endpoint['host'],history_ddb_port=endpoint['port'])
        def save():
            # An unreadable protected password must never be replaced with blank.
            value=module.load_config(path) if path.exists() else {}
            value.update(**endpoint,username=username,password=password or value.get('password',''))
            if not value['password']:raise ValueError('missing_password')
            value.setdefault('enable_ssl',True);module.save_config(path,value);value.clear()
        self.save_config(candidate,'数据库凭据已按原保护方式保存；可点击“DDB一键补齐”。',before=save)
