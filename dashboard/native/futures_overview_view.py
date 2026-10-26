"""Four expiry cards, term structure and pricing changes from the approved sketch."""
import math

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton

from .overview_pages import (ScrollPage, Panel, FlowGrid, Split, lab, put, numeric,
                             ink, clock, table, cell)
from .instruments import UNDERLYINGS
from .card_views import stamp
from .theme import ACCENT, MUTED, TEXT, PANEL, BORDER, CHART_COLORS, THEME

SLOTS=('当月','次月','季月','远季')
COLORS=(ACCENT,'#4c8fbc','#7bb3d3','#a7c9e0') if THEME=='public' else CHART_COLORS


class FuturesCard(Panel):
    def __init__(self,parent):
        super().__init__(parent=parent);self.row={}
        head=QHBoxLayout();self.heading=lab('',23,ACCENT,True);self.badge=lab('',16,ACCENT)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignRight);head.addWidget(self.heading,3);head.addWidget(self.badge,1);self.box.addLayout(head)
        self.price=lab('—',36,ACCENT,True);self.box.addWidget(self.price)
        self.values=[]
        for title in ('点基差','对数年化','20日基差分位'):
            line=QHBoxLayout();caption=lab(title,16,MUTED);value=lab('—',25,TEXT,True)
            value.setAlignment(Qt.AlignmentFlag.AlignRight);line.addWidget(caption,1);line.addWidget(value,1)
            self.box.addLayout(line);self.values.append(value)
        self.basis_value,self.annual_value,self.rank_value=self.values
        self.clock=lab('',14,MUTED);self.box.addWidget(self.clock);self.setMinimumHeight(260)

    def render(self,row,position):
        self.row=row;self.heading.setText(row.get('symbol','待合约').replace('.CFE',''));self.badge.setText(SLOTS[position])
        self.heading.setToolTip('到期 '+str(row.get('expiry') or '待核验'))
        self.price.setText(numeric(row.get('price')))
        for widget,key,suffix,digits in ((self.basis_value,'basis_points','点',1),(self.annual_value,'annual_pct','%',2)):
            put(widget,numeric(row.get(key),digits,True,suffix),color=ink(row.get(key)),size=25,bold=True)
            widget.setToolTip(row.get('basis_reason') or '待有效同步期现报价')
        rank=row.get('percentile')
        self.rank_value.setText(numeric(rank,1,suffix='%') if rank is not None else '样本不足' if row.get('basis_points') is not None else '待同步行情')
        self.rank_value.setToolTip(row.get('percentile_reason') or '同一具体合约，此前20交易日，排除当前日')
        source=('源 '+clock(row.get('source_at'))) if row.get('quality',{}).get('usable') else '缓存 '+stamp(row.get('source_at'),True) if row.get('source_at') else '等待行情'
        self.clock.setText(source+f" · 样本 {row.get('percentile_samples',0)}/20")
        self.clock.setToolTip('行情源 '+stamp(row.get('source_at'))+'\n接收 '+stamp(row.get('received_at'))+
            '\n'+str(row.get('percentile_start') or '—')+' 至 '+str(row.get('percentile_end') or '—'))


class VolumeDistribution(QWidget):
    def __init__(self):
        super().__init__();self.rows=[];self.reason='待四个到期合约的有效成交数据';self.setMinimumHeight(90)
    def render(self,rows,reason):
        self.rows=rows;self.reason=reason;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            p.setPen(QColor(MUTED));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.reason);return
        x=0;available=max(0,self.width()-9)
        for i,row in enumerate(self.rows):
            width=available*row['share_pct']/100
            p.setBrush(QColor(COLORS[i]));p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x,14,width,25),3,3);x+=width+3
            p.setPen(QColor(MUTED));p.drawText(QRectF(i*self.width()/4,51,self.width()/4,30),Qt.AlignmentFlag.AlignVCenter,
                SLOTS[row['slot']]+' '+numeric(row['share_pct'],1,suffix='%'))


class FuturesOverviewPage(ScrollPage):
    def __init__(self):
        super().__init__();self.selected_root='IF';self.rows=[];self.indices=[];self.groups={};self.cards={}
        self.products={}
        for root,(_,name,_) in UNDERLYINGS.items():
            button=QPushButton(root+' · '+name);button.setCheckable(True);button.setMinimumHeight(39)
            button.clicked.connect(lambda _,r=root:self.select(r));self.products[root]=button
        self.box.addWidget(FlowGrid(list(self.products.values()),4,220,self.body))
        head=QHBoxLayout();self.spot=lab('现货 —',25,ACCENT,True);self.note=lab('未调整口径 · 分位按具体合约独立计算',16,MUTED)
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight);head.addWidget(self.spot,3);head.addWidget(self.note,2);self.box.addLayout(head)
        self.contract_cards=[FuturesCard(self.body) for _ in range(4)]
        self.box.addWidget(FlowGrid(self.contract_cards,4,290,self.body))
        self.term=Panel('年化期限结构','按真实到期日');self.curve=pg.PlotWidget(background=PANEL)
        self.curve.setMinimumWidth(0);self.curve.setMinimumHeight(225);self.curve.setMaximumHeight(240)
        self.curve.setMenuEnabled(False);self.curve.setMouseEnabled(x=False,y=False);self.curve.hideButtons()
        self.curve.showGrid(y=True,alpha=.13);self.curve.getAxis('left').setLabel('%')
        self.term.box.addWidget(self.curve);self.empty_curve=lab('待有效同步期现报价与到期日',17,MUTED)
        self.empty_curve.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty_curve.setMinimumHeight(225);self.term.box.addWidget(self.empty_curve)
        self.changes=Panel('相对昨日的定价变化','按具体合约')
        self.change_values=[]
        for title in ('当月基差变化','近月 − 次月价差','近5分钟基差变化'):
            line=QHBoxLayout();line.addWidget(lab(title,18,MUTED),1);value=lab('—',27,ACCENT,True)
            value.setAlignment(Qt.AlignmentFlag.AlignRight);line.addWidget(value,1);self.changes.box.addLayout(line);self.change_values.append(value)
        self.changes.box.addWidget(lab('分位：沿用第六版A02前窗规则',17,ACCENT,True))
        self.changes.box.addWidget(lab('缺历史只影响分位，最新行情独立显示',16,MUTED))
        self.box.addWidget(Split(self.term,self.changes,(2,1)))
        self.volumes=Panel('成交分布与昨日持仓','昨日持仓待可靠日频数据')
        self.distribution=VolumeDistribution();self.volumes.box.addWidget(self.distribution)
        self.more=QPushButton('量仓明细 ›');self.more.setCheckable(True);self.volumes.box.addWidget(self.more,alignment=Qt.AlignmentFlag.AlignRight)
        self.volume_table=table(['合约','累计成交（手）','成交占比','昨日持仓','持仓日期'],190)
        self.volume_table.hide();self.more.toggled.connect(self.volume_table.setVisible);self.volumes.box.addWidget(self.volume_table)
        self.box.addWidget(self.volumes);self.footer=lab('分位为自身未调整对数基差相对前20交易日的位置；当前日排除，缺日留空',15,MUTED);self.box.addWidget(self.footer)

    def select(self,root):
        self.selected_root=root;self.show_group()

    def render(self,rows,indices=None,groups=None):
        self.rows=rows;self.indices=indices or [];self.groups=groups or {};self.show_group()

    def show_group(self):
        root=self.selected_root
        for key,button in self.products.items():button.setChecked(key==root)
        rows=sorted((r for r in self.rows if r['root']==root),key=lambda r:r.get('slot',99))
        self.visible_rows=rows;self.cards={}
        spot=next((r for r in self.indices if r['root']==root),{})
        self.spot.setText('现货 '+numeric(spot.get('price'))+'  '+numeric(spot.get('change_pct'),signed=True,suffix='%'))
        self.spot.setToolTip('行情源 '+stamp(spot.get('source_at'))+'\n'+str(spot.get('status') or '等待行情'))
        by_slot={r.get('slot'):r for r in rows}
        for i,card in enumerate(self.contract_cards):
            row=by_slot.get(i,{});card.render(row,i)
            if row.get('symbol'):self.cards[row['symbol']]=card
        self.curve.clear();self.curve_points=[];xs=[];ys=[];ticks=[]
        for row in rows:
            days=row.get('days');value=row.get('annual_pct')
            if days is None:continue
            xs.append(days);ys.append(value if value is not None else float('nan'))
            ticks.append((days,SLOTS[min(3,row.get('slot',0))]+' · '+str(days)+'天'))
            if value is not None:self.curve_points.append(dict(symbol=row['symbol'],days=days,annual_pct=value))
        if self.curve_points:
            self.curve.plot(xs,ys,pen=pg.mkPen(ACCENT,width=3),symbol='o',symbolSize=7,symbolBrush=ACCENT,symbolPen=ACCENT,connect='finite')
            self.curve.getAxis('bottom').setTicks([ticks]);self.curve.enableAutoRange(axis='y')
            span=max(max(xs)-min(xs),30)
            self.curve.setXRange(min(xs)-span*.1,max(xs)+span*.1,padding=0)
        self.curve.setVisible(bool(self.curve_points));self.empty_curve.setVisible(not self.curve_points)
        group=self.groups.get(root,{})
        for widget,key in zip(self.change_values,('basis_change_previous','calendar_points','basis_change_5m')):
            value=group.get(key);put(widget,numeric(value,2,True,'点'),color=ink(value),size=27,bold=True)
        self.change_values[0].setToolTip(group.get('previous_reason') or '待同步当前基差与准确昨日参照')
        self.change_values[1].setToolTip('第六版B01近月−次月点差；两合约与现货需同步')
        self.change_values[2].setToolTip(group.get('five_minute_reason') or '待五分钟前同步期现观测')
        distribution=group.get('distribution',[]);reason=group.get('distribution_reason') or '待四个到期合约的完整有效成交数据'
        self.distribution.render(distribution,reason);shares={r['symbol']:r['share_pct'] for r in distribution}
        self.volume_table.setRowCount(len(rows));self.volume_table.clearContents()
        for i,row in enumerate(rows):
            cell(self.volume_table,i,0,row['symbol'].replace('.CFE',''))
            cell(self.volume_table,i,1,numeric(row.get('volume'),0))
            cell(self.volume_table,i,2,numeric(shares.get(row['symbol']),1,suffix='%'))
            cell(self.volume_table,i,3,'—',MUTED);cell(self.volume_table,i,4,'待核验',MUTED)
