from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from .portfolio import date_filter, section_title
from .widgets import MetricCard, Table, fmt, label, text_input


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
        layout.addWidget(self.table, 1)
        self.table.cellDoubleClicked.connect(self.select_group)
        self.rows = []
        self.displayed_values = None

    def show_loading(self, section):
        self.show_values(section, [], {})
        self.description.setText('正在计算交易组汇总…')

    def show_values(self, section, rows, totals):
        self.rows = rows
        self.title.setText(section_title(section))
        pending = sum(row['total'] is None for row in rows)
        active = sum(row['active'] for row in rows)
        self.description.setText(f'{len(rows)} 组　·　存续 {active}　·　已结束 {len(rows) - active}' +
                                 (f'　·　待估值 {pending} 组' if pending else ''))
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

    def select_group(self, row, _column):
        self.group_selected.emit(self.rows[row]['config']['id'])
