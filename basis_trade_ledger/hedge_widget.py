from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .hedge import HEDGE_METHODS, hedge_size, projected_borrow
from .model import ZERO
from .quotes import compatible_marks
from .widgets import MetricCard, card, fmt, label, text_input


class HedgePage(QWidget):
    def __init__(self, *, embedded=False):
        super().__init__()
        self.default_direction = 1 if embedded else 0
        self.config = self.positions = None
        self.group_id = None
        self.quotes = {}
        self.planned = {}
        self.capacity = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(8)
        if not embedded:
            layout.addWidget(label('对冲换算', 'hedgeTitle'))

        inputs = card()
        self.input_grid = QGridLayout(inputs)
        self.input_grid.setHorizontalSpacing(12)
        self.method = QComboBox()
        for key, caption in HEDGE_METHODS.items():
            self.method.addItem(caption, key)
        self.direction = QComboBox()
        self.direction.addItems(['买基差', '卖基差'])
        self.basis = QComboBox()
        self.basis.addItem('期货估值价', 'futures')
        self.basis.addItem('跟踪指数（原表口径）', 'index')
        for combo, minimum in ((self.method, 7), (self.direction, 4), (self.basis, 8)):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(minimum)
        self.qty_label = label('输入期货手数', 'fieldCaption')
        self.qty = text_input(name='hedgeQuantity')
        self.step = text_input(name='hedgeEtfStep')
        self.step.setText('100')
        self.input_fields = ((label('换算方式', 'fieldCaption'), self.method),
                (label('方向', 'fieldCaption'), self.direction), (label('折算基准', 'fieldCaption'), self.basis),
                (self.qty_label, self.qty), (label('ETF 份额步长', 'fieldCaption'), self.step))
        self.input_columns = 0
        self.arrange_inputs(3)
        layout.addWidget(inputs)

        amounts = QHBoxLayout()
        self.etf = MetricCard('ETF · 份', variant='hedgeLeg')
        self.futures = MetricCard('期货 · 手', variant='hedgeLeg')
        self.residual = MetricCard('折算后净敞口 · 元', variant='positionCard')
        for panel in (self.etf, self.futures, self.residual):
            amounts.addWidget(panel, 1)
        layout.addLayout(amounts)
        self.borrow_notice = label('', 'quoteStatus')
        self.borrow_notice.setWordWrap(True)
        self.borrow_notice.hide()
        layout.addWidget(self.borrow_notice)

        price_panel = card()
        price_grid = QGridLayout(price_panel)
        self.price_labels = {}
        for col, key in enumerate(('etf', 'basis')):
            title = label('', 'sectionTitle')
            source = label('', 'hedgeQuote')
            source.setWordWrap(True)
            price_grid.addWidget(title, 0, col)
            price_grid.addWidget(source, 1, col)
            price_grid.setColumnStretch(col, 1)
            self.price_labels[key] = (title, source)
        self.status = label('', 'quoteStatus')
        self.status.setWordWrap(True)
        price_grid.addWidget(self.status, 2, 0, 1, 2)
        layout.addWidget(price_panel)
        layout.addStretch()
        self.method.currentIndexChanged.connect(self.change_method)
        self.direction.currentTextChanged.connect(self.render)
        self.basis.currentIndexChanged.connect(self.render)
        self.qty.textEdited.connect(self.edit_quantity)
        self.step.textEdited.connect(self.render)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange_inputs(5 if event.size().width() >= 820 else 3)

    def arrange_inputs(self, columns):
        if columns == self.input_columns:
            return
        self.input_columns = columns
        for index, (caption, field) in enumerate(self.input_fields):
            row, col = divmod(index, columns)
            self.input_grid.addWidget(caption, 2 * row, col)
            self.input_grid.addWidget(field, 2 * row + 1, col)
        for col in range(len(self.input_fields)):
            self.input_grid.setColumnStretch(col, (4, 2, 4, 2, 2)[col] if col < columns else 0)

    def set_context(self, group_id, config, positions, quotes, capacity=None):
        self.config, self.positions, self.quotes = config, positions, quotes
        self.capacity = capacity
        if self.group_id != group_id:
            self.group_id = group_id
            plan = Decimal(self.config.get('plan_lots') or 0)
            base = Decimal(self.config.get('base_shares') or 0)
            self.planned = {'futures': str(int(plan)) if plan else '1', 'etf': str(int(base)) if base else ''}
            self.method.setCurrentIndex(0)
            self.direction.setCurrentIndex(self.default_direction)
            self.basis.setCurrentIndex(0)
            self.step.setText('100')
            self.change_method()
        else:
            self.render()
        for method in ('adjust_etf', 'adjust_futures'):
            self.method.model().item(self.method.findData(method)).setEnabled(positions is not None)

    def set_capacity(self, capacity):
        if capacity != self.capacity:
            self.capacity = capacity
            self.render()

    def change_method(self):
        if not self.config:
            return
        method = self.method.currentData()
        planned = method in ('futures', 'etf')
        self.direction.setEnabled(planned)
        self.qty.setEnabled(planned)
        self.step.setEnabled(method in ('futures', 'adjust_etf'))
        if method == 'futures':
            self.qty_label.setText('输入期货手数')
            self.qty.setText(self.planned[method])
        elif method == 'etf':
            self.qty_label.setText('输入 ETF 份额')
            self.qty.setText(self.planned[method])
        else:
            self.qty_label.setText('按净仓换算')
            self.qty.clear()
        self.render()

    def edit_quantity(self, quantity):
        self.planned[self.method.currentData()] = quantity
        self.render()

    def render(self):
        if not self.config:
            return
        basis_leg = self.basis.currentData()
        etf_mark, basis_mark = self.quotes.get('etf'), self.quotes.get(basis_leg)
        self.show_price('etf', 'ETF', self.config['etf'], etf_mark, 4)
        self.show_price('basis', '期货' if basis_leg == 'futures' else '跟踪指数',
                        self.config[basis_leg], basis_mark, 2)
        if not self.config[basis_leg]:
            self.clear_result('当前组缺少跟踪指数代码，可选期货估值价折算。')
            return
        if not (etf_mark and basis_mark):
            self.clear_result('等待两侧报价。可点「刷新报价」或进入「手填估值」。')
            return
        if not compatible_marks(etf_mark, basis_mark):
            self.clear_result('报价时点未对齐，等待同一时段的价格。')
            return
        current_etf = self.positions['etf'].quantity if self.positions is not None else ZERO
        current_futures = self.positions['futures'].quantity if self.positions is not None else ZERO
        try:
            result = hedge_size(self.method.currentData(), etf_price=etf_mark['price'], basis_price=basis_mark['price'],
                multiplier=self.config['multiplier'], quantity=self.qty.text(), direction=self.direction.currentText(),
                etf_step=self.step.text(), current_etf=current_etf, current_futures=current_futures)
        except (ValueError, ArithmeticError) as exc:
            self.clear_result(str(exc))
            return
        over_limit = self.show_borrow_projection(result.etf, current_etf)
        self.show_size(self.etf, 'ETF · 份', result.etf, result.raw_etf, result.etf_notional, warning=over_limit)
        self.show_size(self.futures, '期货 · 手', result.futures, result.raw_futures, result.futures_notional)
        exposure = '净多' if result.residual > 0 else '净空' if result.residual < 0 else '多空对等'
        self.residual.set_metric(result.residual, exposure)
        live = etf_mark.get('kind') == basis_mark.get('kind') == 'live'
        method = self.method.currentData()
        scope = '调整后的组内净敞口' if method.startswith('adjust_') else '本笔增量净敞口'
        quality = '同步实时折算' if live else '参考价折算'
        self.status.setText(f'{quality}　·　{scope}　·　按最接近的份额步长或整手取整')

    def show_borrow_projection(self, order, current_etf):
        if self.capacity is None:
            self.set_borrow_notice('正在读取该 ETF 的融券额度…' if order < 0 else '')
            return False
        limit = self.capacity.get('limit')
        projection = projected_borrow(order, current_etf, self.capacity['used'], limit)
        change = projection['change']
        change_text = (f'新增占用 {fmt(change, 0)} 份' if change > 0 else
                       f'释放 {fmt(-change, 0)} 份' if change < 0 else '本笔占用不变')
        if limit is None:
            self.set_borrow_notice(f'ETF 未设置融券上限 · {change_text}' if change > 0 else '')
            return False
        excess = projection['excess']
        balance = f'预计超额 {fmt(excess, 0)} 份' if excess else f"预计还可卖空 {fmt(projection['available'], 0)} 份"
        self.set_borrow_notice(f"{balance}　·　{change_text}　·　预计已用 {fmt(projection['used'], 0)} / {fmt(limit, 0)} 份",
                               warning=bool(excess))
        return bool(excess)

    def set_borrow_notice(self, text, *, warning=False):
        tone = 'borrowWarning' if warning else 'quoteStatus'
        if self.borrow_notice.objectName() != tone:
            self.borrow_notice.setObjectName(tone)
            self.borrow_notice.style().unpolish(self.borrow_notice)
            self.borrow_notice.style().polish(self.borrow_notice)
        self.borrow_notice.setText(text)
        self.borrow_notice.setVisible(bool(text))

    def show_price(self, key, caption, symbol, mark, digits):
        title, source = self.price_labels[key]
        title.setText(f'{caption}  {symbol}　{fmt(mark.get("price") if mark else None, digits)}')
        if mark:
            time = (mark.get('time') or '行情时间缺失').replace('T', ' ').removesuffix('+08:00').split('.', 1)[0]
            source.setText(f'{mark["source"]} · {time}')
            source.setToolTip(mark.get('date_basis') or '')
        else:
            source.setText('待估值' if symbol else '未配置')
            source.setToolTip('')

    @staticmethod
    def show_size(panel, caption, rounded, raw, notional, *, warning=False):
        action = '买入' if rounded > 0 else '卖出' if rounded < 0 else '本次无需交易'
        panel.caption.setText(f'{action} {caption}')
        panel.set_metric(rounded, f'理论 {fmt(abs(raw), 2)} · 名义 {fmt(notional)} 元', digits=0,
                         absolute=True, color=True, warning=warning)

    def clear_result(self, message):
        for panel, title in ((self.etf, 'ETF · 份'), (self.futures, '期货 · 手'), (self.residual, '折算后净敞口 · 元')):
            panel.caption.setText(title)
            panel.set_metric(None, '', missing='—')
        self.set_borrow_notice('')
        self.status.setText(message)
