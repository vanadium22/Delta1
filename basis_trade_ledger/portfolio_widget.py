from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QHeaderView, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from .hedge_widget import HedgePage
from .portfolio import date_filter, index_section, section_title
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


class DailyTradesPage(QWidget):
    group_selected = Signal(int)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(label('今日成交汇总', 'groupTitle'))
        self.description = label('', 'muted')
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        metrics = QHBoxLayout()
        self.metrics = {}
        for key, caption, context in (
            ('turnover', '今日成交额 · 元', '两腿成交名义额绝对值'),
            ('trade_net', '今日成交净额 · 元', '按成交价，买入为正'),
            ('position_net', '全台账净敞口 · 元', '按当前估值，含历史持仓'),
            ('position_gross', '全台账总敞口 · 元', '各组各腿绝对名义额'),
        ):
            panel = MetricCard(caption, variant='positionCard' if key.startswith('position') else 'pnlCard')
            self.metrics[key] = panel, context
            metrics.addWidget(panel, 1)
        layout.addLayout(metrics)
        self.table = Table(('交易组', '笔数', 'ETF 成交净额', '期货成交净额', '成交净额', '当前净敞口', '当前总敞口'),
                           (125, 52, 101, 108, 94, 99, 99), number_columns=range(1, 7))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.table.cellDoubleClicked.connect(lambda row, _: self.group_selected.emit(self.rows[row]['config']['id']))
        self.rows = []
        self.cells = None

    def show_values(self, day, rows, trades=None, positions=None):
        self.rows = rows
        message = '正在读取台账…'
        values = {}
        if trades is not None:
            message = f"{trades['count']} 笔已入账 · 金额单位为元" if rows else '今日暂无已入账成交'
            if trades['undated']:
                message += f" · {trades['undated']} 笔历史成交缺少日期，未计入当日汇总"
            values = dict(turnover=trades['turnover'], trade_net=trades['net'],
                          position_net=positions['net'], position_gross=positions['gross'])
        self.description.setText(f'{day} 北京时间　·　{message}')
        for key, (panel, context) in self.metrics.items():
            panel.set_metric(values.get(key), context, missing='待估值' if values else '—')
        cells = [((row['config']['name'], str(row['count']), *(fmt(row[key], missing='待估值') for key in
                   ('etf', 'futures', 'net', 'position_net', 'position_gross'))), row['config']) for row in rows]
        if cells != self.cells:
            self.cells = cells
            self.table.fill([values for values, _ in cells])
            for index, (_, config) in enumerate(cells):
                self.table.item(index, 0).setToolTip(f"{config['name']} · #{config['id']}\n{config['etf']} / {config['futures']}")
                for col in range(1, self.table.columnCount()):
                    self.table.item(index, col).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class PortfolioPage(QWidget):
    group_selected = Signal(int)
    borrow_limit_selected = Signal(str)
    hedge_selection_changed = Signal()
    hedge_refresh_requested = Signal()

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
                           (129, 74, 93, 88, 91, 91, 91, 101, 101, 103), number_columns=range(2, 9))
        self.positions_table = Table(('交易组', '对应指数', '持仓标的', '方向', '实际持仓', '敞口 · 元'),
                                     (111, 170, 120, 59, 100, 128), number_columns=(2, 4, 5))
        self.tabs = QTabWidget()
        self.tabs.addTab(self.positions_table, '实际持仓')
        self.tabs.addTab(self.table, '交易组盈亏')
        self.borrow_page = QScrollArea()
        self.borrow_page.setWidgetResizable(True)
        borrow_content = QWidget()
        self.borrow_page.setWidget(borrow_content)
        borrow_layout = QVBoxLayout(borrow_content)
        borrow_layout.setContentsMargins(12, 10, 12, 12)
        borrow_layout.setSpacing(9)
        borrow_actions = QHBoxLayout()
        borrow_actions.addWidget(label('ETF 融券额度 · 份', 'sectionTitle'), 1)
        self.edit_borrow = button('修改额度', self.select_borrow)
        self.edit_borrow.setEnabled(False)
        borrow_actions.addWidget(self.edit_borrow)
        borrow_actions.addWidget(button('新增 ETF', lambda: self.borrow_limit_selected.emit(''), True))
        borrow_layout.addLayout(borrow_actions)
        self.borrow_table = Table(('ETF 代码', '对应指数', '可融券上限', '已用额度', '还可卖空', '超出额度'),
                                  (116, 114, 110, 103, 112, 104), number_columns=(0, 2, 3, 4, 5))
        self.borrow_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.borrow_table.setToolTip('数量单位为份。已用额度来自台账当前的全部组，双击一行可修改上限。')
        self.borrow_table.itemSelectionChanged.connect(self.borrow_row_selected)
        self.borrow_table.cellDoubleClicked.connect(lambda *_: self.select_borrow())
        borrow_layout.addWidget(self.borrow_table)
        borrow_layout.addWidget(label('对冲换算', 'hedgeTitle'))
        controls = QHBoxLayout()
        self.hedge_etf = QComboBox()
        self.hedge_group = QComboBox()
        for combo, width in ((self.hedge_etf, 8), (self.hedge_group, 11)):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(width)
        controls.addWidget(label('ETF', 'fieldCaption'))
        controls.addWidget(self.hedge_etf, 2)
        controls.addWidget(label('参考组', 'fieldCaption'))
        controls.addWidget(self.hedge_group, 4)
        self.hedge_refresh = button('刷新报价', lambda: self.hedge_refresh_requested.emit())
        controls.addWidget(self.hedge_refresh)
        borrow_layout.addLayout(controls)
        self.hedge_empty = label('先选 ETF，再选提供期货合约和乘数的交易组。', 'muted')
        self.hedge_empty.setWordWrap(True)
        borrow_layout.addWidget(self.hedge_empty)
        self.hedge = HedgePage(embedded=True)
        self.hedge.hide()
        borrow_layout.addWidget(self.hedge)
        borrow_layout.addStretch()
        self.hedge_etf.currentIndexChanged.connect(self.update_hedge_groups)
        self.hedge_group.currentIndexChanged.connect(self.hedge_selection_changed)
        self.hedge_configs = []
        self.hedge_capacities = {}
        self.reference_etf = None
        self.tabs.addTab(self.borrow_page, '融券额度')
        layout.addWidget(self.tabs, 1)
        self.quote_note = label('', 'muted')
        self.quote_note.setMinimumWidth(0)
        self.quote_note.setWordWrap(True)
        self.quote_note.hide()
        layout.addWidget(self.quote_note)
        self.tabs.currentChanged.connect(self.tab_changed)
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

    def tab_changed(self):
        self.update_quote_note()
        self.hedge_selection_changed.emit()

    def show_borrow_capacity(self, rows):
        values = [(row['etf'], '、'.join(section_title(index) for index in row['indices']) or '—',
                   fmt(row['limit'], 0, '未设置'), fmt(row['used'], 0), fmt(row['available'], 0),
                   fmt(row['excess'], 0) if row['excess'] else '—') for row in rows]
        if values == self.displayed_borrow:
            return
        selected = self.borrow_table.currentRow()
        previous = self.displayed_borrow[selected][0] if self.displayed_borrow and selected >= 0 else None
        self.displayed_borrow = values
        with QSignalBlocker(self.borrow_table):
            self.borrow_table.fill(values)
            self.borrow_table.setCurrentCell(-1, -1)
            for n, row in enumerate(rows):
                if row['etf'] == previous:
                    self.borrow_table.selectRow(n)
                    break
        self.edit_borrow.setEnabled(self.borrow_table.currentRow() >= 0)
        self.borrow_table.setFixedHeight(self.borrow_table.horizontalHeader().sizeHint().height() +
                                         self.borrow_table.verticalHeader().defaultSectionSize() * min(5, max(2, len(rows))) + 4)
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

    def borrow_row_selected(self):
        row = self.borrow_table.currentRow()
        self.edit_borrow.setEnabled(row >= 0)
        if row >= 0:
            self.hedge_etf.setCurrentIndex(self.hedge_etf.findData(self.displayed_borrow[row][0]))

    def select_borrow(self):
        row = self.borrow_table.currentRow()
        if row >= 0:
            self.borrow_limit_selected.emit(self.displayed_borrow[row][0])

    def select_borrow_code(self, etf):
        for index, row in enumerate(self.displayed_borrow):
            if row[0] == etf:
                self.borrow_table.selectRow(index)
                self.hedge_etf.setCurrentIndex(self.hedge_etf.findData(etf))
                return

    def show_hedge_choices(self, configs, rows, *, refresh=True):
        indices = {row['etf']: tuple(row['indices']) for row in rows}
        if configs == self.hedge_configs and indices == self.hedge_capacities:
            return
        self.hedge_configs, self.hedge_capacities = configs, indices
        etfs = sorted(set(indices) | {cfg['etf'] for cfg in configs})
        self.replace_choices(self.hedge_etf, [(etf, etf) for etf in etfs])
        self.update_hedge_groups(refresh=refresh)

    def update_hedge_groups(self, _index=-1, *, refresh=True):
        etf = self.hedge_etf.currentData()
        indices = set(self.hedge_capacities.get(etf, ()))
        indices.update(index_section(cfg) for cfg in self.hedge_configs if cfg['etf'] == etf)
        candidates = [cfg for cfg in self.hedge_configs if etf and (cfg['etf'] == etf or index_section(cfg) in indices)]
        candidates.sort(key=lambda cfg: cfg['etf'] != etf)
        preferred = next((cfg['id'] for cfg in candidates if cfg['etf'] == etf), None) if self.reference_etf != etf else None
        self.reference_etf = etf
        self.replace_choices(self.hedge_group, [(f"{cfg['name']} · {cfg['futures']}", cfg['id']) for cfg in candidates],
                             preferred=preferred)
        self.hedge_group.setToolTip(self.hedge_group.currentText())
        if refresh:
            self.hedge_selection_changed.emit()

    @staticmethod
    def replace_choices(combo, choices, *, preferred=None):
        previous = combo.currentData()
        with QSignalBlocker(combo):
            combo.clear()
            for caption, value in choices:
                combo.addItem(caption, value)
            index = combo.findData(preferred if preferred is not None else previous)
            combo.setCurrentIndex(max(0, index) if choices else -1)
