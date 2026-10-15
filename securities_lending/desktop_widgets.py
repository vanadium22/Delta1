from PySide6.QtCore import Qt, Signal
from html import escape

from PySide6.QtGui import QKeySequence, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QLineEdit, QPlainTextEdit,
    QTableWidget, QVBoxLayout, QStyledItemDelegate, QStyle, QStyleOptionViewItem,
)

from .batch_input import parse_batch


class EmphasisDelegate(QStyledItemDelegate):
    """Keep plain cell text for accessibility/copy, with a larger primary value."""
    def paint(self, painter, option, index):
        if not index.data(Qt.ItemDataRole.UserRole):
            return super().paint(painter, option, index)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        styled.text = ""
        style = styled.widget.style() if styled.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        lines = text.splitlines()
        color = index.data(Qt.ItemDataRole.ForegroundRole)
        color = color.color().name() if color else "#203f50"
        size = 19 if index.column() == 2 else 14
        align = "right" if option.displayAlignment & Qt.AlignmentFlag.AlignRight else "left"
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setDocumentMargin(0)
        document.setHtml(f'<div style="text-align:{align};color:{color};font-size:{size}px;font-weight:700">{escape(lines[0])}</div>'
                         + ''.join(f'<div style="text-align:{align};color:#647887;font-size:11px">{escape(line)}</div>' for line in lines[1:]))
        document.setTextWidth(max(1, option.rect.width() - 16))
        painter.save()
        painter.setClipRect(option.rect)
        painter.translate(option.rect.x() + 8, option.rect.y() + max(4, (option.rect.height() - document.size().height()) / 2))
        document.drawContents(painter)
        painter.restore()


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
