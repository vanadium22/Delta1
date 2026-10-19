"""The single dashboard component used unchanged by developer and viewer editions."""
import math
import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup,QCheckBox,QComboBox,QHBoxLayout,QHeaderView,
    QPushButton,QScrollArea,QSlider,QTabWidget,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from .theme import ACCENT, MUTED, UP, DOWN
from .widgets import Chart,MetricCard,Panel,curve,label

PRODUCT_NAMES = {"IF":"沪深300","IH":"上证50","IC":"中证500","IM":"中证1000"}


def stamp(value):
    return pd.Timestamp(value).tz_convert("Asia/Shanghai").strftime("%m-%d %H:%M:%S") if value else "—"


def number(value,suffix=""):
    return f"{value:,.2f}{suffix}" if isinstance(value,(float,int)) and math.isfinite(value) else "—"


def observation_rows(state):
    values = state["values"]
    product = state["product"]
    near = state["roles"]["$near"] or product+" 近端"
    far = state["roles"]["$far"] or product+" 远端"
    frames = {"spread":state["spread"],"basis_bp":state["basis"],"zscore":state["spread"],"realized_bp":state["near"]}
    definitions = (("spread",near+" / "+far,"跨期价差"," 点",0,"近端 − 远端；两腿同刻对齐"),
        ("basis_bp",near+" / "+PRODUCT_NAMES[product],"期现基差"," bp",1,"未扣除分红、资金成本与交易费用"),
        ("zscore",product+" 跨期价差","价差 Z 值","",0,"此前 30 条；当前值不入参照窗"),
        ("realized_bp",near,"短窗实现波动"," bp",3,"连续 30 个收益；非年化"))
    rows = []
    for key,obj,title,unit,chart,explanation in definitions:
        value = values[key]
        frame = frames[key]
        latest = frame.iloc[-1].event_time if len(frame) else None
        cutoff=pd.Timestamp(state["as_of"]) if state["demo"] or state["replay"] else pd.Timestamp.now(tz="UTC")
        historical = latest is not None and (cutoff-pd.Timestamp(latest)).total_seconds()>{"1d":129600,"1m":120,"1s":5}[state["frequency"]]
        quality = "待接入" if value is None else "研究观察"
        if value is not None:
            if state["demo"]: quality="合成演示"
            elif state.get("publication_stale"): quality="发布已过期"
            elif historical: quality="历史观察"
            elif state["history_limited"]: quality="质量待核验"
            elif latest is None: quality="源时间待核验"
            elif key=="zscore" and abs(value)>=2: quality="偏离观察"
        reason = state["reasons"].get(key,explanation)
        if key=="zscore" and values["percentile"] is not None:
            reason += f" · 历史分位 {values['percentile']:.0f}%"
        rows.append({"id":key,"columns":[obj,title,number(value,unit),quality,stamp(latest),reason],"chart":chart})
    rows.append({"id":"etf","columns":[PRODUCT_NAMES[product]+" ETF","折溢价 / 量能异动","—","待接入","—",
        "ETF 行情与 IOPV 尚未下载；不构造交易信号"],"chart":None})
    for factor in state["factors"]:
        spec = factor["spec"]
        result = " · ".join(k+": "+number(v) for k,v in factor.get("values",{}).items()) or "—"
        quality = "输入不足" if factor.get("error") else "暖启动" if factor["quality"]=="warmup" else "已发布指标"
        if state["demo"] and not factor.get("error"): quality="合成演示"
        elif state.get("publication_stale"): quality="发布已过期"
        elif factor["quality"] in {"unverified_history","unverified_observation"}: quality="质量待核验"
        frequencies = " / ".join(dict.fromkeys(i.get("frequency","实时观测") for i in spec["inputs"]))
        rows.append({"id":spec["id"],"columns":[spec["name"],"自定义 · "+frequencies,result,quality,"—",
            factor.get("error") or "版本 "+spec["version"]+" · 单位 "+(spec["unit"] or "未指定")],"chart":None})
    return rows


class DashboardPage(QScrollArea):
    def __init__(self,window):
        super().__init__()
        self.window = w = window
        self.setWidgetResizable(True)
        self.setObjectName("shared_dashboard")
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,8,0);layout.setSpacing(11)
        w.banner=label("真实数据待接入","banner");w.banner.setWordWrap(True);layout.addWidget(w.banner)
        controls=QHBoxLayout();controls.addWidget(label("观察品种","muted"))
        w.product=QComboBox();w.product.addItems(list(PRODUCT_NAMES));w.product.setCurrentText(w.model.config.get("product","IC"))
        w.product.setObjectName("product_selector");w.product.currentTextChanged.connect(w.selection_changed)
        controls.addWidget(w.product);controls.addSpacing(14)
        w.frequency_group=QButtonGroup(w);w.frequency_group.setExclusive(True)
        for i,(value,title) in enumerate((("1d","日频"),("1m","分钟"),("1s","秒级"))):
            item=QPushButton(title);item.setObjectName("freq_"+value);item.setCheckable(True);item.setChecked(value==w.frequency)
            w.frequency_group.addButton(item,i);controls.addWidget(item)
        w.frequency_group.idClicked.connect(w.frequency_changed)
        controls.addStretch();w.time_label=label("行情截至 —","muted");controls.addWidget(w.time_label)
        layout.addLayout(controls)
        summary=QHBoxLayout()
        insight=Panel();insight.layout.addWidget(label("优先关注","muted"))
        self.insight=label("等待行情与参考数据","section");insight.layout.addWidget(self.insight)
        self.insight_note=label("先看偏离，再核对数据与成交条件。","muted");self.insight_note.setWordWrap(True);insight.layout.addWidget(self.insight_note)
        summary.addWidget(insight,2)
        quality=Panel();quality.layout.addWidget(label("数据状态","muted"));self.quality=label("待接入","section");quality.layout.addWidget(self.quality)
        quality.layout.addWidget(label("缺数据时不显示“无异动”","muted"));summary.addWidget(quality,1)
        etf=Panel();etf.layout.addWidget(label("ETF 观察池","muted"));etf.layout.addWidget(label("待接入","section"));etf.layout.addWidget(label("行情 · IOPV · 同刻对齐","muted"));summary.addWidget(etf,1)
        layout.addLayout(summary)
        indices=QHBoxLayout();w.index_cards=[]
        for name in PRODUCT_NAMES.values():
            card=MetricCard(name,"正式前收待补充");card.setMinimumHeight(96)
            w.index_cards.append(card);indices.addWidget(card,1)
        layout.addLayout(indices)
        signals=Panel();head=QHBoxLayout();head.addWidget(label("机会与异动观察","section"));head.addStretch()
        head.addWidget(label("单击查看依据 · 异动不等于可成交机会","muted"));signals.layout.addLayout(head)
        w.factor_table=QTableWidget(0,6);w.factor_table.setObjectName("signal_table")
        w.factor_table.setHorizontalHeaderLabels(["观察对象","指标","当前值","状态","行情时刻","依据 / 限制"])
        w.factor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        w.factor_table.horizontalHeader().setStretchLastSection(True)
        for i,width in enumerate((220,145,165,100,135,290)): w.factor_table.setColumnWidth(i,width)
        w.factor_table.verticalHeader().hide();w.factor_table.verticalHeader().setDefaultSectionSize(37)
        w.factor_table.setAlternatingRowColors(True);w.factor_table.setShowGrid(False)
        w.factor_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        w.factor_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        w.factor_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        w.factor_table.setMinimumHeight(220);w.factor_table.setMaximumHeight(220)
        w.factor_table.itemSelectionChanged.connect(self.select_evidence)
        signals.layout.addWidget(w.factor_table);layout.addWidget(signals)
        self.detail=label("选择一条指标查看计算依据。","muted");self.detail.setWordWrap(True);layout.addWidget(self.detail)
        self.charts=QTabWidget();self.charts.setObjectName("evidence_tabs")
        w.spread_chart=Chart("跨期价差轨迹","点",height=205)
        w.basis_chart=Chart("期现基差","bp",height=205)
        w.term_chart=Chart("期限结构","指数点",height=205,term=True)
        w.price_chart=Chart("指数与期货 · 区间表现","bp",height=205)
        for chart,title in ((w.spread_chart,"跨期价差"),(w.basis_chart,"期现基差"),(w.term_chart,"期限结构"),(w.price_chart,"区间表现")):
            self.charts.addTab(chart,title)
        layout.addWidget(self.charts)
        w.book_label=label("盘口观测：待接入。","muted");w.book_label.setWordWrap(True);layout.addWidget(w.book_label)
        if w.developer:
            playback=Panel();row=QHBoxLayout()
            w.play_button=QPushButton("播放历史");w.play_button.setObjectName("play_button");w.play_button.clicked.connect(w.toggle_play);row.addWidget(w.play_button)
            w.slider=QSlider(Qt.Orientation.Horizontal);w.slider.setObjectName("replay_slider");w.slider.setRange(0,0);w.slider.valueChanged.connect(w.scrub);row.addWidget(w.slider,1)
            w.speed=QComboBox();w.speed.addItems(["1×","5×","10×"]);row.addWidget(w.speed)
            w.save_replay=QCheckBox("保存回放");row.addWidget(w.save_replay)
            latest=QPushButton("返回最新");latest.clicked.connect(w.return_latest);row.addWidget(latest)
            playback.layout.addLayout(row);playback.layout.addWidget(label("开发者回放独立于共享快照；回放不会覆盖精简版的最新指标。","muted"));layout.addWidget(playback)
        layout.addStretch();self.setWidget(page);self.rows=[]

    def select_evidence(self,switch_chart=True):
        index=self.window.factor_table.currentRow()
        if not 0<=index<len(self.rows): return
        row=self.rows[index];self.selected_id=row["id"]
        cols=row["columns"]
        self.detail.setText(" · ".join((cols[0],cols[1],cols[2],cols[3],cols[5]))+
            (" · 当前为标量结果，下方可切换查看市场背景图。" if row["chart"] is None else ""))
        if switch_chart and row["chart"] is not None: self.charts.setCurrentIndex(row["chart"])

    def render(self,state):
        w=self.window
        has_data=bool(state["versions"] or state["live_quotes"])
        stale=state.get("publication_stale",False)
        w.mode.setText("合成演示" if state["demo"] else "历史回放" if state["replay"] else "指标观察" if has_data else "数据待接入")
        if w.demo_button: w.demo_button.setText("退出合成演示" if w.demo else "查看合成演示")
        w.banner.setText("合成演示 · 所有价格、日期与指标仅供交互测试，不代表真实市场。" if state["demo"] else
            "指标观察 · 基差尚未扣除分红与成本；ETF 数据待接入。" if has_data else "真实数据尚未接入。指标保留空值，等待开发者配置数据并发布。")
        if state.get("publication_error"): w.banner.setText(w.banner.text()+" "+state["publication_error"])
        elif stale: w.banner.setText(w.banner.text()+" 发布已超过 120 秒未更新，保留最后快照；请检查开发者版。")
        if state["history_limited"] and not state["demo"]: w.banner.setText(w.banner.text()+" 输入时间或质量待核验。")
        latest=max((r["time"] for r in state["indices"] if r["time"]),default=None)
        w.time_label.setText("行情截至 "+stamp(latest))
        for card,row in zip(w.index_cards,state["indices"]):
            change="前收待核验" if row["change"] is None else f"相对前收 {row['change']:+.2f}%"
            card.update_value(row["close"],caption=("接收时间 · 源日期待核验" if row.get("observation") else change)+" · "+stamp(row["time"]))
            color=MUTED if row["change"] is None else UP if row["change"]>0 else DOWN if row["change"]<0 else ACCENT
            card.value.setStyleSheet("color:"+color+";")
        z=state["values"]["zscore"]
        self.insight.setText("等待行情与参考数据" if z is None else f"{state['product']} 价差 Z 值 {z:+.2f}"+ (" · 偏离观察" if abs(z)>=2 else " · 窗口内观察"))
        self.insight_note.setText("发布已过期；下方保留历史结果。" if stale else "历史偏离用于观察；请结合盘口、分红、成本和流动性核验。")
        self.quality.setText("发布已过期" if stale and has_data else "合成演示" if state["demo"] else "质量待核验" if state["history_limited"] else "已接入" if has_data else "待接入")
        selected=getattr(self,"selected_id","spread")
        self.rows=observation_rows(state);table=w.factor_table;scroll_position=table.verticalScrollBar().value()
        table.blockSignals(True);table.setRowCount(len(self.rows))
        for i,row in enumerate(self.rows):
            for j,value in enumerate(row["columns"]):
                item=QTableWidgetItem(value);item.setToolTip(value)
                if j==2: item.setForeground(QColor(ACCENT))
                table.setItem(i,j,item)
        table.selectRow(next((i for i,r in enumerate(self.rows) if r["id"]==selected),0));table.blockSignals(False)
        table.verticalScrollBar().setValue(scroll_position)
        self.select_evidence(switch_chart=False)
        key=(state["product"],state["frequency"],state["demo"])
        x,y=curve(state["spread"],"value",w.frequency)
        w.spread_chart.draw([("近端−远端",x,y)] if x else [],key=key,note="同一时刻 / 交易日 / 会话对齐；缺口与午休断线")
        x,y=curve(state["basis"],"value",w.frequency)
        w.basis_chart.draw([("期货 / 指数 − 1",x,y)] if x else [],key=key,note="原始价格基差，未扣除分红、资金成本与交易费用")
        points=state["term"]
        w.term_chart.draw([("合约价格",list(range(len(points))),[r["close"] for r in points])] if points else [],key=key,
            ticks=[(i,r["symbol"].split('.')[0]) for i,r in enumerate(points)],note="同刻具体合约 · "+("挂牌资料已配置" if state["contracts_verified"] else "挂牌 / 到期资料待补"))
        lines=[]
        for name,frame in (("对应指数",state["spot"]),("近端期货",state["near"])):
            x,y=curve(frame,frequency=w.frequency,normalize=True)
            if x: lines.append((name,x,y))
        w.price_chart.draw(lines,key=key,note="相对各自区间首价的变化；与正式日涨跌分开")
        book=state["book"]
        w.book_label.setText((f"盘口观测：买入价差 {book['buy']:.2f} · 卖出价差 {book['sell']:.2f} · " if book else "盘口观测：")+state["book_reason"])
        if w.developer:
            w.timeline=state["timeline"];w.slider.blockSignals(True);w.slider.setRange(0,max(0,len(w.timeline)-1))
            if w.as_of is None: w.slider.setValue(max(0,len(w.timeline)-1))
            w.slider.blockSignals(False);w.play_button.setEnabled(len(w.timeline)>1)
            w.collect_once.setEnabled(not w.demo);w.collect_start.setEnabled(not w.demo)
        w.status.setText(f"{len(state['spread'])} 条对齐记录 · "+("合成演示" if state["demo"] else "数据待接入" if not has_data else "研究观察")+
            (" · 共享快照 "+state["publication_id"][:8] if state.get("publication_id") else ""))
        for key,title in (("archive_error","结果未保存"),("publish_error","共享发布失败"),("publication_error","发布状态")):
            if state.get(key): w.status.setText(w.status.text()+f" · {title}："+state[key])
