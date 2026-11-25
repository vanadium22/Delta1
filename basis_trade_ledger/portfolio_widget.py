from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from .portfolio import date_filter, section_title
from .widgets import MetricCard, Table, button, fmt, label, text_input


class PortfolioFilters(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        filters = QHBoxLayout()
        filters.setSpacing(4)
        self.status = QComboBox()
        for caption, status in (('全状态', 'all'), ('存续', 'active'), ('已结束', 'closed')):
            self.status.addItem(caption, status)
        self.status.setToolTip('按交易组存续状态筛选')
        self.period = QComboBox()
        for caption, period in (('全时段', 'all'), ('今天', 'today'), ('近7天', 'week'),
                                ('本月', 'month'), ('自定义', 'custom')):
            self.period.addItem(caption, period)
        self.period.setToolTip('按开组日或成交日筛选')
        for combo in (self.status, self.period):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(4)
            filters.addWidget(combo, 1)
        layout.addLayout(filters)
        self.date_box = QWidget()
        dates = QVBoxLayout(self.date_box)
        dates.setContentsMargins(0, 0, 0, 0)
        self.low = text_input('从 YYYY-MM-DD', 'portfolioDateFrom')
        self.high = text_input('到 YYYY-MM-DD', 'portfolioDateTo')
        self.low.setToolTip('起始日期，含当天')
        self.high.setToolTip('截止日期，含当天')
        dates.addWidget(self.low)
        dates.addWidget(self.high)
        layout.addWidget(self.date_box)
        self.date_box.hide()
        self.period.currentIndexChanged.connect(self.period_changed)
        self.status.currentIndexChanged.connect(lambda _: self.changed.emit())
        self.low.editingFinished.connect(self.changed)
        self.high.editingFinished.connect(self.changed)

    def period_changed(self):
        self.date_box.setVisible(self.period.currentData() == 'custom')
        self.changed.emit()

    def query(self):
        return self.status.currentData(), date_filter(self.period.currentData(), self.low.text().strip(), self.high.text().strip())

    def reset(self):
        for combo in (self.status, self.period):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.date_box.hide()


class PortfolioPage(QWidget):
    group_selected = Signal(int)
    borrow_limit_selected = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.title = label('', 'groupTitle')
        self.description = label('', 'muted')
        layout.addWidget(self.title)
        layout.addWidget(self.description)
        metrics = QHBoxLayout()
        self.metrics = {}
        for key, caption in (('total', '总盈亏 · 元'), ('realized', '已实现 · 元'), ('floating', '浮盈亏 · 元'),
                             ('net', '净敞口 · 元'), ('gross', '总敞口 · 元')):
            panel = MetricCard(caption, primary=key == 'total', variant='positionCard' if key in ('net', 'gross') else 'pnlCard')
            metrics.addWidget(panel, 1)
            self.metrics[key] = panel
        layout.addLayout(metrics)
        self.table = Table(('交易组', '状态', '总盈亏', '已实现', '浮盈亏', '净敞口', '总敞口', 'ETF 敞口', '期货敞口', '估值状态'),
                           (129, 74, 93, 88, 91, 91, 91, 101, 101, 103))
        self.positions_table = Table(('交易组', '对应指数', '持仓标的', '方向', '实际持仓', '敞口 · 元'),
                                     (111, 170, 120, 59, 100, 128))
        self.tabs = QTabWidget()
        self.tabs.addTab(self.positions_table, '实际持仓')
        self.tabs.addTab(self.table, '交易组盈亏')
        self.borrow_page = QWidget()
        borrow_layout = QVBoxLayout(self.borrow_page)
        borrow_layout.setContentsMargins(10, 8, 10, 8)
        borrow_actions = QHBoxLayout()
        borrow_actions.addWidget(label('按 ETF 汇总未回补空头 · 单位为份', 'muted'), 1)
        borrow_actions.addWidget(button('设置额度', lambda: self.borrow_limit_selected.emit(''), True))
        borrow_layout.addLayout(borrow_actions)
        self.borrow_table = Table(('ETF 代码', '对应指数', '可融券上限', '已用额度', '还可卖空', '超出额度'),
                                  (107, 112, 112, 103, 112, 105))
        self.borrow_table.setToolTip('数量单位为份。已用额度来自台账当前的全部组，双击一行可修改上限。')
        self.borrow_table.cellDoubleClicked.connect(self.select_borrow)
        borrow_layout.addWidget(self.borrow_table)
        self.tabs.addTab(self.borrow_page, '融券额度')
        layout.addWidget(self.tabs, 1)
        self.quote_note = label('', 'muted')
        self.quote_note.setMinimumWidth(0)
        self.quote_note.setWordWrap(True)
        self.quote_note.hide()
        layout.addWidget(self.quote_note)
        self.tabs.currentChanged.connect(lambda _: self.update_quote_note())
        self.table.cellDoubleClicked.connect(self.select_group)
        self.positions_table.cellDoubleClicked.connect(self.select_position_group)
        self.rows = []
        self.position_groups = []
        self.displayed_values = None
        self.displayed_positions = None
        self.displayed_borrow = None

    def show_loading(self, section):
        self.show_values(section, [], {})
        self.show_borrow_capacity([])
        self.description.setText('正在计算交易组汇总…')

    def show_values(self, section, rows, totals, quote_message=''):
        self.rows = rows
        self.title.setText(section_title(section))
        pending = sum(row['total'] is None for row in rows)
        active = sum(row['active'] for row in rows)
        self.description.setText(f'{len(rows)} 组　·　存续 {active}　·　已结束 {len(rows) - active}' +
                                 (f'　·　待估值 {pending} 组' if pending else ''))
        self.quote_note.setText(quote_message)
        self.update_quote_note()
        contexts = dict(total='已实现 + 浮盈亏', realized='扣除成交费用', floating='', net='带方向名义额', gross='各腿绝对名义额')
        for key, panel in self.metrics.items():
            panel.set_metric(totals.get(key), contexts[key], missing='待估值' if totals else '—',
                             color=key in ('total', 'realized', 'floating'))
        values = [(row['config']['name'], '存续' if row['active'] else '已结束',
                   *(fmt(row[key], missing='待估值') for key in ('total', 'realized', 'floating', 'net', 'gross',
                                                              'etf_exposure', 'futures_exposure')), row['quality']) for row in rows]
        if values != self.displayed_values:
            self.displayed_values = values
            self.table.fill(values)
            for row in range(len(values)):
                for col in range(2, 9):
                    self.table.item(row, col).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        positions = []
        self.position_groups = []
        for row in rows:
            for position in row['positions']:
                self.position_groups.append(row['config']['id'])
                mark = position['mark']
                tooltip = ' · '.join(filter(None, (fmt(mark['price'], 4), mark.get('source'), mark.get('time')))) if mark else '待估值'
                index = position['index']
                index_title = section_title(index)
                index_label = f'{index_title} {index}' if index and index != index_title else index_title
                etf = position['leg'] == 'etf'
                quantity = position['quantity']
                exposure = position['exposure']
                positions.append(((row['config']['name'], index_label, f"ETF {position['code']}" if etf else position['code'],
                                   '多头' if quantity > 0 else '空头', f"{fmt(abs(quantity), 0)} {'份' if etf else '手'}",
                                   fmt(exposure, missing='待估值')), tooltip))
        self.tabs.setTabText(0, f'实际持仓 ({len(positions)})')
        if positions != self.displayed_positions:
            self.displayed_positions = positions
            self.positions_table.fill([cells for cells, _ in positions])
            for n, (cells, tooltip) in enumerate(positions):
                self.positions_table.item(n, 3).setForeground(QColor('#a73440' if cells[3] == '多头' else '#13735d'))
                self.positions_table.item(n, 5).setToolTip(tooltip)
                for col in (4, 5):
                    self.positions_table.item(n, col).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def select_group(self, row, _column):
        self.group_selected.emit(self.rows[row]['config']['id'])

    def select_position_group(self, row, _column):
        self.group_selected.emit(self.position_groups[row])

    def update_quote_note(self):
        self.quote_note.setVisible(bool(self.quote_note.text()) and self.tabs.currentWidget() != self.borrow_page)

    def show_borrow_capacity(self, rows):
        values = [(row['etf'], '、'.join(section_title(index) for index in row['indices']) or '—',
                   fmt(row['limit'], 0, '未设置'), fmt(row['used'], 0), fmt(row['available'], 0),
                   fmt(row['excess'], 0) if row['excess'] else '—') for row in rows]
        if values == self.displayed_borrow:
            return
        self.displayed_borrow = values
        self.borrow_table.fill(values)
        for n, row in enumerate(rows):
            for col in range(2, 6):
                self.borrow_table.item(n, col).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            available = self.borrow_table.item(n, 4)
            font = available.font()
            font.setBold(True)
            available.setFont(font)
            if row['excess']:
                self.borrow_table.item(n, 5).setForeground(QColor('#a73440'))
            elif row['available']:
                available.setForeground(QColor('#13735d'))

    def select_borrow(self, row, _column):
        self.borrow_limit_selected.emit(self.displayed_borrow[row][0])
