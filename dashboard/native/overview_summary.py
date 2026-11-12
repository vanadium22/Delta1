"""All four indices and sixteen actual contracts, with responsive large cards."""
from PySide6.QtCore import Signal, QSize, QEvent, QTimer
from PySide6.QtWidgets import QWidget, QBoxLayout

from .overview_pages import ScrollPage, IndexCard,lab
from .theme import ACCENT
from .futures_overview_view import FuturesCard
from .instruments import UNDERLYINGS


class ContractFlow(QWidget):
    def __init__(self,items,maximum,minimum,parent=None):
        super().__init__(parent);self.items=items;self.maximum=maximum;self.minimum=minimum;self.columns=0;self.spacing=16
        self.setMinimumWidth(0)
        for item in items:item.setParent(self)
        self.reflow()

    def sizeHint(self):
        return QSize(0,self.minimumHeight())

    def resizeEvent(self,event):
        super().resizeEvent(event);self.reflow()

    def reflow(self):
        # The product row selects four columns when wide and two when narrow.
        # Re-deciding from the scaled inner width can oscillate between three
        # and four columns while the graphics view is fitting its height.
        columns=max(1,min(self.maximum,len(self.items)))
        rows=(len(self.items)+columns-1)//columns
        needed=rows*max(item.minimumSizeHint().height() for item in self.items)+(rows-1)*self.spacing
        if self.minimumHeight()!=needed:self.setMinimumHeight(needed);self.updateGeometry()
        self.columns=columns
        width=max(1,self.width()-(columns-1)*self.spacing);height=max(1,self.height()-(rows-1)*self.spacing)
        for i,item in enumerate(self.items):
            x=i%columns;y=i//columns
            left=width*x//columns+x*self.spacing;right=width*(x+1)//columns+x*self.spacing
            top=height*y//rows+y*self.spacing;bottom=height*(y+1)//rows+y*self.spacing
            item.setGeometry(left,top,right-left,bottom-top)


class ProductRow(QWidget):
    def __init__(self, root):
        super().__init__()
        self.index = IndexCard(root, self)
        self.index.heading.setText(UNDERLYINGS[root][1])
        self.futures = [FuturesCard(self,compact=True) for _ in range(4)]
        self.flow = ContractFlow(self.futures, 4, 240, self)
        from .overview_charts import ProductCharts
        self.chart=ProductCharts(root,UNDERLYINGS[root][1],compact=True)
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0,0,0,0)
        self.box.setSpacing(16)
        self.box.addWidget(self.index,7)
        self.box.addWidget(self.flow,36)
        self.box.addWidget(self.chart,17)
        self.wide=None;self.set_wide(True)

    def set_wide(self,wide):
        if self.wide==wide:return
        self.wide=wide
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
        self.dividend_source=lab('最新分红表：待核验',18,ACCENT,True);self.box.addWidget(self.dividend_source)
        self.products = {}
        self.cards = {}
        self.index_cards = {}
        self.charts = {}
        for root,(symbol,_,_) in UNDERLYINGS.items():
            group = ProductRow(root)
            group.index.clicked.connect(self.index_clicked)
            self.products[root] = group
            self.index_cards[symbol] = group.index
            self.charts[root] = group.chart
            self.box.addWidget(group)
        self.visible_rows = []
        self.scroll.installEventFilter(self);QTimer.singleShot(0,self.reflow_products)

    def eventFilter(self,obj,event):
        if obj is self.scroll and event.type()==QEvent.Type.Resize:self.reflow_products()
        return super().eventFilter(obj,event)

    def reflow_products(self):
        wide=self.scroll.width()>=1100
        for group in self.products.values():group.set_wide(wide)

    def render_data(self, data):
        from .overview_status import data_dates,dates_text
        self.dividend_source.setText(dates_text(data_dates(data)))
        self.dividend_source.setToolTip('价格日取卡片真实源时间；DDB目标是最近已完成交易日；分红业务日取公盘表内B1，三者独立。')
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
