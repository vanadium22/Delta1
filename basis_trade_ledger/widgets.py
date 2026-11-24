from decimal import Decimal
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .model import DIRECTIONS, NUMBERS, calculate, trade_data


def fmt(value, digits=2, missing='—'):
    if value is None or value == '':
        return missing
    return f'{Decimal(str(value)) if value else Decimal(0):,.{digits}f}'


def text_input(placeholder='', name=''):
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setObjectName(name)
    edit.setMinimumWidth(0)
    return edit


def label(text='', name=''):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def button(text, action, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName('primary')
    widget.clicked.connect(action)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName('card')
    return widget


class MetricCard(QFrame):
    def __init__(self, caption, *, primary=False):
        super().__init__()
        self.setObjectName('pnlHero' if primary else 'pnlCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 9)
        layout.setSpacing(3)
        layout.addWidget(label(caption, 'pnlCaption'))
        self.value = label('—', 'metricValue')
        self.context = label('', 'pnlContext')
        self.context.setMinimumWidth(0)
        layout.addWidget(self.value)
        layout.addWidget(self.context)
        self.tone = None

    def set_metric(self, value, context, *, digits=2, missing='待估值', color=False):
        self.value.setText(fmt(value, digits, missing))
        self.context.setText(context)
        tone = 'gain' if color and value and value > 0 else 'loss' if color and value and value < 0 else 'metricValue'
        if tone != self.tone:
            self.tone = tone
            self.value.setObjectName(tone)
            self.value.style().unpolish(self.value)
            self.value.style().polish(self.value)


class Table(QTableWidget):
    def __init__(self, headers, widths):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(31)
        self.horizontalHeader().setStretchLastSection(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for i, width in enumerate(widths):
            self.setColumnWidth(i, width)

    def fill(self, rows):
        self.setUpdatesEnabled(False)
        try:
            self.clearContents()
            self.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for j, value in enumerate(row):
                    item = QTableWidgetItem('' if value is None else str(value))
                    item.setToolTip(item.text())
                    self.setItem(i, j, item)
        finally:
            self.setUpdatesEnabled(True)


TRADE_BASIS_COLUMN = 3


class TradeTable(Table):
    def __init__(self):
        super().__init__(('成交时间', '方向', '状态', '等价基差', 'ETF 份额', 'ETF 均价', 'ETF 金额', '期货手数',
                          '期货价', '费用', '本笔已实现', '来源', '备注'),
                         (157, 78, 92, 95, 94, 96, 110, 82, 90, 76, 105, 105, 135))

    def fill(self, rows):
        super().fill(rows)
        for i, row in enumerate(rows):
            for col in range(TRADE_BASIS_COLUMN, 11):
                self.item(i, col).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            basis = self.item(i, TRADE_BASIS_COLUMN)
            if row[TRADE_BASIS_COLUMN] != '—':
                basis.setForeground(QColor('#126b60'))
                font = basis.font()
                font.setBold(True)
                basis.setFont(font)
                basis.setToolTip(f'{basis.text()} 点 · 查看折算明细')


def trade_table():
    return TradeTable()


def trade_display(row):
    status = '已入账' if row['status'] == 'posted' else '草稿'
    if row.get('source_status') == '待核配对':
        status += ' · 待核'
    origin = ' · '.join(filter(None, (row.get('origin'), row.get('entry_type'))))
    timestamp = row.get('time')
    if timestamp and timestamp.count(':') == 2 and timestamp.endswith(':00'):
        timestamp = timestamp[:-3]
    return (timestamp, row['direction'], status, fmt(row.get('basis'), 4), fmt(row.get('shares'), 0), fmt(row.get('etf_price'), 6),
            fmt(row.get('amount')), fmt(row.get('lots'), 0), fmt(row.get('futures_price'), 4), fmt(row.get('fee')),
            fmt(row.get('realized')), origin, row.get('note'))


class FormDialog(QDialog):
    def __init__(self, title, fields, values, commit, parent, *, submit='保存', hint=''):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        outer = QVBoxLayout(self)
        outer.addWidget(label(title, 'dialogTitle'))
        if hint:
            guidance = label(hint, 'muted')
            guidance.setWordWrap(True)
            outer.addWidget(guidance)
        form = QFormLayout()
        self.fields = {}
        for key, caption, placeholder in fields:
            edit = text_input(placeholder, key)
            value = values.get(key)
            edit.setText(str(value) if value is not None else '')
            self.fields[key] = edit
            form.addRow(caption, edit)
        outer.addLayout(form)
        self.error = label('', 'error')
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button('取消', self.reject))
        save = button(submit, self.submit, True)
        save.setDefault(True)
        actions.addWidget(save)
        outer.addLayout(actions)
        self.commit = commit
        self.result_value = None

    def submit(self):
        try:
            self.result_value = self.commit({key: edit.text().strip() for key, edit in self.fields.items()})
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()


PLAN_FIELDS = (('base_shares', '参考底仓（份）', '选填'), ('plan_lots', '计划期货（手）', '选填'))
GROUP_FIELDS = (('name', '组名', '留空使用标的组合'), ('opened', '开组日期', 'YYYY-MM-DD'),
                ('etf', 'ETF 代码', '例如 510500.SH'), ('futures', '股指期货合约', '例如 IC2612.CFE'),
                ('multiplier', '合约乘数', '例如 200'), ('index', '跟踪指数代码', '选填，用于计划折算'), *PLAN_FIELDS)


class TradeEditor(QFrame):
    save_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('card')
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.heading = label('录入成交', 'sectionTitle')
        top.addWidget(self.heading)
        top.addStretch()
        self.cancel = button('返回新录入', self.reset)
        top.addWidget(self.cancel)
        layout.addLayout(top)
        self.fields = {key: text_input(name=key) for key in (*NUMBERS, 'time', 'note', 'reason')}
        self.fields['time'].setPlaceholderText('YYYY-MM-DD HH:MM 或留空')
        self.fields['fee'].setPlaceholderText('选填')
        self.fields['note'].setPlaceholderText('选填')
        self.direction = QComboBox()
        self.direction.setObjectName('direction')
        self.direction.addItems(DIRECTIONS.keys())
        self.method = QComboBox()
        self.method.addItem('填 ETF 均价', 'etf_price')
        self.method.addItem('填 ETF 金额', 'amount')
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        for i, (caption, control) in enumerate((('交易方向', self.direction), ('成交时间', self.fields['time']),
                ('ETF 输入方式', self.method), ('费用', self.fields['fee']), ('备注', self.fields['note']),
                ('ETF 份额', self.fields['shares']), ('ETF 均价', self.fields['etf_price']),
                ('ETF 金额', self.fields['amount']), ('期货手数', self.fields['lots']), ('期货均价', self.fields['futures_price']))):
            row, col = divmod(i, 5)
            grid.addWidget(label(caption, 'muted'), row * 2, col)
            grid.addWidget(control, row * 2 + 1, col)
            grid.setColumnStretch(col, (2, 3, 2, 2, 2)[col])
        layout.addLayout(grid)
        actions = QHBoxLayout()
        self.reason_label = label('更正原因', 'muted')
        actions.addWidget(self.reason_label)
        actions.addWidget(self.fields['reason'], 1)
        actions.addStretch(1)
        self.draft = button('存草稿', lambda: self.save_requested.emit('draft'))
        self.post = button('入账', lambda: self.save_requested.emit('posted'), True)
        self.post.setObjectName('primary')
        actions.addWidget(self.draft)
        actions.addWidget(self.post)
        layout.addLayout(actions)
        self.direction.currentIndexChanged.connect(self.update_legs)
        self.method.currentIndexChanged.connect(self.update_legs)
        for key in ('shares', 'amount', 'etf_price'):
            self.fields[key].textEdited.connect(self.update_legs)
        self.reset()

    def values(self):
        return dict({key: edit.text().strip() for key, edit in self.fields.items()},
                    direction=self.direction.currentText(), etf_input=self.method.currentData())

    def update_legs(self):
        etf, futures = DIRECTIONS[self.direction.currentText()]
        self.method.setEnabled(bool(etf))
        for key in ('shares', 'amount', 'etf_price'):
            self.fields[key].setEnabled(bool(etf))
        for key in ('lots', 'futures_price'):
            self.fields[key].setEnabled(bool(futures))
        method = self.method.currentData()
        derived = 'amount' if method == 'etf_price' else 'etf_price'
        self.fields[method].setReadOnly(False)
        self.fields[method].setPlaceholderText('')
        self.fields[derived].setReadOnly(True)
        self.fields[derived].setPlaceholderText('自动折算')
        if not etf:
            return
        data = self.values()
        try:
            # The entry calculation is independent of incomplete fields on the other leg.
            result = trade_data({key: data[key] for key in ('shares', method, 'etf_input')}
                                | {'direction': 'ETF买入'}, 'draft')[derived]
        except ValueError:
            result = None
        self.fields[derived].setText(format(result.normalize(), 'f') if result is not None else '')

    def reset(self):
        self.load(None)

    def load(self, row):
        self.entry = row
        posted = row and row['status'] == 'posted'
        self.heading.setText('更正已入账成交' if posted else '编辑草稿' if row else '录入成交')
        self.cancel.setVisible(bool(row))
        self.draft.setVisible(not posted)
        self.post.setText('保存更正' if posted else '入账')
        self.fields['reason'].setVisible(bool(posted))
        self.reason_label.setVisible(bool(posted))
        self.direction.setCurrentText((row or {}).get('direction', '买基差'))
        self.method.setCurrentIndex(max(0, self.method.findData((row or {}).get('etf_input'))))
        for key, field in self.fields.items():
            value = (row or {}).get(key)
            field.setText(str(value) if value is not None else '')
        self.update_legs()


def audit_display(audit, layout):
    warnings = audit.get('warnings', [])
    layout.addWidget(label(f"{audit['file']}  /  {audit['sheet']}", 'sectionTitle'))
    if warnings:
        alert = label('\n'.join(warnings), 'notice')
        alert.setWordWrap(True)
        layout.addWidget(alert)
    rows = audit['differences']
    layout.addWidget(label(f'汇总差异（{len(rows)} 项）', 'sectionTitle'))
    if rows:
        differences = Table(('指标', '来源单元格', '原表', '重算', '差额'), (156, 105, 110, 110, 110))
        differences.fill([_comparison(row, True) for row in rows])
        layout.addWidget(differences, 2)
    if audit.get('legacy'):
        layout.addWidget(label('旧版两腿成交与结算', 'sectionTitle'))
        legacy = Table(('来源行', '类型', '标的', '原方向', '数量', '均价', '金额', 'ETF 折算手数', '原表基差', '原表配对'),
                       (88, 74, 63, 74, 88, 99, 112, 101, 90, 130))
        legacy.fill([(row['origin'], row['type'], row['leg'], row['direction'], fmt(row['quantity'], 0),
                      fmt(row['price'], 6), fmt(row['amount']), fmt(row['equiv_lots'], 0),
                      fmt(row['source_basis'], 4), row['match']) for row in audit['legacy']])
        layout.addWidget(legacy, 2)
        pnl = Table(('结算指标', '来源单元格', '原表（元）', '导入时重算（元）'), (150, 105, 120, 150))
        pnl.fill([_comparison(row, False) for row in audit['settlement']])
        layout.addWidget(pnl, 1)
    if not rows and not audit.get('legacy'):
        layout.addStretch()


def _comparison(row, include_delta):
    def display(value):
        try:
            return fmt(value, row['digits'])
        except ArithmeticError:
            return str(value)
    result = (row['label'], row['cell'], display(row['original']), display(row['current']))
    if include_delta:
        try:
            delta = Decimal(str(row['current'])) - Decimal(str(row['original']))
        except ArithmeticError:
            delta = None
        result += (fmt(delta, row['digits']),)
    return result


class ImportDialog(QDialog):
    def __init__(self, groups, skipped, parent):
        super().__init__(parent)
        self.groups = groups
        self.setWindowTitle('Excel 导入预览')
        self.resize(1100, 670)
        outer = QVBoxLayout(self)
        outer.addWidget(label('Excel 导入预览', 'dialogTitle'))
        body = QHBoxLayout()
        self.sheets = QListWidget()
        self.sheets.setFixedWidth(176)
        for group in groups:
            item = QListWidgetItem(group.config['name'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.sheets.addItem(item)
        body.addWidget(self.sheets)
        self.tabs = QTabWidget()
        body.addWidget(self.tabs, 1)
        outer.addLayout(body, 1)
        if skipped:
            summary = label('以下工作表无法导入，需复核原表\n' + '\n'.join(skipped), 'notice')
            summary.setWordWrap(True)
            outer.addWidget(summary)
        footer = QHBoxLayout()
        footer.addWidget(label('勾选要入库的交易组。' if groups else '工作簿中暂无可导入的交易组。', 'muted'))
        footer.addStretch()
        footer.addWidget(button('取消', self.reject))
        confirm = button('确认入库', self.accept, True)
        confirm.setEnabled(bool(groups))
        footer.addWidget(confirm)
        outer.addLayout(footer)
        self.sheets.currentRowChanged.connect(self.show_sheet)
        self.sheets.itemChanged.connect(lambda: confirm.setEnabled(bool(self.selected())))
        if groups:
            self.sheets.setCurrentRow(0)

    def selected(self):
        return [group for i, group in enumerate(self.groups) if self.sheets.item(i).checkState() == Qt.CheckState.Checked]

    def show_sheet(self, index):
        if index < 0:
            return
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        group = self.groups[index]
        result = calculate(group.config, group.trades, group.quotes)
        differences = QWidget()
        audit_display(group.audit, QVBoxLayout(differences))
        self.tabs.addTab(differences, '原表核对')
        rows = QWidget()
        layout = QVBoxLayout(rows)
        layout.addWidget(label(f"{group.config['etf']}　/　{group.config['futures']}　"
                               f"ETF 净仓 {fmt(result['etf'].quantity, 0)} 份　"
                               f"期货净仓 {fmt(result['futures'].quantity, 0)} 手　"
                               f"已实现 {fmt(result['realized'])} 元", 'sectionTitle'))
        table = trade_table()
        table.fill([trade_display(row) for row in result['rows']])
        layout.addWidget(table)
        self.tabs.addTab(rows, f'流水（{len(group.trades)}）')
        if group.marks is not None and not group.audit['warnings']:
            self.tabs.setCurrentIndex(1)


class BasisDialog(QDialog):
    def __init__(self, rows, parent, *, selected=None):
        super().__init__(parent)
        self.entries = [row for row in rows if row.get('basis_detail')]
        self.setWindowTitle('逐笔等价基差')
        self.resize(900, 530)
        layout = QVBoxLayout(self)
        layout.addWidget(label('逐笔等价基差', 'dialogTitle'))
        self.table = Table(('成交时间', '方向', 'ETF 金额（元）', '期货手数', '期货价（点）', '等价基差（点）', '来源'),
                           (154, 80, 115, 82, 101, 111, 105))
        self.table.fill([self._display(row) for row in self.entries])
        layout.addWidget(self.table, 1)
        panel = card()
        breakdown = QVBoxLayout(panel)
        self.detail_caption = label('', 'sectionTitle')
        self.equation = label('', 'equivalentEquation')
        self.origin = label('', 'muted')
        for widget in (self.detail_caption, self.equation, self.origin):
            widget.setWordWrap(True)
            breakdown.addWidget(widget)
        layout.addWidget(panel)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(button('关闭', self.accept))
        layout.addLayout(footer)
        self.table.currentCellChanged.connect(lambda row, *_: self.show_formula(row))
        if self.entries:
            index = next((i for i, row in enumerate(self.entries) if row is selected), 0)
            self.table.setCurrentCell(index, 0)
        else:
            self.show_formula(-1)

    @staticmethod
    def _display(row):
        detail = row['basis_detail']
        direction = row['direction']
        if detail.get('future_origin'):
            direction = '买基差' if direction == 'ETF买入' else '卖基差'
        return (trade_display(row)[0], direction, fmt(detail['amount']), fmt(detail['lots'], 0),
                fmt(detail['futures_price'], 4), fmt(detail['value'], 4), row.get('origin'))

    def show_formula(self, index):
        if index < 0:
            self.detail_caption.setText('暂无已入账的双腿成交')
            self.equation.clear()
            self.origin.clear()
            return
        row = self.entries[index]
        detail = row['basis_detail']
        self.detail_caption.setText(f"{self._display(row)[1]}　等价基差 {fmt(detail['value'], 4)} 点")
        self.equation.setText(f"ETF 金额 {fmt(detail['amount'])} ÷（{fmt(detail['lots'], 0)} 手 × "
                              f"{fmt(detail['multiplier'], 0)}）= {fmt(detail['etf_points'], 4)} 点\n"
                              f"{fmt(detail['etf_points'], 4)} − {fmt(detail['futures_price'], 4)} = {fmt(detail['value'], 4)} 点")
        sources = dict.fromkeys(filter(None, (row.get('origin'), detail.get('future_origin'), row.get('import_origin'))))
        self.origin.setText('　·　'.join(filter(None, (*sources, row.get('note')))))
