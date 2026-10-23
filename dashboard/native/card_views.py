"""Native overview cards and drill-down research panels (no network operations)."""
import math
from html import escape

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox,QComboBox,QFrame,QGridLayout,QHBoxLayout,QLabel,
    QPushButton,QScrollArea,QStackedWidget,QTabWidget,QTextBrowser,QVBoxLayout,QWidget)

from .theme import ACCENT,BORDER,CHART_COLORS,MUTED,PANEL,TEXT
from .widgets import Chart,Panel,label
from .continuous import SLOT_NAMES
from .indicator_help import explain_metric


def chart_font(plot):
    font=QFont('Microsoft YaHei UI');font.setPixelSize(14)
    for axis in ('left','bottom'):
        plot.getAxis(axis).setStyle(tickFont=font)
    plot.getAxis('left').setWidth(72)


def number(value, digits=2):
    return f"{value:,.{digits}f}" if isinstance(value,(int,float)) and math.isfinite(value) else "—"


def stamp(value, short=False):
    if value is None:return "—"
    try:
        t=pd.Timestamp(value).tz_convert("Asia/Shanghai")
        return t.strftime("%m-%d %H:%M" if short else "%Y-%m-%d %H:%M:%S")
    except (ValueError,TypeError):return str(value)


def month_text(value):
    return f"20{value[:2]}年{value[2:]}月" if len(value)==4 else "暂无合约"


def replace_choices(combo, items, selected):
    combo.blockSignals(True)
    wanted=[(str(title),key) for title,key in items]
    if [(combo.itemText(i),combo.itemData(i)) for i in range(combo.count())]!=wanted:
        combo.clear()
        for title,key in wanted:combo.addItem(title,key)
    i=combo.findData(selected)
    combo.setCurrentIndex(i if i>=0 else 0)
    combo.blockSignals(False)


def scroll_widget():
    scroll=QScrollArea();scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content=QWidget();scroll.setWidget(content)
    return scroll,content


def display_metric(row):
    if row is None:return None,"—","无此项数据"
    if row.get("current") is not None:
        scope=row.get("current_scope") or ("采集区间" if "采集以来" in row["scope"] else "盘中")
        return row["current"],row["unit"],scope+" "+stamp(row.get("current_time"),True)
    if row.get("value") is not None:
        return row["value"],row["unit"],("最后有效历史 " if row.get("last_valid") else "历史 ")+stamp(row.get("time"),True)
    return None,row["unit"],"缺少数据"


class QuantilePlot(pg.PlotWidget):
    """P25/P75 box, P50 median, P5/P95 whiskers and an explicitly dated marker."""
    def __init__(self):
        super().__init__(background=PANEL)
        self.setMinimumHeight(175);self.setMaximumHeight(195)
        self.setMenuEnabled(False);self.setMouseEnabled(x=False,y=False)
        self.hideButtons();self.showGrid(y=True,x=False,alpha=.12)
        chart_font(self);self.getAxis("bottom").setStyle(tickTextOffset=5)
        self.getAxis("bottom").setHeight(62)
        for axis in ("left","bottom"):
            self.getAxis(axis).setPen(BORDER);self.getAxis(axis).setTextPen(MUTED)
        self.last_key=None

    def render(self,data,color):
        key=repr(data)
        if key==self.last_key:return
        self.last_key=key;self.clear();self.setLabel("left",data["unit"])
        ticks=[];bounds=[];rows=data.get("rows",[])
        for i,r in enumerate(rows):
            suffix=f"分位 {r['percentile']:.0f}%" if r.get('percentile') is not None else r.get('reason') or '—'
            if r.get('percentile') is not None and r.get('missing'):suffix+=f" · 缺{r['missing']}日"
            ticks.append((i,f"{r['title']} · n={r['n']}\n{suffix}"))
            if r.get("available",r["complete"]):
                lo,hi=r["p05"],r["p95"];bounds.extend((lo,hi))
                self.addItem(pg.ErrorBarItem(x=np.array([i]),y=np.array([(lo+hi)/2]),height=np.array([hi-lo]),beam=.17,pen=pg.mkPen(color,width=1.5)))
                brush=pg.mkColor(color);brush.setAlpha(65)
                self.addItem(pg.BarGraphItem(x=[i],width=.38,y0=[r["p25"]],height=[r["p75"]-r["p25"]],brush=brush,pen=pg.mkPen(color)))
                self.plot([i-.19,i+.19],[r["p50"]]*2,pen=pg.mkPen(TEXT,width=2))
            if data.get("value") is not None:
                marker="#f59195" if data["kind"]=="盘中观测" else ACCENT
                self.plot([i],[data["value"]],pen=None,symbol="d",symbolSize=9,symbolPen=marker,
                    symbolBrush=marker if data["kind"]=="盘中观测" else PANEL)
        if data.get("value") is not None:bounds.append(data["value"])
        self.getAxis("bottom").setTicks([ticks]);self.setXRange(-.5,max(.5,len(rows)-.5),padding=0)
        if bounds:
            low,high=min(bounds),max(bounds);pad=max((high-low)*.12,abs(low)*.01,.03)
            self.setYRange(low-pad,high+pad,padding=0)
        else:
            self.setYRange(-1,1);text=pg.TextItem("连续档位历史不足或缺少分红情景",color=MUTED,anchor=(.5,.5));text.setFont(QFont('Microsoft YaHei UI',11));text.setPos(1.5,0);self.addItem(text)


class ProductCard(Panel):
    def __init__(self,root,color):
        super().__init__();self.root=root;self.color=color
        self.layout.setContentsMargins(16,12,16,12);self.layout.setSpacing(7)
        self.setMinimumWidth(470)
        header=QHBoxLayout();self.heading=label(root,"title");self.heading.setStyleSheet(f"color:{color};font-size:24px;font-weight:700")
        header.addWidget(self.heading);header.addStretch();self.contract=label("—","section");header.addWidget(self.contract);self.layout.addLayout(header)
        self.context=label("等待本地数据","muted");self.context.setWordWrap(True);self.layout.addWidget(self.context)
        self.index_quote=label("对应指数 —","muted");self.index_quote.setWordWrap(True);self.layout.addWidget(self.index_quote)
        self.value_grid=QGridLayout();self.value_grid.setHorizontalSpacing(14);self.values={};self.captions={};self.value_boxes=[];self.value_columns=0
        for key,title in (("price","最新期货价"),("volume","累计成交 · 手"),("basis","调整基差 · bp"),("annual","简单年化 · %")):
            box=QWidget();vbox=QVBoxLayout(box);vbox.setContentsMargins(0,0,0,0);vbox.setSpacing(2);vbox.addWidget(label(title,"muted"))
            value=label("—","metric");value.setStyleSheet("font-size:33px;font-weight:600")
            vbox.addWidget(value);self.values[key]=value
            caption=label("—","muted");caption.setWordWrap(True)
            vbox.addWidget(caption);self.captions[key]=caption;self.value_boxes.append(box)
        self.layout.addLayout(self.value_grid);self.reflow_values()
        self.chart_caption=label("分位参考","muted");self.chart_caption.setWordWrap(True);self.layout.addWidget(self.chart_caption)
        self.chart=QuantilePlot();self.layout.addWidget(self.chart)
        self.footer=label("箱体 P25—P75 · 中线 P50 · 须线 P5—P95 · ◇ 有日期的定位值","muted")
        self.footer.setWordWrap(True);self.layout.addWidget(self.footer)
        self.detail_button=QPushButton("展开报价、分红与换月映射");self.detail_button.setCheckable(True);self.detail_button.setObjectName('action')
        self.layout.addWidget(self.detail_button)
        self.details=label("","muted");self.details.setWordWrap(True);self.details.hide();self.layout.addWidget(self.details)
        self.detail_button.toggled.connect(self.details.setVisible)
        self.detail_button.toggled.connect(lambda checked:self.detail_button.setText('收起报价、分红与换月映射' if checked else '展开报价、分红与换月映射'))

    def reflow_values(self):
        columns=4 if self.width()>=680 else 2
        if columns==self.value_columns:return
        self.value_columns=columns
        for i,box in enumerate(self.value_boxes):self.value_grid.addWidget(box,i//columns,i%columns)
        for i in range(4):self.value_grid.setColumnStretch(i,1 if i<columns else 0)

    def resizeEvent(self,event):
        super().resizeEvent(event);self.reflow_values()

    def render(self,row):
        q=row["quote"];current=row["current"];quality=row["quality"]
        self.heading.setText(f"{(row.get('alias') or row['root']).replace('.CFE','')}  ·  {row['symbol'].replace('.CFE','')}");self.contract.setText(row['name'])
        fresh=quality["usable"]
        d_label='逐日剩余 D' if (row.get('continuity') or {}).get('mode')=='continuous_daily_dividends' else '固定 D'
        if row.get('dividend_inherited_from'):d_label='D沿用 '+row['dividend_inherited_from'].replace('.CFE','')
        self.context.setText(f"{quality['status']} · 源 {stamp(q.get('source_event_time'),True)} · {d_label} {number(row['dividend'],4)} 点")
        self.context.setToolTip("期货与指数分别校验源时间和接收时间；源日期未认证。\n"+row["reason"])
        spot=row.get('spot') or {}
        self.index_quote.setText(f"对应指数 {row['spot_symbol']}  {number(spot.get('close'))} · 源 {stamp(spot.get('source_event_time'),True)}")
        self.index_quote.setToolTip(f"对应指数接收 {stamp(spot.get('received_at'))}；期货与指数源时分别保留。\n"+row['reason'])
        self.values["price"].setText(number(q.get("close")))
        self.values["volume"].setText(number(q.get("volume_total"),0))
        for key in ("price","volume"):
            self.values[key].setStyleSheet(f"font-size:33px;font-weight:600;color:{ACCENT if fresh else MUTED}")
            self.captions[key].setText("盘中观测" if fresh else "缓存行情")
        self.values["basis"].setText(number(current["bp"]))
        self.values["annual"].setText(number(current["annual_pct"]))
        points=current["points"]
        self.captions["basis"].setText(number(points)+" 点" if points is not None else "无有效同步期现报价" if not row["aligned"] else "缺少分红映射")
        self.captions["annual"].setText("临期 T<5，隐藏" if row["days"] is not None and row["days"]<5 else f"T={row['days']} 自然日" if row["days"] is not None else "到期日缺失")
        chart=row["chart"]
        self.chart_caption.setText(f"连续档位{'年化' if chart['unit']=='%' else '基差'}分位 · {chart['kind']} {stamp(chart['time'],True)} · {number(chart['value'])} {chart['unit']}")
        self.chart.render(chart,self.color)
        self.chart.setToolTip('\n'.join(f"{r['title']}：有效 {r['n']} 日，临期排除 {r.get('excluded',0)} 日，缺失 {r.get('missing',0)} 日"
            + ('：'+', '.join(r['missing_dates']) if r.get('missing_dates') else '') for r in chart.get('rows',[])))
        self.footer.setText("参考截至 "+stamp(chart.get('reference_end'),True)+" · 箱 P25—75 / 线 P50 / 须 P5—95")
        continuity=row.get('continuity') or {};rolls=[];previous=None
        for item in continuity.get('mappings',[]):
            identity=(item['symbol'],item['expiry'])
            if identity!=previous:
                rolls.append(f"{item['date']} → {item['symbol'] or '映射缺失'} · 到期 {item['expiry'] or '—'}");previous=identity
        self.details.setText(f"到期 {row['expiry'] or '—'} · D={number(row['dividend'],4)}点 · 接收 {stamp(q.get('received_at'))}\n"
            f"开/高/低 {number(q.get('open'))} / {number(q.get('high'))} / {number(q.get('low'))} · 昨收 {number(q.get('prev_close'))}\n"
            f"买一 {number(q.get('bid_price_1'))} × {number(q.get('bid_volume_1'),0)} · 卖一 {number(q.get('ask_price_1'))} × {number(q.get('ask_volume_1'),0)}\n"
            f"指数源时刻 {stamp(row['spot'].get('source_event_time'))} · 指数接收 {stamp(row['spot'].get('received_at'))}\n"
            f"实时持仓 {q.get('oi_reason') or q.get('oi_status') or '缺失'} · {'源标记完成' if q.get('is_final') else '未完成/盘中'} · 源日期按接收日推定\n"
            f"{row['reason']}\n指数 {row['spot_symbol']}：{number(row['spot'].get('close'))}；参考截至 {stamp(chart.get('reference_end'))}\n"
            f"{continuity.get('assumption','')}\n{continuity.get('policy','')}\n"
            f"历史参考排除定位当日；20交易日 / 3、6、12自然月窗口。年化排除T<5日，n为实际样本数；窗口缺日时按已有有效样本显示并标注缺口。\n"
            f"情景版本 {continuity.get('version','—')}\n换月记录（区间首日或合约变化日）：\n"+'\n'.join(rolls))


class QuotePanel(QWidget):
    changed=Signal()
    def __init__(self):
        super().__init__();layout=QVBoxLayout(self);layout.setContentsMargins(10,10,10,10)
        controls=QHBoxLayout();controls.addWidget(label("四品种行情","section"));controls.addSpacing(15)
        controls.addWidget(label("连续档位","muted"));self.month=QComboBox();self.month.setMinimumWidth(155);controls.addWidget(self.month)
        controls.addWidget(label("分位图","muted"));self.distribution=QComboBox()
        self.distribution.addItem("分红调整基差 · bp","basis");self.distribution.addItem("分红调整年化 · %","annual");controls.addWidget(self.distribution)
        controls.addStretch();layout.addLayout(controls)
        self.note=label("正在读取本地行情…","muted");self.note.setWordWrap(True);layout.addWidget(self.note)
        scroll,self.container=scroll_widget();grid=QGridLayout(self.container);grid.setContentsMargins(0,0,8,0);grid.setSpacing(12)
        self.cards={}
        for i,root in enumerate(("IF","IH","IC","IM")):
            card=ProductCard(root,CHART_COLORS[i]);grid.addWidget(card,i//2,i%2);self.cards[root]=card
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1);layout.addWidget(scroll,1)
        self.month.currentIndexChanged.connect(lambda *_:self.changed.emit())
        self.distribution.currentIndexChanged.connect(lambda *_:self.changed.emit())

    def render(self,state):
        selection=state["selection"]
        replace_choices(self.month,[(name,i) for i,name in enumerate(SLOT_NAMES)],selection['overview_slot'])
        self.container.setEnabled(True)
        for row in state["overview"]:self.cards[row["root"]].render(row)
        assumption='固定D情景，非逐日分红' if state['dividend_mode']=='fixed_snapshot' else '逐日具体合约剩余分红'
        self.note.setText(f"00—03为到期档位，非主力 · 分位按历日连续档位映射统计 · {assumption} · 灰色为缓存；◇ 历史定位带原日期")


class IndicatorCard(Panel):
    opened=Signal(str)
    def __init__(self,group):
        super().__init__();self.key=group["id"];self.rows={}
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(210)
        head=QHBoxLayout();head.addWidget(label(group["title"],"section"));head.addStretch()
        head.addWidget(label(group["id"]+"  ↗","muted"));self.layout.addLayout(head)
        self.subtitle=label("","muted");self.subtitle.setWordWrap(True);self.layout.addWidget(self.subtitle)
        grid=QGridLayout();grid.setHorizontalSpacing(18);grid.setVerticalSpacing(9)
        for i,e in enumerate(group["entities"]):
            box=QVBoxLayout();title=label(e["title"],"muted");box.addWidget(title)
            value=label("—","metric");value.setStyleSheet("font-size:30px;font-weight:600");box.addWidget(value)
            date=label("—","muted");date.setWordWrap(True);box.addWidget(date)
            grid.addLayout(box,i//2,i%2);self.rows[e["title"]]=(value,date,title)
        self.layout.addLayout(grid);self.layout.addStretch()
        self.open_button=QPushButton('查看图表与公式  →');self.open_button.setObjectName('action')
        self.open_button.clicked.connect(lambda:self.opened.emit(self.key));self.layout.addWidget(self.open_button);self.render(group)

    def render(self,group):
        first=next((r for e in group["entities"] for r in e["metrics"] if r["id"]==group["primary"]),None)
        self.subtitle.setText((first["title"]+" · "+first["unit"]) if first else "—")
        for e in group["entities"]:
            row=next((r for r in e["metrics"] if r["id"]==group["primary"]),None)
            value,unit,date=display_metric(row);vl,dl,title=self.rows[e["title"]]
            vl.setText(number(value,2));dl.setText(date);title.setToolTip(e['left']+" / "+e['right'])
            vl.setStyleSheet(f"font-size:30px;font-weight:600;color:{ACCENT if value is not None else MUTED}")
            vl.setToolTip((row["meaning"]+"\n"+(row.get('current_reason') or row['reason'])) if row else e.get('error') or '无此指标')

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):self.opened.emit(self.key)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space):self.opened.emit(self.key)
        else:super().keyPressEvent(event)


class NonRegressionPanel(QWidget):
    def __init__(self):
        super().__init__();self.groups={};self.cards={};self.group_key=None;self.current_group=None;self.plots=[];self.columns=0
        self.category='basis';self.price_input='basis'
        self.help_html=None;self.data_html=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.note=label("固定合约历史 · 参考窗口排除当前值","muted");self.note.setWordWrap(True);layout.addWidget(self.note)
        self.stack=QStackedWidget();layout.addWidget(self.stack,1)
        scroll,self.catalog=scroll_widget();self.catalog_layout=QVBoxLayout(self.catalog);self.catalog_layout.setContentsMargins(0,4,10,8)
        self.grid=QGridLayout();self.grid.setSpacing(12);self.catalog_layout.addLayout(self.grid)
        self.extra_button=QPushButton("待补输入的指标");self.extra_button.setCheckable(True);self.catalog_layout.addWidget(self.extra_button)
        self.extra=QWidget();self.extra_grid=QGridLayout(self.extra);self.extra.hide();self.catalog_layout.addWidget(self.extra)
        self.extra_button.toggled.connect(self.extra.setVisible);self.catalog_layout.addStretch();self.stack.addWidget(scroll)
        detail=QWidget();body=QVBoxLayout(detail);body.setContentsMargins(0,0,0,0)
        top=QHBoxLayout();self.back=QPushButton("← 指标目录");self.back.setObjectName('action');self.back.clicked.connect(lambda:self.stack.setCurrentIndex(0));top.addWidget(self.back)
        self.title=label("指标详情","section");top.addWidget(self.title);top.addStretch()
        body.addLayout(top);top=QHBoxLayout()
        self.submetric=QComboBox();self.submetric.setMinimumWidth(220);top.addWidget(self.submetric)
        self.view=QComboBox();self.view.addItem("多品种分面","facets");self.view.addItem("同单位叠加","overlay");top.addWidget(self.view)
        self.window=QComboBox()
        for title,n in (("全部历史",0),("最近20个观测",20),("最近60个观测",60),("最近120个观测",120)):self.window.addItem(title,n)
        top.addWidget(self.window);body.addLayout(top)
        self.detail_note=label("","muted");self.detail_note.setWordWrap(True);body.addWidget(self.detail_note)
        self.detail_tabs=QTabWidget();body.addWidget(self.detail_tabs,1)
        sc,self.chart_container=scroll_widget();self.plot_grid=QGridLayout(self.chart_container);self.plot_grid.setContentsMargins(0,0,8,0);self.plot_grid.setSpacing(12)
        self.detail_tabs.addTab(sc,'多品种图表')
        self.details=QTextBrowser();self.details.setOpenExternalLinks(False);self.detail_tabs.addTab(self.details,'公式与解释')
        self.data_details=QTextBrowser();self.detail_tabs.addTab(self.data_details,'数据时点与缺失')
        # Compatibility with existing native smoke checks; the visible entry is a tab.
        self.explain_button=QPushButton(self);self.explain_button.setCheckable(True);self.explain_button.hide()
        self.explain_button.toggled.connect(lambda checked:self.detail_tabs.setCurrentIndex(1 if checked else 0))
        self.stack.addWidget(detail)
        for combo in (self.submetric,self.view,self.window):combo.currentIndexChanged.connect(self.draw_detail)

    def render(self,state):
        self.category=state['category'];self.price_input=state['price_input']
        groups=state["metric_groups"];self.groups={g["id"]:g for g in groups}
        self.note.setText(state.get("pair_error") or state["comparison_note"]+" · 点击任一指标查看多品种图表")
        key=tuple((g["id"],tuple(e["title"] for e in g["entities"])) for g in groups)
        if key!=self.group_key:
            for card in self.cards.values():card.setParent(None);card.deleteLater()
            self.cards={};extra=0
            for g in groups:
                card=IndicatorCard(g);card.opened.connect(self.open_group);self.cards[g['id']]=card
                if g['extra']:self.extra_grid.addWidget(card,extra//2,extra%2);extra+=1
            self.columns=0;self.reflow_catalog()
            self.group_key=key
        else:
            for g in groups:self.cards[g['id']].render(g)
        if self.current_group in self.groups:
            self.set_submetrics();self.draw_detail()
        elif self.stack.currentIndex()==1:self.stack.setCurrentIndex(0);self.current_group=None

    def reflow_catalog(self):
        columns=3 if self.width()>=1400 else 2
        if columns==self.columns:return
        self.columns=columns;cards=[self.cards[k] for k,g in self.groups.items() if not g['extra'] and k in self.cards]
        for i,card in enumerate(cards):self.grid.addWidget(card,i//columns,i%columns)
        for i in range(3):self.grid.setColumnStretch(i,1 if i<columns else 0)

    def resizeEvent(self,event):
        super().resizeEvent(event);self.reflow_catalog()

    def open_group(self,key):
        if key not in self.groups:return
        self.current_group=key;self.set_submetrics(reset=True);self.stack.setCurrentIndex(1);self.detail_tabs.setCurrentIndex(0);self.draw_detail()

    def set_submetrics(self,reset=False):
        group=self.groups[self.current_group];items={r['id']:r['title']+" · "+r['unit'] for e in group['entities'] for r in e['metrics']}
        selected=group['primary'] if reset else self.submetric.currentData()
        replace_choices(self.submetric,[(title,key) for key,title in items.items()],selected)
        self.title.setText(group['title'])

    def draw_detail(self,*_):
        group=self.groups.get(self.current_group)
        if not group:return
        code=self.submetric.currentData();rows=[];n=self.window.currentData() or 0
        for e in group['entities']:
            r=next((r for r in e['metrics'] if r['id']==code),None)
            if r:rows.append((e,r))
        overlay=self.view.currentData()=='overlay'
        units={r['unit'] for _,r in rows}
        if len(units)>1:overlay=False
        needed=1 if overlay else len(rows)
        if len(self.plots)!=needed:
            for chart in self.plots:chart.setParent(None);chart.deleteLater()
            self.plots=[]
            for i in range(needed):
                chart=Chart("", "",height=230 if not overlay else 440);chart.note.setWordWrap(True)
                chart_font(chart.plot);chart.title_label.setStyleSheet('font-size:21px;font-weight:600')
                chart.note.setStyleSheet('font-size:15px');chart.readout.setStyleSheet('font-size:14px')
                chart.legend.setLabelTextSize('15px');chart.reset.setFixedHeight(38);chart.reset.setStyleSheet('font-size:15px;padding:5px 12px')
                if needed==1:
                    chart.plot.setMinimumHeight(300);chart.plot.setMaximumHeight(16777215)
                chart.readout.setMaximumWidth(230)
                self.plot_grid.addWidget(chart,i//2 if not overlay else 0,i%2 if not overlay else 0);self.plots.append(chart)
        series=[];descriptions=[];statuses=[]
        for i,(e,r) in enumerate(rows):
            history=r['history'][-n:] if n else r['history']
            xs=[pd.Timestamp(v['time']).timestamp() for v in history];ys=[v['value'] if v['value'] is not None else float('nan') for v in history]
            series.append((e['title'],xs,ys))
            value,unit,when=display_metric(r)
            statuses.append(f"{e['title']} {number(value)} {unit} · {when}")
            descriptions.append(f"<h2>{escape(e['title'])} · {number(value)} {escape(unit)}</h2><p>{escape(e['left'])} / {escape(e['right'])}</p>"
                f"<p><b>数据时点</b>　{escape(when)}</p><p><b>计算范围</b>　{escape(r['scope'])}</p>"
                f"<p><b>历史状态</b>　{escape(r['reason'] or '该日期有效')}</p>"
                f"<p><b>盘中状态</b>　{escape(r.get('current_reason') or '仅使用完整历史数据')}</p><hr>")
            if not overlay:
                chart=self.plots[i];chart.title_label.setText(f"{e['title']}   {number(value)} {unit}")
                chart.plot.setLabel('left',unit)
                chart.draw([series[-1]],key=(self.current_group,code,e['left'],e['right'],n),frequency='1m' if '分钟' in r['scope'] and '日内' not in r['scope'] else '1d',
                    note=f"{e['left']} / {e['right']} · {when}")
        if overlay and rows:
            chart=self.plots[0];chart.title_label.setText(group['title']+" · 同单位对比");chart.plot.setLabel('left',rows[0][1]['unit'])
            chart.draw(series,key=(self.current_group,code,tuple(e['left']+e['right'] for e,_ in rows),n),
                frequency='1m' if '分钟' in rows[0][1]['scope'] and '日内' not in rows[0][1]['scope'] else '1d',note='同单位原始数值叠加；各序列保持自己的真实时点和缺口。')
        self.detail_note.setText(f"{len(rows)} 组固定合约 · 各图单独标注时点 · 公式、变量与缺失原因可在下方切换")
        css='<style>body{font-family:Microsoft YaHei UI;font-size:18px;color:'+TEXT+';}h2{font-size:22px;color:'+ACCENT+';}p,li{line-height:1.6;}td{padding:8px;}hr{color:'+BORDER+';}</style>'
        data_html=css+''.join(descriptions)
        if data_html!=self.data_html:
            position=self.data_details.verticalScrollBar().value();self.data_details.setHtml(data_html)
            self.data_details.verticalScrollBar().setValue(position);self.data_html=data_html
        if rows:
            help=explain_metric(rows[0][1],self.category,self.price_input)
            lines=lambda items:'<ul>'+''.join('<li>'+escape(s)+'</li>' for s in items)+'</ul>'
            variables=''.join('<tr><td><b>'+escape(k)+'</b></td><td>'+escape(v)+'</td></tr>' for k,v in help['variables'])
            html=(f"<h2>{escape(code)} · {escape(help['title'])}</h2><p>单位：{escape(help['unit'])}</p>"
                '<h2>计算公式</h2><p style="font-size:22px">'+escape(help['formula']).replace('\n','<br>')+'</p>'
                '<h2>变量与窗口</h2><table>'+variables+'</table><p>'+escape(help['window'])+'</p>'
                '<h2>如何理解</h2>'+lines(help['reading'])+'<h2>何时不可用</h2>'+lines(help['boundaries']))
            if css+html!=self.help_html:
                self.details.setHtml(css+html);self.help_html=css+html
