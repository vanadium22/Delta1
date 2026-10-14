import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget, QScrollArea, QApplication,
)

from .config import DEFAULTS, validate


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None, demo=False):
        super().__init__(parent)
        self.config = dict(config)
        self.fields = {}
        self.column_fields = {}
        self.setWindowTitle("数据与环境设置 · Delta1")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(780, screen.width() - 40), min(650, screen.height() - 60))
        layout = QVBoxLayout(self)
        if demo:
            note = QLabel("演示设置单独保存；演示始终使用合成文件和价格。")
            note.setObjectName("notice")
            layout.addWidget(note)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        for name in ("券单来源", "Wind 与环境", "表头与口径", "列名映射"):
            panel = QWidget()
            form = QFormLayout(panel)
            form.setContentsMargins(16, 16, 16, 16)
            form.setSpacing(10)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            tabs.addTab(scroll, name)
            if name == "券单来源":
                self.add_text(form, "source_root", "发送券单根目录")
                browse = QPushButton("选择共享目录…")
                browse.clicked.connect(self.choose_source)
                form.addRow("", browse)
                help_text = QLabel("每天按北京时间读取根目录 / YYYY-MM-DD / 文件名。\n先下载至项目本地，再读取 Excel；粘贴日期目录会自动替换日期。")
                help_text.setObjectName("muted")
                form.addRow("", help_text)
                self.add_text(form, "file_glob", "文件名模板 / 筛选")
                self.fields["file_glob"].setToolTip("{date} 自动替换为运行日 YYYY-MM-DD；也支持文件名通配符。")
                restore = QPushButton("恢复默认文件名和 Sheet")
                restore.clicked.connect(self.restore_file_defaults)
                form.addRow("", restore)
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
            elif name == "表头与口径":
                self.add_combo(form, "quantity_policy", "库存数量口径", [("逐笔取两列较小值", "minimum"), ("仅使用可融数量列", "primary")])
                self.add_combo(form, "quantity_unit", "无单位数量列", [(x, x) for x in ("股", "万股")])
                self.add_combo(form, "nominal_unit", "无单位名本列", [(x, x) for x in ("元", "万元", "亿元")])
                self.add_combo(form, "numeric_rate_unit", "数字费率", [("2.5 代表 2.5%", "percent"), ("0.025 代表 2.5%", "decimal")])
                row = QSpinBox()
                row.setRange(0, 100)
                row.setSpecialValueText("自动识别前 50 行")
                row.setValue(config["header_row"] or 0)
                self.fields["header_row"] = row
                form.addRow("Excel 表头行", row)
                help_text = QLabel("两列取小值：逐笔比较实际可融与可融股数，再汇总到股票。\n任一列缺失时无法确认上限。库存市值 = 有效股数 × 本次 Wind 最新价。\n单元格/表头显式单位优先；每只股票按 100 股向下取整。")
                help_text.setWordWrap(True)
                help_text.setObjectName("muted")
                form.addRow("", help_text)
            else:
                help_text = QLabel("填写 Excel 中的完整列名；留空使用自动识别。\n默认每笔取两列股数的较小值；原始市值仅供追溯，不用于计算。")
                help_text.setWordWrap(True)
                form.addRow(help_text)
                for key, title in (("code", "证券代码"), ("name", "证券名称"), ("quantity", "可融股数"), ("quantity_actual", "实际可融股数"), ("nominal", "券单原始市值（参考）"), ("nominal_limit", "券单市值上限（参考）"), ("rate", "出借费率"), ("industry", "行业"), ("price", "券单价格（参考）"), ("term", "期限"), ("source", "券源来源")):
                    field = QLineEdit(config["columns"].get(key, ""))
                    field.setPlaceholderText("自动识别")
                    self.column_fields[key] = field
                    form.addRow(title, field)
                defaults = QPushButton("使用申万库存券单默认列名")
                defaults.clicked.connect(self.restore_column_defaults)
                form.addRow("", defaults)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #af6946")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存演示设置并同步" if demo else "保存并同步")
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

    def restore_file_defaults(self):
        for key in ("file_glob", "sheet_name"):
            self.fields[key].setText(DEFAULTS[key])

    def restore_column_defaults(self):
        for key, field in self.column_fields.items():
            field.setText(DEFAULTS["columns"].get(key, ""))

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
            updated["columns"] = {key: field.text().strip() for key, field in self.column_fields.items() if field.text().strip()}
            validate(updated)
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            return
        self.config = updated
        self.accept()
