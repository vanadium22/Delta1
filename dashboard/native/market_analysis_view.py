"""Large on-demand query page; no acquisition starts on construction or repaint."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QDateTime, QSignalBlocker
from PySide6.QtWidgets import (QHBoxLayout,QGridLayout,QLineEdit,QComboBox,QDateTimeEdit,
    QPushButton,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView)

from index_futures_basis.security_model import SecurityQuery,FIELDS,VOLUME_UNITS,AMOUNT_UNITS,calculate
from index_futures_basis.security_data import export_result
from .market_analysis import execute,QueryCancellation,safe_error
from .overview_pages import ScrollPage,Panel,lab,FlowGrid,numeric
from .theme import ACCENT,MUTED,TEXT,PANEL,CHART_COLORS


class QuerySignals(QObject):
    completed=Signal(object)
    failed=Signal(object)
    progress=Signal(str)


class QueryWorker(QRunnable):
    def __init__(self,query,config,root,mode,cancel,*,runner=execute):
        super().__init__();self.query=query;self.config=config;self.root=root;self.mode=mode;self.cancel=cancel
        self.runner=runner;self.signals=QuerySignals()

    def run(self):
        try:
            value=self.runner(self.query,self.config,self.root,mode=self.mode,cancel=self.cancel,progress=self.signals.progress.emit)
            self.signals.completed.emit(value)
        except Exception as exc:
            result=safe_error(exc,getattr(exc,'query_stage',None));result['cancelled']=self.cancel.is_set() or result['cancelled']
            self.signals.failed.emit(result)


class MarketAnalysisPage(ScrollPage):
    state_changed=Signal()

    def __init__(self,model,*,runner=execute):
        super().__init__();self.model=model;self.runner=runner;self.busy=False;self.result=None;self.cancel=None
        self.source_active=None;self.allow_network=True;self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.inputs=Panel('行情分析','按需查询 · 自动复用缓存');self.box.addWidget(self.inputs)
        form=QGridLayout();self.inputs.box.addLayout(form)
        self.code=QLineEdit();self.code.setPlaceholderText('600519.SH / 510300.SH / IF00.CFE');self.code.setMinimumHeight(40)
        self.frequency=QComboBox()
        for title,value in [('1分钟','1m'),('5分钟','5m'),('15分钟','15m'),('30分钟','30m'),('60分钟','60m'),('日线','1d'),('最新单值','snapshot')]:self.frequency.addItem(title,value)
        self.mode=QComboBox();self.mode.addItem('查询并复用缓存','wind');self.mode.addItem('只读本地缓存','offline')
        form.addWidget(lab('标的',18,MUTED),0,0);form.addWidget(self.code,0,1,1,3)
        form.addWidget(self.frequency,0,4);form.addWidget(self.mode,0,5)
        self.start=QDateTimeEdit();self.end=QDateTimeEdit()
        for control in (self.start,self.end):control.setDisplayFormat('yyyy-MM-dd HH:mm');control.setCalendarPopup(True);control.setMinimumHeight(40)
        today=self.today_button=QPushButton('今日');today.clicked.connect(self.today)
        form.addWidget(lab('开始',18,MUTED),1,0);form.addWidget(self.start,1,1,1,2)
        form.addWidget(lab('结束',18,MUTED),1,3);form.addWidget(self.end,1,4);form.addWidget(today,1,5)
        self.fields={}
        for key,label in FIELDS.items():
            control=QCheckBox(label);control.setChecked(key=='close');self.fields[key]=control
        self.inputs.box.addWidget(FlowGrid(list(self.fields.values()),7,120,self.inputs))
        self.twap=QCheckBox('TWAP · 分钟采样');self.twap.setChecked(True);self.vwap=QCheckBox('VWAP · 量额加权')
        self.volume_unit=QComboBox();self.amount_unit=QComboBox()
        for key,(title,_) in VOLUME_UNITS.items():self.volume_unit.addItem('成交量：'+title,key)
        for key,(title,_) in AMOUNT_UNITS.items():self.amount_unit.addItem('成交额：'+title,key)
        self.inputs.box.addWidget(FlowGrid([self.twap,self.vwap,self.volume_unit,self.amount_unit],4,240,self.inputs))
        actions=QHBoxLayout();self.inputs.box.addLayout(actions)
        self.search=QPushButton('查询并计算');self.search.clicked.connect(self.query)
        self.cancel_button=QPushButton('取消');self.cancel_button.clicked.connect(self.stop);self.cancel_button.setEnabled(False)
        self.export_button=QPushButton('导出CSV');self.export_button.clicked.connect(self.export);self.export_button.setEnabled(False)
        actions.addWidget(self.search);actions.addWidget(self.cancel_button);actions.addStretch();actions.addWidget(self.export_button)
        self.note=lab('默认今日；只查询已完成周期，午休不补造分钟。',16,MUTED);self.note.setTextFormat(Qt.TextFormat.PlainText);self.inputs.box.addWidget(self.note)
        self.metrics={};cards=[]
        for key,title in [('mean','均值'),('twap','TWAP · 有效分钟'),('vwap','VWAP · 成交加权')]:
            card=Panel(title);value=lab('—',32,ACCENT,True);detail=lab('',15,MUTED);card.box.addWidget(value);card.box.addWidget(detail)
            self.metrics[key]=(value,detail);cards.append(card)
        self.box.addWidget(FlowGrid(cards,3,240,self.body))
        self.price_panel=Panel('价格图像','');self.box.addWidget(self.price_panel)
        self.plot=pg.PlotWidget(background=PANEL);self.plot.setMinimumHeight(320);self.plot.setMinimumWidth(0)
        self.plot.setMenuEnabled(False);self.plot.showGrid(y=True,alpha=.15);self.plot.addLegend()
        self.plot.getAxis('left').enableAutoSIPrefix(False);self.price_panel.box.addWidget(self.plot)
        self.extra_plots={}
        for key,title in [('volume','成交量'),('amt','成交额'),('oi','持仓量')]:
            panel=Panel(title);plot=pg.PlotWidget(background=PANEL);plot.setMinimumHeight(220);plot.setMenuEnabled(False);plot.showGrid(y=True,alpha=.15)
            panel.box.addWidget(plot);self.box.addWidget(panel);panel.hide();self.extra_plots[key]=(panel,plot)
        self.raw_toggle=QPushButton('查看原始数据 / 统计');self.raw_toggle.setCheckable(True);self.box.addWidget(self.raw_toggle)
        self.raw=QTableWidget();self.raw.setMaximumHeight(300);self.raw.hide();self.raw_toggle.toggled.connect(self.raw.setVisible);self.box.addWidget(self.raw)
        self.today()
        self.code.textChanged.connect(self.input_changed);self.frequency.currentIndexChanged.connect(self.input_changed);self.mode.currentIndexChanged.connect(self.clear)
        self.start.dateTimeChanged.connect(self.clear);self.end.dateTimeChanged.connect(self.clear)
        for control in (self.volume_unit,self.amount_unit):control.currentIndexChanged.connect(self.recalculate)
        for control in (*self.fields.values(),self.twap,self.vwap):control.toggled.connect(self.recalculate)
        self.input_changed()

    def today(self):
        day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        self.start.setDateTime(QDateTime.fromString(day+' 09:30','yyyy-MM-dd HH:mm'))
        self.end.setDateTime(QDateTime.fromString(day+' 15:00','yyyy-MM-dd HH:mm'))

    def set_readonly(self):
        self.allow_network=False;self.mode.setCurrentIndex(1);self.mode.setEnabled(False)

    def lock_inputs(self,locked):
        for control in (self.code,self.frequency,self.mode,self.start,self.end,self.today_button,
                        *self.fields.values(),self.twap,self.vwap,self.volume_unit,self.amount_unit):
            control.setEnabled(not locked)
        if not locked:
            self.apply_policy()
            self.mode.setEnabled(self.allow_network)

    def input_changed(self,*_):
        self.clear()
        self.apply_policy()

    def apply_policy(self):
        try:kind=SecurityQuery(self.code.text(),'snapshot');future=kind.is_future;equity=kind.is_equity
        except ValueError:future=False;equity=False
        if future and self.frequency.currentData()!='1d':
            with QSignalBlocker(self.frequency):self.frequency.setCurrentIndex(self.frequency.findData('1d'))
        minute=self.frequency.currentData().endswith('m') and not future
        snapshot=self.frequency.currentData()=='snapshot'
        for control in (self.twap,self.vwap):
            enabled=minute if control is self.twap else equity and not snapshot
            previous=control.isEnabled();control.setEnabled(enabled)
            if not enabled:control.setChecked(False)
            elif not previous:control.setChecked(True)
        self.fields['oi'].setEnabled(future)
        if not future:self.fields['oi'].setChecked(False)
        for control in (self.volume_unit,self.amount_unit):control.setEnabled(not future)
        self.start.setEnabled(not snapshot);self.end.setEnabled(not snapshot)

    def draft(self):
        return SecurityQuery(self.code.text(),self.frequency.currentData(),tuple(k for k,w in self.fields.items() if w.isChecked()),
            self.start.dateTime().toString('yyyy-MM-dd HH:mm'),self.end.dateTime().toString('yyyy-MM-dd HH:mm'),
            self.twap.isChecked(),self.vwap.isChecked(),self.volume_unit.currentData(),self.amount_unit.currentData())

    def query(self):
        if self.busy:return
        try:query=self.draft()
        except ValueError as exc:self.note.setText(str(exc));return
        mode=self.mode.currentData() if self.allow_network else 'offline'
        self.clear();self.busy=True;self.search.setEnabled(False);self.cancel_button.setEnabled(True)
        self.lock_inputs(True)
        self.cancel=QueryCancellation();self.source_active='local';self.note.setText('正在读取所选窗口…')
        self.worker=QueryWorker(query,dict(self.model.config),self.model.local_root,mode,self.cancel,runner=self.runner)
        self.worker.signals.completed.connect(self.completed);self.worker.signals.failed.connect(self.failed);self.worker.signals.progress.connect(self.progress)
        self.pool.start(self.worker);self.state_changed.emit()

    def progress(self,text):
        if not self.busy:return
        self.source_active='wind' if self.mode.currentData()=='wind' and self.allow_network else 'local'
        self.note.setText('正在读取 '+self.code.text().strip().upper()+'…');self.state_changed.emit()

    def finish(self):
        # Restore controls before releasing busy so their policy signals cannot
        # recalculate or clear the just-completed request.
        self.lock_inputs(False)
        self.busy=False;self.source_active=None;self.search.setEnabled(True);self.cancel_button.setEnabled(False);self.state_changed.emit()

    def completed(self,result):
        self.finish()
        if self.cancel is not None and self.cancel.is_set():self.note.setText('已取消；完成的缓存批次保留。');return
        self.result=result;self.render_result()

    def failed(self,error):
        self.finish();self.clear()
        self.note.setText('已取消或达到查询时限；完成的缓存批次保留。' if error['cancelled'] else
            '查询未完成：'+error['stage']+' / '+error['error_type']+((' / ErrorCode '+str(error['error_code'])) if error.get('error_code') is not None else ''))
        from dashboard.marketdata.bars import _atomic_bytes,_json_bytes
        path=Path(self.model.local_root)/'analysis_data/last_error.json'
        try:_atomic_bytes(path,_json_bytes(error))
        except OSError:pass

    def stop(self):
        if self.cancel is not None:self.cancel.set()

    def clear(self,*_):
        if self.busy:return
        self.result=None;self.plot.clear();self.raw.setRowCount(0);self.export_button.setEnabled(False)
        self.plot.getAxis('bottom').setTicks([])
        self.note.setText('选择窗口后查询；默认今日，午休不补造分钟。');self.note.setToolTip('')
        for value,detail in self.metrics.values():value.setText('—');detail.setText('')
        for panel,plot in self.extra_plots.values():plot.clear();panel.hide()

    def recalculate(self,*_):
        if self.busy or self.result is None:return
        try:query=self.draft()
        except ValueError:return
        old=self.result.query
        if (query.code,query.frequency,query.start,query.end)!=(old.code,old.frequency,old.start,old.end):return
        if any(f not in self.result.frame for f in query.required_fields):
            self.clear();self.note.setText('所需字段未缓存，请重新查询补齐。');return
        self.result.query=query;self.result.summary=calculate(query,self.result.frame)
        self.result.metadata['query']=query.metadata()
        if not query.is_future:self.result.metadata['units']=dict(volume=query.volume_unit,amount=query.amount_unit,price='原始报价单位，不复权')
        self.render_result()

    def render_result(self):
        result=self.result;query=result.query;frame=result.frame
        primary=next((r for r in result.summary['statistics'] if r['field']==('close' if 'close' in query.fields else query.fields[0])),{})
        for key,(value,detail) in self.metrics.items():
            number=primary.get('mean') if key=='mean' else result.summary['metrics'].get(key)
            value.setText(numeric(number,4))
            counts=dict(n=primary.get('n',0),total=len(frame)) if key=='mean' else result.summary.get('metric_details',{}).get(key,{})
            detail.setText(('有效 '+str(counts.get('n',0))+'/'+str(counts.get('total',len(frame)))) if number is not None else str(counts.get('reason') or '未启用 / 无有效样本'))
        self.note.setText(query.code+' · '+str(result.metadata.get('name') or '')+' · '+str(result.metadata.get('source') or '')+
            ' · 截至 '+str(result.metadata.get('actual_end') or '无有效数据'))
        self.note.setToolTip('\n'.join([*result.metadata.get('notes',[]),*result.summary.get('notes',[])]))
        self.plot.clear()
        times=[pd.Timestamp(v) for v in frame.time]
        ticks=[(i,times[i].strftime('%m-%d %H:%M') if query.bar_minutes else times[i].strftime('%m-%d')) for i in sorted({0,len(frame)//4,len(frame)//2,3*len(frame)//4,len(frame)-1}) if 0<=i<len(frame)]
        self.plot.getAxis('bottom').setTicks([ticks])
        price_fields=[f for f in ('close','open','high','low') if f in query.fields or f=='close' and query.twap]
        for index,field in enumerate(price_fields):
            xs=[];ys=[]
            for i,value in enumerate(frame[field]):
                if i and query.bar_minutes and (times[i]-times[i-1]).total_seconds()>query.bar_minutes*60:xs.append(i-.25);ys.append(float('nan'))
                xs.append(i);ys.append(float(value) if pd.notna(value) else float('nan'))
            self.plot.plot(xs,ys,pen=pg.mkPen(CHART_COLORS[index%len(CHART_COLORS)],width=2),name=FIELDS[field],connect='finite')
        for key,color in [('twap',ACCENT),('vwap','#b27820')]:
            if (value:=result.summary['metrics'].get(key)) is not None:self.plot.addItem(pg.InfiniteLine(value,angle=0,pen=pg.mkPen(color,width=2,style=Qt.PenStyle.DashLine),label=key.upper()))
        for field,(panel,plot) in self.extra_plots.items():
            plot.clear();panel.setVisible(field in query.fields)
            if field not in query.fields:continue
            values=[(i,float(v)) for i,v in enumerate(frame[field]) if pd.notna(v)]
            plot.addItem(pg.BarGraphItem(x=[x for x,_ in values],height=[v for _,v in values],width=.8,brush=ACCENT))
            plot.getAxis('bottom').setTicks([ticks])
        columns=['time',*query.required_fields];self.raw.setColumnCount(len(columns));self.raw.setHorizontalHeaderLabels(['时刻',*[FIELDS[f] for f in query.required_fields]])
        self.raw.setRowCount(min(500,len(frame)));self.raw.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i,row in enumerate(frame.head(500).to_dict('records')):
            for j,key in enumerate(columns):self.raw.setItem(i,j,QTableWidgetItem(str(row[key]) if key=='time' else numeric(row[key],4)))
        self.raw.setToolTip('仅展示前500行；CSV导出包含全部所选窗口。');self.export_button.setEnabled(True)

    def export(self):
        if self.busy or self.result is None:return
        folder=Path(self.model.local_root)/'analysis_exports'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        try:export_result(self.result,folder);self.note.setText('已导出CSV：'+str(folder))
        except Exception as exc:self.note.setText('导出失败：'+type(exc).__name__)
