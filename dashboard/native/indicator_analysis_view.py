"""One-root, four-chart indicator page; widgets never acquire market data."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QSignalBlocker, QEvent, QTimer
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QGridLayout,
    QScrollArea, QFrame, QComboBox, QSpinBox, QCheckBox, QPushButton, QToolTip, QSizePolicy)

from dashboard.marketdata.indicator_analysis import selection, chart_selections, finite
from .overview_pages import Panel, FlowGrid, lab, numeric
from .theme import ACCENT, MUTED, TEXT, PANEL, BORDER, THEME

PRIMARY = '#1766ad' if THEME == 'public' else '#94b8d5'
RAW = '#d28a35' if THEME == 'public' else '#e6c27e'
AVG = '#18867f' if THEME == 'public' else '#7dccb1'
MEDIAN = '#8b67af' if THEME == 'public' else '#c0a5da'


def seconds(day):
    return pd.Timestamp(day, tz='UTC').timestamp()


def display_policy(value):
    """Present even older frozen snapshots with the current field names."""
    return str(value or '').replace('t_z','指标计算窗口').replace('t_w','坐标轴窗口')


def chart_data(rows):
    x = np.array([seconds(r['day']) for r in rows], dtype=float)
    y = np.array([r['value'] if finite(r.get('value')) else np.nan for r in rows], dtype=float)
    connect = np.zeros(len(rows), dtype=bool)
    for i in range(len(rows)-1):
        connect[i] = bool(np.isfinite(y[i]) and np.isfinite(y[i+1]) and rows[i]['symbols'] == rows[i+1]['symbols'])
    return x, y, connect


class IndicatorChart(Panel):
    def __init__(self, title, key, *, overlay=False):
        super().__init__()
        self.key=key;self.overlay=overlay;self.result=None;self.reference_lines={}
        head=QHBoxLayout();head.setSpacing(4);self.heading=lab(title,19,ACCENT,True);head.addWidget(self.heading,1)
        self.unit=lab('点' if overlay else '% / 年',13,MUTED);self.unit.setFixedWidth(42)
        self.unit.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred);head.addWidget(self.unit)
        self.window_spin=QSpinBox();self.window_spin.setRange(10,365);self.window_spin.setValue(90)
        self.stats=QSpinBox();self.stats.setRange(2,120);self.stats.setValue(20)
        self.auto=QCheckBox('自动');self.auto.setChecked(True);self.stats.setEnabled(False)
        self.window_spin.setToolTip('坐标轴窗口：自然日，包含定价日')
        self.stats.setToolTip('指标计算窗口：定价日之前的交易日')
        self.auto.setToolTip('自动取坐标轴窗口的一半并向下取整，最多20个交易日；取消后可手动设置指标计算窗口')
        self.window_caption=lab('坐标轴窗口',13,MUTED);self.stats_caption=lab('指标计算窗口',13,MUTED)
        for caption,control in ((self.window_caption,self.window_spin),(self.stats_caption,self.stats)):
            caption.setWordWrap(False);caption.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred)
            control.setFixedWidth(64);control.setMinimumHeight(36);head.addWidget(caption);head.addWidget(control)
        head.addWidget(self.auto)
        self.box.addLayout(head)
        self.content=QBoxLayout(QBoxLayout.Direction.LeftToRight);self.content.setSpacing(12);self.box.addLayout(self.content,1)
        self.plot=pg.PlotWidget(background=PANEL,axisItems={'bottom':pg.DateAxisItem(utcOffset=0)})
        self.plot.setMinimumWidth(0);self.plot.setMinimumHeight(145)
        self.plot.setMenuEnabled(False);self.plot.hideButtons();self.plot.showGrid(y=True,alpha=.12)
        self.plot.setMouseEnabled(x=False,y=False)
        self.plot.getPlotItem().setContentsMargins(0,0,8,0)
        for axis in ('left','bottom'):
            a=self.plot.getAxis(axis);a.setTextPen(MUTED);a.setPen(BORDER);a.setTickFont(QFont('Segoe UI',9));a.enableAutoSIPrefix(False)
        self.plot.getAxis('left').setWidth(58)
        self.plot.addLegend(offset=(8,2),labelTextColor=MUTED,labelTextSize='10pt',horSpacing=12)
        self.plot.plotItem.legend.setColumnCount(2)
        self.content.addWidget(self.plot,1)
        self.stats_widget=QWidget();self.stats_widget.setMinimumWidth(116)
        self.stats_box=QGridLayout(self.stats_widget);self.stats_box.setContentsMargins(0,0,0,0);self.stats_box.setVerticalSpacing(1)
        self.metrics={}
        for i,(key,label) in enumerate((('z','Z 值'),('percentile','分位点'),('median','中位数'),('mean','均值'))):
            caption=lab(label,11,MUTED);value=lab('—',20,TEXT,True)
            self.metrics[key]=(caption,value)
            self.stats_box.addWidget(caption,2*i,0);self.stats_box.addWidget(value,2*i+1,0)
        self.content.addWidget(self.stats_widget)
        self.footer=lab('等待本地历史',12,MUTED);self.box.addWidget(self.footer)
        self.setMinimumHeight(254)
        self.hover=pg.SignalProxy(self.plot.scene().sigMouseMoved,rateLimit=15,slot=self.hovered)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        below=self.width()<560 or self.window().width()<1000
        self.content.setDirection(QBoxLayout.Direction.TopToBottom if below else QBoxLayout.Direction.LeftToRight)
        for i,(caption,value) in enumerate(self.metrics.values()):
            self.stats_box.addWidget(caption,0 if below else 2*i,i if below else 0)
            self.stats_box.addWidget(value,1 if below else 2*i+1,i if below else 0)

    def clear_result(self, text='正在读取所选窗口…'):
        self.result=None;self.plot.clear();self.reference_lines={}
        for _,value in self.metrics.values():value.setText('—')
        self.footer.setText(text)

    def render(self,result,*,stat_key='adjusted',references=True,draw=True):
        selected_key=stat_key if self.overlay else self.key
        series=result['series'];selected=series[selected_key];stats=selected['statistics']
        if draw:
            self.result=result;self.stat_key=selected_key
            self.plot.clear();self.reference_lines={}
            for key in (('raw','adjusted') if self.overlay else (self.key,)):
                rows=series[key]['rows'];x,y,connect=chart_data(rows)
                color=RAW if key=='raw' else PRIMARY
                title='绝对基差 F−S' if key=='raw' else '去分红基差' if key=='adjusted' else '年化去分红'
                self.plot.plot(x,y,connect=connect,pen=pg.mkPen(color,width=1.9 if key=='raw' else 2.5),name=title)
                current=series[key]['current']
                if finite(current.get('value')):
                    self.plot.plot([seconds(current['day'])],[current['value']],pen=None,symbol='o',symbolSize=11,
                                   symbolBrush=color,symbolPen=pg.mkPen(PANEL,width=2))
            scope=(result.get('charts') or {}).get(self.key,result)
            left,right=seconds(scope['start']),seconds(scope['end'])
            if references:
                for key,color,title in (('mean',AVG,'均值'),('median',MEDIAN,'中位数')):
                    if finite(stats.get(key)):
                        self.reference_lines[key]=self.plot.plot([left,right],[stats[key],stats[key]],
                            pen=pg.mkPen(color,width=1.3,style=Qt.PenStyle.DashLine),name=title)
            self.plot.setXRange(left,right,padding=.01)
            self.plot.enableAutoRange(axis='y',enable=True)
            self.plot.getViewBox().setDefaultPadding(.14)
        for key,(_,value) in self.metrics.items():
            value.setText(numeric(stats.get(key),1 if key=='percentile' else 2,suffix='%' if key=='percentile' else ''))
        latest=selected['current'];n=stats['samples'];requested=stats['requested']
        title=('去分红' if selected_key=='adjusted' else '绝对')+'基差 · ' if self.overlay else ''
        now=numeric(latest.get('value'),2,suffix='' if self.overlay else '%')
        reasons={'index_close_missing':'指数收盘缺失','future_close_missing':'期货收盘缺失',
                 'dividend_missing_or_conflict':'分红缺失或冲突','mapping_missing':'合约映射缺失','T_LT_5':'临期T<5'}
        reason=latest.get('reason') if not finite(latest.get('value')) else stats.get('reason')
        explanation=(' · '+reasons.get(reason,reason)) if reason else ''
        self.footer.setText(f"{title}最新 {now} · 样本 {n}/{requested} · 排除 {len(stats['excluded_dates'])}日 · 缺 {len(stats['missing'])}日"+explanation)
        detail=[display_policy(result['statistics_policy']),f"参考 {stats['start']} 至 {stats['end']}",
                '排除T<5：'+(', '.join(stats['excluded_dates']) or '无'),
                '缺项：'+('; '.join(r['day']+' '+r['reason'] for r in stats['missing']) or '无'),
                '历史D暂0：'+(', '.join(stats['zero_dividend_dates']) or '无'),
                'HTTP日期推定：'+(', '.join(stats['http_session_inferred_dates']) or '无'),
                '当前：'+str(latest.get('reason') or latest.get('source_at') or result['pricing_day'])]
        self.footer.setToolTip('\n'.join(detail))
        self.stats_widget.setToolTip('\n'.join(detail))
        visible=[r for r in selected['rows'] if finite(r.get('value'))]
        if draw and not visible:
            empty=pg.TextItem('此窗口暂无有效数据',color=MUTED,anchor=(.5,.5))
            self.plot.addItem(empty);empty.setPos((left+right)/2,0);self.plot.setYRange(-1,1,padding=0)

    def hovered(self,event):
        if self.result is None:return
        pos=event[0]
        if not self.plot.sceneBoundingRect().contains(pos):return
        x=self.plot.getViewBox().mapSceneToView(pos).x()
        rows=self.result['series'][self.stat_key]['rows']
        if not rows:return
        row=min(rows,key=lambda r:abs(seconds(r['day'])-x))
        lines=[row['day']+' · '+' / '.join(row['symbols']),
               numeric(row.get('value'),4)+(' 点' if self.overlay else '% / 年')]
        inputs=row.get('inputs',{})
        if inputs:
            lines.append('S='+numeric(inputs.get('S'),4))
            for leg in inputs.get('legs',[]):
                lines.append(str(leg['symbol'])+' F='+numeric(leg['F'],4)+' D='+numeric(leg['D'],4)+' T='+str(leg['T']))
                record=leg.get('dividend',{})
                lines.append('D来源 '+str(record.get('source_snapshot') or record.get('source_business_date') or record.get('source_kind') or '缺失'))
        if row.get('reason'):lines.append(row['reason'])
        if row.get('zero_dividend_symbols'):lines.append('历史缺D暂0：'+', '.join(row['zero_dividend_symbols']))
        if row.get('source_at'):lines.append('源时 '+row['source_at'])
        QToolTip.showText(QCursor.pos(),'\n'.join(lines),self.plot)


class IndicatorAnalysisPage(QWidget):
    changed=Signal()
    history_requested=Signal(object)

    def __init__(self,model):
        super().__init__();self.model=model;self.active=False;self.result=None;self._ready=False
        self._last_draw=None;self._timer_draws=[]
        outer=QVBoxLayout(self);outer.setContentsMargins(8,12,8,4);outer.setSpacing(8)
        self.controls=Panel();outer.addWidget(self.controls)
        self.root=QComboBox()
        for root,title in (('IF','沪深300'),('IH','上证50'),('IC','中证500'),('IM','中证1000')):self.root.addItem(root+' · '+title,root)
        self.slot=QComboBox()
        for i,title in enumerate(('00 · 当月','01 · 次月','02 · 季月','03 · 远季')):self.slot.addItem(title,i)
        self.view=QComboBox()
        for title,key in (('四图同屏','all'),('简单基差','basis'),('跨期','calendar')):self.view.addItem(title,key)
        fields=[]
        for title,control in (('品种',self.root),('基差档位',self.slot),('查看',self.view)):
            field=QWidget();box=QVBoxLayout(field);box.setContentsMargins(0,0,0,0);box.setSpacing(2)
            box.addWidget(lab(title,12,MUTED));box.addWidget(control);control.setMinimumHeight(36);fields.append(field)
        self.controls.box.addWidget(FlowGrid(fields,3,150,self.controls))
        actions=QHBoxLayout();self.controls.box.addLayout(actions)
        self.references=QCheckBox('均值 / 中位数虚线');self.references.setChecked(True);actions.addWidget(self.references)
        self.overlay=QComboBox();self.overlay.addItem('叠加图统计 · 去分红','adjusted');self.overlay.addItem('叠加图统计 · 绝对','raw');actions.addWidget(self.overlay)
        actions.addStretch()
        self.history=QPushButton('补齐所选窗口');actions.addWidget(self.history)
        self.history.setToolTip('使用原有本地 → HTTP昨收 → DDB流程，覆盖四图所需最长窗口；需等待安全排空')
        status=QHBoxLayout();self.note=lab('选择一个品种查看；指标计算不含定价日，参考线横跨坐标轴窗口。',13,MUTED)
        self.draw_clock=lab('图像等待更新 · 30秒重画',12,MUTED);self.draw_clock.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        status.addWidget(self.note,3);status.addWidget(self.draw_clock,2);outer.addLayout(status)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);outer.addWidget(self.scroll,1)
        self.scroll.viewport().installEventFilter(self)
        self.body=QWidget();self.grid=QGridLayout(self.body);self.grid.setContentsMargins(0,0,4,0);self.grid.setSpacing(10)
        self.scroll.setWidget(self.body)
        self.charts={}
        for key,title in (('adjusted','绝对基差 ＋ 去分红基差'),('calendar_03_02','03 − 02 · 年化去分红价差'),
                          ('annual','去分红年化基差'),('calendar_02_01','02 − 01 · 年化去分红价差')):
            self.charts[key]=IndicatorChart(title,key,overlay=key=='adjusted')
        self.window=self.charts['adjusted'].window_spin;self.stats=self.charts['adjusted'].stats;self.auto=self.charts['adjusted'].auto
        self.arrangement=None
        self.restore()
        for control in (self.root,self.slot):control.currentIndexChanged.connect(self.inputs_changed)
        for key,chart in self.charts.items():
            chart.window_spin.valueChanged.connect(lambda _,k=key:self.chart_changed(k))
            chart.stats.valueChanged.connect(lambda _,k=key:self.chart_changed(k))
            chart.auto.toggled.connect(lambda _,k=key:self.chart_changed(k))
        self.view.currentIndexChanged.connect(self.presentation_changed);self.overlay.currentIndexChanged.connect(self.presentation_changed);self.references.toggled.connect(self.presentation_changed)
        self.history.clicked.connect(lambda:self.history_requested.emit(self.request()))
        self.draw_timer=QTimer(self);self.draw_timer.setInterval(30000);self.draw_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.draw_timer.timeout.connect(lambda:self.redraw(reason='timer'))
        self._ready=True;self.frozen=False;self.set_active(False);self.arrange()

    def request(self):
        base=selection(self.root.currentData(),self.slot.currentData(),self.window.value(),self.stats.value())
        charts={key:dict(window=chart.window_spin.value(),stats=chart.stats.value()) for key,chart in self.charts.items()}
        if any(value!=dict(window=base['window'],stats=base['stats']) for value in charts.values()):base['charts']=charts
        return base

    def set_active(self,active):
        was_active=self.active
        self.active=active
        self.model.indicator_analysis_request=self.request() if active and not getattr(self,'frozen',False) else None
        if hasattr(self,'draw_timer'):
            if active and not self.frozen:
                self.draw_timer.start()
                if not was_active and self.result:self.redraw()
            else:self.draw_timer.stop()

    def freeze(self,result):
        self.frozen=True;self._ready=False
        controls=(self.root,self.slot,*(control for chart in self.charts.values() for control in (chart.window_spin,chart.stats,chart.auto)))
        blockers=[QSignalBlocker(c) for c in controls]
        request=result['selection']
        self.root.setCurrentIndex(self.root.findData(request['root']));self.slot.setCurrentIndex(self.slot.findData(request['slot']))
        for key,choice in chart_selections(request).items():
            chart=self.charts[key];chart.window_spin.setValue(choice['window']);chart.stats.setValue(choice['stats']);chart.auto.setChecked(False)
        for control in controls:control.setEnabled(False)
        del blockers
        self.history.hide();self.set_active(False);self.render(result)

    def chart_changed(self,key):
        chart=self.charts[key]
        if chart.auto.isChecked():
            with QSignalBlocker(chart.stats):chart.stats.setValue(min(20,chart.window_spin.value()//2))
        chart.stats.setEnabled(not chart.auto.isChecked())
        self.inputs_changed()

    def inputs_changed(self,*_):
        self.result=None
        for chart in self.charts.values():chart.clear_result()
        self.note.setText('读取 '+self.root.currentData()+' 的逐日实际合约与所选窗口…')
        self.set_active(self.active);self.save();self.changed.emit()

    def presentation_changed(self,*_):
        self.arrange();self.save()
        if self.result:self.render(self.result,force=True)

    def resizeEvent(self,event):
        super().resizeEvent(event);self.arrange()

    def eventFilter(self,obj,event):
        if hasattr(self,'scroll') and obj is self.scroll.viewport() and event.type()==QEvent.Type.Resize:
            QTimer.singleShot(0,self.arrange)
        return super().eventFilter(obj,event)

    def arrange(self):
        if not hasattr(self,'charts'):return
        mode=self.view.currentData();keys=[k for k in self.charts if mode=='all' or (k.startswith('calendar') == (mode=='calendar'))]
        columns=2 if self.width()>=1200 else 1
        rows=(len(keys)+columns-1)//columns
        available=max(1,self.scroll.viewport().height())
        height=max(254,(available-10*(rows-1))//rows) if columns==2 else 340 if self.width()<1000 else 360
        arrangement=(tuple(keys),columns,height)
        if self.arrangement==arrangement:return
        self.arrangement=arrangement
        while self.grid.count():self.grid.takeAt(0)
        for column in range(2):self.grid.setColumnStretch(column,1 if column<columns else 0)
        for key,chart in self.charts.items():
            chart.setFixedHeight(height);chart.setVisible(key in keys)
        for i,key in enumerate(keys):self.grid.addWidget(self.charts[key],i//columns,i%columns)

    def render(self,result,*,force=False):
        if result is None:return
        try:
            if chart_selections(result.get('selection') or {})!=chart_selections(self.request()):return
        except (TypeError,ValueError,KeyError,AttributeError):return
        if result.get('error'):
            self.result=None;self.note.setText('指标窗口暂不可用：'+result['error'])
            for chart in self.charts.values():chart.clear_result('窗口不可用；原概览保持可读')
            return
        first=self.result is None
        self.result=result
        mode='实时末点' if result['mode']=='realtime' else '收盘参考'
        dates=[r.get('source_at') for r in (v['current'] for v in result['series'].values()) if r.get('source_at')]
        stamp=pd.Timestamp(max(dates)).tz_convert('Asia/Shanghai').strftime('%m-%d %H:%M:%S') if dates else result['pricing_day']+' · 当前点缺项'
        fallback=' · 最新完成日 '+result['completed_target']+' 收盘待补' if result.get('reference_fallback') else ''
        reference=('各图独立窗口' if result.get('charts') else '参考 '+result['reference_days'][0]+' 至 '+result['reference_days'][-1])
        self.note.setText(f"{self.root.currentData()} · {mode} {stamp}{fallback} · {reference}")
        self.note.setToolTip(result['mapping_policy']+'\n'+display_policy(result['statistics_policy'])+'\n历史读取起点 '+result['history_start'])
        for chart in self.charts.values():chart.render(result,stat_key=self.overlay.currentData(),references=self.references.isChecked(),draw=False)
        if first or force:self.redraw()

    def redraw(self,*,reason='manual'):
        if self.result is None:return
        for chart in self.charts.values():chart.render(self.result,stat_key=self.overlay.currentData(),references=self.references.isChecked())
        at=datetime.now(ZoneInfo('Asia/Shanghai'))
        self.draw_clock.setText('图像更新 '+at.strftime('%H:%M:%S')+' · 30秒重画；数值随行情计算更新')
        from dashboard.marketdata.indicator_analysis import summary
        safe=summary(self.result)
        event=dict(draw_at=at.isoformat(),reason=reason,selection=safe.get('selection'),mode=safe.get('mode'),
                   calculation_at=safe.get('as_of'),pricing_day=safe.get('pricing_day'),series={})
        for key,channel in safe['series'].items():
            current=channel['current'];stats=channel['statistics']
            event['series'][key]=dict(source_at=current.get('source_at'),current=current.get('value'),
                                      z=stats.get('z'),percentile=stats.get('percentile'))
        self._last_draw=event
        if reason=='timer':self._timer_draws=(self._timer_draws+[event])[-3:]

    def draw_evidence(self):
        return dict(active=self.active,frozen=self.frozen,interval_ms=self.draw_timer.interval(),
                    last_draw=self._last_draw,timer_draws=list(self._timer_draws))

    def save(self):
        if not self._ready:return
        from dashboard.marketdata.bars import _atomic_bytes, _json_bytes
        preference=dict(**self.request(),automatic=self.auto.isChecked(),view=self.view.currentData(),
                        overlay=self.overlay.currentData(),references=self.references.isChecked(),
                        chart_settings={key:dict(window=chart.window_spin.value(),stats=chart.stats.value(),automatic=chart.auto.isChecked())
                                        for key,chart in self.charts.items()})
        try:_atomic_bytes(Path(self.model.local_root)/'indicator_ui.json',_json_bytes(preference))
        except OSError:self.note.setToolTip('显示偏好暂未保存')

    def restore(self):
        try:
            p=json.loads((Path(self.model.local_root)/'indicator_ui.json').read_text(encoding='utf8'))
            request=selection(p['root'],p['slot'],p['window'],p['stats'])
            for control,key in ((self.root,'root'),(self.slot,'slot')):control.setCurrentIndex(control.findData(request[key]))
            settings=p.get('chart_settings') if isinstance(p.get('chart_settings'),dict) else {}
            for key,chart in self.charts.items():
                values=settings.get(key,{}) if isinstance(settings.get(key,{}),dict) else {}
                try:choice=selection(request['root'],request['slot'],values.get('window',request['window']),values.get('stats',request['stats']))
                except ValueError:choice=request
                chart.window_spin.setValue(choice['window']);chart.stats.setValue(choice['stats'])
                chart.auto.setChecked(bool(values.get('automatic',p.get('automatic',True))))
                if chart.auto.isChecked():chart.stats.setValue(min(20,chart.window_spin.value()//2))
                chart.stats.setEnabled(not chart.auto.isChecked())
            for control,key in ((self.view,'view'),(self.overlay,'overlay')):
                index=control.findData(p.get(key))
                if index>=0:control.setCurrentIndex(index)
            self.references.setChecked(bool(p.get('references',True)))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
