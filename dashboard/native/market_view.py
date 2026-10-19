"""Three shared market views built from read-only indicator snapshots."""
from datetime import timezone,timedelta
import math

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup,QCheckBox,QComboBox,QHBoxLayout,QHeaderView,
    QScrollArea,QTableWidget,QTableWidgetItem,QTabWidget,QVBoxLayout,QWidget,QPushButton)

from .instruments import UNDERLYINGS
from .theme import ACCENT,CHART_COLORS,MUTED,UP,DOWN
from .widgets import Chart,MetricCard,Panel,curve,label
from .basis_panel import BasisResearchPanel
from .presentation import (MODULE_TITLES,FREQUENCY_OPTIONS,SHOW_SPECIAL,SHOW_EVENTS,
    SHOW_DETAIL,SHOW_EVENT_DETAIL,METRIC_ROWS,CHART_OPTIONS,MATRIX_TITLE,OVERVIEW_TEXT)

PRODUCTS=tuple(UNDERLYINGS)
CHINA=timezone(timedelta(hours=8))


class QuotePanel(Panel):
    """Company HTTP observations only; historical reference is a separate field."""
    def __init__(self):
        super().__init__("基础实时行情 · 16个具体股指期货 / 4个指数")
        self.note=label("等待HTTP观测；不会使用旧历史价格补齐实时腿。","muted")
        self.note.setWordWrap(True);self.layout.addWidget(self.note)
        self.table=make_table(["标的","最新价","较昨收%","开 / 高 / 低","累计成交量","买一 × 量","卖一 × 量","实时持仓","历史持仓 / 日期","到期日","源时分秒","行情状态"],660)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(31)
        self.layout.addWidget(self.table)
        self.detail=label("点击行查看接收时间、日期推定状态和原始字段。","muted")
        self.detail.setWordWrap(True);self.layout.addWidget(self.detail)
        self.rows=[];self.table.currentCellChanged.connect(self.select)

    def render(self,state):
        selected=self.table.currentRow();self.rows=state["quotes"]
        rows=[]
        for q in self.rows:
            oi=number(q.get("open_interest"),0) if q.get("oi_status")=="source_reported" else "不可用"
            rows.append([q["symbol"],number(q["close"]),number(q["change_pct"],2,True),
                " / ".join(number(q[k],1) for k in ("open","high","low")),number(q["volume_total"],0),
                number(q["bid_price_1"],1)+" × "+number(q["bid_volume_1"],0),number(q["ask_price_1"],1)+" × "+number(q["ask_volume_1"],0),
                oi,number(q["history_oi"],0)+" / "+(q["history_oi_date"] or "—"),q["expiry"] or "—",q["quote_time"] or "—",q["quality"]["status"]])
        self.table.blockSignals(True);fill_table(self.table,rows);self.table.blockSignals(False)
        self.table.setCurrentCell(max(0,selected),0);self.select()
        self.note.setText("最新价使用 latestPrice；累计量不逐轮相加。实时OI缺失时只另列带日期的历史持仓。源行情日期未经认证；陈旧报价仅留作缓存查看。")

    def select(self,*_):
        i=self.table.currentRow()
        if not 0<=i<len(self.rows): return
        q=self.rows[i]
        self.detail.setText(f"{q['symbol']}  · 接收 {q.get('received_at') or '—'}  · 源时分秒 {q.get('quote_time') or '—'}  · 日期按接收日推定，未认证\n"
            f"昨收 {number(q.get('prev_close'))}  · OI原值 {number(q.get('open_interest_raw'),0)} / {q.get('oi_reason') or '—'}  · "
            f"{'源标记完成' if q.get('is_final') else '未完成/盘中'}  · 区间增量 {number(q.get('volume'),0)}  · {q.get('snapshot_status') or '旧版观测'}")


def number(value,digits=2,signed=False):
    if not isinstance(value,(int,float)) or not math.isfinite(value): return "—"
    return format(value,("+" if signed else "")+","+f".{digits}f")


def when(stamp,full=False):
    if not stamp: return "—"
    try: return pd.Timestamp(stamp).tz_convert(CHINA).strftime("%m-%d %H:%M:%S" if full else "%H:%M:%S")
    except (ValueError,TypeError): return "—"


def make_table(headers,height):
    item=QTableWidget(0,len(headers));item.setHorizontalHeaderLabels(headers)
    item.verticalHeader().hide();item.verticalHeader().setDefaultSectionSize(32)
    item.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    item.setAlternatingRowColors(True);item.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    item.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    item.setMinimumHeight(height)
    return item


def fill_table(widget,rows,tooltips=None):
    widget.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,value in enumerate(row):
            cell=QTableWidgetItem(str(value));cell.setToolTip(str(value))
            if tooltips and i<len(tooltips): cell.setToolTip(tooltips[i])
            if j: cell.setTextAlignment(Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignCenter)
            widget.setItem(i,j,cell)


def latest(state,key="near"):
    frame=state.get(key,pd.DataFrame())
    if frame.empty: return None,None
    return float(frame.iloc[-1].close),frame.iloc[-1].event_time.isoformat()


def quality(state):
    if state.get("demo"): return "合成演示"
    if state.get("publication_stale"): return "数据源未更新"
    if state.get("replay"): return "历史回放"
    if state.get("history_limited"): return "历史观测 · 时序待核验"
    if not len(state.get("near",[])): return "待接入"
    price,stamp=latest(state)
    limit={"1d":129600,"1m":120,"1s":5}.get(state.get("frequency"),120)
    if stamp and (pd.Timestamp.now(tz="UTC")-pd.Timestamp(stamp)).total_seconds()>limit:
        return "历史观测"
    return "已对齐观测"


class MarketPage(QScrollArea):
    def __init__(self,host):
        super().__init__();self.host=host;self.states={};self.state=None
        self.setWidgetResizable(True);self.setFrameShape(QScrollArea.Shape.NoFrame)
        body=QWidget();self.body=QVBoxLayout(body);self.body.setContentsMargins(0,0,0,0);self.body.setSpacing(12)
        self.setWidget(body)


class MarketOverviewPage(MarketPage):
    def __init__(self,host):
        super().__init__(host)
        self.banner=label("IF / IH / IC / IM · 同一口径横向比较","banner");self.banner.setWordWrap(True)
        self.body.addWidget(self.banner)
        controls=QHBoxLayout();controls.addWidget(label("采样频率","muted"))
        host.frequency_group=QButtonGroup(host);host.frequency_group.setExclusive(True)
        for frequency,title in FREQUENCY_OPTIONS:
            index=("1d","1m","1s").index(frequency)
            b=QPushButton(title);b.setObjectName("freq_"+frequency);b.setCheckable(True);b.setChecked(host.frequency==frequency)
            host.frequency_group.addButton(b,index);controls.addWidget(b)
        host.frequency_group.idClicked.connect(host.frequency_changed)
        controls.addStretch();controls.addWidget(label("详情品种","muted"))
        host.product=QComboBox();host.product.addItems(PRODUCTS);host.product.setCurrentText(host.model.config.get("product","IC"))
        host.product.currentTextChanged.connect(host.selection_changed);controls.addWidget(host.product)
        self.time_label=label("数据时刻 —","muted");controls.addWidget(self.time_label)
        self.body.addLayout(controls)
        cards=QHBoxLayout();self.cards={}
        for index,product in enumerate(PRODUCTS):
            card=MetricCard(product+" · "+UNDERLYINGS[product][1],"合约待接入")
            card.value.setStyleSheet(f"color:{CHART_COLORS[index]};font-size:28px;font-weight:600;")
            self.cards[product]=card;cards.addWidget(card)
        self.body.addLayout(cards)
        panel=Panel(MATRIX_TITLE)
        self.matrix=make_table(["指标 / 口径",*PRODUCTS,"单位"],max(185,len(METRIC_ROWS)*28+40))
        self.matrix.verticalHeader().setDefaultSectionSize(28)
        self.matrix.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        panel.layout.addWidget(self.matrix)
        self.body.addWidget(panel)
        tabs=QTabWidget();compare=QWidget();layout=QVBoxLayout(compare);layout.setContentsMargins(0,8,0,0)
        row=QHBoxLayout();self.chart_metric=QComboBox()
        self.chart_metric.addItems([item[0] for item in CHART_OPTIONS])
        self.chart_metric.currentIndexChanged.connect(self.draw_comparison);row.addWidget(self.chart_metric)
        self.product_checks={}
        for index,product in enumerate(PRODUCTS):
            check=QCheckBox(product);check.setChecked(True);check.setStyleSheet(f"color:{CHART_COLORS[index]};")
            check.toggled.connect(self.draw_comparison);self.product_checks[product]=check;row.addWidget(check)
        row.addStretch();row.addWidget(label("勾选品种，可仅显示一个","muted"));layout.addLayout(row)
        self.comparison=Chart("四品种 · 期现基差","bp",height=195);layout.addWidget(self.comparison)
        tabs.addTab(compare,"同指标对比")
        if SHOW_DETAIL: self.build_details(tabs)
        self.body.addWidget(tabs);self.body.addStretch()

    def build_details(self,tabs):
        host=self.host
        detail=QTabWidget()
        host.basis_chart=Chart("期现基差","bp",height=235)
        host.spread_chart=Chart("近月 − 远月","点",height=235)
        host.term_chart=Chart("同期合约期限结构","点",height=235,term=True)
        host.price_chart=Chart("期货 / 指数 · 窗口收益","bp",height=235)
        for name,chart in (("期现",host.basis_chart),("跨期",host.spread_chart),("期限结构",host.term_chart),("期货与现货",host.price_chart)):
            detail.addTab(chart,name)
        tabs.addTab(detail,"单品种详情")

    def render(self,state,states):
        self.state=state;self.states=states;h=self.host;freq=state["frequency"]
        self.banner.setText("合成演示 · 以下价格和异动均为虚构，非真实行情" if state["demo"] else
                            OVERVIEW_TEXT)
        self.time_label.setText("所选品种数据时刻 "+when(latest(state)[1],True))
        for product,card in self.cards.items():
            s=states.get(product,{});price,stamp=latest(s)
            basis=s.get("values",{}).get("basis_bp")
            card.update_value(price,caption=f"{s.get('roles',{}).get('$near') or '合约待接入'}  ·  基差 {number(basis,signed=True)} bp")
            card.setToolTip(f"{when(stamp,True)} · {quality(s)}")
        rows=[];tips=[]
        for title,key,unit in METRIC_ROWS:
            values=[];reasons=[]
            for product in PRODUCTS:
                s=states.get(product,{});a=s.get("analytics",{})
                value=latest(s)[0] if key=="near_price" else latest(s,"spot")[0] if key=="spot_price" else a.get(key,s.get("values",{}).get(key))
                values.append(number(value,3 if key in ("beta","r_squared") else 2))
                reason=a.get("reasons",{}).get(key) or s.get("reasons",{}).get(key)
                reasons.append(product+"："+(reason or f"{quality(s)} · 数据时刻 {when(latest(s)[1],True)}"))
            rows.append([title,*values,unit]);tips.append("\n".join(reasons))
        fill_table(self.matrix,rows,tips);self.draw_comparison()
        if SHOW_DETAIL: self.draw_details(state)

    def draw_details(self,state):
        h=self.host;freq=state["frequency"]
        for chart,key in ((h.basis_chart,"basis"),(h.spread_chart,"spread")):
            x,y=curve(state.get(key,pd.DataFrame()),"value",freq)
            chart.draw([(state["product"],x,y)] if x else [],key=(state["product"],freq,key),note=quality(state)+" · 仅交易时段；缺口断线",frequency=freq)
        term=state.get("term",[]);h.term_chart.draw([("期货",list(range(len(term))),[r["close"] for r in term])] if term else [],
            key=(state["product"],freq,"term"),ticks=[(i,t["symbol"].replace(".CFE","")) for i,t in enumerate(term)],
            note="同一事件时刻的具体合约价格 · 到期信息"+("已核验" if state.get("contracts_verified") else "待核验"))
        series=[]
        # Normalize over a shared intersection, so both lines use one anchor timestamp.
        near=state.get("near",pd.DataFrame());spot=state.get("spot",pd.DataFrame())
        if len(near) and len(spot):
            stamps=set(near.event_time)&set(spot.event_time)
            for name,frame in (("期货",near),("指数",spot)):
                x,y=curve(frame[frame.event_time.isin(stamps)],frequency=freq,normalize=True)
                if x: series.append((name,x,y))
        h.price_chart.draw(series,key=(state["product"],freq,"price"),note="共同起点的累计价格收益 · bp；休市折叠",frequency=freq)

    def draw_comparison(self,*_):
        if self.state is None: return
        metric=self.chart_metric.currentIndex();freq=self.state["frequency"]
        _,key,field,normalize=CHART_OPTIONS[metric]
        chosen=[p for p in PRODUCTS if self.product_checks[p].isChecked()]
        frames={p:self.states.get(p,{}).get(key,pd.DataFrame()) for p in chosen}
        if key=="spread":
            normalized={}
            for p,frame in frames.items():
                spot=self.states.get(p,{}).get("spot",pd.DataFrame())
                if len(frame) and len(spot):
                    sample=frame[["event_time","trade_date","session_id","value"]].merge(
                        spot[["event_time","trade_date","session_id","close"]],on=["event_time","trade_date","session_id"])
                    sample=sample[sample.close>0].copy();sample["value"]=sample["value"] / sample.close * 10000
                    normalized[p]=sample
                else: normalized[p]=pd.DataFrame()
            frames=normalized
        # Price performance is comparable only from a common timestamp.
        if normalize:
            valid=[set(f.event_time) for f in frames.values() if len(f)]
            common=set.intersection(*valid) if valid else set()
            frames={p:f[f.event_time.isin(common)] if len(f) else f for p,f in frames.items()}
        series=[]
        for p,frame in frames.items():
            x,y=curve(frame,field,freq,normalize)
            if x: series.append((p,x,y))
        title=self.chart_metric.currentText();self.comparison.title_label.setText("四品种 · "+title.split(" / ")[0])
        self.comparison.plot.setLabel("left",title.split(" / ")[-1],color=MUTED)
        self.comparison.draw(series,key=(freq,metric,tuple(chosen)),
            note=("共同起点收益" if normalize else "同指标按各自指数标准化")+" · 休市折叠，缺口断线 · 拖动 / 滚轮缩放",frequency=freq)


class SpecialIndicatorsPage(MarketPage):
    def __init__(self,host):
        super().__init__(host)
        intro=label("专题指标 · 将价格偏离、统计偏离与成本条件分开观察","banner")
        intro.setWordWrap(True);self.body.addWidget(intro)
        if SHOW_DETAIL:
            self.research_panel=BasisResearchPanel()
            self.body.addWidget(self.research_panel)
        row=QHBoxLayout();self.basis_card=MetricCard("期现 · 理论价偏离","融资、预计股息与有效到期日待接入")
        self.carry_card=MetricCard("跨期 · 隐含年化持有收益","近远月有效到期日待接入")
        self.etf_card=MetricCard("ETF · 折溢价 / IOPV","ETF 价格、IOPV、申赎清单与成本待接入")
        for card in (self.basis_card,self.carry_card,self.etf_card): row.addWidget(card)
        self.body.addLayout(row)
        pairpanel=Panel("跨股指相对价值 · 收益回归与同期限基差差")
        self.pair_table=make_table(["组合 · A / B","基差差 / bp","收益 β","R²","残差 / bp","残差 Z","样本 / 状态"],176)
        pairpanel.layout.addWidget(self.pair_table)
        note=label("A 的收益对 B 回归；同期限基差差 = A 基差 − B 基差。跨指数为相对价值观察，需额外验证关系稳定性与交易成本。","muted")
        note.setWordWrap(True);pairpanel.layout.addWidget(note);self.body.addWidget(pairpanel)
        custom=Panel("自定义指标 · 自动加载新增指标与版本")
        host.factor_table=make_table(["指标","IF","IH","IC","IM","单位 / 输入频率","版本 / 状态"],225)
        host.factor_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        custom.layout.addWidget(host.factor_table)
        self.custom_note=label("窗口与频率由每个指标声明，缺失结果保留空值与原因。","muted");self.custom_note.setWordWrap(True)
        custom.layout.addWidget(self.custom_note);self.body.addWidget(custom)
        definitions=Panel("指标口径")
        text=label("期现基差 = (F / S − 1) × 10,000 bp；跨期 = (近月 − 远月) / S × 10,000 bp。\n理论价与净空间需融资、预计股息、到期日、手续费及冲击成本。ETF 折溢价需同期 IOPV。\n回归用前 30 个同步对数收益拟合：rA = α + β · rB + ε；展示当前残差与历史尺度。","muted")
        text.setWordWrap(True);definitions.layout.addWidget(text);self.body.addWidget(definitions);self.body.addStretch()

    def render(self,state,states):
        self.state=state;self.states=states
        if SHOW_DETAIL:
            self.research_panel.render(state.get("pair_research",{}),state.get("demo",False))
        carry=state.get("analytics",{}).get("carry",{})
        carry_reasons=carry.get("reasons",{})
        self.basis_card.update_value(carry.get("fair_deviation_bp")," bp",caption=
            "简单股息率模型 · ACT/365 · 模型偏离" if carry.get("fair_deviation_bp") is not None else
            carry_reasons.get("fair_value") or carry_reasons.get("expiry") or "融资、预计股息与有效到期日待接入")
        self.carry_card.update_value(carry.get("implied_carry_pct"),"%",caption=
            "近远月同期价格 · ACT/365" if carry.get("implied_carry_pct") is not None else
            carry_reasons.get("implied_carry_pct") or carry_reasons.get("expiry") or "近远月有效到期日待接入")
        reason_text="；".join(carry.get("reasons",{}).values())
        self.basis_card.setToolTip(reason_text);self.carry_card.setToolTip(reason_text)
        pairs=state.get("relative_value",[])
        if not pairs:
            pairs=next((s.get("relative_value",[]) for s in states.values() if s.get("relative_value")),[])
        rows=[]
        for pair in pairs:
            status=pair.get("reasons",{}).get("beta") or f"{pair.get('samples',0)} / 30 · 观测"
            rows.append([pair["left"]+" / "+pair["right"],number(pair.get("basis_gap_bp"),signed=True),
                number(pair.get("beta"),3),number(pair.get("r_squared"),3),number(pair.get("residual_bp"),signed=True),
                number(pair.get("residual_z"),signed=True),status])
        fill_table(self.pair_table,rows or [["IF / IH","—","—","—","—","—","等待同期数据"],["IC / IM","—","—","—","—","—","等待同期数据"]])
        headers={};factors={}
        for product,s in states.items():
            for factor in s.get("factors",[]):
                spec=factor["spec"]
                keys=list(factor.get("values",{})) or [""]
                for key in keys:
                    identity=(spec["id"],key);headers[identity]=(spec,key);factors[(product,identity)]=factor
        custom_rows=[];tips=[]
        for identity,(spec,key) in headers.items():
            cells=[];statuses=[];versions=[]
            for product in PRODUCTS:
                factor=factors.get((product,identity),{});value=factor.get("values",{}).get(key)
                cells.append(number(value));statuses.append(product+"："+(factor.get("error") or factor.get("quality","待接入")))
                if factor: versions.append(factor["spec"]["version"])
            frequencies=" / ".join(dict.fromkeys(i.get("frequency","观测") for i in spec.get("inputs",[])))
            version="一致 " + versions[0][:8] if len(set(versions))==1 and versions else "版本不同 / 待接入"
            title=spec["name"]+(" · "+key if key and key!=spec["name"] else "")
            custom_rows.append([title,*cells,(spec.get("unit") or "—")+" · "+frequencies,version]);tips.append("\n".join(statuses))
        fill_table(self.host.factor_table,custom_rows,tips)
        self.custom_note.setText(f"当前 {len(custom_rows)} 个结果项 · 所选品种 {state['product']} · {quality(state)}。悬停查看各品种数据状态。")


class MarketEventsPage(MarketPage):
    def __init__(self,host):
        super().__init__(host)
        self.banner=label("偏离事件 · |Z| ≥ 2 连续 3 根触发，同一持续状态合并","banner")
        self.banner.setWordWrap(True);self.body.addWidget(self.banner)
        top=QHBoxLayout();self.event_count=MetricCard("偏离事件","当前窗口内 · 最近 24 条")
        self.coverage=MetricCard("数据覆盖","四品种同步指标输入")
        top.addWidget(self.event_count)
        if SHOW_EVENT_DETAIL:
            self.ongoing_count=MetricCard("末窗持续偏离","数据失效时转为历史观测");top.addWidget(self.ongoing_count)
        top.addWidget(self.coverage)
        self.body.addLayout(top)
        panel=Panel("偏离事件记录")
        columns=["首次触发 · 北京时间","品种","事件","当前 / 末值"]
        if SHOW_EVENT_DETAIL: columns.extend(["峰值 |Z|","持续根数"])
        columns.append("状态");self.event_table=make_table(columns,260)
        if SHOW_EVENT_DETAIL: self.event_table.currentCellChanged.connect(self.select_event)
        panel.layout.addWidget(self.event_table)
        self.empty_note=label("等待足够的同步历史数据。","muted");self.empty_note.setWordWrap(True);panel.layout.addWidget(self.empty_note)
        self.body.addWidget(panel)
        if SHOW_EVENT_DETAIL:
            self.event_chart=Chart("事件依据 · 价格偏离序列","bp",height=230);self.body.addWidget(self.event_chart)
            self.event_detail=label("检测基差、跨期与回归残差；默认观察阈值未经盈利有效性验证。","muted")
            self.event_detail.setWordWrap(True);self.body.addWidget(self.event_detail)
        self.body.addStretch();self.events=[]

    def render(self,state,states):
        self.state=state;self.states=states
        self.events=sorted([e for s in states.values() for e in s.get("events",[])],key=lambda e:e["event_time"],reverse=True)[:24]
        coverage=sum(bool(len(s.get("near",[]))) and bool(len(s.get("spot",[]))) for s in states.values())
        self.event_count.value.setText(str(len(self.events)))
        if SHOW_EVENT_DETAIL:
            ongoing=sum((e.get("lifecycle") or e.get("status"))=="active" for e in self.events)
            self.ongoing_count.value.setText(str(ongoing))
        self.coverage.value.setText(f"{coverage} / 4")
        rows=[]
        for e in self.events:
            status={"active":"持续偏离","recovered":"已恢复","observed":"历史观测"}.get(e.get("status"),"观测")
            if state["demo"]: status="演示 · "+status
            row=[when(e["event_time"],True),e["product"],e["title"],number(e.get("value"),signed=True)+" "+e.get("unit","σ")]
            if SHOW_EVENT_DETAIL: row.extend([number(e.get("peak")),str(e.get("duration","—"))])
            rows.append([*row,status])
        self.event_table.blockSignals(True);fill_table(self.event_table,rows);self.event_table.blockSignals(False)
        self.empty_note.setText("合成演示事件：价格、回归与触发时间均为虚构。" if state["demo"] else
            "历史观测保留检测结果；数据未更新或时间不可核验时，不显示为当前可交易机会。" if rows else "当前窗口未发现满足阈值的事件，或同步样本不足。")
        if SHOW_EVENT_DETAIL:
            if rows: self.event_table.setCurrentCell(0,0);self.select_event(0)
            else: self.event_chart.draw([],key=(state["frequency"],"empty")),self.event_detail.setText("|Z| ≥ 2 连续 3 根；回归需要 30 个历史训练收益。")

    def select_event(self,row,*_):
        if not 0<=row<len(self.events): return
        e=self.events[row];state=self.states.get(e["product"],{});kind=e.get("type","")
        key="regression" if "residual" in kind or "regression" in kind else "basis" if "basis" in kind else "spread"
        frame=state.get(key,pd.DataFrame());x,y=curve(frame,"value",state.get("frequency","1m"))
        self.event_chart.plot.setLabel("left","点" if key=="spread" else "bp",color=MUTED)
        self.event_chart.readout.setText("点" if key=="spread" else "bp")
        self.event_chart.title_label.setText(e["product"]+" · "+e["title"]+" · 原始序列")
        self.event_chart.draw([(e["product"],x,y)] if x else [],key=(e["product"],key,state.get("frequency")),
            note="触发 "+when(e["event_time"],True)+" · "+quality(state)+" · 休市折叠；事件强度为 Z",frequency=state.get("frequency","1m"))
        self.event_detail.setText(f"{e['product']} · {e['title']} · |Z| 阈值 {e.get('threshold',2)} · 持续 {e.get('duration','—')} 根 · "
            +("演示观测" if state.get("demo") else quality(state))+"。当前样本不进入历史均值、标准差与回归拟合。")


class MarketPages:
    def __init__(self,host):
        self.host=host;self.overview=MarketOverviewPage(host);self.pages=[self.overview]
        if SHOW_SPECIAL:
            self.special=SpecialIndicatorsPage(host);self.pages.append(self.special)
        if SHOW_EVENTS:
            self.events=MarketEventsPage(host);self.pages.append(self.events)

    def render(self,state):
        host=self.host
        states=host.model.market_states(state["frequency"],state["demo"]) if hasattr(host.model,"market_states") and not state.get("replay") else {}
        states[state["product"]]=state
        for product in PRODUCTS:
            states.setdefault(product,{"product":product,"frequency":state["frequency"],"demo":state["demo"]})
        for item in states.values():
            if quality(item)!="已对齐观测":
                for event in item.get("events",[]): event["status"]="observed"
        for page in self.pages: page.render(state,states)
        host.mode.setText("合成演示" if state["demo"] else quality(state))
        host.status.setText(state.get("publication_error") or state.get("publish_error") or
            f"{quality(state)} · {state['frequency']} · 截止 {when(state['as_of'],True)} · 数值为空时悬停查看原因")
        if host.demo_button is not None: host.demo_button.setText("返回数据看板" if state["demo"] else "查看合成演示")
