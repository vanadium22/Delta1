"""Edition-six desktop projection. Calculation stays in indicator_v6.Service."""
from html import escape
from pathlib import Path
import math
from PySide6.QtCore import Qt,Signal,QThreadPool,QTimer,QRunnable,QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QComboBox,QPushButton,QScrollArea,QFrame,QTextBrowser)
import numpy as np
import pyqtgraph as pg
from dashboard.indicator_v6.service import Service,CARDS,variants,CHOICE_LABELS,display,variant_label
from dashboard.indicator_v6.presentation import detail_html
from .theme import PANEL,TEXT,MUTED,ACCENT,BORDER,CHART_COLORS,STYLE,THEME


class Signals(QObject):
    done=Signal(object);failed=Signal(str)
class Job(QRunnable):
    def __init__(self,fn):super().__init__();self.fn=fn;self.signals=Signals()
    def run(self):
        try:self.signals.done.emit(self.fn())
        except Exception as exc:self.signals.failed.emit(str(exc))


class Axis(pg.AxisItem):
    def __init__(self,points):super().__init__('bottom');self.points=points;self.setStyle(tickFont=QFont('Microsoft YaHei UI',9))
    def tickStrings(self,values,scale,spacing):
        labels=[]
        for value in values:
            i=round(value)
            if abs(value-i)>.1 or not 0<=i<len(self.points):labels.append('');continue
            p=self.points[i];labels.append(p['timestamp'][11:16] if p['frequency']=='1m' else p['timestamp'][2:10])
        return labels


class Trend(QWidget):
    def __init__(self,result,fields):
        super().__init__();self.result=result;self.fields=fields;self.points=result['series'][fields[0]['key']]
        layout=QVBoxLayout(self);layout.setContentsMargins(12,10,12,10)
        self.setStyleSheet(f'Trend {{ background:{PANEL};border:1px solid {BORDER};border-radius:8px; }}')
        title=QLabel(('分钟观测' if fields[0]['frequency']=='1m' else '日频观测')+' · '+('%' if fields[0]['key']=='K' else result['units'][fields[0]['unit']]['label']));title.setStyleSheet('font-weight:600;font-size:15px');layout.addWidget(title)
        self.plot=pg.PlotWidget(axisItems={'bottom':Axis(self.points)},background=PANEL);self.plot.setMinimumHeight(230);self.plot.setMaximumHeight(280)
        self.plot.showGrid(x=False,y=True,alpha=.12);self.plot.setMenuEnabled(False);self.plot.setMouseEnabled(x=True,y=False)
        self.plot.getAxis('left').setTextPen(TEXT);self.plot.getAxis('bottom').setTextPen(MUTED)
        legend=self.plot.addLegend(offset=(8,4));legend.setLabelTextColor(TEXT);legend.setColumnCount(2)
        for j,field in enumerate(fields):
            pts=result['series'][field['key']];xs=[];ys=[]
            for p in pts:
                x=p.get('trade_day_index',p.get('trade_minute_index'));v=p['value']
                if p['break_before']:xs.append(x-.0001);ys.append(float('nan'))
                xs.append(x);ys.append(float('nan') if v is None else (v*100 if field['key']=='K' else v))
            colors=result.get('chart_colors',CHART_COLORS)
            self.plot.plot(xs,ys,pen=pg.mkPen(colors[j%len(colors)],width=1.7),name=field['label'],connect='finite',skipFiniteCheck=False)
        for i in range(1,len(self.points)):
            if self.points[i]['break_before'] or self.points[i]['session_id']!=self.points[i-1]['session_id']:
                self.plot.addItem(pg.InfiniteLine(i-.5,pen=pg.mkPen(BORDER,style=Qt.PenStyle.DashLine)))
        self.line=pg.InfiniteLine(angle=90,pen=pg.mkPen(MUTED,style=Qt.PenStyle.DotLine));self.plot.addItem(self.line);self.line.hide()
        layout.addWidget(self.plot)
        self.hint=QLabel('移动鼠标查看真实时刻、合约、数值与有效性；空值处可查看原因。');self.hint.setWordWrap(True);self.hint.setMinimumHeight(48);self.hint.setStyleSheet(f'color:{MUTED};font-size:12px');layout.addWidget(self.hint)
        self.proxy=pg.SignalProxy(self.plot.scene().sigMouseMoved,rateLimit=30,slot=self.hover)
    def hover_text(self,index):
        if not 0<=index<len(self.points):return ''
        p=self.points[index];lines=[p['timestamp'].replace('T',' ')+'　'+' / '.join(str(s or '缺合约') for s in p['contract_ids'])+'　'+self.result['variant_label']]
        for field in self.fields:
            p=self.result['series'][field['key']][index];v,u=display(p);reason='；'.join(self.result['reason_labels'].get(r,r) for r in p['reason_codes'])
            lines.append(field['label']+' '+v+' '+u+' · '+('有效' if p['value'] is not None else reason))
        return '\n'.join(lines)
    def hover(self,event):
        pos=event[0]
        if self.plot.sceneBoundingRect().contains(pos):
            p=self.plot.plotItem.vb.mapSceneToView(pos);index=round(p.x());text=self.hover_text(index)
            if text:self.line.setValue(index);self.line.show();self.hint.setText(text);self.plot.setToolTip(text)


class ResearchV6Page(QWidget):
    changed=Signal()
    def __init__(self,group,service):
        super().__init__();self.group=group;self.service=service;self.selection=None;self.result=None;self.generation=0;self.busy=False;self.pending=False;self.initialized=False;self.frozen=False
        self.setStyleSheet(STYLE)
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1);self.jobs=[]
        root=QVBoxLayout(self);root.setContentsMargins(18,16,18,12);root.setSpacing(12)
        self.title=QLabel({'A':'A 期指 · 12 项','B':'B 跨期 · 10 项','C':'C 跨指数期货 · 10 项'}[group]);self.title.setStyleSheet('font-size:24px;font-weight:700');root.addWidget(self.title)
        controls=QGridLayout();controls.setHorizontalSpacing(12)
        self.indicator=QComboBox();self.variant=QComboBox();self.source=QComboBox();self.identity=QComboBox();self.day=QComboBox()
        self.source.addItem('现有数据服务 · 已发布历史','published');self.source.addItem('研究回放 · 第六版真实归档','replay')
        if not service.config.get('history_roots'):self.source.setCurrentIndex(1)
        for c in CARDS.values():
            if c['group']==group:self.indicator.addItem(c['id']+'  '+c['title'],c['id'])
        self.identity.addItem('按资料规则逐日选择合约',None);self.day.addItem('最新可用观测',None)
        for col,(label,widget) in enumerate([('研究指标',self.indicator),('输入 X',self.variant),('数据来源',self.source)]):
            controls.addWidget(QLabel(label),0,col);controls.addWidget(widget,1,col);controls.setColumnStretch(col,3 if col==0 else 2)
        controls.addWidget(QLabel('合约 / 固定合约对'),2,0);controls.addWidget(self.identity,3,0)
        controls.addWidget(QLabel('截止日期'),2,1);controls.addWidget(self.day,3,1)
        refresh=QPushButton('刷新已发布数据');refresh.clicked.connect(self.refresh_source);controls.addWidget(refresh,3,2)
        root.addLayout(controls)
        self.note=QLabel('正在读取已完成观测…');self.note.setWordWrap(True);self.note.setStyleSheet(f'color:{MUTED};font-size:13px');root.addWidget(self.note)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame);root.addWidget(self.scroll,1)
        self.indicator.currentIndexChanged.connect(self.choose_indicator);self.variant.currentIndexChanged.connect(self.schedule)
        self.source.currentIndexChanged.connect(self.source_changed);self.identity.currentIndexChanged.connect(self.schedule);self.day.currentIndexChanged.connect(self.schedule)
        self.choose_indicator()
    def showEvent(self,event):
        super().showEvent(event)
        if not self.initialized:self.schedule()
    def choose_indicator(self,*_):
        old=self.variant.currentData();self.variant.blockSignals(True);self.variant.clear()
        for v in variants(self.indicator.currentData()):self.variant.addItem(variant_label(self.indicator.currentData(),v),v)
        i=self.variant.findData(old)
        if i>=0:self.variant.setCurrentIndex(i)
        self.variant.blockSignals(False);self.schedule()
    def source_changed(self,*_):
        for combo,label in [(self.identity,'按资料规则逐日选择合约'),(self.day,'最新可用观测')]:
            combo.blockSignals(True);combo.clear();combo.addItem(label,None);combo.blockSignals(False)
        self.schedule()
    def refresh_source(self):
        # Queue invalidation with calculation; never wait for the engine lock on the GUI thread.
        mode=self.source.currentData();job=Job(lambda:self.service.refresh(mode));self.jobs.append(job)
        job.signals.done.connect(lambda _:self.source_changed());self.pool.start(job)
    def schedule(self,*_):
        if self.frozen:return
        self.generation+=1;self.result=None;self.note.setText('正在重新读取完整历史并计算所选口径…')
        if self.scroll.widget():self.scroll.widget().hide()
        if self.isVisible():QTimer.singleShot(30,self.load)
    def load(self):
        if self.frozen:return
        if self.busy:self.pending=True;return
        self.busy=True;self.pending=False;generation=self.generation
        args=dict(code=self.indicator.currentData(),x=self.variant.currentData(),mode=self.source.currentData(),identity=self.identity.currentData(),day=self.day.currentData())
        job=Job(lambda:self.service.query(**args));self.jobs.append(job)
        def done(result):
            self.busy=False
            if generation==self.generation:self.apply(result)
            if self.pending or generation!=self.generation:QTimer.singleShot(0,self.load)
        def fail(message):
            self.busy=False
            if generation==self.generation:self.initialized=True;self.note.setText('读取未完成：'+message+'。可选择“研究回放”核对已有真实样例。')
            if self.pending or generation!=self.generation:QTimer.singleShot(0,self.load)
        job.signals.done.connect(done);job.signals.failed.connect(fail);self.pool.start(job)
    def render(self,_):
        if self.frozen:return
        if self.isVisible() and not self.initialized and not self.busy:self.load()
    def freeze(self,result=None):
        self.frozen=True;self.initialized=True
        if result:
            for control,value in [(self.indicator,result['id']), (self.source,result['mode'])]:
                control.blockSignals(True);control.setCurrentIndex(control.findData(value));control.blockSignals(False)
            self.variant.blockSignals(True);self.variant.clear()
            for v in result['variants']:self.variant.addItem(v['label'],v['id'])
            self.variant.setCurrentIndex(self.variant.findData(result['variant']));self.variant.blockSignals(False)
            self.apply(result);self.note.setText('冻结快照 · '+self.note.text())
        elif not self.result:self.note.setText('该组未包含在此冻结快照中；不重新查询当前数据。')
        for control in (self.indicator,self.variant,self.source,self.identity,self.day):control.setEnabled(False)
        for b in self.findChildren(QPushButton):
            if b.text()=='刷新已发布数据':b.setEnabled(False)
    def apply(self,result):
        self.result=result;self.initialized=True
        for combo,options,label in [(self.identity,result['choices']['identities'],'按资料规则逐日选择合约'),(self.day,result['choices']['days'],'最新可用观测')]:
            current=combo.currentData();combo.blockSignals(True);combo.clear();combo.addItem(label,None)
            for option in options:combo.addItem(' / '.join(option) if isinstance(option,list) else option,option)
            idx=combo.findData(current);combo.setCurrentIndex(max(0,idx));combo.blockSignals(False)
        for i,v in enumerate(result['variants']):
            self.variant.model().item(i).setEnabled(v['enabled']);self.variant.setItemData(i,v['reason'],Qt.ItemDataRole.ToolTipRole)
        self.note.setText(result['source']+' · 观测 '+str(result['observed_at']).replace('T',' ')+' · '+result['volume_note'])
        body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(0,0,8,0);layout.setSpacing(12)
        heading=QLabel(result['id']+'  '+result['title']);heading.setStyleSheet('font-size:21px;font-weight:650');heading.setWordWrap(True);layout.addWidget(heading)
        purpose=QLabel(result['purpose']);purpose.setWordWrap(True);purpose.setStyleSheet(f'color:{MUTED};font-size:14px');layout.addWidget(purpose)
        status=QLabel({'VALID':'全部输出有效','PARTIAL':'部分输出有效 · 独立有效值予以保留','INVALID':'当前输出无效 · 具体原因见各数值'}[result['status']]);status.setStyleSheet(f'color:{ACCENT};font-weight:600');layout.addWidget(status)
        metrics=QGridLayout();metrics.setHorizontalSpacing(18);metrics.setVerticalSpacing(12)
        for i,field in enumerate(result['fields']):
            points=result['series'][field['key']]
            if not points:continue
            p=points[-1];val,unit=display(p);cell=QFrame();cell.setStyleSheet(f'QFrame {{background:{PANEL};border:1px solid {BORDER};border-radius:7px;}} QLabel {{border:none;}}')
            box=QVBoxLayout(cell);name=QLabel(field['label']);name.setWordWrap(True);box.addWidget(name)
            value=QLabel(val+' <span style="font-size:13px">'+unit+'</span>');value.setStyleSheet(f'font-size:26px;font-weight:650;color:{ACCENT}');box.addWidget(value)
            reason='；'.join(result['reason_labels'].get(r,r) for r in p['reason_codes'])
            context=QLabel(('日频' if p['frequency']=='1d' else '分钟')+' · '+p['timestamp'][:16].replace('T',' ')+'\n'+' / '.join(str(s or '缺合约') for s in p['contract_ids'])+ ('\n'+reason if reason else ''))
            context.setWordWrap(True);context.setStyleSheet(f'font-size:12px;color:{MUTED}');box.addWidget(context);metrics.addWidget(cell,i//3,i%3)
        for i in range(3):metrics.setColumnStretch(i,1)
        layout.addLayout(metrics)
        for label,advanced in [('展开：经济含义、公式、符号与边界',False),('高级详情：原始字段与原因代码',True)]:
            toggle=QPushButton(label);toggle.setCheckable(True);layout.addWidget(toggle)
            formula=(Path(__file__).parents[1]/'indicator_v6/formula_assets'/f'{result["id"]}_{THEME}.png').as_uri()
            detail=QTextBrowser();detail.setOpenExternalLinks(False);detail.setHtml(detail_html(result,advanced,formula));detail.setMinimumHeight(480);detail.hide();toggle.toggled.connect(detail.setVisible);layout.addWidget(detail)
        groups={}
        for f in result['fields']:
            key=(f['frequency'],'pct' if f['key']=='K' else f['unit']);groups.setdefault(key,[]).append(f)
        self.charts=[]
        for fields in groups.values():
            chart=Trend(result,fields);self.charts.append(chart);layout.addWidget(chart)
        for text in result['limitations']:
            label=QLabel(text);label.setWordWrap(True);layout.addWidget(label)
        layout.addStretch();old=self.scroll.takeWidget();self.scroll.setWidget(body)
        if old:old.deleteLater()
        self.changed.emit()


def add_pages(window,tabs):
    window.model.indicator_v6_active=True
    service=window.indicator_v6_service=Service(window.model.config,lambda:window.model.config)
    window.research_pages={}
    for group,title in [('A','A 期指'),('B','B 跨期'),('C','C 跨指数期货')]:
        page=ResearchV6Page(group,service);window.research_pages[group]=page;tabs.addTab(page,title)
        def save(group=group,page=page):
            if window.state is not None and page.result:window.state.setdefault('research_v6',{})[group]=page.result
        page.changed.connect(save)
        if getattr(window,'frozen_payload',None):page.freeze(window.frozen_payload.get('research_v6',{}).get(group))
    return window.research_pages
