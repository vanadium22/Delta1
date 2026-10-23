"""Simple presentation workflow: compare all listed contracts, then inspect one row."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel,QComboBox,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView
from .research_v6_view import ResearchV6Page,Job
from .theme import ACCENT,MUTED,PANEL,BORDER
from dashboard.indicator_v6.service import display


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
        self.table=QTableWidget();self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide();self.table.setWordWrap(False);self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(f'QTableWidget {{background:{PANEL};gridline-color:{BORDER};}} QHeaderView::section {{padding:7px;font-weight:600;}}')
        self.table.setMinimumHeight(180);self.table.setMaximumHeight(275)
        self.table.currentCellChanged.connect(self.choose_row);self.compare_toggle.toggled.connect(self.table.setVisible)
        self.layout().insertWidget(3,self.compare_toggle);self.layout().insertWidget(4,self.table)
        self.ready=True

    def schedule(self,*_):
        if not self.ready or self.frozen:return
        self.request_kind='batch';self.generation+=1;self.result=None
        self.note.setText('正在计算全部挂牌合约及合法组合…')
        self.table.setEnabled(False)
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
                self.initialized=True;self.note.setText('暂无可用比较结果：'+message);self.table.setRowCount(0);self.table.setEnabled(True)
            if self.pending or generation!=self.generation:QTimer.singleShot(0,self.load)
        job.signals.done.connect(done);job.signals.failed.connect(fail);self.pool.start(job)

    def apply_overview(self,value):
        self.overview=value;rows=value['rows'];fields=value['fields'];result=value['detail']
        ids=next((r['identity'] for r in rows if r['identity']==self.preferred),rows[0]['identity']);self.preferred=ids
        self.table.blockSignals(True);self.table.clear();self.table.setRowCount(len(rows));self.table.setColumnCount(len(fields)+2)
        headers=['合约' if self.group=='A' else '合约组合']
        for f in fields:
            unit='%' if f['key']=='K' else result['units'][f['unit']]['label']
            headers.append(f['label']+'\n'+unit+' · '+('日频' if f['frequency']=='1d' else '分钟'))
        self.table.setHorizontalHeaderLabels(headers+['有效性'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        for i,row in enumerate(rows):
            label=' / '.join(s.replace('.CFE','') for s in row['identity'])
            self.table.setItem(i,0,QTableWidgetItem(label))
            for j,f in enumerate(fields,1):
                p=row['points'][f['key']];item=QTableWidgetItem(display(p)[0] if p else '—')
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                reason='；'.join(result['reason_labels'].get(r,r) for r in p['reason_codes']) if p else '没有该频率观测'
                item.setToolTip(label+'\n'+(p['timestamp'] if p else value['day'])+'\n'+result['variant_label']+'\n'+((display(p)[0]+' '+display(p)[1]) if p else '—')+'\n'+(reason or '有效'))
                if not p or p['value'] is None:item.setForeground(QColor(MUTED))
                self.table.setItem(i,j,item)
            status=QTableWidgetItem({'VALID':'有效','PARTIAL':'部分有效','INVALID':'暂无有效值'}[row['status']]);status.setToolTip('观测 '+str(row['observed_at'])+'；逐数值悬浮查看具体原因')
            self.table.setItem(i,len(fields)+1,status);self.table.setRowHeight(i,33)
            if row['identity']==ids:self.table.selectRow(i)
        self.table.setFixedHeight(min(len(rows),8)*33+60)
        self.table.blockSignals(False);self.table.setEnabled(True)
        self.compare_toggle.setText(f'合约比较 · {len(rows)} '+('个合约' if self.group=='A' else '组组合')+' · '+value['rule']+' · 点击行查看详情 / 点击此处收起列表')
        self.apply(result)

    def choose_row(self,row,*_):
        if not self.overview or row<0 or row>=len(self.overview['rows']):return
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
        if self.overview:self.note.setText(self.overview['source']+' · 观测日 '+self.overview['day']+' · 各行使用同一日期与所选口径，空值原因可悬浮查看')
