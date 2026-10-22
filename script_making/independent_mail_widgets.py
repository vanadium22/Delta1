"""Separate recipient settings for the two independent mail-producing jobs."""
import json
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                              QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from .desktop_widgets import label
from .pnl_history import CONFIG_NAME, self_config
from .stock_mail import CONFIG, load_profile, profile
from .storage import ReportError, atomic_json


class IndependentMailDialog(QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.setWindowTitle('独立任务邮箱')
        self.resize(820, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(label('各任务独立保存收件邮箱。下一次运行自动读取；此处保存不会发邮件或修改定时。', 'muted', True))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        values = load_profile(root)
        stock = QWidget()
        body = QVBoxLayout(stock)
        body.addWidget(label('收益互换纯个股敞口', 'sectionTitle'))
        body.addWidget(label('沿用附件3的纯个股口径和日报阈值/永久剔除名单，不含ETF。正文自动解释筛选范围及带符号Delta金额，附一张明细图。', 'muted', True))
        form = QFormLayout()
        self.entries = {}
        for key, caption in (('to', '收件人'), ('cc', '抄送'), ('subject', '邮件主题')):
            widget = QLineEdit(values[key])
            self.entries[key] = widget
            form.addRow(caption, widget)
        body.addLayout(form)
        body.addWidget(label('多个邮箱用逗号分隔；主题中的 {{date}} 自动替换为来源报表日期。收件人留空表示尚未配置，该任务不会生成可发送结果。', 'muted', True))
        body.addWidget(label('正文补充说明（附在自动生成的敞口解释之后）'))
        self.note = QTextEdit(values['note'])
        self.note.setAcceptRichText(False)
        body.addWidget(self.note, 1)
        tabs.addTab(stock, '纯个股敞口任务')
        history = QWidget()
        history_layout = QVBoxLayout(history)
        history_layout.addWidget(label('本人场外业务及各组收益历史', 'sectionTitle'))
        history_layout.addWidget(label('沿用已有本人收益两图任务，只允许一个本人邮箱，不设抄送或密送。原日报收件人仍在原“邮件设置”中管理。', 'muted', True))
        path = self.root / CONFIG_NAME
        self.original_self = self_config(json.loads(path.read_text(encoding='utf-8')))['to'] if path.exists() else ''
        self.self_email = QLineEdit(self.original_self)
        self_form = QFormLayout()
        self_form.addRow('本人邮箱', self.self_email)
        history_layout.addLayout(self_form)
        history_layout.addStretch()
        tabs.addTab(history, '本人收益两图任务')
        self.error = label('', 'error', True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            values = profile({**{key: widget.text() for key, widget in self.entries.items()},
                              'note': self.note.toPlainText()})
            history = None
            if self.self_email.text().strip() != self.original_self:
                history = self_config({'to': self.self_email.text()})
            atomic_json(self.root / CONFIG, values)
            if history is not None:
                atomic_json(self.root / CONFIG_NAME, history)
            self.accept()
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()
