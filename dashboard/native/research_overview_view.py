"""Simple presentation workflow: compare contract cards, then inspect one identity."""
from html import escape
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QLabel,QComboBox,QPushButton,QScrollArea,QWidget,QGridLayout,QVBoxLayout,QHBoxLayout,QFrame
from .research_v6_view import ResearchV6Page,Job
from .theme import ACCENT,MUTED,PANEL,BORDER
from dashboard.indicator_v6.service import display


class ContractCard(QPushButton):
    def __init__(self,row,fields,result,day,parent=None):
        super().__init__(parent);self.setObjectName('contractCard');self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFixedHeight(184)
        self.setStyleSheet(f'''QPushButton#contractCard {{background:{PANEL};border:1px solid {BORDER};border-radius:9px;padding:0;}}
            QPushButton#contractCard:hover {{border:1px solid {ACCENT};}}
            QPushButton#contractCard:checked {{border:2px solid {ACCENT};background:{PANEL};}}
            QLabel {{background:transparent;border:none;padding:0;}}''')
        box=QVBoxLayout(self);box.setContentsMargins(14,11,14,10);box.setSpacing(4)
        def label(text,size=12,color=MUTED,bold=False):
            w=QLabel(text);w.setWordWrap(True);w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            w.setStyleSheet(f'font-size:{size}px;color:{color};font-weight:{600 if bold else 400};');return w
        identity=' / '.join(s.replace('.CFE','') for s in row['identity'])
        status={'VALID':'有效','PARTIAL':'部分有效','INVALID':'暂无有效值'}[row['status']]
        header=QHBoxLayout();header.addWidget(label(identity,16,ACCENT,True),1);header.addWidget(label(status,11));box.addLayout(header)
        primary=fields[0];point=row['points'][primary['key']]
        value,unit=display(point) if point else ('—',result['units'][primary['unit']]['label'])
        box.addWidget(label(primary['label'],12))
        box.addWidget(label(escape(value)+f' <span style="font-size:12px">{escape(unit)}</span>',27,ACCENT,True))
        for f in fields[1:3]:
            p=row['points'][f['key']];v,u=display(p) if p else ('—',result['units'][f['unit']]['label'])
            box.addWidget(label(f['label'].split(' · ')[-1]+'  '+v+' '+u,12))
        box.addStretch()
        frequency='分钟' if primary['frequency']=='1m' else '日频'
        when=(point['timestamp'] if point else day).replace('T',' ')[:16]
        box.addWidget(label(frequency+' · '+when+(' · 更多数值见详情' if len(fields)>3 else ' · 点击查看详情'),10))
        tips=[identity,result['variant_label']]
        for f in fields:
            p=row['points'][f['key']]
            if p:
                v,u=display(p);reason='；'.join(result['reason_labels'].get(r,r) for r in p['reason_codes'])
                tips.append(f['label']+' '+v+' '+u+'\n'+p['timestamp']+' · '+(reason or '有效'))
            else:
                tips.append(f['label']+' —\n'+day+' · 没有该频率观测')
        self.setToolTip('\n'.join(tips));self.setAccessibleName(identity+' '+status+' '+value+' '+unit)


class PresentationResearchPage(ResearchV6Page):
    def __init__(self,group,service):
        self.ready=False;self.overview=None;self.request_kind='batch';self.preferred=None
        super().__init__(group,service)
        # Keep the advanced controls for the development view only.
        for i in range(self.controls.count()):
            item=self.controls.itemAt(i);row,col,_,_=self.controls.getItemPosition(i)
            if row>=2 or col==2:item.widget().hide()
        self.product=QComboBox();self.product.addItem('全部品种',None)
        for code,name in [('IF','沪深300'),('IH','上证50'),('IC','中证500'),('IM','中证1000')]:self.product.addItem(code+' · '+name,code)
        if group=='C':self.product.clear();self.product.addItem('IF / IC · 同到期月份',None);self.product.setEnabled(False)
        self.controls.addWidget(QLabel('比较范围'),0,2);self.controls.addWidget(self.product,1,2)
        refresh=QPushButton('刷新数据');refresh.clicked.connect(self.refresh_source);self.controls.addWidget(refresh,1,3)
        self.product.currentIndexChanged.connect(self.schedule)
        self.compare_toggle=QPushButton('合约比较');self.compare_toggle.setCheckable(True);self.compare_toggle.setChecked(True)
        self.cards_scroll=QScrollArea();self.cards_scroll.setWidgetResizable(True);self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_body=QWidget();self.cards_grid=QGridLayout(self.cards_body);self.cards_grid.setContentsMargins(3,3,12,3);self.cards_grid.setSpacing(12)
        self.cards_scroll.setWidget(self.cards_body);self.contract_cards=[];self.card_columns=0
        self.compare_toggle.toggled.connect(self.cards_scroll.setVisible)
        self.layout().insertWidget(3,self.compare_toggle);self.layout().insertWidget(4,self.cards_scroll)
        self.ready=True

    def schedule(self,*_):
        if not self.ready or self.frozen:return
        self.request_kind='batch';self.generation+=1;self.result=None
        self.note.setText('正在计算全部挂牌合约及合法组合…')
        self.cards_scroll.setEnabled(False)
        if self.scroll.widget():self.scroll.widget().hide()
        if self.isVisible():QTimer.singleShot(30,self.load)

    def load(self):
        if not self.ready or self.frozen:return
        if self.busy:self.pending=True;return
        self.busy=True;self.pending=False;generation=self.generation;kind=self.request_kind
        args=dict(code=self.indicator.currentData(),x=self.variant.currentData(),mode=self.source.currentData())
        if kind=='batch':
            args.update(product=self.product.currentData(),preferred=self.preferred)
            fn=lambda:self.service.universe(**args)
        else:
            args.update(identity=list(self.preferred),day=self.overview['day'])
            fn=lambda:self.service.query(**args)
        job=Job(fn);self.jobs.append(job)
        def done(value):
            self.busy=False
            if generation==self.generation:
                if kind=='batch':self.apply_overview(value)
                else:self.apply(value)
            if self.pending or generation!=self.generation:QTimer.singleShot(0,self.load)
        def fail(message):
            self.busy=False
            if generation==self.generation:
                self.initialized=True;self.note.setText('暂无可用比较结果：'+message);self.clear_cards();self.cards_scroll.setEnabled(True)
            if self.pending or generation!=self.generation:QTimer.singleShot(0,self.load)
        job.signals.done.connect(done);job.signals.failed.connect(fail);self.pool.start(job)

    def apply_overview(self,value):
        self.overview=value;rows=value['rows'];fields=value['fields'];result=value['detail']
        ids=next((r['identity'] for r in rows if r['identity']==self.preferred),rows[0]['identity']);self.preferred=ids
        self.clear_cards()
        for i,row in enumerate(rows):
            card=ContractCard(row,fields,result,value['day'],self.cards_body);card.setChecked(row['identity']==ids)
            card.clicked.connect(lambda checked=False,index=i:self.choose_card(index));self.contract_cards.append(card)
        self.card_columns=0;self.reflow_cards();self.cards_scroll.setEnabled(True)
        self.compare_toggle.setText(f'合约卡片 · {len(rows)} '+('个合约' if self.group=='A' else '组组合')+' · '+value['rule']+' · 点击卡片查看详情 / 点击此处收起卡片')
        self.apply(result)

    def clear_cards(self):
        while self.cards_grid.count():
            item=self.cards_grid.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.contract_cards=[];self.card_columns=0

    def reflow_cards(self):
        if not self.contract_cards:return
        columns=max(1,min(3 if self.group=='B' else 4,(self.cards_scroll.viewport().width()-16)//310))
        if columns==self.card_columns:return
        while self.cards_grid.count():self.cards_grid.takeAt(0)
        for col in range(4):self.cards_grid.setColumnStretch(col,1 if col<columns else 0)
        for i,card in enumerate(self.contract_cards):self.cards_grid.addWidget(card,i//columns,i%columns)
        self.card_columns=columns
        self.cards_scroll.setFixedHeight(min(2,(len(self.contract_cards)+columns-1)//columns)*196+6)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.ready:QTimer.singleShot(0,self.reflow_cards)

    def choose_card(self,row):
        if not self.overview or row<0 or row>=len(self.overview['rows']):return
        for i,card in enumerate(self.contract_cards):card.setChecked(i==row)
        self.preferred=self.overview['rows'][row]['identity'];self.request_kind='detail'
        self.generation+=1;self.result=None;self.note.setText('正在载入所选合约的趋势与说明…')
        if self.scroll.widget():self.scroll.widget().hide()
        QTimer.singleShot(0,self.load)

    def apply(self,result):
        super().apply(result)
        body=self.scroll.widget()
        identity=QLabel('当前详情：'+' / '.join(s.replace('.CFE','') for s in (self.preferred or [])))
        identity.setStyleSheet(f'font-weight:600;color:{ACCENT};font-size:15px');body.layout().insertWidget(0,identity)
        for b in body.findChildren(QPushButton):
            if b.text().startswith('高级详情'):b.hide()
        if self.overview:self.note.setText(self.overview['source']+' · 观测日 '+self.overview['day']+' · 卡片使用同一日期与所选口径，空值原因可悬浮查看')
