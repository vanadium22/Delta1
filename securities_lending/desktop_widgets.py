from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QLineEdit, QPlainTextEdit,
    QTableWidget, QVBoxLayout,
)

from .batch_input import parse_batch


class ResultTable(QTableWidget):
    copyRequested = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copyRequested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class TargetEdit(QLineEdit):
    focused = Signal()
    advance = Signal(int)
    pasteColumn = Signal(str)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            text = QApplication.clipboard().text()
            if "\n" in text.strip() or "\t" in text:
                self.pasteColumn.emit(text)
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down, Qt.Key.Key_Up) and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.advance.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
            return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, next):
        self.advance.emit(1 if next else -1)
        return True


class BatchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量录入 · 目标名本单位：万元")
        self.resize(620, 440)
        self.result_data = None
        layout = QVBoxLayout(self)
        hint = QLabel("粘贴代码/名称列表，或从 Excel 复制两列：代码/名称 + 目标名本（万元）。\n两列之间使用制表符；名称须唯一匹配。同一证券的冲突金额会被拒绝。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("600519\t500\n300750\t5000\n平安银行\t100")
        layout.addWidget(self.input)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用并查询")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply(self):
        try:
            self.result_data = parse_batch(self.input.toPlainText())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
