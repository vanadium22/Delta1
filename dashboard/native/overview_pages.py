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
        self.box = QVBoxLayout(self); self.box.setContentsMargins(14, 10, 14, 10); self.box.setSpacing(8)
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
        from .page_scale import ScaleScrollArea
        self.scroll = ScaleScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget(); self.box = QVBoxLayout(self.body); self.box.setContentsMargins(2, 2, 12, 12); self.box.setSpacing(12)
        self.box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.body); outer.addWidget(self.scroll)


class IndexCard(Panel):
    clicked = Signal(str)
    def __init__(self, root, parent):
        super().__init__(parent=parent); self.root = root; self.row = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        top = QHBoxLayout(); self.heading = lab(UNDERLYINGS[root][1], 23, ACCENT, True); self.change = lab('—', 27, TEXT, True)
        self.change.setAlignment(Qt.AlignmentFlag.AlignRight); top.addWidget(self.heading, 1); top.addWidget(self.change, 1)
        self.box.addLayout(top); self.price = lab('—', 42, ACCENT, True); self.box.addWidget(self.price)
        bottom = QHBoxLayout(); self.short = lab('5分钟 —', 16, MUTED); self.clock = lab('行情源 —', 14, MUTED)
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight); bottom.addWidget(self.short, 1);self.clock.setParent(self);self.clock.hide()
        self.box.addLayout(bottom); self.setMinimumHeight(148)
        self._pressed=False
        for widget in (self.heading,self.change,self.price,self.short,self.clock):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self._pressed=True;event.accept();return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pressed=self._pressed;self._pressed=False
            if pressed and self.rect().contains(event.position().toPoint()):self.clicked.emit(self.root)
            event.accept();return
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
    w.setStyleSheet(f'QTableWidget{{border:0;background:{PANEL};font-size:20px;}} QTableWidget::item{{padding:4px;}} QHeaderView::section{{background:{PANEL};font-size:16px;padding:5px;color:{MUTED};border:0;}}')
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
        painter.drawRoundedRect(QRectF(5, self.height()/2-7, max(3, max(0,self.width()-10)*abs(self.value)/self.maximum), 14), 3, 3)


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
        if detail.get('display_saved'):self.snapshot.setText('上次显示 · '+stamp(detail.get('snapshot_at'))+' · '+self.snapshot.text())
        self.snapshot.setToolTip('成分源 '+str(detail.get('source_at') or '—')+'\n'+str(detail.get('reason') or ''))
        self.snapshot.setToolTip('实际取得 '+stamp(detail.get('snapshot_at'))+'\n权重基准 '+str(detail.get('weight_date') or '待核验')+'\n官方权重日 '+str(detail.get('official_weight_date') or '待核验')+'\n'+str(detail.get('weight_reason') or detail.get('reason',''))+f"\n有效 {detail.get('covered',0)}/{detail.get('expected',0)}只")
        for widget, key, suffix in zip(self.metrics, ('up_pct', 'actual_points', 'contribution_points', 'residual_points'), ('%', '点', '点', '点')):
            value = detail.get(key); put(widget, numeric(value, 1 if key == 'up_pct' else 2, key != 'up_pct', suffix), color=ink(value), size=28, bold=True)
        self.weight_panel.note.setText((detail.get('industry_standard') or '行业分类待核验')+(' · 估算权重 ' if detail.get('weight_method')=='fixed_quantity_estimate' else ' · 权重 ')+str(detail.get('weight_date') or '待核验'))
        groups = detail.get('industries', []); self.weights.render(groups)
        ranked = detail.get('leaders', [])+detail.get('laggards', [])
        displayed = ranked if ranked else groups[:6]
        self.industry_panel.note.setText('按已覆盖成分计算 · 缺项已剔除' if detail.get('partial') else '按有效权重计算' if ranked else '贡献待核验，先看权重')
        self.displayed_industries = displayed; self.industries.setRowCount(max(6, len(displayed)))
        self.industries.clearContents()
        maximum = max([abs(r['change_pct']) for r in displayed if r.get('change_pct') is not None] or [1]) or 1
        for i in range(max(6, len(displayed))):
            if i >= len(displayed):
                cell(self.industries, i, 0, '待行业资料' if not displayed else '—', MUTED)
                for col in (1, 2, 4): cell(self.industries, i, col, '—', MUTED)
                continue
            r = displayed[i]; value = r.get('contribution_points')
            cell(self.industries, i, 0, r['name'], ACCENT, r['name'])
            cell(self.industries, i, 1, numeric(r.get('weight_pct'), 1, suffix='%'))
            cell(self.industries, i, 2, numeric(r.get('change_pct'), signed=True, suffix='%'), ink(r.get('change_pct')))
            self.industries.setCellWidget(i, 3, MiniBar(r.get('change_pct'), maximum, self.industries))
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
        values = QHBoxLayout(); self.price = lab('—', 43, ACCENT, True); self.change = lab('—', 29, TEXT, True)
        self.change.setAlignment(Qt.AlignmentFlag.AlignRight); values.addWidget(self.price, 1); values.addWidget(self.change, 1); self.box.addLayout(values)
        second = QHBoxLayout(); self.iopv = lab('', 16,MUTED); self.premium = lab('', 29, TEXT, True)
        self.premium.setAlignment(Qt.AlignmentFlag.AlignRight); second.addWidget(self.iopv, 1); second.addWidget(self.premium, 1); self.box.addLayout(second)
        self.closing_premium=lab('',14,MUTED);self.box.addWidget(self.closing_premium)
        divider = QFrame(); divider.setFixedHeight(1); divider.setStyleSheet(f'background:{BORDER};'); self.box.addWidget(divider)
        metrics=QHBoxLayout();self.scale=lab('',28,ACCENT,True);self.share=lab('',28,ACCENT,True);self.spread=lab('',28,ACCENT,True)
        for caption,value in (('规模 · 亿元',self.scale),('同指数占比',self.share),('买卖价差 · bp',self.spread)):
            column=QVBoxLayout();column.setSpacing(3);column.addWidget(value);column.addWidget(lab(caption,14,MUTED));metrics.addLayout(column,1)
        self.box.addLayout(metrics)
        self.activity=lab('',14,MUTED);self.box.addWidget(self.activity);self.clock = lab('', 14, MUTED)
        self.clock.setParent(self);self.clock.hide()
        self.setMinimumHeight(245)

    def render(self, row, position):
        self.row = row
        self.heading.setText(row.get('name') or f'规模第{position} · 待核验')
        self.heading.setToolTip((row.get('symbol') or '')+'\n'+(row.get('name') or '待同指数完整规模排名'))
        self.badge.setText('规模 #'+str(row['rank']) if row.get('rank') else '待排名')
        self.price.setText(numeric(row.get('price'), 3))
        put(self.change, numeric(row.get('change_pct'), signed=True, suffix='%'), color=ink(row.get('change_pct')), size=27, bold=True)
        from dashboard.marketdata.overview_reference import premium_display,finite
        display=premium_display(row);value=display['display_premium_bp']
        label=row.get('display_premium_label') if row.get('display_premium_mode')==display['display_premium_mode'] else None
        self.iopv.setText((label or display['display_premium_label']) if display['display_premium_mode']=='closing' else
            'IOPV '+numeric(row['iopv'],4) if row.get('iopv') is not None else 'IOPV待有效报价' if row.get('iopv_id') else 'IOPV待接入')
        put(self.premium,numeric(value,1,True,' bp'),color=ink(value),size=32,bold=True)
        self.iopv.setToolTip(row.get('premium_reason') or '缺少可核验IOPV来源或明确映射')
        self.premium.setToolTip(display['display_premium_reason'] or '待可用折溢价')
        self.closing_premium.setText('净值日期 '+str(row.get('nav_date') or '待核验') if display['display_premium_mode']=='closing' else '')
        self.closing_premium.setVisible(display['display_premium_mode']=='closing')
        self.closing_premium.setToolTip(row.get('closing_premium_reason') or '待同日收盘和单位净值，非盘中IOPV')
        scale_valid=finite(row.get('aum_cny')) and row['aum_cny']>0
        put(self.scale,numeric(row.get('aum_cny')/1e8 if scale_valid else None),color=ACCENT if scale_valid else MUTED,size=28,bold=True)
        put(self.share,numeric(row.get('aum_share_pct'),1,suffix='%'),color=ACCENT,size=28,bold=True)
        self.scale.setToolTip('规模日期 '+str(row.get('aum_date') or '待核验')+'；人民币资产净值')
        self.share.setToolTip('占比日期 '+str(row.get('aum_share_date') or row.get('aum_date') or '待核验')+'；分母为同日同指数全部普通ETF，不混用更新后的单只规模')
        spread_valid=finite(row.get('spread_bp'))
        put(self.spread,numeric(row.get('spread_bp'),1),color=ACCENT if spread_valid else MUTED,size=28,bold=True)
        self.activity.setText('成交额 '+money(row['amount_cny']) if row.get('amount_cny') is not None else '成交额待来源')
        self.activity.setVisible(row.get('amount_cny') is not None)
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
        super().__init__();self.selected_root='IF';self.groups={};self.rows=[];self.reference={};self.cards={};self.market_sizes={}
        self.products={}
        for root,(_,name,_) in UNDERLYINGS.items():
            button=QPushButton(name+' · 3只');button.setCheckable(True);button.setMinimumHeight(39)
            button.clicked.connect(lambda _,r=root:self.select(r));self.products[root]=button
        self.box.addWidget(FlowGrid(list(self.products.values()),4,220,self.body))
        head=QHBoxLayout();self.summary=lab('同一指数内筛选 · 基金规模前三',24,ACCENT,True);self.review=lab('',16,MUTED)
        self.review.setAlignment(Qt.AlignmentFlag.AlignRight);head.addWidget(self.summary,3);head.addWidget(self.review,2);self.box.addLayout(head)
        self.fund_cards=[EtfCard(self.body) for _ in range(3)];self.box.addWidget(FlowGrid(self.fund_cards,3,320,self.body))
        self.capacity=Panel('规模对比 · ETF资产与期货名义本金','')
        from .market_size_view import SizePie
        self.etf_panel=Panel('同指数ETF · 前三与其它','');self.futures_panel=Panel('四档期货 · 持仓名义本金','')
        self.etf_pie=SizePie();self.futures_pie=SizePie();self.etf_panel.box.addWidget(self.etf_pie);self.futures_panel.box.addWidget(self.futures_pie)
        self.capacity.box.addWidget(Split(self.etf_panel,self.futures_panel,(1,1)));self.box.addWidget(self.capacity)
        self.note=lab('ETF采用完整同指数普通ETF净资产；期货采用持仓手数 × 价格 × 合约乘数',17,MUTED);self.box.addWidget(self.note)

    def render(self,rows,groups=None,reference=None,market_sizes=None):
        self.rows=rows;self.groups=groups or {};self.reference=reference or {};self.market_sizes=market_sizes or {};self.show_group()

    def select(self,root):
        self.selected_root=root;self.show_group()

    def show_group(self):
        from dashboard.marketdata.overview_reference import finite
        root=self.selected_root;group=self.groups.get(root,{});meta=group.get('ranking',{})
        rows=group.get('rows',[r for r in self.rows if r['root']==root][:1]);self.visible_rows=rows;self.cards={}
        for r,button in self.products.items():button.setChecked(r==root)
        pending=bool(meta.get('reason')) or not meta.get('as_of')
        self.summary.setText('同一指数内筛选 · 基金规模前三'+('待核验' if pending else ''))
        self.review.setText('规模排名 '+str(meta.get('as_of') or '待核验'))
        if group.get('display_saved'):self.review.setText('保留上次资料 · '+self.review.text())
        self.review.setToolTip(meta.get('reason') or str(meta.get('source') or '')+'\n资料取得 '+stamp(self.reference.get('fetched_at')))
        for i,card in enumerate(self.fund_cards):
            row=rows[i] if i<len(rows) else {};card.render(row,i+1)
            if row.get('symbol'):self.cards[row['symbol']]=card
        sizes=self.market_sizes.get(root,{})
        assets=sizes.get('etfs',{});futures=sizes.get('futures',{})
        self.etf_pie.render(assets);self.futures_pie.render(futures)
        self.etf_panel.note.setText(str(assets.get('as_of') or '待规模日期')+' · '+str(assets.get('universe_count') or '—')+'只')
        source='HTTP同步持仓/价格' if futures.get('basis')=='current_http' else '已完成同日收盘'
        covered=futures.get('covered',0);status=('已知 '+str(covered)+'/4 · ' if covered<4 else '')
        self.futures_panel.note.setText(status+str(futures.get('as_of') or '待持仓日期'))
        self.futures_panel.setToolTip(source+'\n'+str(futures.get('reason') or '待可靠持仓来源'))
        ratio=sizes.get('futures_to_etf')
        self.capacity.note.setText('期货 / ETF '+numeric(ratio,2)+'倍' if finite(ratio) else '缺项只显示已知规模')
        self.note.setText('ETF净资产 · 期货持仓手数 × 价格 × 合约乘数（IF/IH 300，IC/IM 200）')
