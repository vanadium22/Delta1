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
from .market_view import MarketPages,MODULE_TITLES


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


class Window(QMainWindow):
    loaded=Signal(object)

    def __init__(self,model,*,demo=False):
        super().__init__()
        self.model=model;self.demo=demo;self.state=None;self.timeline=[];self.as_of=None
        self.frequency=model.config.get("frequency","1m")
        self.busy=False;self.active_task=None;self.queue=[];self.pending=False;self.generation=0;self.closing=False
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.developer=getattr(model,"edition","developer")=="developer"
        self.collection=None
        if self.developer:
            from .collection import CollectionJob
            self.collection=CollectionJob(model.local_root)
        self.setWindowTitle("Delta1 · "+("开发者工作台" if self.developer else "市场看板"))
        self.setWindowIcon(app_icon())
        self.resize(1480,960);self.setMinimumSize(1100,700)
        self.setStyleSheet(STYLE)
        self.build()
        self.play_timer=QTimer(self);self.play_timer.setInterval(350);self.play_timer.timeout.connect(self.advance)
        self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(2500);self.refresh_timer.timeout.connect(self.periodic)
        self.refresh_timer.start()
        QTimer.singleShot(0,self.refresh)

    def build(self):
        root=QWidget();self.setCentralWidget(root)
        layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        self.navigation=QButtonGroup(self);self.navigation.setExclusive(True)
        self.demo_button=None
        if self.developer:
            sidebar=QFrame();sidebar.setObjectName("sidebar");sidebar.setFixedWidth(174)
            side=QVBoxLayout(sidebar);side.setContentsMargins(14,24,14,20);side.setSpacing(9)
            logo=label("Δ  DELTA1");logo.setStyleSheet(f"color:{ACCENT};font-size:23px;font-weight:650;")
            side.addWidget(logo);side.addWidget(label("开发者工作台 · 石墨金","muted"));side.addSpacing(28)
            for i,name in enumerate((*MODULE_TITLES,"公式工作台","数据与任务","结果档案")):
                item=button(name,name="nav");item.setCheckable(True);item.setChecked(i==0)
                self.navigation.addButton(item,i);side.addWidget(item)
            self.navigation.idClicked.connect(self.navigate);side.addStretch()
            self.demo_button=button("查看合成演示",self.toggle_demo,name="demo_button")
            side.addWidget(self.demo_button)
            side.addWidget(button("数据格式规范",self.open_contract))
            side.addWidget(label("统一计算 · 自动发布\n指标与视图同步更新","muted"))
            layout.addWidget(sidebar)
        content=QWidget();body=QVBoxLayout(content);body.setContentsMargins(23,19,23,12);body.setSpacing(12)
        header=QHBoxLayout();self.page_title=label(MODULE_TITLES[0],"title");header.addWidget(self.page_title)
        header.addStretch()
        self.mode=label("数据待接入","pill");header.addWidget(self.mode)
        self.refresh_button=button("刷新",self.refresh,name="refresh_button");header.addWidget(self.refresh_button)
        body.addLayout(header)
        self.pages=QStackedWidget();body.addWidget(self.pages,1)
        self.market_pages=MarketPages(self);self.dashboard=self.market_pages.overview
        for page in self.market_pages.pages: self.pages.addWidget(page)
        if self.developer:
            replay=Panel();row=QHBoxLayout()
            row.addWidget(label("历史回放","muted"));self.play_button=button("播放历史",self.toggle_play)
            row.addWidget(self.play_button);self.slider=QSlider(Qt.Orientation.Horizontal);self.slider.setEnabled(False)
            self.slider.valueChanged.connect(self.scrub);row.addWidget(self.slider,1)
            self.speed=QComboBox();self.speed.addItems(("1×","5×","10×"));row.addWidget(self.speed)
            self.save_replay=QCheckBox("保存回放结果");row.addWidget(self.save_replay)
            row.addWidget(button("返回最新",self.return_latest));replay.layout.addLayout(row)
            self.dashboard.body.insertWidget(self.dashboard.body.count()-1,replay)
            self.pages.addWidget(self.formula_page());self.pages.addWidget(self.settings_page());self.pages.addWidget(self.archive_page())
        self.status=label("正在加载指标…","muted");self.status.setWordWrap(True)
        body.addWidget(self.status);layout.addWidget(content,1)

    def formula_page(self):
        page=QWidget();layout=QHBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        left=QVBoxLayout();self.formula_list=QListWidget();self.formula_list.setFixedWidth(230)
        self.formula_list.currentRowChanged.connect(self.load_formula);left.addWidget(self.formula_list)
        left.addWidget(button("新增公式",self.new_formula));layout.addLayout(left)
        editor=Panel();top=QHBoxLayout()
        self.formula_name=QLineEdit();self.formula_name.setPlaceholderText("指标名称")
        self.formula_id=QLineEdit();self.formula_id.setPlaceholderText("formula_id")
        self.formula_unit=QLineEdit();self.formula_unit.setPlaceholderText("单位");self.formula_unit.setMaximumWidth(100)
        top.addWidget(self.formula_name,2);top.addWidget(self.formula_id,1);top.addWidget(self.formula_unit)
        editor.layout.addLayout(top)
        editor.layout.addWidget(label("compute(inputs, params) · 输入声明支持 $near / $far / $spot 与具体合约","muted"))
        self.code=QPlainTextEdit();self.code.setObjectName("formula_code");self.code.setFont(QFont("Consolas",12));self.code.setTabStopDistance(32)
        self.highlight=PythonHighlight(self.code.document());editor.layout.addWidget(self.code,2)
        tabs=QTabWidget();self.inputs_edit=QPlainTextEdit();self.params_edit=QPlainTextEdit()
        tabs.addTab(self.inputs_edit,"输入声明 · 频率 / 字段 / 窗口");tabs.addTab(self.params_edit,"参数")
        tabs.setMinimumHeight(180);editor.layout.addWidget(tabs,1)
        help_text=label("函数：last、column、sma、aligned_difference、zscore、mean、stdev、sqrt、log 等。\n先声明输入，再计算；缺数据显示原因，窗口不足返回 None。","muted")
        help_text.setWordWrap(True);editor.layout.addWidget(help_text)
        actions=QHBoxLayout();self.formula_enabled=QCheckBox("发布后启用");self.formula_enabled.setChecked(True)
        actions.addWidget(self.formula_enabled);actions.addStretch();actions.addWidget(button("当前时刻试算",self.preview_formula,name="preview_formula"))
        actions.addWidget(button("发布并加入看板",self.publish_formula,primary=True,name="publish_formula"))
        editor.layout.addLayout(actions)
        self.formula_response=label("请选择模板，或创建新的多频指标。","muted");self.formula_response.setWordWrap(True)
        editor.layout.addWidget(self.formula_response);layout.addWidget(editor,1)
        self.reload_formula_list()
        return page

    def settings_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        source=Panel("历史数据 · 只选择未来新下载的数据集")
        row=QHBoxLayout();row.addWidget(button("添加数据集目录",self.add_source,primary=True,name="add_source"))
        row.addWidget(button("移除选中来源",self.remove_source));row.addWidget(button("校验覆盖",self.inspect_sources));row.addStretch()
        source.layout.addLayout(row)
        self.sources_table=table(["数据集","代码数","频率","最新时刻","目录"]);self.sources_table.setMinimumHeight(150)
        source.layout.addWidget(self.sources_table)
        source.layout.addWidget(label("选择含 dataset.json 与 current.json 的目录；指数和具体股指合约可分两个数据集。","muted"))
        layout.addWidget(source)
        paths=Panel("保存路径与实时输入")
        form=QGridLayout()
        self.path_edits={}
        for i,(key,title,file_mode) in enumerate((("realtime_root","新的实时行情目录",False),
                 ("reference_file","新参考资料 reference.json",True),("results_root","看板结果保存目录",False),
                 ("publish_root","看板数据发布目录",False))):
            edit=QLineEdit(self.model.config.get(key,""));edit.setObjectName(key)
            self.path_edits[key]=edit
            form.addWidget(label(title,"muted"),i,0);form.addWidget(edit,i,1)
            form.addWidget(button("选择",lambda checked=False,k=key,f=file_mode:self.choose_path(k,f)),i,2)
        paths.layout.addLayout(form)
        self.unverified=QCheckBox("允许可用时刻未认证的数据用于研究展示（保留限制标记）")
        self.unverified.setChecked(self.model.config.get("allow_unverified",False));paths.layout.addWidget(self.unverified)
        paths.layout.addWidget(button("保存路径与设置",self.save_settings,primary=True,name="save_settings"));layout.addWidget(paths)
        release=Panel("看板发布 · 独立 Git")
        release.layout.addWidget(label("从当前共享视图与只读入口构建，自动包含本次界面和指标协议变化。","muted"))
        release.layout.addWidget(button("生成看板发布 Git",self.build_public_release,name="build_public_release"))
        release.layout.addWidget(button("生成全部阶段稿",self.build_stage_releases,name="build_stage_releases"))
        self.release_note=label("只导出公开文件与合成示例，不配置远端。","muted");self.release_note.setWordWrap(True)
        release.layout.addWidget(self.release_note);layout.addWidget(release)
        collection=Panel("实时采集 · 调用独立采集模块")
        self.symbols_edit=QPlainTextEdit(", ".join(self.model.config.get("collection_symbols",[])))
        self.symbols_edit.setMaximumHeight(75)
        collection.layout.addWidget(self.symbols_edit)
        collection.layout.addWidget(label("仅已注册 A 股指数及 IF/IH/IC/IM 具体年月合约。00/01 别名需新参考资料中的当日映射。","muted"))
        controls=QHBoxLayout()
        self.collect_once=button("采集一轮",lambda:self.start_collection(True),name="collect_once")
        self.collect_start=button("开始采集",lambda:self.start_collection(False),name="collect_start")
        controls.addWidget(self.collect_once);controls.addWidget(self.collect_start)
        controls.addWidget(button("停止采集",self.collection.stop if hasattr(self,"collection") else lambda:None))
        controls.addStretch();self.collect_label=label("未启动","muted");controls.addWidget(self.collect_label)
        collection.layout.addLayout(controls);layout.addWidget(collection)
        self.source_report=label("历史和实时源均不会自动绑定原项目其他市场库。","muted");self.source_report.setWordWrap(True)
        layout.addWidget(self.source_report);layout.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    def archive_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        note=label("按历史输入交易日保存；纯实时观测按接收日分区。包含公式版本、实际合约、截止时刻与来源版本。","banner")
        note.setWordWrap(True);layout.addWidget(note)
        actions=QHBoxLayout();actions.addWidget(button("刷新记录",self.load_archive))
        actions.addWidget(button("发布 Parquet",self.flush_archive));actions.addStretch();layout.addLayout(actions)
        self.archive_table=table(["数据交易日","指标","计算结果","数据类型","计算时刻"])
        layout.addWidget(self.archive_table,1)
        self.archive_note=label("尚无计算记录","muted");self.archive_note.setWordWrap(True);layout.addWidget(self.archive_note)
        return page

    def submit(self,function,callback=None,critical=False):
        if self.closing: return
        if self.busy:
            if critical: self.queue.append((function,callback))
            else: self.pending=True
            return
        self.busy=True;self.status.setText("正在读取与计算…")
        task=Task(function);self.active_task=task
        task.signals.completed.connect(lambda value:self.finish(value,callback))
        task.signals.failed.connect(lambda error:self.finish(error,None,failed=True))
        self.pool.start(task)

    def finish(self,value,callback,failed=False):
        self.busy=False;self.active_task=None
        if self.closing: return
        if failed:
            self.status.setText(value)
            if self.developer: self.formula_response.setText(value)
        elif callback:
            self.status.setText("已更新")
            try: callback(value)
            except Exception as exc: self.status.setText(str(exc))
        if self.queue:
            function,callback=self.queue.pop(0);self.submit(function,callback,critical=True)
        elif self.pending:
            self.pending=False;self.refresh()

    def request(self):
        return {"demo":self.demo,"product":self.product.currentText(),"frequency":self.frequency,
                "as_of":self.as_of,"save":self.developer and (self.as_of is None or self.save_replay.isChecked())}

    def refresh(self,*_,automatic=False):
        if self.closing: return
        self.generation+=1;generation=self.generation;request=self.request()
        def accepted(state):
            if generation==self.generation and state is not None: self.render(state)
            elif state is None: self.status.setText("无新增记录 · 保留最后数据时刻与图表")
        self.submit(lambda:self.model.auto_snapshot(request) if automatic else self.model.snapshot(request),accepted)

    def render(self,state):
        self.state=state
        self.market_pages.render(state)
        if self.developer:
            self.timeline=state["timeline"]
            self.slider.blockSignals(True);self.slider.setRange(0,max(0,len(self.timeline)-1))
            self.slider.setEnabled(bool(self.timeline))
            if self.timeline:
                selected=pd.Timestamp(state["as_of"])
                positions=[i for i,t in enumerate(self.timeline) if pd.Timestamp(t)<=selected]
                self.slider.setValue(positions[-1] if positions else 0)
            self.slider.blockSignals(False)
        self.loaded.emit(state)

    def navigate(self,index):
        if not 0<=index<self.pages.count():
            self.status.setText("页面不存在");return
        if self.navigation.button(index): self.navigation.button(index).setChecked(True)
        self.pages.setCurrentIndex(index)
        self.page_title.setText((*MODULE_TITLES,"公式工作台","数据与任务","结果档案")[index])
        if index==4: self.inspect_sources()
        if index==5: self.load_archive()

    def selection_changed(self,*_):
        self.play_timer.stop()
        if self.developer: self.play_button.setText("播放历史")
        self.as_of=None;self.timeline=[];self.refresh()

    def frequency_changed(self,index):
        self.frequency=("1d","1m","1s")[index];self.selection_changed()

    def toggle_demo(self):
        if self.collection and self.collection.running():
            self.status.setText("请先停止采集，再切换演示模式");return
        self.demo=not self.demo;self.selection_changed()

    def scrub(self,index):
        if self.developer and index<len(self.timeline): self.as_of=self.timeline[index];self.refresh()

    def toggle_play(self):
        if not self.developer: return
        if self.play_timer.isActive(): self.play_timer.stop();self.play_button.setText("播放历史")
        elif len(self.timeline)>1:
            if self.slider.value()>=len(self.timeline)-1: self.slider.setValue(len(self.timeline)//3)
            self.play_button.setText("暂停回放");self.play_timer.start()

    def advance(self):
        if self.busy or not self.developer: return
        target=min(len(self.timeline)-1,self.slider.value()+(1,5,10)[self.speed.currentIndex()])
        self.slider.setValue(target)
        if target>=len(self.timeline)-1: self.play_timer.stop();self.play_button.setText("播放历史")

    def return_latest(self):
        self.as_of=None;self.play_timer.stop()
        if self.developer: self.play_button.setText("播放历史")
        self.refresh()

    def periodic(self):
        if self.collection:
            state=self.collection.state()
            self.collect_label.setText(f"{state['status']} · {state['polls']} 轮 · {state['rows']} 条"+(" · "+state["error"] if state.get("error") else ""))
        # Publish keeps running on all developer pages; readers only poll snapshots.
        if not self.busy:
            if self.as_of is None: self.refresh(automatic=True)
            elif self.developer and hasattr(self.model,"maintain_publication"):
                request={**self.request(),"as_of":None,"save":False}
                self.submit(lambda:self.model.maintain_publication(request),
                    lambda _:self.status.setText("历史回放 · 共享最新指标继续更新"))

    def reload_formula_list(self):
        self.formula_list.blockSignals(True);self.formula_list.clear()
        for spec in self.model.formulas: self.formula_list.addItem(spec["name"]+(" · 停用" if not spec["enabled"] else ""))
        self.formula_list.blockSignals(False)
        self.formula_list.setCurrentRow(0)

    def load_formula(self,index):
        if not 0<=index<len(self.model.formulas): return
        spec=self.model.formulas[index]
        self.formula_name.setText(spec["name"]);self.formula_id.setText(spec["id"]);self.formula_unit.setText(spec["unit"])
        self.code.setPlainText(spec["code"]);self.inputs_edit.setPlainText(json.dumps(spec["inputs"],ensure_ascii=False,indent=2))
        self.params_edit.setPlainText(json.dumps(spec["params"],ensure_ascii=False,indent=2));self.formula_enabled.setChecked(spec["enabled"])
        self.formula_response.setText("版本 "+spec["version"]+" · 可试算后发布")

    def new_formula(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        self.load_formula(0);self.formula_list.setCurrentRow(-1)
        self.formula_id.setText("custom_"+uuid.uuid4().hex[:6]);self.formula_name.setText("新增指标")

    def editor_spec(self):
        return {"id":self.formula_id.text().strip(),"name":self.formula_name.text().strip(),"unit":self.formula_unit.text().strip(),
            "code":self.code.toPlainText(),"inputs":json.loads(self.inputs_edit.toPlainText()),
            "params":json.loads(self.params_edit.toPlainText()),"enabled":self.formula_enabled.isChecked()}

    def preview_formula(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        try: spec=self.editor_spec()
        except Exception as exc: self.formula_response.setText(str(exc));return
        request=self.request();self.formula_response.setText("正在读取声明的多频输入…")
        def done(item):
            self.formula_response.setText("试算："+json.dumps(item["values"],ensure_ascii=False)+f" · {sum(i['rows'] for i in item['inputs'])} 条输入")
            self.status.setText("试算完成，未写入计算档案")
        self.submit(lambda:self.model.preview(spec,request),done,critical=True)

    def publish_formula(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        try: spec=self.editor_spec()
        except Exception as exc: self.formula_response.setText(str(exc));return
        def done(value):
            self.reload_formula_list();self.formula_response.setText("已发布版本 "+value["version"])
            self.refresh()
        self.submit(lambda:self.model.publish_formula(spec),done,critical=True)

    def choose_path(self,key,file_mode):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        if file_mode: path,_=QFileDialog.getOpenFileName(self,"选择新下载的参考资料",str(self.model.local_root),"JSON (*.json)")
        else: path=QFileDialog.getExistingDirectory(self,"选择保存目录",str(self.model.local_root))
        if path: self.path_edits[key].setText(path)

    def save_settings(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        if self.collection.running(): self.status.setText("请先停止采集，再修改保存路径与订阅");return
        candidate=deepcopy(self.model.config)
        for key,edit in self.path_edits.items(): candidate[key]=edit.text().strip()
        if not candidate["results_root"]: self.status.setText("请选择看板结果保存目录");return
        if getattr(self.model,"edition",None)=="developer" and not candidate.get("publish_root"):
            self.status.setText("请选择看板数据发布目录");return
        candidate["allow_unverified"]=self.unverified.isChecked()
        candidate["product"]=self.product.currentText();candidate["frequency"]=self.frequency
        candidate["collection_symbols"]=list(dict.fromkeys(self.symbols_edit.toPlainText().upper().replace("，",",").replace("\n",",").replace(" ",",").split(",")))
        candidate["collection_symbols"]=[s.strip() for s in candidate["collection_symbols"] if s.strip()]
        if candidate["realtime_root"]!=self.model.config.get("realtime_root"):
            candidate["realtime_id"]=uuid.uuid4().hex
        def saved(value):
            self.source_report.setText("路径与订阅已保存。演示数据仍单独保存，不写入新真实数据目录。")
            self.refresh()
        self.submit(lambda:self.model.save_config(candidate),saved,critical=True)

    def build_public_release(self):
        if not self.developer: return
        from dashboard.build_public_repository import build_repository
        demo_path=Path(self.model.config.get("publish_root",""))/"demo.json"
        def built(path):
            self.release_note.setText("已更新独立 Git："+str(path))
            self.status.setText("看板代码已生成；可从独立仓库发布更新")
        self.submit(lambda:build_repository(demo_path=demo_path if demo_path.is_file() else None),built,critical=True)

    def build_stage_releases(self):
        if not self.developer: return
        from dashboard.build_stage_releases import build_all
        formulas=deepcopy(self.model.formulas)
        self.release_note.setText("正在生成 Excel 样稿、三个阶段 Git 与预览图……")
        def built(path):
            self.release_note.setText("全部阶段稿已生成："+str(path))
            self.status.setText("本批次完成；旧交付保留，各阶段使用同一份演示数据")
        self.submit(lambda:build_all(formulas=formulas),built,critical=True)

    def add_source(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        root=QFileDialog.getExistingDirectory(self,"选择新标准数据集目录",str(self.model.local_root))
        if not root: return
        candidate=deepcopy(self.model.config)
        if root not in candidate["history_roots"]: candidate["history_roots"].append(root)
        def saved(_): self.inspect_sources();self.refresh()
        self.submit(lambda:self.model.save_config(candidate),saved,critical=True)

    def remove_source(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        index=self.sources_table.currentRow()
        if not 0<=index<len(self.model.config["history_roots"]): return
        candidate=deepcopy(self.model.config);candidate["history_roots"].pop(index)
        self.submit(lambda:self.model.save_config(candidate),lambda _:self.inspect_sources(),critical=True)

    def inspect_sources(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        from dashboard.marketdata.repository import MarketDataRepository
        roots=list(self.model.config["history_roots"])
        def done(reports):
            rows=[]
            for report in reports:
                coverage=report["coverage"]
                last=max((r["last"] for r in coverage),default=None)
                rows.append([report["descriptor"]["dataset_id"],len(report["descriptor"]["instruments"]),
                    " / ".join(sorted({r["frequency"] for r in coverage})),
                    pd.Timestamp(last).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S") if last else "尚无已发布数据",report["root"]])
            fill_table(self.sources_table,rows)
            self.source_report.setText(f"{len(reports)} 个新数据源。"+("演示模式正在使用独立合成数据；此处仍是你的新真实数据设置。" if self.demo else "未绑定其他历史库。"))
        self.submit(lambda:[MarketDataRepository.inspect(root) for root in roots],done,critical=True)

    def start_collection(self,once):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        if self.demo: self.status.setText("退出合成演示后，选择新的实时目录再采集");return
        if self.path_edits["realtime_root"].text().strip()!=self.model.config.get("realtime_root","") or self.symbols_edit.toPlainText().replace(" ","")!=",".join(self.model.config["collection_symbols"]):
            self.status.setText("请先保存实时目录与订阅设置");return
        index_ids={code for code,_,_ in UNDERLYINGS.values()}
        if self.model.repo:
            index_ids.update(s for s,i in self.model.repo.symbols().items() if i["asset_type"]=="cn_index")
        try:
            self.collection.start(self.model.config["realtime_root"],self.model.config["collection_symbols"],index_ids,
                self.model.config.get("reference_file") or None,once=once)
            self.status.setText("已启动独立采集模块；停盘时返回的缓存报价仍标为源时间待核验。")
        except Exception as exc: self.status.setText(str(exc))

    def load_archive(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        def done(items):
            names={"spread":"跨期价差","basis_bp":"基差 bp","zscore":"Z 值","realized_bp":"波动 bp","percentile":"分位 %"}
            statuses={"synthetic":"合成","research":"研究观察","unverified_history":"历史质量受限","unverified_observation":"源日期待核验","warmup":"暖启动"}
            rows=[[r["trade_date"],r["name"]," · ".join(f"{names.get(k,k)}: {'缺失' if v is None else format(v,'.3f')}" for k,v in r["values"].items()),
                statuses.get(r["quality"],r["quality"]),pd.Timestamp(r["calculated_at"]).tz_convert("Asia/Shanghai").strftime("%m-%d %H:%M:%S")] for r in items]
            fill_table(self.archive_table,rows)
            root=self.model.result_directory()
            self.archive_note.setText(f"最近 {len(items)} 条 · 保存目录：{root}")
        self.submit(self.model.result_history,done,critical=True)

    def flush_archive(self):
        if not self.developer: self.status.setText("此功能仅开发者版可用");return
        self.submit(lambda:self.model.results.flush() if self.model.results and self.model.results.connection else None,
                    lambda _:self.load_archive(),critical=True)

    def open_contract(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/"data_contract"/"README.md")))

    def closeEvent(self,event):
        self.refresh_timer.stop();self.play_timer.stop()
        if self.collection: self.collection.stop()
        if self.busy or (self.collection and self.collection.running()):
            self.status.setText("正在结束后台任务并保存结果…")
            event.ignore();QTimer.singleShot(300,self.close);return
        self.closing=True;self.queue.clear();self.pending=False
        self.model.close();event.accept()


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
        from .card_views import QuotePanel,NonRegressionPanel
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
        self.stop_button=button("停止",self.collection.stop);header.addWidget(self.stop_button)
        header.addWidget(button("刷新",self.refresh));body.addLayout(header)
        dividend_line=QHBoxLayout();self.dividend_banner=label("正在读取固定分红情景…","banner");self.dividend_banner.setWordWrap(True);dividend_line.addWidget(self.dividend_banner,1)
        dividend_line.addWidget(button('分红与映射 →',lambda:self.navigate(2)));body.addLayout(dividend_line)
        self.pages=QTabWidget();body.addWidget(self.pages,1)
        self.quotes=QuotePanel();self.pages.addTab(self.quotes,"行情总览")
        study=QWidget();layout=QVBoxLayout(study);layout.setContentsMargins(0,6,0,0)
        types=QHBoxLayout();types.addWidget(label("研究类型","muted"));self.category=QComboBox(study);self.category.hide()
        self.category_buttons=QButtonGroup(self)
        for i,(title,key) in enumerate((("期现","basis"),("跨期","calendar"),("跨品种 · 同月","cross"))):
            self.category.addItem(title,key)
            item=button(title);item.setCheckable(True);item.setMinimumWidth(130);self.category_buttons.addButton(item,i);types.addWidget(item)
        self.category_buttons.button(0).setChecked(True)
        self.category_buttons.idClicked.connect(self.category.setCurrentIndex);types.addStretch();layout.addLayout(types)
        controls=QHBoxLayout()
        self.left=QComboBox();self.right=QComboBox();self.price=QComboBox()
        self.cross_pair=QComboBox();self.cross_pair.addItem("全部品种对","all")
        from .card_data import CROSS_PAIRS
        for a,b in CROSS_PAIRS:self.cross_pair.addItem(a+" − "+b,a+"/"+b)
        for title,key in (("真实期货价格","future"),("分红调整基差","basis"),("分红调整年化基差","annual")):self.price.addItem(title,key)
        self.price.setCurrentIndex(1)
        for title,widget in (("合约 / 近月",self.left),("远月",self.right),("品种对",self.cross_pair),("适用指标输入",self.price)):
            controls.addWidget(label(title,"muted"));controls.addWidget(widget)
        controls.addStretch();layout.addLayout(controls)
        self.indicators=NonRegressionPanel();layout.addWidget(self.indicators,1);self.pages.addTab(study,"指标研究")
        for widget in (self.category,self.left,self.right,self.price,self.cross_pair):widget.currentIndexChanged.connect(self.selection_changed)
        self.quotes.changed.connect(self.selection_changed)
        self.pages.addTab(self.settings_page(),"数据管理 / 设置")
        from .history_maintenance import HistoryMaintenance,MaintenancePage
        self.history_maintenance=HistoryMaintenance(model)
        self.maintenance_page=MaintenancePage(self.history_maintenance)
        self.pages.addTab(self.maintenance_page,"数据维护")
        self.pages.currentChanged.connect(self.update_dividend_banner)
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
        return dict(cards=True,category=self.category.currentData(),research_month=self.left.currentData(),
            far_month=self.right.currentData(),cross_pair=self.cross_pair.currentData(),price_input=self.price.currentData(),
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
        def rendered(state):
            if generation==self.generation:self.render(state)
            else:self.pending=True
        def read():
            if self.model.config.get('reference_file') or self.model.config.get('realtime_root'):
                self.model.sync_contract_reference()
            return self.model.snapshot(request)
        self.submit(read,rendered)

    def selection_changed(self,*_):
        self.generation+=1
        self.category_buttons.button(self.category.currentIndex()).setChecked(True)
        if self.category.currentData()=="cross" and self.price.currentData()=="future":
            self.price.blockSignals(True);self.price.setCurrentIndex(1);self.price.blockSignals(False)
        self.price.model().item(0).setEnabled(self.category.currentData()!="cross")
        if self.state:self.set_contract_choices(self.state,preserve=True)
        self.quotes.container.setEnabled(False)
        self.status.setText("正在切换选择；页面保留上一组带代码和日期的数据，计算完成后整体更新。")
        self.refresh()

    def set_contract_choices(self,state,preserve=False):
        from .card_views import month_text,replace_choices
        selection=state['selection'];months=selection['months']
        left=self.left.currentData() if preserve else selection['research_month']
        right=self.right.currentData() if preserve else selection['far_month']
        replace_choices(self.left,[(month_text(m),m) for m in months],left)
        options=[m for m in months if m>self.left.currentData()] if self.left.currentData() else []
        replace_choices(self.right,[(month_text(m),m) for m in options],right)
        self.right.setEnabled(self.category.currentData()=="calendar")
        self.cross_pair.setEnabled(self.category.currentData()=="cross")

    def render(self,state):
        self.state=state;self.set_contract_choices(state)
        self.quotes.render(state);self.indicators.render(state)
        self.update_dividend_banner()
        info=state["dividend_info"]
        fmtdate=lambda v:pd.Timestamp(v).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M")
        fill_table(self.coverage_table,[[r["product"],r["frequency"],r["symbols"],fmtdate(r["first"]),fmtdate(r["last"]),r["dataset_id"]] for r in state["coverage"]])
        self.paths_note.setPlainText("\n".join(["历史："+p for p in self.model.config["history_roots"]]+["实时："+self.model.config.get("realtime_root",""),"分红："+self.model.config.get("dividend_root","")]))
        self.mapping.setPlainText(info.get('mapping_policy','固定分红情景映射')+"\n"+"\n".join(f"{v['alias']} → {s} | 到期 {v['expiry']} | D={v['points']:.6f} 点"+(' | 沿用 '+v['inherited_from'] if v.get('inherited_from') else '') for s,v in info.get("mapping",{}).items())+"\n"+state["dividend_reason"])
        reference=getattr(self.model,'contract_sync',{})
        collection_note=' · 实时采集中' if self.collection.running() else ' · 点击开始实时启动采集'
        self.status.setText("本地数据刷新 "+fmtdate(state["as_of"])+" · "+reference.get('message','合约参考待更新')+collection_note)
        self.loaded.emit(state)

    def update_dividend_banner(self,*_):
        state=self.state
        if not state:return
        self.dividend_banner.setToolTip('')
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
        try:
            symbols=[v[0] for v in UNDERLYINGS.values()]
            self.collection.start(self.model.config["realtime_root"],symbols,
                set(symbols),self.model.config.get("reference_file"),once=once,auto_roll=True)
            self.periodic()
        except Exception as exc:self.status.setText(str(exc))

    def update_contract_reference(self):
        if self.busy:
            self.status.setText('当前任务完成后会自动检查合约；查询失败每5分钟重试。');return
        self.submit(lambda:self.model.sync_contract_reference(force=True),lambda _:self.refresh())

    def navigate(self,index):
        if 0<=index<self.pages.count():self.pages.setCurrentIndex(index)

    def choose_import(self):
        if self.busy:self.status.setText("当前任务尚在执行，请稍后导入。");return
        from dashboard.marketdata.paths import DATA_ROOT,HISTORY_ROOT
        files,_=QFileDialog.getOpenFileNames(self,"选择已下载批次清单",str(DATA_ROOT),"JSON (*.json)")
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

    def choose_standard(self):
        if self.busy:self.status.setText("当前任务尚在执行，请稍后注册。");return
        from dashboard.marketdata.paths import DATA_ROOT
        root=QFileDialog.getExistingDirectory(self,"选择 dashboard_bars_v1 标准目录",str(DATA_ROOT))
        if not root:return
        def register():
            from dashboard.marketdata.ddb_import import validate_standard
            validate_standard(root)
            config=deepcopy(self.model.config);config["history_roots"]=list(dict.fromkeys(config["history_roots"]+[root]));self.model.save_config(config)
        self.submit(register,lambda _:self.refresh())

    def choose_dividends(self):
        if self.busy:return
        root=QFileDialog.getExistingDirectory(self,"选择仅含缓存分红文件的目录",self.model.config.get("dividend_root",""))
        if not root:return
        config=deepcopy(self.model.config);config["dividend_root"]=root;config["dividend_mode"]="fixed_snapshot"
        self.submit(lambda:self.model.save_config(config),lambda _:self.refresh())

    def create_scenario(self):
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
            answer=QMessageBox.question(self,"保存明确的固定情景映射",text)
            if answer!=QMessageBox.StandardButton.Yes:return
            path=HISTORY_ROOT.parent/"dividend_scenarios"/(scenario["version"]+".json")
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():path.write_text(json.dumps(scenario,ensure_ascii=False,indent=2),encoding="utf-8")
            config=deepcopy(self.model.config);config.update(dividend_mode="fixed_snapshot",dividend_scenario_file=str(path))
            self.submit(lambda:self.model.save_config(config),lambda _:self.refresh())
        except Exception as exc:self.status.setText(str(exc))

    def choose_daily_dividends(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,"选择按日期/具体合约的剩余分红",self.model.config.get("dividend_root",""),"JSON (*.json)")
        if not path:return
        from dashboard.marketdata.dividends import DividendBook
        book=DividendBook.load(self.model.config.get("dividend_root",""),daily_file=path,mode="daily_remaining")
        if book.reason:self.status.setText(book.reason);return
        config=deepcopy(self.model.config);config.update(dividend_mode="daily_remaining",daily_dividend_file=path)
        self.submit(lambda:self.model.save_config(config),lambda _:self.refresh())

    def closeEvent(self,event):
        self.refresh_timer.stop();self.collection.stop()
        self.history_maintenance.stop();self.history_maintenance.tick()
        if self.history_maintenance.process is not None:
            event.ignore();QTimer.singleShot(100,self.close);return
        if self.busy or self.collection.running():
            event.ignore();QTimer.singleShot(100,self.close);return
        self.closing=True;self.model.close();event.accept()
