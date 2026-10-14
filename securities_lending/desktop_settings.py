import json
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from .config import validate


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.fields = {}
        self.setWindowTitle("数据与环境设置 · Delta1")
        self.resize(720, 680)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        for name in ("券单来源", "Wind 与环境", "表头与口径"):
            panel = QWidget()
            form = QFormLayout(panel)
            form.setContentsMargins(20, 24, 20, 20)
            form.setSpacing(17)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            tabs.addTab(panel, name)
            if name == "券单来源":
                self.add_text(form, "source_root", "发送券单根目录")
                browse = QPushButton("选择共享目录…")
                browse.clicked.connect(self.choose_source)
                form.addRow("", browse)
                help_text = QLabel("每天自动读取根目录 / YYYY-MM-DD。\n粘贴带日期的目录也可以，运行时会替换日期。")
                help_text.setObjectName("muted")
                form.addRow("", help_text)
                self.add_text(form, "file_glob", "文件筛选")
                self.add_combo(form, "file_selection", "读取方式", [("最新一份（修改时间）", "latest"), ("合并独立券源", "merge")])
                self.add_text(form, "sheet_name", "库存 Sheet")
            elif name == "Wind 与环境":
                current = QLabel(sys.executable)
                current.setWordWrap(True)
                current.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                form.addRow("App 当前 Python", current)
                self.fields["wind_enabled"] = QCheckBox("使用 Wind 获取最新价格和缺失行业")
                self.fields["wind_enabled"].setChecked(config["wind_enabled"])
                form.addRow("Wind", self.fields["wind_enabled"])
                self.add_text(form, "wind_python", "Wind Python 路径")
                self.fields["wind_python"].setPlaceholderText("留空：使用 App 同一 Python 环境")
                note = QLabel("公司建议使用 D:\\conda\\envs\\swhy_delta1。\nWindPy 由你在公司安装；家中没有 Wind 也可使用演示。\n最新价使用 WSQ / RT_LAST，每次查询、计算重新获取。")
                note.setObjectName("muted")
                note.setWordWrap(True)
                form.addRow("", note)
                self.add_text(form, "wind_field", "行业字段")
                self.add_text(form, "wind_options", "行业参数")
                self.add_text(form, "industry_label", "行业口径名称")
                timeout = QSpinBox()
                timeout.setRange(1, 120)
                timeout.setValue(int(config["wind_timeout_seconds"]))
                timeout.setSuffix(" 秒")
                self.fields["wind_timeout_seconds"] = timeout
                form.addRow("Wind 总超时", timeout)
            else:
                self.add_combo(form, "quantity_unit", "无单位数量列", [(x, x) for x in ("股", "万股")])
                self.add_combo(form, "nominal_unit", "无单位名本列", [(x, x) for x in ("元", "万元", "亿元")])
                self.add_combo(form, "numeric_rate_unit", "数字费率", [("2.5 代表 2.5%", "percent"), ("0.025 代表 2.5%", "decimal")])
                row = QSpinBox()
                row.setRange(0, 100)
                row.setSpecialValueText("自动识别前 50 行")
                row.setValue(config["header_row"] or 0)
                self.fields["header_row"] = row
                form.addRow("Excel 表头行", row)
                columns = QPlainTextEdit(json.dumps(config["columns"], ensure_ascii=False, indent=2))
                columns.setMinimumHeight(160)
                self.fields["columns"] = columns
                form.addRow("原始列名映射 JSON", columns)
                help_text = QLabel("支持：code、name、quantity、nominal、rate、industry、price、term。\n计算规则固定为每只票 100 股向下取整。")
                help_text.setWordWrap(True)
                help_text.setObjectName("muted")
                form.addRow("", help_text)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #af6946")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并同步")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_text(self, form, key, label):
        self.fields[key] = QLineEdit(self.config[key])
        form.addRow(label, self.fields[key])

    def add_combo(self, form, key, label, choices):
        field = QComboBox()
        for text, value in choices:
            field.addItem(text, value)
        field.setCurrentIndex(field.findData(self.config[key]))
        self.fields[key] = field
        form.addRow(label, field)

    def choose_source(self):
        folder = QFileDialog.getExistingDirectory(self, "选择发送券单根目录", self.fields["source_root"].text())
        if folder:
            self.fields["source_root"].setText(folder)

    def save(self):
        updated = dict(self.config)
        try:
            for key, field in self.fields.items():
                if isinstance(field, QLineEdit):
                    updated[key] = field.text().strip()
                elif isinstance(field, QComboBox):
                    updated[key] = field.currentData()
                elif isinstance(field, QCheckBox):
                    updated[key] = field.isChecked()
                elif isinstance(field, QSpinBox):
                    updated[key] = (field.value() or None) if key == "header_row" else field.value()
                elif key == "columns":
                    updated[key] = json.loads(field.toPlainText() or "{}")
            validate(updated)
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            return
        self.config = updated
        self.accept()
