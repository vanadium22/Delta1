"""Native Qt controls for report filtering, local paths and record inspection."""
from __future__ import annotations

import os

from PySide6.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                              QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                              QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                              QListWidgetItem, QMenu, QPushButton, QTableView, QVBoxLayout,
                              QWidget)

from .query import number, parse_epsilon
from .storage import ReportError

DEFAULT_COLUMNS = {
    "swap": ["交易确认书编号", "交易对手名称", "标的物代码", "标的物名称", "我方资产方向",
             "标的名义数量", "标的名义本金额", "计息费率", "起始日", "期末观察日", "标的估值价格", "交易货币"],
    "review": ["协议编号", "交易对手", "标的", "互换类型", "交易起始日", "交易结算日",
               "起始价格", "股数", "利率", "币种", "起始/结算价是否在收盘价8%变动区间内",
               "期初/结算汇率是否在当前汇率10%变动区间内", "操作人员"],
}
COMMON_OPS = [("blank", "为空"), ("not_blank", "不为空")]
OPERATORS = {
    "text": [("fuzzy", "模糊匹配"), ("contains", "连续包含"), ("eq", "精确等于"), ("ne", "不等于")],
    "number": [("range", "范围（含边界）"), ("gt", "大于 >"), ("gte", "大于等于 ≥"),
               ("lt", "小于 <"), ("lte", "小于等于 ≤"), ("eq", "近似等于 ≈"),
               ("ne", "不等于 ≠"), ("zero", "近似零 |x| ≤ ε"), ("nonzero", "非零 |x| > ε")],
    "date": [("range", "日期区间"), ("eq", "等于"), ("gte", "不早于"), ("lte", "不晚于")],
}


def label(text="", name="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback=None, name=""):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:
        widget.setObjectName(name)
    if callback:
        widget.clicked.connect(callback)
    return widget


def default_visible(columns, kind):
    selected = [c["id"] for c in columns if c["name"] in DEFAULT_COLUMNS.get(kind, [])]
    return selected if len(selected) >= 3 else [c["id"] for c in columns[:12]]


class FilterRow(QWidget):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, columns, selected=None, parent=None):
        super().__init__(parent)
        self.columns = columns
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.join = QComboBox()
        self.join.addItem("必须 AND", "must")
        self.join.addItem("任一 OR", "any")
        self.join.setFixedWidth(124)
        self.join.setToolTip("所有必须条件都满足；所有任一条件组成一组，至少满足其中一条。空白条件不参与。")
        self.column = QComboBox()
        self.column.setMinimumWidth(145)
        self.column.setMaximumWidth(260)
        self.column.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.column.setToolTip("第一步：选择要筛选的列")
        for entry in columns:
            self.column.addItem(entry["name"], entry["id"])
        if selected:
            self.column.setCurrentIndex(max(0, self.column.findData(selected)))
        self.value_type = QComboBox()
        self.value_type.setMinimumWidth(85)
        for key, text in (("text", "文本"), ("number", "数字"), ("date", "日期")):
            self.value_type.addItem(text, key)
        self.value_type.setToolTip("第二步：选择内容格式。只影响此条件，不修改 Excel 原始值。")
        self.op = QComboBox()
        self.op.setMinimumWidth(135)
        self.value = QLineEdit()
        self.upper = QLineEdit()
        self.value.setMinimumWidth(100)
        self.upper.setMinimumWidth(100)
        self.separator = label("至")
        self.remove_button = button("移除", lambda: self.removed.emit(self), "quiet")
        for control in (self.join, self.column, self.value_type, self.op, self.value, self.separator,
                        self.upper, self.remove_button):
            row.addWidget(control, 1 if control in (self.column, self.value, self.upper) else 0)
        self.column.currentIndexChanged.connect(self._column_changed)
        self.join.currentIndexChanged.connect(self.changed)
        self.value_type.currentIndexChanged.connect(self._type_changed)
        self.op.currentIndexChanged.connect(self._op_changed)
        self.value.textChanged.connect(self.changed)
        self.upper.textChanged.connect(self.changed)
        self._column_changed()

    def _column_changed(self, *_):
        entry = next(c for c in self.columns if c["id"] == self.column.currentData())
        self.value_type.blockSignals(True)
        self.value_type.setCurrentIndex(self.value_type.findData(entry["type"]))
        self.value_type.blockSignals(False)
        self._type_changed()

    def _type_changed(self, *_):
        self.op.blockSignals(True)
        self.op.clear()
        for key, text in OPERATORS[self.value_type.currentData()] + COMMON_OPS:
            self.op.addItem(text, key)
        self.op.blockSignals(False)
        # Changing interpretation starts a fresh condition, avoiding a stale bound.
        for control in (self.value, self.upper):
            control.blockSignals(True)
            control.clear()
            control.blockSignals(False)
        self._op_changed()

    def _op_changed(self, *_):
        op = self.op.currentData()
        empty = op in ("zero", "nonzero", "blank", "not_blank")
        interval = op == "range"
        self.value.setVisible(not empty)
        self.upper.setVisible(interval)
        self.separator.setVisible(interval)
        kind = self.value_type.currentData()
        hint = "YYYY-MM-DD" if kind == "date" else "支持 1,000 / 1e-8 / 5%"
        self.value.setPlaceholderText("下限，可留空" if interval else (
            "例如：申万 / 证投" if kind == "text" else hint))
        self.upper.setPlaceholderText("上限，可留空")
        self.value.setToolTip(hint if kind != "text" else "空格：同时满足；/：满足任一；支持顺序简称")
        self.upper.setToolTip(hint)
        self.changed.emit()

    def condition(self):
        result = {"column": self.column.currentData(), "value_type": self.value_type.currentData(),
                  "op": self.op.currentData(), "join": self.join.currentData()}
        if result["op"] == "range":
            result.update(min=self.value.text().strip(), max=self.upper.text().strip())
        else:
            result["value"] = self.value.text().strip()
        return result


class ReportModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns, self.rows = [], []

    def set_result(self, result=None, columns=None):
        self.beginResetModel()
        self.columns = result["columns"] if result else (columns or [])
        self.rows = result["rows"] if result else []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.rows[index.row()]["values"][index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"Excel 第 {self.rows[index.row()]['excel_row']} 行\n原始值：{value if value is not None else '（空）'}"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            align = Qt.AlignmentFlag.AlignRight if self.columns[index.column()]["type"] == "number" else Qt.AlignmentFlag.AlignLeft
            return align | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and value is None:
            return QColor("#94a3b8")
        if role == Qt.ItemDataRole.DisplayRole:
            if value is None or value == "":
                return "—"
            if self.columns[index.column()].get("percent") and number(value) is not None:
                return f"{number(value) * 100:.10g}%"
            if isinstance(value, float):
                return f"{value:,.12g}"
            return str(value)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section]["name"] if orientation == Qt.Orientation.Horizontal else str(self.rows[section]["excel_row"])
        if role == Qt.ItemDataRole.ToolTipRole:
            return "单击排序" if orientation == Qt.Orientation.Horizontal else "Excel 原始行号"
        return None


class CopyTable(QTableView):
    cell_copied = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setDefaultSectionSize(35)
        self.verticalHeader().setMinimumWidth(48)
        self.horizontalHeader().setMinimumSectionSize(70)
        self.horizontalHeader().setStretchLastSection(False)
        self.setToolTip("右键可复制单个值；Ctrl+Shift+C 复制当前单元格，Ctrl+C 复制选中行。")

    def can_copy_cell(self, index=None):
        index = self.currentIndex() if index is None else index
        return (index.isValid() and index.model() == self.model()
                and not self.isColumnHidden(index.column()) and not self.isRowHidden(index.row())
                and self.selectionModel().isSelected(index))

    def copy_cell(self, index=None):
        index = self.currentIndex() if index is None else index
        if not self.can_copy_cell(index):
            return
        value = self.model().data(index, Qt.ItemDataRole.UserRole)
        QApplication.clipboard().setText("" if value is None else str(value))
        self.cell_copied.emit(str(self.model().headerData(index.column(), Qt.Orientation.Horizontal)))

    def contextMenuEvent(self, event):
        index = self.currentIndex() if event.reason() == event.Reason.Keyboard else self.indexAt(event.pos())
        if not index.isValid():
            return
        if self.selectionModel().isSelected(index):
            self.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        else:
            self.setCurrentIndex(index)
        # A query may finish while the menu is open; never copy the replacement row.
        target = QPersistentModelIndex(index)
        menu = QMenu(self)
        menu.addAction("复制此单元格", lambda: self.copy_cell(target))
        menu.addAction("复制选中行（含列名）", self.copy)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def copy(self):
        rows = sorted({index.row() for index in self.selectedIndexes()})
        columns = [i for i in range(self.model().columnCount()) if not self.isColumnHidden(i)]
        if not rows or not columns:
            return
        text_rows = [[self.model().headerData(c, Qt.Orientation.Horizontal) for c in columns]]
        text_rows += [[self.model().data(self.model().index(r, c), Qt.ItemDataRole.UserRole)
                       for c in columns] for r in rows]
        QApplication.clipboard().setText("\n".join("\t".join(str(v).replace("\t", " ").replace("\n", " ")
                                                   for v in row) for row in text_rows))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_C and event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self.copy_cell()
            event.accept()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
        else:
            super().keyPressEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        values = settings.get()
        self.values = None
        self.setWindowTitle("数据与同步")
        self.resize(740, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("数据与同步", "dialogTitle"))
        layout.addWidget(label("设置保存在本机，保存后立即生效。", "muted"))
        form = QFormLayout()
        form.setSpacing(12)
        self.source = QLineEdit(values["source_root"])
        self.destination = QLineEdit(values["data_dir"])
        self.destination.setToolTip(f"@shared 使用公共日报目录：{settings.paths.reports}")
        self.epsilon = QLineEdit(str(values["epsilon"]))
        self.source.setPlaceholderText("包含 YYYY-MM-DD 子文件夹的共享目录")
        for caption, field, env_key in (("共享来源目录", self.source, "SCRIPT_MAKING_SOURCE"),
                                        ("本地保存目录", self.destination, "SCRIPT_MAKING_DATA")):
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(field, 1)
            choose = button("浏览…", lambda checked=False, control=field: self.choose_folder(control))
            row.addWidget(choose)
            form.addRow(caption, container)
            if env_key in os.environ:
                field.setReadOnly(True)
                choose.setEnabled(False)
                form.addRow("", label(f"由环境变量 {env_key} 覆盖。移除覆盖后可修改。", "muted", True))
        form.addRow("默认数值容差 ε", self.epsilon)
        self.download_sources = {}
        for key, caption in (("pnl_source", "盈亏统计来源"), ("strategy_source", "策略台日报来源")):
            field = QLineEdit(values.get(key, ""))
            field.setPlaceholderText("留空：沿用上方来源的服务器前缀（自动识别年份）")
            self.download_sources[key] = field
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(field, 1)
            row.addWidget(button("浏览…", lambda checked=False, control=field: self.choose_folder(control)))
            form.addRow(caption, container)
        layout.addLayout(form)
        layout.addWidget(label("原日报来源按交易日提供两份同日期 Excel。新增来源留空时自动沿用同一服务器。\n"
                               "盈亏统计和策略台日报独立补齐，存入保存目录下的 downloads 子目录。\n"
                               "相对保存路径以本模块为基准；更换目录不会搬移已有文件。", "muted", True))
        self.preview = label("", "pathPreview", True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.preview)
        self.destination.textChanged.connect(self.update_preview)
        self.update_preview()
        self.error = label("", "error", True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addStretch()
        actions = QDialogButtonBox()
        actions.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        actions.addButton("保存设置", QDialogButtonBox.ButtonRole.AcceptRole)
        actions.accepted.connect(self.validate)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def update_preview(self):
        try:
            path = self.settings.data_path({"data_dir": self.destination.text().strip() or "data/reports"})
            self.preview.setText("实际保存位置：" + str(path))
        except (OSError, ValueError):
            self.preview.setText("请输入有效的本地保存目录。")

    def choose_folder(self, field):
        # Opening the chooser at a disconnected UNC path can block Windows.
        chosen = QFileDialog.getExistingDirectory(self, "选择文件夹", str(self.settings.root))
        if chosen:
            field.setText(chosen)

    def validate(self):
        try:
            if not self.destination.text().strip():
                raise ReportError("请填写本地保存目录。")
            self.values = {"source_root": self.source.text().strip(),
                           "data_dir": self.destination.text().strip(),
                           "epsilon": parse_epsilon(self.epsilon.text()),
                           **{key: field.text().strip() for key, field in self.download_sources.items()}}
            self.accept()
        except ReportError as exc:
            self.error.setText(str(exc))
            self.error.show()


class ColumnsDialog(QDialog):
    def __init__(self, columns, visible, kind, parent=None):
        super().__init__(parent)
        self.columns, self.kind = columns, kind
        self.setWindowTitle("显示列")
        self.resize(480, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(label("隐藏列仍参与搜索和筛选。", "muted"))
        tools = QHBoxLayout()
        tools.addWidget(button("全选", lambda: self.select([c["id"] for c in columns])))
        tools.addWidget(button("常用列", lambda: self.select(default_visible(columns, kind))))
        layout.addLayout(tools)
        self.list = QListWidget()
        for column in columns:
            item = QListWidgetItem(column["name"])
            item.setData(Qt.ItemDataRole.UserRole, column["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if column["id"] in visible else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        self.error = label("", "error")
        self.error.hide()
        layout.addWidget(self.error)
        actions = QDialogButtonBox()
        actions.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        actions.addButton("应用", QDialogButtonBox.ButtonRole.AcceptRole)
        actions.accepted.connect(self.apply)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def select(self, ids):
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)

    def selected(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def apply(self):
        if self.selected():
            self.accept()
        else:
            self.error.setText("请至少保留一列。")
            self.error.show()


class DetailDialog(QDialog):
    def __init__(self, columns, row, caption, parent=None):
        super().__init__(parent)
        self.setWindowTitle("合约记录详情")
        self.resize(820, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(label("记录详情", "dialogTitle"))
        layout.addWidget(label(f"{caption}  ·  Excel 第 {row['excel_row']} 行", "muted", True))
        self.table = CopyTable()
        self.model = ReportModel(self.table)
        self.model.set_result({"columns": [{"id": "field", "name": "字段", "type": "text"},
                                           {"id": "value", "name": "原始值", "type": "text"}],
                               "rows": [{"excel_row": i + 1, "values": [c["name"],
                                         "" if row["values"][i] is None else str(row["values"][i])]}
                                        for i, c in enumerate(columns)]})
        self.table.setModel(self.model)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.copy_cell_button = button("复制单元格", lambda: self.table.copy_cell())
        self.copy_cell_button.setToolTip("复制当前单元格原始值，不带字段名（Ctrl+Shift+C）")
        self.copy_cell_button.setEnabled(False)
        self.table.selectionModel().selectionChanged.connect(self.update_copy_cell)
        self.table.selectionModel().currentChanged.connect(self.update_copy_cell)
        actions.addWidget(self.copy_cell_button)
        actions.addWidget(button("复制全部字段", self.copy_all))
        actions.addStretch()
        actions.addWidget(button("关闭", self.accept, "primary"))
        layout.addLayout(actions)

    def update_copy_cell(self, *_):
        self.copy_cell_button.setEnabled(self.table.can_copy_cell())

    def copy_all(self):
        self.table.selectAll()
        self.table.copy()
