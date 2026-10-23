from __future__ import annotations

from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import uuid

from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Qt,Signal,QUrl
from PySide6.QtGui import QDesktopServices,QFont,QFontDatabase
from PySide6.QtWidgets import (QApplication,QButtonGroup,QCheckBox,QComboBox,QFileDialog,QFrame,
    QGridLayout,QHBoxLayout,QHeaderView,QLabel,QLineEdit,QListWidget,QMainWindow,QMessageBox,
    QPlainTextEdit,QPushButton,QScrollArea,QSlider,QStackedWidget,QTableWidget,QTableWidgetItem,
    QTabWidget,QVBoxLayout,QWidget)
import pandas as pd
import pyqtgraph as pg

from .branding import app_icon
from .instruments import UNDERLYINGS
from .widgets import Panel,PythonHighlight,STYLE,label
from .theme import ACCENT,MUTED,PANEL



class Signals(QObject):
    completed=Signal(object)
    failed=Signal(str)


class Task(QRunnable):
    def __init__(self,function):
        super().__init__();self.function=function;self.signals=Signals()

    def run(self):
        try: self.signals.completed.emit(self.function())
        except Exception as exc: self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


def button(text,callback=None,primary=False,name=None):
    item=QPushButton(text)
    if primary: item.setObjectName("primary")
    if name: item.setObjectName(name)
    if callback: item.clicked.connect(callback)
    return item


def table(headers):
    widget=QTableWidget(0,len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(38)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    return widget


def fill_table(widget,rows):
    widget.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,value in enumerate(row):
            item=QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            widget.setItem(i,j,item)


def configure_style(app):
    # Qt's offscreen Windows platform has no default font database. Loading
    # existing OS fonts also keeps native/headless screenshots consistent.
    import os
    font_root=Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"
    for name in ("msyh.ttc","msyhbd.ttc","segoeui.ttf","consola.ttf"):
        path=font_root/name
        if path.is_file(): QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI",10))
    pg.setConfigOptions(antialias=True,foreground=MUTED,background=PANEL,useOpenGL=False)


class ResearchWindow(QMainWindow):
    """Focused native shell using the existing model, Qt tasks and collector."""
    loaded=Signal(object)

    def __init__(self,model,*,demo=False):
        super().__init__();self.model=model;self.state=None;self.busy=False;self.closing=False
        self.pending=False;self.active_task=None;self.generation=0
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        from .collection import CollectionJob
        from .card_views import QuotePanel
        from .card_style import CARD_STYLE
        self.collection=CollectionJob(model.local_root)
        self.setWindowTitle("Delta1 · 股指期货行情与指标研究");self.setWindowIcon(app_icon())
        self.resize(1600,1050);self.setMinimumSize(1150,760);self.setStyleSheet(CARD_STYLE)
        root=QWidget();self.setCentralWidget(root);body=QVBoxLayout(root);body.setContentsMargins(22,16,22,12)
        header=QHBoxLayout();header.addWidget(label("Δ DELTA1  ·  股指期货","title"));header.addStretch()
        self.connection_label=label("采集未启动","pill");header.addWidget(self.connection_label)
        self.once_button=button("采集一轮",lambda:self.start_collection(True));header.addWidget(self.once_button)
        self.start_button=button("开始实时",lambda:self.start_collection(False),primary=True);header.addWidget(self.start_button)
        header.addWidget(button("更新合约",self.update_contract_reference))
        self.stop_button=button("停止",lambda:self.pipeline.readonly());header.addWidget(self.stop_button)
        header.addWidget(button("刷新",self.refresh));body.addLayout(header)
        dividend_line=QHBoxLayout();self.dividend_banner=label("正在读取固定分红情景…","banner");self.dividend_banner.setWordWrap(True);dividend_line.addWidget(self.dividend_banner,1)
        dividend_line.addWidget(button('分红与映射 →',lambda:self.pages.setCurrentWidget(self.settings_tab)));body.addLayout(dividend_line)
        self.pages=QTabWidget();body.addWidget(self.pages,1)
        self.quotes=QuotePanel();self.pages.addTab(self.quotes,"行情总览")
        from .research_pages_view import add_research_pages
        add_research_pages(self,self.pages,self.selection_changed)
        self.quotes.changed.connect(self.selection_changed)
        self.settings_tab=self.settings_page()
        self.pages.addTab(self.settings_tab,"数据管理 / 设置")
        from .history_maintenance import HistoryMaintenance,MaintenancePage
        self.history_maintenance=HistoryMaintenance(model)
        # Mutual VPN workflow owns maintenance before the realtime window opens.
        self.history_maintenance.authorized=False
        self.maintenance_page=MaintenancePage(self.history_maintenance)
        # The shared pipeline adds one inline maintenance/settings page at launch.
        self.pages.currentChanged.connect(self.update_dividend_banner)
        self.pages.currentChanged.connect(self.selection_changed)
        self.status=label("正在读取本地历史与行情…","muted");self.status.setWordWrap(True);body.addWidget(self.status)
        self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(3000);self.refresh_timer.timeout.connect(self.periodic);self.refresh_timer.start()
        QTimer.singleShot(0,self.refresh)

    def settings_page(self):
        from dashboard.marketdata.paths import DATA_ROOT
        page=QWidget();layout=QVBoxLayout(page)
        actions=QHBoxLayout();actions.addWidget(button("导入下载批次 run.json",self.choose_import,primary=True))
        actions.addWidget(button("注册标准数据集",self.choose_standard));actions.addWidget(button("刷新覆盖",self.refresh));actions.addStretch();layout.addLayout(actions)
        note=label(f"共享数据根目录：{DATA_ROOT}\n支持 shared-worker v2、年度研究 bulk_v1 和 dashboard_bars_v1；哈希/字段/单位/具体合约校验后导入。冲突拒绝发布，不覆盖原始文件。","muted");note.setWordWrap(True);layout.addWidget(note)
        self.coverage_table=table(["品种 / 指数","频率","具体代码数","首个数据时刻","最新数据时刻","数据集"]);layout.addWidget(self.coverage_table,1)
        self.paths_note=QPlainTextEdit();self.paths_note.setReadOnly(True);self.paths_note.setMaximumHeight(115);layout.addWidget(self.paths_note)
        self.mapping=QPlainTextEdit();self.mapping.setReadOnly(True);self.mapping.setMaximumHeight(180);layout.addWidget(self.mapping)
        dividend_actions=QHBoxLayout()
        dividend_actions.addWidget(button("选择分红缓存目录",self.choose_dividends))
        dividend_actions.addWidget(button("建立新的固定分红情景",self.create_scenario))
        dividend_actions.addWidget(button("导入逐日剩余分红JSON",self.choose_daily_dividends));dividend_actions.addStretch();layout.addLayout(dividend_actions)
        layout.addWidget(label("固定情景版本变化需重新建立并明确展示映射。逐日分红接口：contract_daily_dividends_v1（日期、具体合约、剩余点数）。","muted"))
        return page

    def request(self):
        return dict(cards=True,category='basis',price_input='annual',
            overview_slot=self.quotes.month.currentData(),distribution_input=self.quotes.distribution.currentData(),demo=False,save=False)

    def submit(self,function,callback):
        if self.busy or self.closing:return False
        self.busy=True;self.status.setText("正在读取与核验…")
        task=Task(function);self.active_task=task
        task.signals.completed.connect(lambda value:self.finish(value,callback))
        task.signals.failed.connect(lambda error:self.finish(error,None))
        self.pool.start(task);return True

    def finish(self,value,callback):
        self.busy=False;self.active_task=None
        if self.closing:return
        if callback:
            try:callback(value)
            except Exception as exc:self.status.setText(f"界面更新失败：{exc}")
        else:self.status.setText(str(value))
        if self.pending:self.pending=False;QTimer.singleShot(0,self.refresh)

    def refresh(self,*_):
        if self.closing:return
        if self.busy:self.pending=True;return
        request=self.request();generation=self.generation
        from .research_pages_view import active_selection
        selection=active_selection(self)
        def rendered(state):
            if generation==self.generation:self.render(state)
            else:self.pending=True
        def read():
            from .research_pages_view import capture
            return capture(self.model,request,selection,display=True)
        self.submit(read,rendered)

    def selection_changed(self,*_):
        self.generation+=1
        self.status.setText("正在读取所选页面；变更的研究值已清空，结果完成后更新。")
        self.refresh()

    def render(self,state):
        self.state=state
        from .research_pages_view import render_pages
        render_pages(self,state.get('research_pages'))
        self.quotes.render(state)
        self.update_dividend_banner()
        info=state["dividend_info"]
        fmtdate=lambda v:pd.Timestamp(v).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M")
        fill_table(self.coverage_table,[[r["product"],r["frequency"],r["symbols"],fmtdate(r["first"]),fmtdate(r["last"]),r["dataset_id"]] for r in state["coverage"]])
        self.paths_note.setPlainText("\n".join(["历史："+p for p in self.model.config["history_roots"]]+["实时："+self.model.config.get("realtime_root",""),"分红："+self.model.config.get("dividend_root","")]))
        self.mapping.setPlainText(info.get('mapping_policy','固定分红情景映射')+"\n"+"\n".join(f"{v['alias']} → {s} | 到期 {v['expiry']} | D={v['points']:.6f} 点"+(' | 沿用 '+v['inherited_from'] if v.get('inherited_from') else '') for s,v in info.get("mapping",{}).items())+"\n"+state["dividend_reason"])
        reference=getattr(self.model,'contract_sync',{})
        collection_note=' · 实时采集中' if self.collection.running() else ' · 点击开始实时启动采集'
        self.status.setText("本地数据刷新 "+fmtdate(state["as_of"])+" · "+reference.get('message','合约参考待更新')+collection_note)
        from dashboard.refresh_evidence import applied
        applied(self,state)
        self.loaded.emit(state)

    def update_dividend_banner(self,*_):
        state=self.state
        if not state:return
        self.dividend_banner.setToolTip('')
        if getattr(self.model,'indicator_v6_active',False) and self.pages.currentWidget() in self.research_pages.values():
            self.dividend_banner.setText('第六版研究 · 未调整基差与相对定价；各输出保留真实观测时间与数据来源')
            return
        info=state["dividend_info"]
        if state["dividend_reason"]:text="分红不可用："+state["dividend_reason"]
        elif state["dividend_mode"]=="fixed_snapshot":
            scope='连续档位固定 D 情景' if self.pages.currentIndex()==0 else '具体合约固定 D 情景'
            text=f"{scope}  · 快照 {info['snapshot_date']}  · 非真实逐日分红"
            if info.get('inherited'):text+=' · 缺失合约分红沿用前一合约（估计）'
            symbols=[r['symbol'] for r in state['overview']] if self.pages.currentIndex()==0 else list(dict.fromkeys(s for e in state['entities'] for s in (e['left'],e['right']) if s.endswith('.CFE')))
            mapped=[(s,info['mapping'].get(s,{}).get('points')) for s in symbols]
            self.dividend_banner.setToolTip(f"映射锚定 {info['mapping_anchor']} · 版本 {state['dividend_version']}\n"+"\n".join((f"{s} D={d:.4f}点" if d is not None else f"{s} D缺失")+('；沿用 '+info['mapping'][s]['inherited_from'] if info.get('mapping',{}).get(s,{}).get('inherited_from') else '') for s,d in mapped))
        else:text="逐日剩余分红 · 按日期与具体合约精确匹配 · "+state["dividend_version"][:10]
        self.dividend_banner.setText(text)

    def periodic(self):
        s=self.collection.state();labels={"idle":"未启动","starting":"连接中","running":"HTTP已连接","disconnected":"连接失败","stopped":"已停止","failed":"采集失败"}
        self.history_maintenance.tick();self.maintenance_page.refresh()
        partial=' · 部分缺失' if s.get('missing_symbols') else ''
        self.connection_label.setText(f"{labels.get(s['status'],s['status'])} · {s['polls']}轮 / {s['rows']}条"+partial)
        self.connection_label.setToolTip(s.get("error") or ('缺失：'+', '.join(s['missing_symbols']) if s.get('missing_symbols') else "HTTP连接状态不代表行情新鲜，行情时效逐行检查"))
        self.start_button.setEnabled(not self.collection.running());self.once_button.setEnabled(not self.collection.running())
        if not self.busy:self.refresh()

    def start_collection(self,once):
        if hasattr(self,'pipeline'):self.pipeline.request_realtime(once)

    def update_contract_reference(self):
        if hasattr(self,'pipeline'):self.pipeline.request_realtime(force_reference=True)

    def navigate(self,index):
        if 0<=index<self.pages.count():self.pages.setCurrentIndex(index)

    def inline_path(self,title,callback,initial=''):
        box=QWidget();layout=QVBoxLayout(box);layout.addWidget(QLabel(title))
        field=QPlainTextEdit(initial);field.setMaximumHeight(80);layout.addWidget(field)
        def apply():
            value=field.toPlainText().strip();box.hide();box.deleteLater()
            if value:callback(value)
        layout.addWidget(button('应用',apply));layout.addWidget(button('取消',box.deleteLater))
        self.settings_tab.layout().addWidget(box);self.pages.setCurrentWidget(self.settings_tab)

    def choose_import(self,files=None):
        if self.busy:self.status.setText("当前任务尚在执行，请稍后导入。");return
        from dashboard.marketdata.paths import DATA_ROOT,HISTORY_ROOT
        if not isinstance(files,list):
            self.inline_path('输入已下载 run.json 完整路径（每行一个）',lambda value:self.choose_import(value.splitlines()));return
        if not files:return
        from dashboard.marketdata.ddb_import import import_runs
        def run():
            audit=import_runs(files,HISTORY_ROOT,self.model.config.get("reference_file"))
            config=deepcopy(self.model.config);new=[r["root"] for r in audit["datasets"]]
            config["history_roots"]=list(dict.fromkeys(config["history_roots"]+new));config["reference_file"]=audit["reference_file"]
            self.model.save_config(config);return audit
        def done(audit):
            self.status.setText(f"导入完成：新增 {sum(r['inserted'] for r in audit['datasets'])}；重复 {sum(r['duplicates'] for r in audit['datasets'])}。")
            self.refresh()
        self.submit(run,done)

    def choose_standard(self,root=None):
        if self.busy:self.status.setText("当前任务尚在执行，请稍后注册。");return
        from dashboard.marketdata.paths import DATA_ROOT
        if not isinstance(root,str):
            self.inline_path('输入已有 dashboard_bars_v1 标准目录',self.choose_standard);return
        if not root:return
        def register():
            from dashboard.marketdata.ddb_import import validate_standard
            validate_standard(root)
            config=deepcopy(self.model.config);config["history_roots"]=list(dict.fromkeys(config["history_roots"]+[root]));self.model.save_config(config)
        self.submit(register,lambda _:self.refresh())

    def choose_dividends(self,root=None):
        if self.busy:return
        if not isinstance(root,str):
            self.inline_path('输入仅含缓存分红文件的目录',self.choose_dividends,self.model.config.get('dividend_root',''));return
        if not root:return
        config=deepcopy(self.model.config);config["dividend_root"]=root;config["dividend_mode"]="fixed_snapshot"
        self.submit(lambda:self.model.save_config(config),lambda _:self.refresh())

    def create_scenario(self,confirmed=None):
        if self.busy:return
        from dashboard.marketdata.dividends import read_snapshot,make_scenario,make_contract_scenario
        from dashboard.marketdata.repository import ReferenceBook
        from dashboard.marketdata.paths import HISTORY_ROOT
        try:
            source=read_snapshot(self.model.config['dividend_root']);reference=ReferenceBook(self.model.config['reference_file'])
            anchor=pd.Timestamp.now(tz='Asia/Shanghai').date()
            if self.model.config.get('dividend_missing_policy')=='previous_contract':
                from dashboard.marketdata.contract_reference import latest_contracts
                scenario=make_contract_scenario(source,latest_contracts(reference.data),anchor)
            else:scenario=make_scenario(source,reference,anchor)
            text=f"快照 {scenario['snapshot_date']}；映射锚定 {scenario['mapping_anchor']}。按独立合约参考映射，旧情景保留；历史将按新版本重新计算。\n\n"+"\n".join(f"{v['alias']} → {s}：{v['points']:.4f}点" for s,v in scenario["mapping"].items())
            if confirmed!=scenario['version']:
                box=QWidget();layout=QVBoxLayout(box);note=QLabel(text);note.setWordWrap(True);layout.addWidget(note)
                layout.addWidget(button('保存此情景',lambda:(box.deleteLater(),self.create_scenario(scenario['version']))))
                layout.addWidget(button('取消',box.deleteLater));self.settings_tab.layout().addWidget(box);return
            path=HISTORY_ROOT.parent/"dividend_scenarios"/(scenario["version"]+".json")
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():path.write_text(json.dumps(scenario,ensure_ascii=False,indent=2),encoding="utf-8")
            config=deepcopy(self.model.config);config.update(dividend_mode="fixed_snapshot",dividend_scenario_file=str(path))
            self.submit(lambda:self.model.save_config(config),lambda _:self.refresh())
        except Exception as exc:self.status.setText(str(exc))

    def choose_daily_dividends(self,path=None):
        if self.busy:return
        if not isinstance(path,str):
            self.inline_path('输入逐日 / 具体合约剩余分红 JSON 完整路径',self.choose_daily_dividends);return
        if not path:return
        from dashboard.marketdata.dividends import DividendBook
        book=DividendBook.load(self.model.config.get("dividend_root",""),daily_file=path,mode="daily_remaining")
        if book.reason:self.status.setText(book.reason);return
        config=deepcopy(self.model.config);config.update(dividend_mode="daily_remaining",daily_dividend_file=path)
        self.submit(lambda:self.model.save_config(config),lambda _:self.refresh())

    def closeEvent(self,event):
        self.closing=True
        self.refresh_timer.stop();self.collection.stop()
        if hasattr(self,'pipeline'):
            self.pipeline.stop()
            if not self.pipeline.drained():event.ignore();QTimer.singleShot(100,self.close);return
        self.history_maintenance.stop();self.history_maintenance.tick()
        if self.history_maintenance.process is not None:
            event.ignore();QTimer.singleShot(100,self.close);return
        if self.busy or self.collection.running() or any(getattr(p,'busy',False) for p in self.research_pages.values()):
            event.ignore();QTimer.singleShot(100,self.close);return
        if hasattr(self,'pipeline'):self.pipeline.timer.stop()
        self.model.close();event.accept()
