from datetime import datetime,timezone,timedelta
import math
import re

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QFont,QSyntaxHighlighter,QTextCharFormat
from PySide6.QtWidgets import QFrame,QHBoxLayout,QLabel,QPushButton,QVBoxLayout,QWidget
import pyqtgraph as pg
from .trading_axis import TradingTimeMap

CHINA=timezone(timedelta(hours=8))
from .theme import (STYLE, PANEL, MUTED, BORDER, CHART_COLORS)
COLORS = CHART_COLORS


def label(text="",name=None):
    item=QLabel(text)
    if name: item.setObjectName(name)
    return item


class Panel(QFrame):
    def __init__(self,title=None):
        super().__init__()
        self.setObjectName("panel")
        self.layout=QVBoxLayout(self)
        self.layout.setContentsMargins(15,11,15,11)
        self.layout.setSpacing(7)
        if title: self.layout.addWidget(label(title,"section"))


class MetricCard(Panel):
    def __init__(self,title,subtitle):
        super().__init__()
        self.layout.addWidget(label(title,"muted"))
        self.value=label("—","metric")
        self.layout.addWidget(self.value)
        self.caption=label(subtitle,"muted")
        self.caption.setWordWrap(True)
        self.layout.addWidget(self.caption)
        self.setMinimumHeight(96)

    def update_value(self,value,suffix="",caption=None):
        self.value.setText("—" if value is None or not np.isfinite(value) else f"{value:,.2f}{suffix}")
        if caption is not None:
            self.caption.setText(caption)
            self.setToolTip(caption)


class ChinaAxis(pg.AxisItem):
    def tickValues(self,minVal,maxVal,size):
        mapping=getattr(self,"mapping",None)
        if mapping is not None: return [(mapping.step,mapping.ticks(minVal,maxVal,size))]
        span=maxVal-minVal
        if span<=0: return []
        desired=span/max(2,size/110)
        steps=[1,2,5,10,15,30,60,120,300,600,900,1800,3600,7200,14400,21600,43200,86400,172800,604800,2592000]
        step=next((s for s in steps if s>=desired),steps[-1]*math.ceil(desired/steps[-1]))
        offset=-8*3600 if step>=86400 else 0
        first=math.ceil((minVal-offset)/step)*step+offset
        return [(step,[first+i*step for i in range(max(0,int((maxVal-first)//step)+1))])]

    def tickStrings(self,values,scale,spacing):
        mapping=getattr(self,"mapping",None)
        if mapping is not None: return [mapping.label(value) for value in values]
        result=[]
        for value in values:
            try:
                stamp=datetime.fromtimestamp(value,timezone.utc).astimezone(CHINA)
                result.append(stamp.strftime("%m-%d" if spacing>=86400 else "%H:%M:%S" if spacing<60 else "%H:%M"))
            except (ValueError,OSError,OverflowError): result.append("")
        return result


class Chart(Panel):
    def __init__(self,title,unit,height=230,term=False):
        super().__init__()
        header=QHBoxLayout()
        self.title_label=label(title,"section");header.addWidget(self.title_label)
        header.addStretch()
        self.readout=label(unit,"muted")
        header.addWidget(self.readout)
        self.reset=QPushButton("复位")
        self.reset.setFixedHeight(28)
        header.addWidget(self.reset)
        self.layout.addLayout(header)
        self.plot=pg.PlotWidget(axisItems=None if term else {"bottom":ChinaAxis(orientation="bottom")},background=PANEL)
        self.plot.setFixedHeight(height)
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=False,y=True,alpha=.15)
        self.plot.setLabel("left",unit,color=MUTED)
        self.plot.getPlotItem().hideButtons()
        for axis in ("left","bottom"):
            self.plot.getAxis(axis).setPen(BORDER)
            self.plot.getAxis(axis).setTextPen(MUTED)
        self.legend=self.plot.addLegend(offset=(12,8),labelTextColor=MUTED,labelTextSize="10pt")
        self.layout.addWidget(self.plot,1)
        self.note=label("待接入数据","muted")
        self.layout.addWidget(self.note)
        self.lines={}
        self.key=None
        self.term=term
        self.time_map=None;self.boundary_lines=[]
        self.reset.clicked.connect(lambda:self.plot.enableAutoRange())
        self.vline=pg.InfiniteLine(angle=90,movable=False,pen=pg.mkPen(MUTED,style=Qt.PenStyle.DashLine))
        self.hline=pg.InfiniteLine(angle=0,movable=False,pen=pg.mkPen(MUTED,style=Qt.PenStyle.DashLine))
        self.plot.addItem(self.vline,ignoreBounds=True)
        self.plot.addItem(self.hline,ignoreBounds=True)
        self.vline.hide();self.hline.hide()
        self.proxy=pg.SignalProxy(self.plot.scene().sigMouseMoved,rateLimit=30,slot=self.mouse)

    def mouse(self,event):
        pos=event[0]
        if self.plot.sceneBoundingRect().contains(pos):
            point=self.plot.getViewBox().mapSceneToView(pos)
            self.vline.setPos(point.x());self.hline.setPos(point.y())
            self.vline.show();self.hline.show()
            try:
                when=dict(getattr(self,"term_ticks",[])).get(round(point.x()),"合约") if self.term else self.time_map.label(point.x(),full=True) if self.time_map else "—"
                self.readout.setText(f"{when}  ·  {point.y():,.2f}")
            except (ValueError,OSError,OverflowError): pass
        else:
            self.vline.hide();self.hline.hide()

    def draw(self,series,*,key=None,note="",ticks=None,frequency="1m"):
        if not self.term:
            self.time_map=TradingTimeMap((x for _,xs,_ in series for x in xs),frequency)
            self.plot.getAxis("bottom").mapping=self.time_map
            self.plot.getAxis("bottom").picture=None
            self.plot.getAxis("bottom").update()
            series=[(name,*self.time_map.project(xs,ys)) for name,xs,ys in series]
            for line in self.boundary_lines: self.plot.removeItem(line)
            self.boundary_lines=[]
            for position,title in self.time_map.boundaries:
                line=pg.InfiniteLine(pos=position,angle=90,movable=False,
                    pen=pg.mkPen(BORDER,style=Qt.PenStyle.DashLine),label=title,
                    labelOpts={"position":.95,"color":MUTED})
                self.plot.addItem(line,ignoreBounds=True);self.boundary_lines.append(line)
        active=set()
        for index,(name,x,y) in enumerate(series):
            active.add(name)
            if name not in self.lines:
                color=COLORS[("IF","IH","IC","IM").index(name)] if name in ("IF","IH","IC","IM") else COLORS[index%len(COLORS)]
                self.lines[name]=self.plot.plot(name=name,pen=pg.mkPen(color,width=2),
                    symbol="o" if self.term else None,symbolSize=6,symbolBrush=color)
                self.lines[name].setClipToView(True)
                self.lines[name].setDownsampling(auto=True,method="peak")
            self.lines[name].setData(x,y,connect="finite")
        for name in list(self.lines):
            if name not in active:
                self.legend.removeItem(name)
                self.plot.removeItem(self.lines.pop(name))
        if ticks is not None:
            self.term_ticks=ticks
            self.plot.getAxis("bottom").setTicks([ticks])
            self.plot.getAxis("bottom").setStyle(hideOverlappingLabels=False)
        if key!=self.key:
            self.plot.enableAutoRange()
            self.key=key
            if ticks:
                self.plot.setXRange(-.35,len(ticks)-.65,padding=0)
        self.note.setText(note or ("拖动 / 滚轮缩放，悬停查看时刻与数值" if active else "缺少该频率的可用数据"))


def curve(frame,field="close",frequency="1m",normalize=False):
    if frame.empty or field not in frame:
        return [],[]
    values=frame[field].to_numpy(dtype=float)
    if normalize and len(values) and np.isfinite(values[0]) and values[0]!=0:
        values=(values/values[0]-1)*10000
    xs,ys=[],[]
    previous=None
    for position,(_,row) in enumerate(frame.iterrows()):
        stamp=pd.Timestamp(row.event_time)
        if previous is not None and frequency!="1d":
            duration={"1m":60,"1s":1}[frequency]
            if (stamp-previous[0]).total_seconds()>duration*1.5 or row.trade_date!=previous[1] or row.session_id!=previous[2]:
                xs.append(stamp.timestamp());ys.append(float("nan"))
        xs.append(stamp.timestamp());ys.append(values[position])
        previous=(stamp,row.trade_date,row.session_id)
    return xs,ys


class PythonHighlight(QSyntaxHighlighter):
    def highlightBlock(self,text):
        for pattern,color in ((r"\b(def|return|if|else|None|True|False|and|or|is|not)\b","#94b8d5"),
                              (r"'[^']*'|\"[^\"]*\"","#e6c27e"),(r"#.*$","#8d959f")):
            fmt=QTextCharFormat();fmt.setForeground(QColor(color))
            for match in re.finditer(pattern,text): self.setFormat(match.start(),match.end()-match.start(),fmt)
