"""Company presentation and local development projections of the shared engine."""
import argparse
import json
from pathlib import Path
import sys
import os

if '--theme' in sys.argv:
    index=sys.argv.index('--theme')
    if index+1<len(sys.argv):os.environ['DELTA1_THEME']=sys.argv[index+1]

from .bootstrap import configure_qt
configure_qt()
from PySide6.QtCore import QTimer,Signal,QThreadPool,Qt
from PySide6.QtGui import QIcon,QPixmap,QPainter,QColor,QFont
from PySide6.QtWidgets import QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QFileDialog,QDialog,QTabWidget
from .app import ResearchWindow,Task
from .card_views import QuotePanel,number,stamp
from .history_maintenance import HistoryMaintenance
from .collection import CollectionJob
from .theme import MUTED
from dashboard.numeric_snapshot import freeze_state,save_snapshot,numeric_rows


def edition_icon(developer=False):
    pix=QPixmap(64,64);pix.fill(QColor('#344d71' if developer else '#087e8b'))
    painter=QPainter(pix);painter.setPen(QColor('white'));painter.setFont(QFont('Segoe UI',30,QFont.Weight.Bold))
    painter.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,'D' if developer else 'Δ');painter.end()
    return QIcon(pix)


def export_window(window,payload):
    from datetime import datetime
    path=Path(__file__).parents[1]/'runtime'/'app_exports'/('snapshot_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    try:
        save_snapshot(payload,path)
        window.status.setText('快照已保存：'+str(path))
    except Exception as exc:window.status.setText('快照保存失败：'+type(exc).__name__)


def freeze_window(state):
    payload=freeze_state(state)
    if state.get('research_pages'):
        # Preserve the shared result contract and its visible entity page.
        # Export never reloads a changed source or substitutes another selection.
        payload['snapshots'][0]['research_pages']=state['research_pages']
        payload['research']=state['research_pages']
    return payload


class PresentationWindow(QMainWindow):
    loaded=Signal(object)
    frozen_payload=None

    def __init__(self,model):
        super().__init__();self.model=model;self.state=None;self.demo=False;self.busy=False;self.closing=False;self.pending=False;self.generation=0
        self.collection=CollectionJob(model.local_root);self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.resize(1580,980);self.setMinimumSize(1100,760)
        from .card_style import CARD_STYLE
        self.setStyleSheet(CARD_STYLE)
        widget=QWidget();self.setCentralWidget(widget);layout=QVBoxLayout(widget);layout.setContentsMargins(24,18,24,18)
        row=QHBoxLayout();title=QLabel('Δ DELTA1  ·  行情与研究');title.setStyleSheet('font-size:26px;font-weight:700');row.addWidget(title);row.addStretch()
        self.network=QLabel('离线 · 已发布历史');row.addWidget(self.network)
        for text,fn in [('验证并开始实时',lambda:self.start_collection(False)),('停止采集',lambda:self.pipeline.readonly()),('导出数字快照',self.export)]:
            b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
            if self.frozen_payload and text!='导出数字快照':b.hide()
        layout.addLayout(row)
        self.notice=QLabel('');self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.pages=QTabWidget();layout.addWidget(self.pages,1)
        self.quotes=QuotePanel();self.pages.addTab(self.quotes,'概览')
        from .research_pages_view import add_research_pages
        add_research_pages(self,self.pages,self.selection_changed)
        if self.frozen_payload:
            # A frozen export carries only the groups evaluated at capture.
            # Keep it readable without allowing filters to imply recalculation.
            for page in self.research_pages.values():
                page.read_only=True
                for widget in (page.input,page.family,page.more_inputs,page.scope,page.product,page.timing,page.expiry,
                               page.left,page.right,page.date,page.participation,page.apply,page.expand,page.representatives,page.directory,page.search):
                    widget.setEnabled(False)
        self.pages.currentChanged.connect(self.selection_changed)
        self.quotes.distribution.setCurrentIndex(1)
        if self.frozen_payload:self.quotes.distribution.setEnabled(False)
        self.window_numbers={}
        self.indicator_numbers={}
        for root,card in self.quotes.cards.items():
            card.chart.hide();card.footer.hide()
            for b in card.findChildren(QPushButton):b.hide()
            details=QLabel();details.setStyleSheet('font-size:14px;');details.setWordWrap(True)
            card.layout.addWidget(details);self.window_numbers[root]=details
            indicators=QLabel();indicators.setStyleSheet(f'font-size:13px;color:{MUTED};');indicators.setWordWrap(True)
            card.layout.addWidget(indicators);self.indicator_numbers[root]=indicators
        # Only current four-product cards; raw quote/debug tables are not exposed.
        if hasattr(self.quotes,'tabs'):self.quotes.tabs.setTabVisible(1,False)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.quotes.changed.connect(self.selection_changed)
        self.timer=QTimer(self);self.timer.setInterval(3000);self.timer.timeout.connect(self.refresh)
        if not self.frozen_payload:self.timer.start()
        QTimer.singleShot(0,self.refresh)

    def refresh(self):
        if self.closing:return
        if self.busy:self.pending=True;return
        if self.frozen_payload:
            states=self.frozen_payload['snapshots'];slot=self.quotes.month.currentData()
            state=next((s for s in states if s['selection']['overview_slot']==slot),states[0])
            self.render(state);return
        self.busy=True
        request=dict(cards=True,category='basis',price_input='annual',distribution_input=self.quotes.distribution.currentData() or 'annual',
                     overview_slot=self.quotes.month.currentData() if self.quotes.month.currentData() is not None else 0,save=False)
        from .research_pages_view import capture,active_selection
        selection=active_selection(self);generation=self.generation
        self.task=Task(lambda:capture(self.model,request,selection,display=True))
        self.task.signals.completed.connect(lambda state:self.completed(state,generation))
        self.task.signals.failed.connect(self.failed);self.pool.start(self.task)

    def selection_changed(self,*_):
        self.generation+=1
        self.refresh()

    def completed(self,state,generation):
        self.busy=False
        if self.closing:return
        try:
            if generation==self.generation:self.render(state)
            else:self.pending=True
        except Exception as exc:self.status.setText('界面应用失败：'+type(exc).__name__)
        if self.pending:self.pending=False;QTimer.singleShot(0,self.refresh)

    def failed(self,error):
        self.busy=False;self.status.setText('读取失败：'+str(error))
        if self.pending:self.pending=False;QTimer.singleShot(0,self.refresh)

    def render(self,state):
        self.busy=False;self.state=state
        from .research_pages_view import render_pages
        render_pages(self,state.get('research_pages'))
        # QuotePanel accepts the same overview data as the research window.
        self.quotes.render({**state,'quotes':state.get('quotes',[])})
        for c in state['overview']:
            product_card=self.quotes.cards[c['root']]
            if c.get('display_kind'):
                product_card.captions['price'].setText(c['display_kind'])
                product_card.captions['volume'].setText(c['display_kind'])
            self.window_numbers[c['root']].setText('\n'.join(
                f"{w['title']}   {number(w['percentile'],2)}%   · n={w['n']} · 缺{w['missing']}日 · 排除{w['excluded']}日"+
                (' · '+w['reason'] if w['reason'] else '') for w in c['chart']['rows'])+
                '\n参考截止 '+stamp(c['chart']['reference_end']))
            entity=next((e for e in state.get('entities',[]) if e['left']==c['symbol']),{})
            wanted=('A02.convergence','B11','B10','B02.center','B04.Q','B09')
            lines=[]
            short={'A02.convergence':'收敛','B11':'振幅','B10':'路径效率','B02.center':'中枢','B04.Q':'换手','B09':'活跃度'}
            metrics={m['id']:m for m in entity.get('metrics',[])}
            alternatives={'B11':'B11.sample','B02.center':'B02.collection_center','B04.Q':'B04.Q.intraday','B09':'B09.same_time'}
            for code in wanted:
                alternate=metrics.get(alternatives.get(code))
                m=alternate if alternate and alternate.get('current') is not None else metrics.get(code)
                if not m:continue
                current=m.get('current') is not None
                value=m.get('current') if current else m.get('value')
                kind=m.get('display_kind') or m.get('current_scope','盘中') if current else '日终'
                if current and kind.startswith('盘中'):kind=m.get('current_scope') or kind
                when=m.get('current_time') if current else m.get('time')
                date=stamp(when,True)[:5] if when else '缺数'
                lines.append(f"{short[code]} {number(value,2)} {m['unit']} · {kind} {date}")
            self.indicator_numbers[c['root']].setText('\n'.join('    |    '.join(lines[i:i+2]) for i in range(0,len(lines),2)) or '暂无可用研究指标；需要对应频率历史数据')
        self.notice.setText('保存行情冻结回放 · 非当前实时' if self.frozen_payload else
            '固定分红情景 · 缺失分红按已披露前一合约继承 · 陈旧行情保留日期，不能视为实时')
        s=self.collection.state()
        self.network.setText('冻结快照' if self.frozen_payload else ('持续采集 · 时效见卡片' if self.collection.running() else '只读缓存 / 未采集'))
        self.status.setText('观察时点 '+stamp(state['as_of'])+' · 分位和有效 n 见各窗口；单位见卡片')
        from dashboard.refresh_evidence import applied
        applied(self,state)
        self.loaded.emit(state)

    def start_collection(self,once):
        if not self.frozen_payload and hasattr(self,'pipeline'):self.pipeline.request_realtime(once)

    def export(self):
        if self.state:export_window(self,self.frozen_payload or freeze_window(self.state))

    def navigate(self,index):
        if 0<=index<self.pages.count():self.pages.setCurrentIndex(index)

    def closeEvent(self,event):
        self.closing=True;self.timer.stop();self.collection.stop()
        if hasattr(self,'pipeline'):
            self.pipeline.stop()
            if not self.pipeline.drained():event.ignore();QTimer.singleShot(100,self.close);return
        if self.busy or self.collection.running():event.ignore();QTimer.singleShot(100,self.close);return
        if hasattr(self,'pipeline'):self.pipeline.timer.stop()
        self.model.close();event.accept()


class DeveloperWindow(ResearchWindow):
    def __init__(self,model):
        super().__init__(model)
        b=QPushButton('导出当前数字快照');b.clicked.connect(self.export)
        self.centralWidget().layout().insertWidget(1,b)
    def export(self):
        if self.state:export_window(self,freeze_window(self.state))


def main(argv=None):
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--edition',choices=('presentation','development'),default='presentation')
    parser.add_argument('--snapshot',type=Path)
    parser.add_argument('--theme',choices=('public','private'))
    args,rest=parser.parse_known_args(argv)
    developer=args.edition=='development'
    cls=DeveloperWindow if developer else PresentationWindow
    if args.snapshot:
        payload=json.loads(args.snapshot.read_text(encoding='utf8'))
        class ReviewWindow(PresentationWindow):frozen_payload=payload
        cls=ReviewWindow
        # Frozen review must never query networks or start maintenance.
        if '--capture' not in rest:rest+=['--no-realtime']
    from dashboard.current import main as launch
    return launch(rest,window_class=cls,title='Delta1 · '+('开发版' if developer else '展示版')+(' · 冻结快照' if args.snapshot else ''),icon=lambda:edition_icon(developer),frozen=bool(args.snapshot),public=not developer)


if __name__=='__main__':raise SystemExit(main())
