"""Three compact, responsive market overviews. Every quote retains its clock."""
import math

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QComboBox, QScrollArea, QFrame, QPushButton, QSizePolicy)

from .card_views import stamp
from .instruments import UNDERLYINGS
from .theme import ACCENT, BORDER, MUTED, PANEL, UP, DOWN, TEXT


def text(value, digits=2, signed=False):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return '—'
    return f'{value:+,.{digits}f}' if signed else f'{value:,.{digits}f}'


def quantity(value):
    if value is None:
        return '—'
    return text(value/1e8, 2)+'亿' if abs(value) >= 1e8 else text(value/1e4, 2)+'万' if abs(value) >= 1e4 else text(value, 0)


def label(size=15, color=TEXT, bold=False):
    w = QLabel(); w.setWordWrap(True)
    w.setStyleSheet(f'background:transparent;color:{color};font-size:{size}px;font-weight:{700 if bold else 400};')
    w.setMinimumWidth(0)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return w


class MarketCard(QFrame):
    def __init__(self, kind, parent=None):
        super().__init__(parent); self.kind = kind; self.row = None; self.chart_key = None
        self.setObjectName('marketCard'); self.setMinimumWidth(300)
        self.setStyleSheet(f'QFrame#marketCard {{background:{PANEL};border:1px solid {BORDER};border-radius:10px;}}')
        self.box = QVBoxLayout(self); self.box.setContentsMargins(16,12,16,10); self.box.setSpacing(6)
        head = QHBoxLayout(); self.heading = label(21, ACCENT, True); self.badge = label(13, MUTED)
        head.addWidget(self.heading, 3); head.addWidget(self.badge, 2); self.box.addLayout(head)
        self.identity = label(14, MUTED); self.box.addWidget(self.identity)
        values = QHBoxLayout(); self.price = label(38, ACCENT, True); self.change = label(27, TEXT, True)
        values.addWidget(self.price, 3); values.addWidget(self.change, 2); self.box.addLayout(values)
        self.market = label(16); self.box.addWidget(self.market)
        self.secondary = label(17); self.box.addWidget(self.secondary)
        self.clock = label(14, MUTED); self.box.addWidget(self.clock)
        self.plot = pg.PlotWidget(background=PANEL)
        self.plot.setMinimumHeight(65); self.plot.setMaximumHeight(70)
        self.plot.setMenuEnabled(False); self.plot.setMouseEnabled(x=False, y=False); self.plot.hideButtons()
        self.plot.hideAxis('bottom'); self.plot.hideAxis('left'); self.plot.showGrid(y=True, alpha=.1)
        self.plot.setMinimumWidth(0); self.plot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.box.addWidget(self.plot); self.plot.hide()
        self.detail_button = QPushButton('详情'); self.detail_button.setCheckable(True)
        self.detail_button.setStyleSheet(f'font-size:13px;color:{MUTED};padding:3px 8px;border:0;text-align:left;')
        self.box.addWidget(self.detail_button)
        self.details = label(14, MUTED); self.details.hide(); self.box.addWidget(self.details)
        self.detail_button.toggled.connect(self.details.setVisible)

    def render(self, row):
        self.row = row
        self.heading.setText(row['symbol'].replace('.CFE','') if self.kind == 'futures' else row['name'].replace('ETF',' ETF'))
        self.badge.setText(row['status'])
        self.badge.setToolTip(row['reason'])
        self.identity.setText((row['name']+' · 到期 '+str(row.get('expiry') or '—')) if self.kind == 'futures' else row['symbol'])
        self.price.setText(text(row['price'], 3 if self.kind == 'etfs' else 2))
        pct = row.get('change_pct'); color = UP if pct is not None and pct > 0 else DOWN if pct is not None and pct < 0 else TEXT
        self.change.setText(text(pct, signed=True)+'%' if pct is not None else '涨跌 —')
        self.change.setStyleSheet(f'background:transparent;font-size:27px;font-weight:700;color:{color};')
        self.change.setToolTip(row['prev_reason']+'\n参考昨收 '+text(row.get('prev_close'), 3 if self.kind == 'etfs' else 2))
        self.market.setText(('较昨收 ' if self.kind == 'futures' else '涨跌 ')+text(row.get('change'), 3 if self.kind == 'etfs' else 2, True)+'　成交 '+quantity(row.get('volume'))+' '+row['volume_unit'])
        if self.kind == 'futures':
            pct = row.get('percentile')
            rank = text(pct, 0)+'%' if pct is not None else '—'
            self.secondary.setText('基差 '+text(row.get('basis_points'), 1, True)+'点　年化 '+text(row.get('annual_pct'), 2, True)+'%　分位 '+rank)
            self.secondary.setToolTip(row.get('basis_reason','')+'\n'+row.get('percentile_reason','')+
                f"\n有效样本 {row.get('percentile_samples',0)}/20；区间 {row.get('percentile_start') or '—'} 至 {row.get('percentile_end') or '—'}")
        elif self.kind == 'etfs':
            if row.get('iopv') is not None:
                self.secondary.setText('IOPV '+text(row['iopv'], 4)+'　折溢价 '+text(row.get('premium_bp'), 1, True)+' bp')
            else:
                self.secondary.setText('IOPV / 折溢价待接入')
            self.secondary.setToolTip(row['premium_reason'])
        else:
            self.secondary.setText('最高 '+text(row.get('high'))+'　最低 '+text(row.get('low')))
        self.clock.setText('行情源 '+stamp(row.get('source_at')))
        self.clock.setToolTip('接收 '+stamp(row.get('received_at'))+'\n'+row['source_date_basis']+'\n页面刷新时间见页面底栏')
        detail = ['开盘 '+text(row.get('open'))+'　最高 '+text(row.get('high'))+'　最低 '+text(row.get('low')),
                  '源端昨收 '+text(row.get('prev_close'))+'；'+row['prev_reason'],
                  '历史昨日 '+str(row.get('yesterday_date') or '—')+'　'+text(row.get('yesterday_close')),
                  '接收 '+stamp(row.get('received_at'))+'；'+row['source_date_basis']]
        if self.kind == 'indices':
            detail.append('成分权重 / 个股及行业贡献：当前配置未提供有效权重与成分行情，待接入。')
        if self.kind == 'etfs':
            detail.append(row['premium_reason']+'；IOPV源 '+stamp(row.get('iopv_source_at')))
        if self.kind == 'futures':
            detail.extend([row.get('basis_reason',''), row.get('percentile_reason',''),
                           '未调整对数基差 '+text(row.get('log_basis_bp'))+' bp；分位仅作历史位置参考'])
        self.details.setText('\n'.join(detail))
        points = row.get('series', [])
        key = repr(points)
        if key != self.chart_key:
            self.chart_key = key; self.plot.clear(); self.plot.setVisible(len(points) > 1)
            if len(points) > 1:
                xs, ys = [], []; previous = None
                for p in points:
                    if previous and (p['session'] != previous['session'] or
                        (pd.Timestamp(p['source_at'])-pd.Timestamp(previous['source_at'])).total_seconds() > 30):
                        xs.append(p['x']); ys.append(float('nan'))
                    xs.append(p['x']); ys.append(p['value']); previous = p
                self.plot.plot(xs, ys, pen=pg.mkPen(color, width=2), connect='finite')
                self.plot.setXRange(min(xs),max(xs),padding=.03)
                self.plot.setToolTip('本地真实采集段相对昨收涨跌（%），按源时间；缺口及午休断线\n'+stamp(points[0]['source_at'])+' 至 '+stamp(points[-1]['source_at']))


class CardPage(QWidget):
    def __init__(self, kind):
        super().__init__(); self.kind = kind; self.cards = {}; self.rows = []; self.columns = 0
        layout = QVBoxLayout(self); layout.setContentsMargins(2,10,2,0); layout.setSpacing(10)
        self.summary = label(16, MUTED); layout.addWidget(self.summary)
        if kind == 'futures':
            controls = QHBoxLayout(); self.product = QComboBox(); self.slot = QComboBox()
            self.product.addItem('全部品种', None)
            for r, (_, n, _) in UNDERLYINGS.items(): self.product.addItem(r+' · '+n, r)
            for title, key in [('当月',0),('次月',1),('季月',2),('远季',3),('全部合约',None)]: self.slot.addItem(title,key)
            controls.addWidget(self.product); controls.addWidget(self.slot); controls.addStretch(); layout.addLayout(controls)
            self.product.currentIndexChanged.connect(self.filter); self.slot.currentIndexChanged.connect(self.filter)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget(); self.grid = QGridLayout(self.body); self.grid.setContentsMargins(0,0,10,8)
        self.grid.setSpacing(12); self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.body); layout.addWidget(self.scroll,1)
        self.scroll.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize: QTimer.singleShot(0,self.reflow)
        return super().eventFilter(obj,event)

    def render(self, rows):
        self.rows = rows
        wanted = {r['symbol'] for r in rows}
        for key in list(self.cards):
            if key not in wanted:
                self.grid.removeWidget(self.cards[key]); self.cards.pop(key).deleteLater()
        for row in rows:
            if row['symbol'] not in self.cards: self.cards[row['symbol']] = MarketCard(self.kind,self.body)
            self.cards[row['symbol']].render(row)
        self.filter()

    def filter(self, *_):
        self.visible_rows = [r for r in self.rows if self.kind != 'futures' or
            (self.product.currentData() in (None,r['root']) and self.slot.currentData() in (None,r.get('slot')))]
        fresh = sum(bool(r['quality'].get('usable')) for r in self.visible_rows)
        if self.kind == 'indices':
            changes = [r for r in self.visible_rows if r.get('change_pct') is not None and r['quality'].get('usable')]
            leaders = sorted(changes,key=lambda r:r['change_pct'],reverse=True)
            self.summary.setText('四大指数　'+('最强 '+leaders[0]['name']+' '+text(leaders[0]['change_pct'],2,True)+'%　最弱 '+leaders[-1]['name']+' '+text(leaders[-1]['change_pct'],2,True)+'%' if len(leaders)>1 else '等待最新报价')+f'　· 有效观测 {fresh}/{len(self.visible_rows)}')
        elif self.kind == 'etfs':
            self.summary.setText(f'对应指数代表 ETF　· 有效观测 {fresh}/{len(self.visible_rows)}　· IOPV按同步输入单独判断')
        else:
            self.summary.setText(f"{len(self.visible_rows)} 个合约　· 有效观测 {fresh}　· 分位：自身对数基差 / 前20交易日")
        while self.grid.count(): self.grid.takeAt(0)
        wanted = {r['symbol'] for r in self.visible_rows}
        for s,card in self.cards.items():card.setVisible(s in wanted)
        self.columns = 0; self.reflow()

    def reflow(self):
        rows = getattr(self,'visible_rows',[])
        columns = max(1,min(3 if self.kind == 'futures' else 2,(self.scroll.viewport().width()-12)//390))
        if columns == self.columns:return
        self.columns = columns
        while self.grid.count():self.grid.takeAt(0)
        for i in range(3):self.grid.setColumnStretch(i,1 if i<columns else 0)
        for i,row in enumerate(rows):self.grid.addWidget(self.cards[row['symbol']],i//columns,i%columns)


class MarketOverviewPanel(QWidget):
    changed = Signal()
    def __init__(self):
        super().__init__(); self.state = None
        layout = QVBoxLayout(self); layout.setContentsMargins(12,8,12,8); layout.setSpacing(6)
        self.tabs = QTabWidget(); self.views = {}
        for key,title in [('indices','指数'),('etfs','ETF'),('futures','股指期货')]:
            page = CardPage(key); self.views[key] = page; self.tabs.addTab(page,title)
        layout.addWidget(self.tabs,1)
        self.note = label(14,MUTED); self.note.setText('正在读取最新行情和昨日参照…'); layout.addWidget(self.note)

    def render(self,state):
        data = state.get('market_overview')
        if not data:
            self.note.setText('等待本轮最新行情；旧研究型启动缓存不混入新概览'); return
        self.state = state
        for key,page in self.views.items():page.render(data[key])
        self.note.setText('昨日参照 '+str(data.get('previous_session') or '待核验')+'　· 源日期按接收日推定'+
                          ('　· '+'；'.join(data['errors']) if data.get('errors') else ''))
