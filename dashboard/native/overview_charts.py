"""Four compact, same-input term and volume/position overview charts."""
import math
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSizePolicy

from .overview_pages import Panel,lab,numeric
from .futures_overview_view import COLORS
from .theme import ACCENT,MUTED,PANEL,TEXT


class CompactDistribution(QWidget):
    def __init__(self,compact=False):
        super().__init__();self.rows=[];self.reason='等待数据'
        self.setMinimumHeight(23 if compact else 34);self.setMaximumHeight(25 if compact else 38)

    def render(self,rows,reason):
        self.rows=rows;self.reason=reason
        self.setToolTip(reason+'\n'+'\n'.join('0'+str(r['slot'])+' '+str(r['symbol'])+' '+numeric(r['share_pct'],1,suffix='%') for r in rows))
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            painter.setPen(QColor(MUTED));painter.drawText(self.rect(),Qt.AlignmentFlag.AlignVCenter,self.reason);return
        x=0;available=max(0,self.width()-3*(len(self.rows)-1))
        for row in self.rows:
            width=available*row['share_pct']/100;slot=row['slot']
            painter.setBrush(QColor(COLORS[slot]));painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x,3,width,max(1,self.height()-6)),4,4)
            if width>=33:
                font=QFont(painter.font());font.setPixelSize(13 if width>=70 else 10);font.setBold(True);painter.setFont(font)
                painter.setPen(QColor('#ffffff' if slot<2 else ACCENT))
                text='0'+str(slot)+' '+numeric(row['share_pct'],0 if width<70 else 1,suffix='%')
                painter.drawText(QRectF(x+2,3,max(0,width-4),max(1,self.height()-6)),Qt.AlignmentFlag.AlignCenter,text)
            x+=width+3


class ProductCharts(Panel):
    def __init__(self,root,name,*,compact=False):
        super().__init__(root+' · '+name,'期限结构 / 成交与持仓')
        if compact:
            self.box.setContentsMargins(10,6,10,6);self.box.setSpacing(3)
            self.title.setStyleSheet(f'background:transparent;color:{ACCENT};font-size:18px;font-weight:700;')
            self.note.setStyleSheet(f'background:transparent;color:{MUTED};font-size:12px;')
        self.root=root;self.curve_points=[]
        self.curve=pg.PlotWidget(background=PANEL);self.curve.setMinimumWidth(0);self.curve.setMinimumHeight(80 if compact else 125);self.curve.setMaximumHeight(95 if compact else 150)
        self.curve.setMenuEnabled(False);self.curve.setMouseEnabled(x=False,y=False);self.curve.hideButtons();self.curve.showGrid(y=True,alpha=.12)
        self.curve.getAxis('left').setLabel('%');self.curve.getAxis('left').enableAutoSIPrefix(False)
        self.box.addWidget(self.curve)
        self.term_note=lab('等待同日有效年化',12,MUTED);self.box.addWidget(self.term_note)
        self.volume=CompactDistribution(compact);self.position=CompactDistribution(compact)
        for title,bar in (('成交',self.volume),('持仓',self.position)):
            line=QHBoxLayout();caption=lab(title,14,TEXT,True);caption.setFixedWidth(40)
            caption.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred)
            line.addWidget(caption);line.addWidget(bar,1);self.box.addLayout(line)
        self.position_note=lab('',11,MUTED);self.position_note.hide();self.box.addWidget(self.position_note)
        self.setMinimumHeight(222 if compact else 245)

    def render(self,rows,group):
        self.curve.clear();self.curve_points=[]
        candidates=[]
        for row in sorted(rows,key=lambda r:r.get('slot',99)):
            if row.get('display_saved'):continue
            value=row.get('annual_pct');days=row.get('days')
            if not isinstance(value,(int,float)) or not math.isfinite(value) or not isinstance(days,(int,float)):continue
            try:
                times=[pd.Timestamp(row[k]) for k in ('basis_future_source_at','basis_spot_source_at')]
                if any(pd.isna(t) or t.tzinfo is None for t in times):continue
            except (KeyError,TypeError,ValueError):continue
            candidates.append((row,times))
        identities={(r.get('pricing_day'),r.get('basis_kind')) for r,_ in candidates}
        times=[t for _,pair in candidates for t in pair]
        coherent=len(identities)<=1 and (not times or (max(times)-min(times)).total_seconds()<=3)
        if coherent:
            for row,_ in candidates:self.curve_points.append(dict(symbol=row['symbol'],slot=row['slot'],days=row['days'],annual_pct=row['annual_pct']))
        if self.curve_points:
            xs=[r['days'] for r in self.curve_points];ys=[r['annual_pct'] for r in self.curve_points]
            connect=np.array([self.curve_points[i+1]['slot']==r['slot']+1 if i+1<len(self.curve_points) else False
                              for i,r in enumerate(self.curve_points)],dtype=bool)
            self.curve.plot(xs,ys,connect=connect,pen=pg.mkPen(ACCENT,width=2),symbol='o',symbolSize=6,symbolBrush=ACCENT)
            self.curve.getAxis('bottom').setTicks([[(r['days'],'0'+str(r['slot'])) for r in self.curve_points]])
            span=max(max(xs)-min(xs),30);self.curve.setXRange(min(xs)-span*.1,max(xs)+span*.1,padding=0)
            pricing,kind=next(iter(identities));self.term_note.setText(('实时 ' if kind=='realtime' else '参考 ')+str(pricing)+' · 年化有效 '+str(len(xs))+'/4')
        else:self.term_note.setText('期现时间不一致' if candidates and not coherent else '等待有效同日期现年化')
        self.volume.render(group.get('distribution',[]),group.get('distribution_reason') or '等待四档成交')
        self.position.render(group.get('position_distribution',[]),group.get('position_reason') or '等待同日持仓')
        self.position_note.setText(group.get('position_reason','') if group.get('position_distribution') else '')
        self.position_note.setVisible(bool(group.get('position_distribution')))
