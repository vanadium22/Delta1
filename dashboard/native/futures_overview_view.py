"""Four expiry cards, term structure and pricing changes from the approved sketch."""
import math

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QPushButton, QLabel

from .overview_pages import (ScrollPage, Panel, FlowGrid, Split, lab, put, numeric,
                             ink, clock, table, cell,source_label)
from .instruments import UNDERLYINGS
from .card_views import stamp
from .theme import ACCENT, ACCENT_BACKGROUND, MUTED, TEXT, PANEL, BORDER, CHART_COLORS, THEME
from dashboard.marketdata.overview_basis import input_summary
from .term_curve import points as term_points,description as term_description,tooltip as term_tooltip

SLOTS=('当月','次月','季月','远季')
COLORS=(ACCENT,'#4c8fbc','#7bb3d3','#a7c9e0') if THEME=='public' else CHART_COLORS


def percentile_color(value):
    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not 0<=value<=100:
        return MUTED,0.0
    intensity=abs(value-50)/50
    neutral=QColor(MUTED);edge=QColor('#126ca5' if value<50 else '#b44f22') if THEME=='public' else QColor('#94b8d5' if value<50 else '#f0ab6d')
    rgb=[round(getattr(neutral,c)()*(1-intensity)+getattr(edge,c)()*intensity) for c in ('red','green','blue')]
    return QColor(*rgb).name(),intensity


class FuturesCard(Panel):
    def __init__(self,parent,*,compact=False):
        super().__init__(parent=parent);self.row={}
        self.compact=compact;self.value_size=27 if compact else 29
        self.box.setContentsMargins(12,8,12,8);self.box.setSpacing(3 if compact else 6)
        head=QHBoxLayout();self.heading=lab('',16 if compact else 24,MUTED if compact else ACCENT,True);self.badge=lab('',23 if compact else 16,ACCENT if compact else MUTED,compact)
        self.price=lab('—',34 if compact else 40,ACCENT,True)
        if compact:
            self.badge.setStyleSheet(f'background:{ACCENT_BACKGROUND};color:{ACCENT};font-size:24px;font-weight:700;border-radius:5px;padding:2px 4px;')
            identity=QVBoxLayout();identity.setSpacing(1);identity.addWidget(self.badge);identity.addWidget(self.heading)
            head.addLayout(identity,1);self.price.setAlignment(Qt.AlignmentFlag.AlignRight);head.addWidget(self.price,1)
        else:
            self.badge.setAlignment(Qt.AlignmentFlag.AlignRight);head.addWidget(self.heading,3);head.addWidget(self.badge,2)
        self.box.addLayout(head)
        if not compact:self.box.addWidget(self.price)
        self.values=[];self.captions=[]
        for title in ('去分红基差','去分红年化基差','较昨日基差变化','20日年化分位','60日年化分位'):
            line=QHBoxLayout();caption=lab(title,15 if compact else 17,MUTED);value=lab('—',self.value_size,TEXT,True)
            value.setAlignment(Qt.AlignmentFlag.AlignRight);line.addWidget(caption,1);line.addWidget(value,1)
            if compact and len(self.values)>=2:
                caption.setParent(self);value.setParent(self);caption.hide();value.hide()
            else:self.box.addLayout(line)
            self.values.append(value);self.captions.append(caption)
        self.basis_value,self.annual_value,self.previous_value,self.rank_value,self.rank60_value=self.values
        self.window_dates={};self.means={};self.medians={}
        if compact:
            grid=QGridLayout();grid.setContentsMargins(0,1,0,0);grid.setHorizontalSpacing(5);grid.setVerticalSpacing(0)
            grid.addWidget(lab('窗口',12,MUTED),0,0)
            for col,length in enumerate((20,60),1):
                heading=lab(str(length)+'日',14,ACCENT,True);heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
                dates=lab('日期待核验',10,MUTED);dates.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.window_dates[length]=dates;grid.addWidget(heading,0,col);grid.addWidget(dates,1,col)
            for row,title in ((2,'分位'),(3,'avg'),(4,'中位')):grid.addWidget(lab(title,12,MUTED),row,0)
            for col,(length,rank) in enumerate(((20,self.rank_value),(60,self.rank60_value)),1):
                rank.setAlignment(Qt.AlignmentFlag.AlignCenter);grid.addWidget(rank,2,col)
                avg=lab('—',16,TEXT,True);middle=lab('—',16,TEXT,True)
                for widget in (avg,middle):widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(avg,3,col);grid.addWidget(middle,4,col);self.means[length]=avg;self.medians[length]=middle
            self.box.addLayout(grid)
        self.dividend_note=lab('分红来源待核验',12 if compact else 14,MUTED);self.box.addWidget(self.dividend_note)
        self.clock=lab('',14,MUTED);self.clock.setParent(self);self.clock.hide();self.setMinimumHeight(222 if compact else 318)
        if compact:
            for label in self.findChildren(QLabel):label.setWordWrap(False)

    def render(self,row,position):
        view=row.get('basis_display') or row
        self.row=row;self.heading.setText(row.get('symbol','待合约').replace('.CFE',''));self.badge.setText(((row.get('root') or '')+' ' if self.compact else '')+f'0{position} · '+SLOTS[position])
        self.heading.setToolTip('到期 '+str(row.get('expiry') or '待核验'))
        self.price.setText(numeric(row.get('price')))
        for widget,key,suffix,digits in ((self.basis_value,'basis_points','点',1),(self.annual_value,'annual_pct','%',2),(self.previous_value,'basis_change_previous','点',1)):
            put(widget,numeric(view.get(key),digits,True,suffix),color=ink(view.get(key)),size=self.value_size,bold=True)
            widget.setToolTip((view.get('basis_reason') or '待有效同步期现报价')+'\n'+input_summary(view))
        self.previous_value.setToolTip('同一实际合约较准确上一交易日收盘；分别使用各时点D，单位点。前日 '+str(view.get('basis_prev_day') or '待核验'))
        history=view.get('continuous_percentiles') or {}
        for i,(length,widget) in enumerate(((20,self.rank_value),(60,self.rank60_value)),3):
            widget.show()
            if not self.compact:self.captions[i].show()
            result=history.get('windows',{}).get(str(length),{});rank=result.get('percentile')
            missing=result.get('missing',[])
            label=(numeric(rank,1,suffix='%') if rank is not None else '缺映射' if any(r['reason']=='mapping_missing' for r in missing) else
                '缺分红' if any(r['reason']=='dividend_missing' for r in missing) else '缺收盘' if missing else 'T<5' if view.get('days') is not None and view['days']<5 else '待年化行情')
            widget.setText(label)
            color,strength=percentile_color(rank)
            widget.setStyleSheet(f'background:transparent;color:{color};font-size:{21 if self.compact else self.value_size}px;font-weight:{700 if strength>=.4 else 500};')
            widget.setToolTip(str(history.get('alias') or f'0{position}')+' · 去分红年化基差\n'+str(result.get('start') or '—')+' 至 '+str(result.get('end') or '—')+
                f"\n有效 {result.get('samples',0)}/{result.get('expected_eligible',length)}；规则排除 {result.get('excluded',0)} 日"+
                '\n'+(result.get('reason') or '等待当前连续档位分位资料，旧版具体合约分位不混用'))
            if missing:
                details=['\n缺项日期/标的：']
                for item in missing[:8]:
                    symbols=item.get('missing_symbols') or [item.get('symbol') or '待映射']
                    details.append(str(item.get('day') or '待日期')+'  '+', '.join(str(s) for s in symbols))
                if len(missing)>8:details.append('其余 '+str(len(missing)-8)+' 日见导出诊断')
                widget.setToolTip(widget.toolTip()+'\n'+'\n'.join(details))
            if self.compact:
                start=result.get('start');end=result.get('end')
                self.window_dates[length].setText((start[5:].replace('-','/')+'–'+end[5:].replace('-','/')) if start and end else '日期待核验')
                self.window_dates[length].setToolTip('参考窗口 '+str(start or '—')+' 至 '+str(end or '—'))
                self.means[length].setText(numeric(result.get('mean'),2,suffix='%'))
                self.medians[length].setText(numeric(result.get('median'),2,suffix='%'))
                for stat in (self.means[length],self.medians[length]):stat.setToolTip(widget.toolTip()+'\n年化基差的同窗统计')
        source_day=view.get('dividend_snapshot');pricing_day=view.get('pricing_day')
        carried=bool(source_day and pricing_day and source_day<pricing_day)
        self.dividend_note.setText('D '+numeric(view.get('dividend_points'),6)+'点 · '+
            ('沿用 ' if carried else '表内 ')+str(source_day or '待核验'))
        if view.get('display_saved'):self.dividend_note.setText('上次显示 '+stamp(view.get('source_at'))+' · '+self.dividend_note.text())
        if view.get('saved'):self.dividend_note.setText('基差沿用 '+clock(view.get('basis_source_at'))+' · '+self.dividend_note.text())
        self.dividend_note.setToolTip(input_summary(view)+'\n来源合约 '+str(view.get('dividend_source_contract') or '—')+
            '\n文件SHA '+str(view.get('dividend_file_sha256') or '—'))
        source=source_label(row)
        self.clock.setText(source)
        self.setToolTip('价格源 '+stamp(row.get('source_at'))+'\n接收 '+stamp(row.get('received_at'))+
            '\n基差源 '+stamp(view.get('basis_source_at'))+
            '\n分红 '+str(view.get('dividend_points'))+' 点；缓存日 '+str(view.get('dividend_snapshot') or '待核验')+
            ('\n沿用 '+view['dividend_inherited_from'] if view.get('dividend_inherited_from') else '')+
            '\n分红生效 '+str(view.get('dividend_effective_from') or '—')+'；精度 '+str(view.get('dividend_precision') or '—')+
            '\n'+str(view.get('percentile_start') or '—')+' 至 '+str(view.get('percentile_end') or '—'))


class VolumeDistribution(QWidget):
    def __init__(self):
        super().__init__();self.rows=[];self.reason='待四个到期合约的有效成交数据';self.setMinimumHeight(90)
    def render(self,rows,reason):
        self.rows=rows;self.reason=reason;self.setToolTip('\n'.join(SLOTS[r['slot']]+' '+numeric(r['share_pct'],1,suffix='%') for r in rows) or reason);self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            p.setPen(QColor(MUTED));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.reason);return
        x=0;available=max(0,self.width()-3*(len(self.rows)-1))
        from PySide6.QtGui import QFont
        for row in self.rows:
            width=available*row['share_pct']/100;color=COLORS[row['slot']]
            p.setBrush(QColor(color));p.setPen(Qt.PenStyle.NoPen);p.drawRoundedRect(QRectF(x,12,width,62),4,4)
            if width>=20:
                size=min(21,max(10,int((width-6)/2)))
                font=QFont(p.font());font.setPixelSize(size);font.setBold(True);p.setFont(font)
                p.setPen(QColor('#ffffff' if row['slot']<2 else ACCENT))
                percentage=numeric(row['share_pct'],0 if width<70 else 1,suffix='%')
                p.drawText(QRectF(x+2,14,max(0,width-4),58),Qt.AlignmentFlag.AlignCenter,SLOTS[row['slot']]+'\n'+percentage)
            x+=width+3



class FuturesOverviewPage(ScrollPage):
    def __init__(self):
        super().__init__();self.selected_root='IF';self.rows=[];self.indices=[];self.groups={};self.cards={}
        self.products={}
        for root,(_,name,_) in UNDERLYINGS.items():
            button=QPushButton(root+' · '+name);button.setCheckable(True);button.setMinimumHeight(39)
            button.clicked.connect(lambda _,r=root:self.select(r));self.products[root]=button
        self.box.addWidget(FlowGrid(list(self.products.values()),4,220,self.body))
        head=QHBoxLayout();self.spot=lab('现货 —',25,ACCENT,True);self.note=lab('连续档位 · 年化基差20 / 60日分位',16,MUTED)
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight);head.addWidget(self.spot,3);head.addWidget(self.note,2);self.box.addLayout(head)
        self.contract_cards=[FuturesCard(self.body) for _ in range(4)]
        self.box.addWidget(FlowGrid(self.contract_cards,4,290,self.body))
        self.term=Panel('年化期限结构','按真实到期日');self.curve=pg.PlotWidget(background=PANEL)
        self.curve.setMinimumWidth(0);self.curve.setMinimumHeight(225);self.curve.setMaximumHeight(240)
        self.curve.setMenuEnabled(False);self.curve.setMouseEnabled(x=False,y=False);self.curve.hideButtons()
        self.curve.showGrid(y=True,alpha=.13);self.curve.getAxis('left').setLabel('%');self.curve.getAxis('left').enableAutoSIPrefix(False)
        self.term.box.addWidget(self.curve);self.empty_curve=lab('待有效同步期现报价与到期日',17,MUTED)
        self.empty_curve.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty_curve.setMinimumHeight(225);self.term.box.addWidget(self.empty_curve)
        self.changes=Panel('盘中定价变化','按具体合约')
        self.change_values=[]
        for title in ('近月 − 次月价差','近5分钟基差变化'):
            line=QHBoxLayout();line.addWidget(lab(title,18,MUTED),1);value=lab('—',27,ACCENT,True)
            value.setAlignment(Qt.AlignmentFlag.AlignRight);line.addWidget(value,1);self.changes.box.addLayout(line);self.change_values.append(value)
        self.changes.box.addWidget(lab('分位：00 / 01 / 02 / 03年化前窗',17,ACCENT,True))
        self.changes.box.addWidget(lab('缺历史只影响分位，最新行情独立显示',16,MUTED))
        self.box.addWidget(Split(self.term,self.changes,(2,1)))
        self.volumes=Panel('成交分布与昨日持仓','昨日持仓待可靠日频数据')
        self.distribution=VolumeDistribution();self.volumes.box.addWidget(self.distribution)
        self.more=QPushButton('量仓明细 ›');self.more.setCheckable(True);self.volumes.box.addWidget(self.more,alignment=Qt.AlignmentFlag.AlignRight)
        self.volume_table=table(['合约','累计成交（手）','成交占比','昨日持仓','持仓日期'],190)
        self.volume_table.hide();self.more.toggled.connect(self.volume_table.setVisible);self.volumes.box.addWidget(self.volume_table)
        self.box.addWidget(self.volumes);self.footer=lab('实际合约展示 · 00/01/02/03按历日换月；20/60交易日前窗，当前日排除，已知T<5另列排除',15,MUTED);self.footer.hide()

    def select(self,root):
        self.selected_root=root;self.show_group()

    def render(self,rows,indices=None,groups=None):
        self.rows=rows;self.indices=indices or [];self.groups=groups or {};self.show_group()

    def show_group(self):
        root=self.selected_root
        for key,button in self.products.items():button.setChecked(key==root)
        rows=sorted((r for r in self.rows if r['root']==root),key=lambda r:r.get('slot',99))
        latest=max((r['dividend_snapshot'] for r in self.rows if r.get('dividend_snapshot')),default=None)
        self.note.setText('最新分红表 '+str(latest or '待核验')+' · 20 / 60日分位')
        self.visible_rows=rows;self.cards={}
        spot=next((r for r in self.indices if r['root']==root),{})
        self.spot.setText('现货 '+numeric(spot.get('price'))+'  '+numeric(spot.get('change_pct'),signed=True,suffix='%'))
        self.spot.setToolTip('行情源 '+stamp(spot.get('source_at'))+'\n'+str(spot.get('status') or '等待行情'))
        by_slot={r.get('slot'):r for r in rows}
        for i,card in enumerate(self.contract_cards):
            row=by_slot.get(i,{});card.render(row,i)
            if row.get('symbol'):self.cards[row['symbol']]=card
        self.curve.clear();self.curve_points=term_points(rows)
        if self.curve_points:
            xs=[r['days'] for r in self.curve_points];ys=[r['annual_pct'] for r in self.curve_points]
            ticks=[(r['days'],SLOTS[min(3,r['slot'])]+' · '+str(r['days'])+'天') for r in self.curve_points]
            connect=np.array([self.curve_points[i+1]['slot']==r['slot']+1 if i+1<len(self.curve_points) else False
                              for i,r in enumerate(self.curve_points)],dtype=bool)
            brushes=[pg.mkBrush(None if r['saved'] else ACCENT) for r in self.curve_points]
            pens=[pg.mkPen(MUTED if r['saved'] else ACCENT,width=2) for r in self.curve_points]
            self.curve.plot(xs,ys,pen=pg.mkPen(ACCENT,width=3),symbol='o',symbolSize=7,symbolBrush=brushes,symbolPen=pens,connect=connect)
            self.curve.getAxis('bottom').setTicks([ticks]);self.curve.enableAutoRange(axis='y')
            span=max(max(xs)-min(xs),30)
            self.curve.setXRange(min(xs)-span*.1,max(xs)+span*.1,padding=0)
        self.curve.setVisible(bool(self.curve_points));self.empty_curve.setVisible(not self.curve_points)
        self.term.note.setText(term_description(self.curve_points));self.curve.setToolTip(term_tooltip(self.curve_points))
        group=self.groups.get(root,{})
        self.changes.title.setText('盘中定价变化' if group.get('basis_kind')=='realtime' else '参考定价变化')
        for widget,key in zip(self.change_values,('calendar_points','basis_change_5m')):
            value=group.get(key);put(widget,numeric(value,2,True,'点'),color=ink(value),size=27,bold=True)
        self.change_values[0].setToolTip('近月−次月原始点差；两合约与现货需同步')
        self.change_values[1].setToolTip(group.get('five_minute_reason') or '待五分钟前同步期现观测')
        distribution=group.get('distribution',[]);reason=group.get('distribution_reason') or '待四个到期合约的完整有效成交数据'
        self.distribution.render(distribution,reason);shares={r['symbol']:r['share_pct'] for r in distribution}
        self.volume_table.setRowCount(len(rows));self.volume_table.clearContents()
        count=sum(r.get('yesterday_open_interest') is not None for r in rows)
        self.volumes.note.setText('昨日持仓 '+str(count)+'/'+str(len(rows))+' 合约已核验' if count else '昨日持仓待可靠日频数据')
        for i,row in enumerate(rows):
            cell(self.volume_table,i,0,row['symbol'].replace('.CFE',''))
            cell(self.volume_table,i,1,numeric(row.get('volume'),0))
            cell(self.volume_table,i,2,numeric(shares.get(row['symbol']),1,suffix='%'))
            cell(self.volume_table,i,3,numeric(row.get('yesterday_open_interest'),0),TEXT if row.get('yesterday_open_interest') is not None else MUTED)
            cell(self.volume_table,i,4,row.get('yesterday_oi_date') or '待核验',MUTED)
