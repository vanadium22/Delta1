"""Native blue/white index and ETF pages matching the approved concept.

All numbers come from the supplied snapshot. Empty panels describe their missing
inputs; production widgets contain no illustrative prices, holdings or rankings.
"""
import math

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, QEvent, Signal, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QBoxLayout, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView)

from .theme import ACCENT, ACCENT_BACKGROUND, BACKGROUND, PANEL, SURFACE, TEXT, MUTED, BORDER, UP, DOWN, CHART_COLORS
from .instruments import UNDERLYINGS
from .card_views import stamp


def numeric(value, digits=2, signed=False, suffix=''):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return '—'
    return (f'{value:+,.{digits}f}' if signed else f'{value:,.{digits}f}')+suffix


def money(value):
    if value is None:
        return '—'
    return numeric(value/1e8, 2)+'亿' if abs(value) >= 1e8 else numeric(value/1e4, 2)+'万'


def ink(value):
    return UP if value is not None and value > 0 else DOWN if value is not None and value < 0 else TEXT


def clock(value):
    try:
        t = pd.Timestamp(value)
        return t.tz_convert('Asia/Shanghai').strftime('%H:%M:%S') if t.tzinfo is not None else '—'
    except (ValueError, TypeError):
        return '—'


def source_label(row):
    if row.get('quality',{}).get('usable'):return '源 '+clock(row.get('source_at'))
    if not row.get('source_at'):return '等待行情'
    title={'completed_daily':'收盘 ','http_snapshot':'快照 '}.get(row.get('display_kind'),'缓存 ')
    return title+stamp(row['source_at'],True)


def lab(value='', size=17, color=TEXT, bold=False):
    w = QLabel(value); w.setWordWrap(True); w.setMinimumWidth(0)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    w.setStyleSheet(f'background:transparent;color:{color};font-size:{size}px;font-weight:{700 if bold else 400};')
    return w


def put(w, value, *, color=None, size=None, bold=False):
    w.setText(value)
    if color is not None:
        w.setStyleSheet(f'background:transparent;color:{color};font-size:{size or 23}px;font-weight:{700 if bold else 400};')


class Panel(QFrame):
    def __init__(self, title='', note='', parent=None):
        super().__init__(parent); self.setObjectName('overviewPanel')
        self.setStyleSheet(f'QFrame#overviewPanel{{background:{PANEL};border:1px solid {BORDER};border-radius:12px;}}')
        self.box = QVBoxLayout(self); self.box.setContentsMargins(18, 15, 18, 15); self.box.setSpacing(12)
        if title:
            head = QHBoxLayout(); self.title = lab(title, 22, ACCENT, True); self.note = lab(note, 15, MUTED)
            self.note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            head.addWidget(self.title, 3); head.addWidget(self.note, 2); self.box.addLayout(head)
        self.setMinimumWidth(0)


class FlowGrid(QWidget):
    def __init__(self, items, maximum, minimum=300, parent=None):
        super().__init__(parent); self.items = items; self.maximum = maximum; self.minimum = minimum; self.columns = 0
        self.grid = QGridLayout(self); self.grid.setContentsMargins(0, 0, 0, 0); self.grid.setSpacing(16)
        self.reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event); self.reflow()

    def reflow(self):
        columns = max(1, min(self.maximum, (self.width()+16)//(self.minimum+16)))
        if columns == self.columns:
            return
        self.columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for i in range(max(self.maximum,self.grid.columnCount())):
            self.grid.setColumnStretch(i, 1 if i < columns else 0)
            self.grid.setColumnMinimumWidth(i, 0)
        for i, widget in enumerate(self.items):
            self.grid.addWidget(widget, i//columns, i % columns)


class Split(QWidget):
    def __init__(self, left, right, stretch=(3, 2)):
        super().__init__(); self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0); self.box.setSpacing(18)
        self.box.addWidget(left, stretch[0]); self.box.addWidget(right, stretch[1])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.box.setDirection(QBoxLayout.Direction.LeftToRight if self.width() >= 1000 else QBoxLayout.Direction.TopToBottom)


class ScrollPage(QWidget):
    def __init__(self):
        super().__init__(); outer = QVBoxLayout(self); outer.setContentsMargins(8, 15, 8, 0)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget(); self.box = QVBoxLayout(self.body); self.box.setContentsMargins(2, 2, 12, 12); self.box.setSpacing(20)
        self.box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.body); outer.addWidget(self.scroll)


class IndexCard(Panel):
    clicked = Signal(str)
    def __init__(self, root, parent):
        super().__init__(parent=parent); self.root = root; self.row = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        top = QHBoxLayout(); self.heading = lab(UNDERLYINGS[root][1], 21, ACCENT, True); self.change = lab('—', 25, TEXT, True)
        self.change.setAlignment(Qt.AlignmentFlag.AlignRight); top.addWidget(self.heading, 1); top.addWidget(self.change, 1)
        self.box.addLayout(top); self.price = lab('—', 36, ACCENT, True); self.box.addWidget(self.price)
        bottom = QHBoxLayout(); self.short = lab('5分钟 —', 16, MUTED); self.clock = lab('行情源 —', 14, MUTED)
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight); bottom.addWidget(self.short, 1);self.clock.setParent(self);self.clock.hide()
        self.box.addLayout(bottom); self.setMinimumHeight(148)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.root)
        super().mouseReleaseEvent(event)

    def selected(self, yes):
        self.setStyleSheet(f'QFrame#overviewPanel{{background:{PANEL};border:{2 if yes else 1}px solid {ACCENT if yes else BORDER};border-radius:12px;}}')

    def render(self, row):
        self.row = row; self.price.setText(numeric(row.get('price')))
        put(self.change, numeric(row.get('change_pct'), signed=True, suffix='%'), color=ink(row.get('change_pct')), size=25, bold=True)
        self.short.setText('5分钟 '+numeric(row.get('change_5m_pct'), signed=True, suffix='%'))
        self.clock.setText(source_label(row))
        self.setToolTip(row.get('status', '')+'\n源 '+stamp(row.get('source_at'))+'\n接收 '+stamp(row.get('received_at'))+'\n'+row.get('source_date_basis',''))


def table(headers, height):
    w = QTableWidget(0, len(headers)); w.setHorizontalHeaderLabels(headers); w.verticalHeader().hide()
    for i in range(len(headers)):
        w.horizontalHeaderItem(i).setTextAlignment((Qt.AlignmentFlag.AlignLeft if i==0 else Qt.AlignmentFlag.AlignRight)|Qt.AlignmentFlag.AlignVCenter)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    w.horizontalHeader().setMinimumSectionSize(20); w.verticalHeader().setDefaultSectionSize(37)
    w.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); w.setShowGrid(False)
    w.setStyleSheet(f'QTableWidget{{border:0;background:{PANEL};font-size:17px;}} QTableWidget::item{{padding:4px;}} QHeaderView::section{{background:{PANEL};font-size:15px;padding:5px;color:{MUTED};border:0;}}')
    w.setMinimumWidth(0); w.setFixedHeight(height); w.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return w


def cell(widget, row, col, value, color=TEXT, key=None):
    item = QTableWidgetItem(str(value)); item.setForeground(QColor(color))
    item.setToolTip(str(value))
    if col:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if key is not None:
        item.setData(Qt.ItemDataRole.UserRole, key)
    widget.setItem(row, col, item)


class MiniBar(QWidget):
    def __init__(self, value, maximum, parent):
        super().__init__(parent); self.value = value; self.maximum = maximum
    def paintEvent(self, event):
        if self.value is None:
            return
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(ink(self.value)); col.setAlpha(65); painter.setBrush(col); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(5, self.height()/2-7, max(0, self.width()-10)*abs(self.value)/self.maximum, 14), 3, 3)


class IndustryWeights(QWidget):
    clicked = Signal(str)
    def __init__(self):
        super().__init__(); self.rows = []; self.hit = []; self.setMinimumHeight(264); self.setMinimumWidth(0)
    def render(self, rows):
        rows = sorted((r for r in rows if isinstance(r.get('weight_pct'),(int,float))), key=lambda r: -r['weight_pct'])
        self.rows = rows[:7]
        if len(rows) > 7:
            self.rows += [dict(name='其他', weight_pct=sum(r['weight_pct'] for r in rows[7:]))]
        self.update()
    def mouseReleaseEvent(self, event):
        for rect, name in self.hit:
            if rect.contains(event.position()) and name != '其他':
                self.clicked.emit(name); break
        super().mouseReleaseEvent(event)
    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); self.hit = []
        if not self.rows:
            p.setPen(QColor(MUTED)); p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '待指数成分及行业权重资料'); return
        name_width = min(112, self.width()*.3); bar_width = max(10, self.width()-name_width-65)
        maximum = max(25, max(r['weight_pct'] for r in self.rows))
        for i, row in enumerate(self.rows):
            y = 4+i*32; p.setPen(QColor(TEXT)); p.drawText(QRectF(0, y, name_width, 30), Qt.AlignmentFlag.AlignVCenter, row['name'])
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(ACCENT if i == 0 else CHART_COLORS[1]))
            p.drawRoundedRect(QRectF(name_width, y+9, bar_width*row['weight_pct']/maximum, 14), 3, 3)
            p.setPen(QColor(MUTED)); p.drawText(QRectF(self.width()-62, y, 62, 30), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, numeric(row['weight_pct'], 1, suffix='%'))
            self.hit.append((QRectF(0, y, self.width(), 32), row['name']))


class IndexOverviewPage(ScrollPage):
    def __init__(self):
        super().__init__(); self.selected_root = 'IF'; self.selected_industry = {}; self.rows = []; self.details = {}; self.expanded = False
        self.cards = {s: IndexCard(root, self.body) for root, (s, _, _) in UNDERLYINGS.items()}
        for card in self.cards.values():
            card.clicked.connect(self.select)
        self.box.addWidget(FlowGrid(list(self.cards.values()), 4, 290, self.body))
        header = QHBoxLayout(); self.heading = lab('', 24, ACCENT, True); self.snapshot = lab('', 15, MUTED)
        self.snapshot.setAlignment(Qt.AlignmentFlag.AlignRight); header.addWidget(self.heading, 3); header.addWidget(self.snapshot, 2); self.box.addLayout(header)
        self.metrics = []
        strips = []
        for caption in ('已覆盖成分上涨占比', '指数实际变化', '已覆盖估算贡献', '未解释差额'):
            panel = Panel(parent=self.body); panel.setStyleSheet(f'QFrame#overviewPanel{{background:{SURFACE};border-radius:8px;}}')
            panel.box.setSpacing(4); panel.box.addWidget(lab(caption, 16, MUTED)); value = lab('—', 28, ACCENT, True)
            panel.box.addWidget(value); self.metrics.append(value); strips.append(panel)
        self.box.addWidget(FlowGrid(strips, 4, 220, self.body))
        self.industry_panel = Panel('行业贡献：上拉 / 下拉各前三', '该指数内行业篮子')
        self.industries = table(['行业', '指数权重', '篮子涨跌', '', '贡献点数'], 270)
        self.industries.cellClicked.connect(self.industry_clicked); self.industry_panel.box.addWidget(self.industries)
        self.weight_panel = Panel('指数行业权重', '')
        self.weights = IndustryWeights(); self.weights.clicked.connect(self.select_industry); self.weight_panel.box.addWidget(self.weights)
        self.box.addWidget(Split(self.industry_panel, self.weight_panel))
        self.stock_panel = Panel('选择行业 → 查看指数内成分', '权重、涨跌和贡献一起看')
        self.stocks = table(['标的', '占指数权重', '个股涨跌', '估算贡献点'], 150); self.stock_panel.box.addWidget(self.stocks)
        self.more = QPushButton('展开全部成分'); self.more.setCheckable(True); self.more.toggled.connect(self.expand)
        self.stock_panel.box.addWidget(self.more, alignment=Qt.AlignmentFlag.AlignRight); self.box.addWidget(self.stock_panel)
        self.reason = lab('待成分权重与行情；主行情独立显示', 15, MUTED); self.box.addWidget(self.reason)

    def select(self, root):
        self.selected_root = root; self.show_detail()

    def render(self, rows, details=None, reference=None):
        self.rows = rows; self.visible_rows = rows; self.details = details or {}
        for row in rows:
            self.cards[row['symbol']].render(row)
        self.show_detail()

    def show_detail(self):
        root = self.selected_root; name = UNDERLYINGS[root][1]; detail = self.details.get(root, {})
        for card in self.cards.values():
            card.selected(card.root == root)
        self.heading.setText(name+' · 谁在推动，谁在拖累')
        self.snapshot.setText(('有效成分 '+str(detail.get('covered',0))+'/'+str(detail.get('expected',0))+
            ' · 权重覆盖 '+numeric(detail.get('coverage_pct'),1,suffix='%')) if detail.get('expected') else '待成分资料')
        self.snapshot.setToolTip('成分源 '+str(detail.get('source_at') or '—')+'\n'+str(detail.get('reason') or ''))
        self.snapshot.setToolTip('实际取得 '+stamp(detail.get('snapshot_at'))+'\n权重基准 '+str(detail.get('weight_date') or '待核验')+'\n官方权重日 '+str(detail.get('official_weight_date') or '待核验')+'\n'+str(detail.get('weight_reason') or detail.get('reason',''))+f"\n有效 {detail.get('covered',0)}/{detail.get('expected',0)}只")
        for widget, key, suffix in zip(self.metrics, ('up_pct', 'actual_points', 'contribution_points', 'residual_points'), ('%', '点', '点', '点')):
            value = detail.get(key); put(widget, numeric(value, 1 if key == 'up_pct' else 2, key != 'up_pct', suffix), color=ink(value), size=28, bold=True)
        self.weight_panel.note.setText((detail.get('industry_standard') or '行业分类待核验')+(' · 估算权重 ' if detail.get('weight_method')=='fixed_quantity_estimate' else ' · 权重 ')+str(detail.get('weight_date') or '待核验'))
        groups = detail.get('industries', []); self.weights.render(groups if detail.get('weights_complete') is not False else [])
        ranked = detail.get('leaders', [])+detail.get('laggards', [])
        displayed = ranked if ranked else groups[:6]
        self.industry_panel.note.setText('完整行业参与排名' if ranked else '权重待核验，可查看成分涨跌' if detail.get('weights_complete') is False else '贡献待核验，先看权重')
        self.displayed_industries = displayed; self.industries.setRowCount(max(6, len(displayed)))
        self.industries.clearContents()
        maximum = max([abs(r['contribution_points']) for r in displayed if r.get('contribution_points') is not None] or [1]) or 1
        for i in range(max(6, len(displayed))):
            if i >= len(displayed):
                cell(self.industries, i, 0, '待行业资料' if not displayed else '—', MUTED)
                for col in (1, 2, 4): cell(self.industries, i, col, '—', MUTED)
                continue
            r = displayed[i]; value = r.get('contribution_points')
            cell(self.industries, i, 0, r['name'], ACCENT, r['name'])
            cell(self.industries, i, 1, numeric(r.get('weight_pct'), 1, suffix='%'))
            cell(self.industries, i, 2, numeric(r.get('change_pct'), signed=True, suffix='%'), ink(r.get('change_pct')))
            self.industries.setCellWidget(i, 3, MiniBar(value, maximum, self.industries))
            cell(self.industries, i, 4, numeric(value, signed=True), ink(value))
            for column in (2,4):self.industries.item(i,column).setToolTip(r.get('reason') or detail.get('reason',''))
        names = {r['name'] for r in groups}
        if self.selected_industry.get(root) not in names:
            self.selected_industry[root] = displayed[0]['name'] if displayed else None
        self.show_stocks(); self.reason.setText(detail.get('reason') or '待成分权重与行情；主行情独立显示')

    def industry_clicked(self, row, _):
        item = self.industries.item(row, 0)
        if item and item.data(Qt.ItemDataRole.UserRole):
            self.select_industry(item.data(Qt.ItemDataRole.UserRole))

    def select_industry(self, name):
        self.selected_industry[self.selected_root] = name
        self.industries.clearSelection()
        for i,group in enumerate(self.displayed_industries):
            if group['name']==name:self.industries.selectRow(i);break
        self.show_stocks()

    def expand(self, value):
        self.expanded = value; self.more.setText('收起成分' if value else '展开全部成分'); self.show_stocks()

    def show_stocks(self):
        root = self.selected_root; selected = self.selected_industry.get(root)
        group = next((r for r in self.details.get(root, {}).get('industries', []) if r['name'] == selected), {})
        members = sorted(group.get('members', []), key=lambda r: (r.get('contribution_points') is None, -abs(r.get('contribution_points') or 0), -(r.get('weight_pct') or 0)))
        rows = members if self.expanded else members[:3]
        self.stock_panel.title.setText((selected+' → 仅看'+UNDERLYINGS[root][1]+'内成分') if selected else '选择行业 → 查看指数内成分')
        self.stocks.setRowCount(max(3, len(rows))); self.stocks.clearContents()
        self.stocks.setFixedHeight(38*max(3, min(12, len(rows)))+36); self.more.setVisible(len(members) > 3)
        for i, r in enumerate(rows):
            cell(self.stocks, i, 0, r['name'] if r['name'] == r['symbol'] else r['name']+'  '+r['symbol'])
            cell(self.stocks, i, 1, numeric(r['weight_pct'], suffix='%'))
            cell(self.stocks, i, 2, numeric(r.get('change_pct'), signed=True, suffix='%'), ink(r.get('change_pct')))
            cell(self.stocks, i, 3, numeric(r.get('contribution_points'), signed=True), ink(r.get('contribution_points')))
        for i in range(len(rows), max(3, len(rows))):
            cell(self.stocks, i, 0, '待成分行情' if not rows else '—', MUTED)
            for c in range(1, 4): cell(self.stocks, i, c, '—', MUTED)


class EtfCard(Panel):
    def __init__(self, parent):
        super().__init__(parent=parent); self.row = None
        head = QHBoxLayout(); self.heading = lab('', 20, ACCENT, True); self.badge = lab('', 15, ACCENT)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignRight); head.addWidget(self.heading, 3); head.addWidget(self.badge, 1); self.box.addLayout(head)
        values = QHBoxLayout(); self.price = lab('—', 39, ACCENT, True); self.change = lab('—', 27, TEXT, True)
        self.change.setAlignment(Qt.AlignmentFlag.AlignRight); values.addWidget(self.price, 1); values.addWidget(self.change, 1); self.box.addLayout(values)
        second = QHBoxLayout(); self.iopv = lab('', 19); self.premium = lab('', 28, TEXT, True)
        self.premium.setAlignment(Qt.AlignmentFlag.AlignRight); second.addWidget(self.iopv, 1); second.addWidget(self.premium, 1); self.box.addLayout(second)
        self.closing_premium=lab('',16,MUTED);self.box.addWidget(self.closing_premium)
        divider = QFrame(); divider.setFixedHeight(1); divider.setStyleSheet(f'background:{BORDER};'); self.box.addWidget(divider)
        self.scale = lab('', 17); self.activity = lab('', 16, MUTED); self.clock = lab('', 14, MUTED)
        for w in (self.scale, self.activity): self.box.addWidget(w)
        self.clock.setParent(self);self.clock.hide()
        self.setMinimumHeight(265)

    def render(self, row, position):
        self.row = row
        self.heading.setText(row.get('name') or f'规模第{position} · 待核验')
        self.heading.setToolTip((row.get('symbol') or '')+'\n'+(row.get('name') or '待同指数完整规模排名'))
        self.badge.setText('规模 #'+str(row['rank']) if row.get('rank') else '待排名')
        self.price.setText(numeric(row.get('price'), 3))
        put(self.change, numeric(row.get('change_pct'), signed=True, suffix='%'), color=ink(row.get('change_pct')), size=27, bold=True)
        self.iopv.setText('IOPV '+numeric(row['iopv'], 4) if row.get('iopv') is not None else 'IOPV待有效报价' if row.get('iopv_id') else 'IOPV待接入')
        put(self.premium, numeric(row['premium_bp'], 1, True, ' bp') if row.get('premium_bp') is not None else '盘中折溢价 —', color=ink(row.get('premium_bp')), size=27 if row.get('premium_bp') is not None else 21, bold=True)
        self.iopv.setToolTip(row.get('premium_reason') or '缺少可核验IOPV来源或明确映射')
        self.premium.setToolTip(row.get('premium_reason') or '不使用昨日净值替代IOPV')
        self.closing_premium.setText('收盘折溢价 '+numeric(row.get('closing_premium_bp'),1,True,' bp')+' · '+str(row.get('nav_date') or '待净值'))
        self.closing_premium.setToolTip(row.get('closing_premium_reason') or '待同日收盘和单位净值，非盘中IOPV')
        self.scale.setText('基金规模 '+money(row.get('aum_cny'))+' · 同指数占比 '+numeric(row.get('aum_share_pct'), 1, suffix='%'))
        self.scale.setToolTip('规模日期 '+str(row.get('aum_date') or '待核验')+'；占比的分母为同指数全部普通ETF')
        self.activity.setText(('成交额 '+money(row['amount_cny']) if row.get('amount_cny') is not None else '成交额待来源')+' · 买卖价差 '+numeric(row.get('spread_bp'), 1, suffix=' bp'))
        self.activity.setToolTip('现有tradedQuantities为源单位成交量，不能冒充人民币成交额。\n累计成交量 '+numeric(row.get('volume'), 0))
        quote_time = source_label(row)
        self.clock.setText('报价 '+quote_time+' · 配对 '+clock(row.get('premium_source_at')))
        self.clock.setToolTip((row.get('status') or '待规模名单与报价')+'\n源 '+stamp(row.get('source_at'))+'\n取得 '+stamp(row.get('received_at'))+'\n'+row.get('source_date_basis',''))


class MinuteAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        result=[]
        for x in values:
            if not 0<=x<=240:result.append('');continue
            if abs(x-120)<.01:result.append('11:30 / 13:00');continue
            minute=int(x)+(570 if x<120 else 660)
            result.append(f'{minute//60:02}:{minute%60:02}')
        return result


class EtfOverviewPage(ScrollPage):
    def __init__(self):
        super().__init__(); self.selected_root = 'IF'; self.groups = {}; self.rows = []; self.reference = {}; self.cards = {}
        self.products = {}
        for root, (_, name, _) in UNDERLYINGS.items():
            button = QPushButton(name+' · 3只'); button.setCheckable(True); button.setMinimumHeight(39)
            button.clicked.connect(lambda _, r=root: self.select(r)); self.products[root] = button
        self.box.addWidget(FlowGrid(list(self.products.values()), 4, 220, self.body))
        head = QHBoxLayout(); self.summary = lab('同一指数内筛选 · 基金规模前三', 21, ACCENT, True); self.review = lab('每周复核 · 规模日期待核验', 15, MUTED)
        self.review.setAlignment(Qt.AlignmentFlag.AlignRight); head.addWidget(self.summary, 3); head.addWidget(self.review, 2); self.box.addLayout(head)
        self.fund_cards = [EtfCard(self.body) for _ in range(3)]; self.box.addWidget(FlowGrid(self.fund_cards, 3, 320, self.body))
        self.flows = Panel('已披露净申购 · 关注份额变化', '按实际数据日期标注')
        self.flow_table = table(['同指数ETF', '最近可核验日', '近5日合计'], 125); self.flows.box.addWidget(self.flow_table)
        self.flow_reason = lab('待已披露份额与净值；成交额不等于净申购', 16, MUTED); self.flows.box.addWidget(self.flow_reason)
        self.pcf = Panel('申赎可用性 · 可选', '需要当日申赎清单')
        for text in ('是否允许申购 / 赎回：待核验', '最小申赎单位 / 当日限额：待核验', '仅展示真实已披露状态'):
            self.pcf.box.addWidget(lab(text, 18, MUTED))
        self.box.addWidget(Split(self.flows, self.pcf, (2, 1)))
        self.chart = Panel('盘中折溢价采集轨迹 · bp', 'ETF与IOPV同刻配对')
        self.plot = pg.PlotWidget(background=PANEL,axisItems={'bottom':MinuteAxis(orientation='bottom')}); self.plot.setMinimumWidth(0); self.plot.setMinimumHeight(155); self.plot.setMaximumHeight(180)
        self.plot.setMenuEnabled(False); self.plot.setMouseEnabled(x=False, y=False); self.plot.hideButtons()
        self.plot.showGrid(y=True, alpha=.12)
        self.chart.box.addWidget(self.plot); self.empty_plot = lab('待可核验IOPV及同步报价；收盘折溢价见上方卡片', 17, MUTED)
        self.empty_plot.setAlignment(Qt.AlignmentFlag.AlignCenter); self.empty_plot.setMinimumHeight(120); self.chart.box.addWidget(self.empty_plot)
        legend=QHBoxLayout();self.legend=[]
        for i in range(3):
            item=lab('',15,CHART_COLORS[i],True);self.legend.append(item);legend.addWidget(item)
        self.chart.box.addLayout(legend)
        self.box.addWidget(self.chart)
        self.note = lab('候选范围：同一标的指数的普通股票ETF；规模占比以该组全部ETF为分母', 15, MUTED); self.box.addWidget(self.note)

    def render(self, rows, groups=None, reference=None):
        self.rows = rows; self.groups = groups or {}; self.reference = reference or {}; self.show_group()

    def select(self, root):
        self.selected_root = root; self.show_group()

    def show_group(self):
        root = self.selected_root; group = self.groups.get(root, {})
        meta = group.get('ranking', {}); rows = group.get('rows', [r for r in self.rows if r['root'] == root][:1])
        self.visible_rows = rows; self.cards = {}
        for r, button in self.products.items(): button.setChecked(r == root)
        pending = bool(meta.get('reason')) or not meta.get('as_of')
        self.summary.setText('同一指数内筛选 · 基金规模前三'+('待核验' if pending else ''))
        self.review.setText('每周复核 · 规模 '+str(meta.get('as_of') or '待核验')+(' · 待复核' if self.reference.get('due') and meta.get('as_of') else ''))
        self.review.setToolTip(meta.get('reason') or str(meta.get('source') or '')+'\n资料取得 '+stamp(self.reference.get('fetched_at')))
        for i, card in enumerate(self.fund_cards):
            row = rows[i] if i < len(rows) else {}; card.render(row, i+1)
            self.legend[i].setText(row.get('name','') if row.get('premium_series') else '')
            if row.get('symbol'): self.cards[row['symbol']] = card
        flow = group.get('flow', {}); self.flow_table.setRowCount(2); self.flow_table.clearContents()
        for i, title in enumerate((UNDERLYINGS[root][1]+'ETF全体', '其中：展示前三只')):
            cell(self.flow_table, i, 0, title)
            for j, key in enumerate((('daily_cny', 'five_day_cny') if i == 0 else ('top_daily_cny', 'top_five_day_cny')), 1):
                value = flow.get(key); cell(self.flow_table, i, j, money(value), ink(value))
        self.flows.note.setText('数据日期 '+str(flow.get('as_of') or '待披露'))
        self.flow_reason.setText(flow.get('reason') or '份额变化与净值估算；成交额不等于净申购')
        self.plot.clear(); self.plot.addItem(pg.InfiniteLine(0, angle=0, pen=pg.mkPen(BORDER)))
        has_points = False
        for i, row in enumerate(rows):
            points = row.get('premium_series', []); xs = []; ys = []; previous = None
            for point in points:
                if previous and (point['session'] != previous['session'] or (pd.Timestamp(point['source_at'])-pd.Timestamp(previous['source_at'])).total_seconds() > 30):
                    xs.append(point['x']); ys.append(float('nan'))
                xs.append(point['x']); ys.append(point['value']); previous = point
            if points:
                has_points = True; self.plot.plot(xs, ys, pen=pg.mkPen(CHART_COLORS[i % len(CHART_COLORS)], width=2),
                    symbol='o' if len(points) == 1 else None, symbolSize=5, connect='finite')
        self.plot.setVisible(has_points); self.empty_plot.setVisible(not has_points)
