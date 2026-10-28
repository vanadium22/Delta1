"""All four indices and sixteen actual contracts, with responsive large cards."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QBoxLayout

from .overview_pages import ScrollPage, IndexCard, FlowGrid
from .futures_overview_view import FuturesCard
from .instruments import UNDERLYINGS


class ProductRow(QWidget):
    def __init__(self, root):
        super().__init__()
        self.index = IndexCard(root, self)
        self.index.heading.setText(UNDERLYINGS[root][1])
        self.futures = [FuturesCard(self) for _ in range(4)]
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
        self.products = {}
        self.cards = {}
        self.index_cards = {}
        for root,(symbol,_,_) in UNDERLYINGS.items():
            group = ProductRow(root)
            group.index.clicked.connect(self.index_clicked)
            self.products[root] = group
            self.index_cards[symbol] = group.index
            self.box.addWidget(group)
        self.visible_rows = []

    def render_data(self, data):
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
