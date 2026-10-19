"""Display-only, selectable two-leg research tables and their evidence charts."""
import math

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget

from .widgets import Chart, Panel, curve, label


class NonRegressionPanel(QWidget):
    def __init__(self):
        super().__init__();self.rows=[]
        from PySide6.QtWidgets import QPushButton, QSplitter, QTextBrowser
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.note=label("固定合约历史 · 参考窗口排除当前值","muted");self.note.setWordWrap(True);layout.addWidget(self.note)
        split=QSplitter(Qt.Orientation.Vertical)
        self.table=QTableWidget(0,8)
        self.table.setHorizontalHeaderLabels(["编号 / 指标","历史有效值","单位","历史数据时点","历史口径","盘中观测值","盘中源时间*","状态 / 缺失原因"])
        self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(29)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setWordWrap(False)
        self.table.currentCellChanged.connect(self.select)
        split.addWidget(self.table)
        self.chart=Chart("选中指标历史", "",height=185);split.addWidget(self.chart);split.setSizes([470,240]);layout.addWidget(split,1)
        self.explain_button=QPushButton("展开公式与解释");self.explain_button.setCheckable(True)
        layout.addWidget(self.explain_button)
        self.details=QTextBrowser();self.details.setMaximumHeight(155);self.details.hide();layout.addWidget(self.details)
        self.explain_button.toggled.connect(self.details.setVisible)
        self.explain_button.toggled.connect(lambda checked:self.explain_button.setText("收起公式与解释" if checked else "展开公式与解释"))

    def render(self,state):
        old=self.rows[self.table.currentRow()]["id"] if 0<=self.table.currentRow()<len(self.rows) else None
        self.rows=state["metrics"]
        self.note.setText(state.get("pair_error") or f"{state['left']} / {state['right']} · 历史与盘中分列；*源日期推定。历史OI不标为实时/昨日持仓；旧有效值保留原日期。")
        self.table.blockSignals(True);self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            def date_text(v):
                if not v: return "—"
                try: return pd.Timestamp(v).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M")
                except (ValueError,TypeError): return str(v)
            reason=r["reason"] or "有效历史"
            short_reason=reason if len(reason)<=28 else reason[:26]+"…"
            values=[r["id"]+"  "+r["title"],fmt(r["value"],4),r["unit"],date_text(r["time"]),r["scope"],fmt(r["current"],4),date_text(r["current_time"]),
                    ("最后有效历史；" if r["last_valid"] else "")+short_reason]
            for j,value in enumerate(values):
                cell=QTableWidgetItem(value);cell.setToolTip(r["meaning"]+"\n"+r["formula"]+"\n"+(r.get("current_reason") or r["reason"]))
                self.table.setItem(i,j,cell)
        self.table.blockSignals(False)
        selected=next((i for i,r in enumerate(self.rows) if r["id"]==old),0)
        if self.rows:self.table.setCurrentCell(selected,0)
        self.select()

    def select(self,*_):
        i=self.table.currentRow()
        if not 0<=i<len(self.rows):
            self.chart.draw([],key="empty");self.details.clear();return
        r=self.rows[i]
        self.chart.title_label.setText(r["id"]+" · "+r["title"]);self.chart.plot.setLabel("left",r["unit"])
        self.chart.draw([(r["title"],[pd.Timestamp(v["time"]).timestamp() for v in r["history"]],[v["value"] if v["value"] is not None else float("nan") for v in r["history"]])],key=r["id"],note=r["scope"]+"；缺失处断线，无前填。",frequency="1m" if "分钟" in r["scope"] and "日内" not in r["scope"] else "1d")
        self.details.setPlainText("公式："+r["formula"]+"\n意义："+r["meaning"]+"\n历史："+(r["reason"] or "该日期有效")+"\n盘中："+(r.get("current_reason") or "此项仅使用完整历史数据"))


def fmt(value, digits=2):
    return f"{value:,.{digits}f}" if isinstance(value, (int, float)) and math.isfinite(value) else "—"


class BasisResearchPanel(Panel):
    def __init__(self):
        super().__init__("一多一空研究 · 期现 / 跨期 / 跨指数")
        self.data = {}
        toolbar = QHBoxLayout()
        self.status = label("等待同步历史数据", "muted")
        toolbar.addWidget(self.status, 1)
        self.product = QComboBox()
        self.product.addItems(["全部品种", "IF", "IH", "IC", "IM"])
        self.product.currentIndexChanged.connect(self.refresh_rows)
        toolbar.addWidget(self.product)
        self.layout.addLayout(toolbar)
        self.tabs = QTabWidget()
        self.tables = {}
        self.rows = {}
        self.categories = ("basis", "calendar", "cross")
        headers = {
            "basis":["期货 / 对应指数", "基差 bp", "Z / 前20根", "分位 %", "距到期天", "年化 %", "5根变化 bp", "每日收敛 bp"],
            "calendar":["近端 / 远端", "价差 bp", "Z / 前20根", "分位 %", "隐含持有率 %", "间隔天", "5根变化 bp", "点位对冲手数"],
            "cross":["A / B · 同月份", "对数基差差 bp", "Z / 前20根", "指数 β", "R²", "B手 / A手", "指数差变化 bp", "基差差变化 bp"],
        }
        for category, title in zip(self.categories, ("期现偏离", "跨期组合", "跨指数组合")):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 5, 0, 0)
            table = QTableWidget(0, len(headers[category]))
            table.setHorizontalHeaderLabels(headers[category])
            table.verticalHeader().hide()
            table.verticalHeader().setDefaultSectionSize(30)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.setFixedHeight(224)
            table.currentCellChanged.connect(self.select_row)
            self.tables[category] = table
            layout.addWidget(table)
            self.tabs.addTab(page, title)
        self.tabs.currentChanged.connect(self.select_row)
        self.layout.addWidget(self.tabs)
        self.direction = label("点击组合，查看两腿方向、对冲比例和解释。", "section")
        self.direction.setWordWrap(True)
        self.layout.addWidget(self.direction)
        self.detail = label("", "muted")
        self.detail.setWordWrap(True)
        self.layout.addWidget(self.detail)
        self.chart = Chart("组合历史 · 选择一行查看", "bp", height=175)
        self.layout.addWidget(self.chart)
        self.logic = label("", "muted")
        self.logic.setWordWrap(True)
        self.layout.addWidget(self.logic)

    def render(self, data, demo=False):
        self.data = data or {}
        frequency = self.data.get("frequency", "1d")
        stamp = self.data.get("time")
        text = pd.Timestamp(stamp).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M") if stamp else "无同步数据"
        count = sum(len(self.data.get(key, [])) for key in self.categories)
        self.status.setText(f"{'合成演示' if demo else '历史研究'} · {text} · {frequency} · {count} 个组合 · 点击行查看解释")
        self.refresh_rows()

    def refresh_rows(self, *_):
        chosen = self.product.currentText()
        for category in self.categories:
            table = self.tables[category]
            current = table.currentRow()
            old_rows = self.rows.get(category, [])
            selected = old_rows[current]["id"] if 0 <= current < len(old_rows) else None
            rows = [r for r in self.data.get(category, []) if chosen == "全部品种" or r["left"].startswith(chosen) or r["right"].startswith(chosen)]
            self.rows[category] = rows
            table.blockSignals(True)
            table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                if category == "basis":
                    values = [row["title"], fmt(row["value"]), fmt(row["z"]), fmt(row["percentile"]), fmt(row.get("dte"),0),
                              fmt(row.get("annual_pct")), fmt(row.get("change5")), fmt(row.get("roll_down_bp_day"))]
                elif category == "calendar":
                    values = [row["title"], fmt(row["value"]), fmt(row["z"]), fmt(row["percentile"]), fmt(row.get("carry_pct")),
                              fmt(row.get("delta_days"),0), fmt(row.get("change5")), "1 : 1"]
                else:
                    values = [row["title"], fmt(row["value"]), fmt(row["z"]), fmt(row.get("beta"),3), fmt(row.get("r_squared"),3),
                              fmt(row.get("hedge_contracts"),3), fmt(row.get("spot_change5")), fmt(row.get("basis_change5"))]
                for j, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    cell.setToolTip(row.get("reason") or row["direction"])
                    if j:
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(i, j, cell)
            if rows:
                index = next((i for i,r in enumerate(rows) if r["id"] == selected), 0)
                table.setCurrentCell(index, 0)
            table.blockSignals(False)
        self.select_row()

    def select_row(self, *_):
        category = self.categories[self.tabs.currentIndex()]
        index = self.tables[category].currentRow()
        rows = self.rows.get(category, [])
        if not 0 <= index < len(rows):
            self.direction.setText("暂无可对齐的组合")
            self.detail.setText("需要同刻有效价格；到期日、历史样本或 β 不足时，对应指标保留为空。")
            self.logic.setText(self.data.get("note", ""))
            self.chart.draw([], key=(category, "empty"))
            return
        row = rows[index]
        self.direction.setText(row["direction"])
        if category == "cross":
            text = (f"等名义：每 1 手 A 对 {fmt(row.get('equal_notional_contracts'),3)} 手 B；"
                    f"β对冲：每 1 手 A 对 {fmt(row.get('hedge_contracts'),3)} 手 B。最近5根等名义对数分解："
                    f"期货差 {fmt(row.get('futures_change5'))} = 指数差 {fmt(row.get('spot_change5'))} + 基差变化 {fmt(row.get('basis_change5'))} bp。")
            if row.get("weighted_futures_change5") is not None:
                text += (f" 当前β固定分解：{fmt(row.get('weighted_futures_change5'))} = "
                         f"{fmt(row.get('weighted_spot_change5'))} + {fmt(row.get('weighted_basis_change5'))} bp。")
            if row.get("beta_reason"):
                text += " β：" + row["beta_reason"]
        elif category == "basis":
            text = (f"期货 {fmt(row.get('future'))} / 指数 {fmt(row.get('spot'))}；每手名义金额 {fmt(row.get('notional'),0)} 元。"
                    f"到期日 {row.get('expiry') or '待核验'}；年化基差 Z {fmt(row.get('annual_z'))}。指数腿需 ETF / 篮子实现。")
        else:
            text = (f"近−远点差 {fmt(row.get('points'))} 点；同品种点位对冲 1 : 1；等名义远端手数 {fmt(row.get('equal_notional_contracts'),3)}。"
                    f"区间隐含持有率 Z {fmt(row.get('carry_z'))}；基准均值 {fmt(row.get('mean'))} bp。")
        if row.get("reason"):
            text += " " + row["reason"]
        self.detail.setText(text)
        self.logic.setText(row["logic"])
        frame = pd.DataFrame(row.get("series", []))
        frequency = self.data.get("frequency", "1d")
        if len(frame):
            frame["event_time"] = pd.to_datetime(frame["event_time"], utc=True)
            frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        x,y = curve(frame, "value", frequency)
        self.chart.title_label.setText(row["title"] + " · " + ("对数基差差" if category == "cross" else "基差" if category == "basis" else "标准化跨期价差"))
        self.chart.draw([("组合", x, y)] if x else [], key=(category,row["id"],frequency), frequency=frequency,
                        note="固定具体合约 · 同刻对齐 · 前20根统计；5根为当前频率 · 未扣成本")
