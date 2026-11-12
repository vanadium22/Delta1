"""All four indices and sixteen actual contracts, with responsive large cards."""
from PySide6.QtCore import Signal, QEvent, QTimer, Qt
from PySide6.QtWidgets import QWidget, QBoxLayout, QScrollArea, QVBoxLayout, QFrame, QPushButton

from .overview_pages import ScrollPage, IndexCard, FlowGrid,lab
from .theme import ACCENT
from .futures_overview_view import FuturesCard
from .instruments import UNDERLYINGS


class ProductRow(QWidget):
    def __init__(self, root):
        super().__init__()
        self.index = IndexCard(root, self)
        self.index.heading.setText(UNDERLYINGS[root][1])
        self.futures = [FuturesCard(self,compact=True) for _ in range(4)]
        self.flow = FlowGrid(self.futures, 4, 240, self)
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0,0,0,0)
        self.box.setSpacing(16)
        self.box.addWidget(self.index,1)
        self.box.addWidget(self.flow,4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wide = self.width() >= 1320
        self.box.setDirection(QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)
        maximum = 4 if wide else 2
        if self.flow.maximum != maximum:
            self.flow.maximum = maximum
            self.flow.columns = 0
        self.flow.reflow()


class OverviewSummary(ScrollPage):
    changed = Signal()
    index_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.outer_scroll=QScrollArea();self.outer_scroll.setWidgetResizable(True);self.outer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.outer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container=QWidget();self.container_box=QVBoxLayout(self.container);self.container_box.setContentsMargins(0,0,0,0);self.container_box.setSpacing(12)
        self.layout().removeWidget(self.scroll);self.container_box.addWidget(self.scroll)
        self.outer_scroll.setWidget(self.container);self.layout().addWidget(self.outer_scroll)
        self.outer_scroll.viewport().installEventFilter(self)
        self.dividend_source=lab('最新分红表：待核验',18,ACCENT,True);self.box.addWidget(self.dividend_source)
        self.charts_button=QPushButton('查看四品种期限结构与成交持仓 ↓');self.box.addWidget(self.charts_button)
        self.charts_button.clicked.connect(lambda:self.outer_scroll.verticalScrollBar().setValue(self.scroll.height()))
        self.products = {}
        self.cards = {}
        self.index_cards = {}
        for root,(symbol,_,_) in UNDERLYINGS.items():
            group = ProductRow(root)
            group.index.clicked.connect(self.index_clicked)
            self.products[root] = group
            self.index_cards[symbol] = group.index
            self.box.addWidget(group)
        from .overview_charts import ProductCharts
        self.charts={root:ProductCharts(root,name) for root,(_,name,_) in UNDERLYINGS.items()}
        self.charts_grid=FlowGrid(list(self.charts.values()),2,520,self.container);self.container_box.addWidget(self.charts_grid)
        QTimer.singleShot(0,self.fit_overview_height)
        self.visible_rows = []

    def eventFilter(self,obj,event):
        if obj is self.outer_scroll.viewport() and event.type()==QEvent.Type.Resize:QTimer.singleShot(0,self.fit_overview_height)
        return super().eventFilter(obj,event)

    def fit_overview_height(self):
        if hasattr(self,'outer_scroll'):self.scroll.setFixedHeight(max(360,self.outer_scroll.viewport().height()-2))

    def render_data(self, data):
        from .overview_status import data_dates,dates_text
        self.dividend_source.setText(dates_text(data_dates(data)))
        self.dividend_source.setToolTip('价格日取卡片真实源时间；DDB目标是最近已完成交易日；分红业务日取Y盘表内B1，三者独立。')
        indices = {r['root']:r for r in data.get('indices', [])}
        futures = {(r['root'],r.get('slot')):r for r in data.get('futures', [])}
        self.cards = {}
        self.visible_rows = list(data.get('futures', []))
        for root,group in self.products.items():
            group.index.render(indices.get(root, {}))
            for slot,card in enumerate(group.futures):
                row = futures.get((root,slot), {})
                card.render(row,slot)
                if row.get('symbol'):
                    self.cards[row['symbol']] = card
            self.charts[root].render([r for r in data.get('futures',[]) if r.get('root')==root],data.get('futures_details',{}).get(root,{}))
