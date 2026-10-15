from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from .trader_contacts import save_contacts


class ContactsDialog(QDialog):
    def __init__(self, book, path, parent=None, error=""):
        super().__init__(parent)
        self.path, self.book = path, book
        self.setWindowTitle("行业联系表 · 修改后立即生效")
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        hint = QLabel("按行业名称精确匹配；不明确的行业可留空。此表只提供询券联系人，不判断券源归属或库存。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.group = QLineEdit(book["group"])
        self.note = QLineEdit(book["note"])
        self.note.setPlaceholderText("例如：照片暂读，姓名待核对；核对后可自行修改此备注")
        form.addRow("微信群名", self.group)
        form.addRow("联系表备注", self.note)
        layout.addLayout(form)
        self.tabs = QTabWidget()
        self.desks = self.add_table("交易台与联系人", ["交易台 / 分组", "联系人（多人用逗号或顿号分隔）"],
                                    [(desk, "、".join(names)) for desk, names in book["desks"].items()])
        self.industries = self.add_table("行业映射", ["行业名称（与查询结果一致）", "交易台 / 分组（不确定则留空）"],
                                         list(book["industries"].items()))
        layout.addWidget(self.tabs, 1)
        self.error = QLabel(error)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        location = QLabel(f"本机保存位置：{path}")
        location.setTextFormat(Qt.TextFormat.PlainText)
        location.setWordWrap(True)
        location.setObjectName("muted")
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(location)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_table(self, title, headers, rows):
        page = QWidget()
        layout = QVBoxLayout(page)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(headers)
        table.setColumnWidth(0, 280)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        for values in rows:
            self.append_row(table, values)
        if rows:
            table.setCurrentCell(0, 0)
        layout.addWidget(table)
        actions = QHBoxLayout()
        add, remove = QPushButton("新增一行"), QPushButton("删除选中行")
        add.clicked.connect(lambda: self.append_row(table))
        remove.clicked.connect(lambda: self.remove_rows(table))
        actions.addWidget(add)
        actions.addWidget(remove)
        actions.addStretch()
        layout.addLayout(actions)
        self.tabs.addTab(page, title)
        return table

    @staticmethod
    def append_row(table, values=("", "")):
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))
        table.setCurrentCell(row, 0)

    @staticmethod
    def remove_rows(table):
        for row in sorted({index.row() for index in table.selectionModel().selectedRows()}, reverse=True):
            table.removeRow(row)

    @staticmethod
    def table_values(table):
        values = {}
        for row in range(table.rowCount()):
            key, value = (table.item(row, column).text().strip() if table.item(row, column) else "" for column in range(2))
            if not key and not value:
                continue
            if not key or key in values:
                raise ValueError(f"第 {row + 1} 行名称为空或重复：{key}")
            values[key] = value
        return values

    def save(self):
        try:
            desks = {desk: [name.strip() for name in re.split(r"[,，、;；]+", names) if name.strip()]
                     for desk, names in self.table_values(self.desks).items()}
            value = {"schema_version": 1, "group": self.group.text(), "note": self.note.text(),
                     "desks": desks, "industries": self.table_values(self.industries)}
            self.book = save_contacts(self.path, value)
        except (OSError, ValueError) as exc:
            self.error.setText(f"未保存：{exc}")
            return
        self.error.clear()
        self.accept()
