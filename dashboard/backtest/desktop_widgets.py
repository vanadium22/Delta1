"""Native widgets shared by the standalone backtest window."""
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QDir, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QBoxLayout, QFileSystemModel, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTableView, QTreeView, QVBoxLayout, QWidget)
import pyqtgraph as pg

from ..native.theme import ACCENT, DOWN, MUTED, PANEL, TEXT, UP


LABELS = {"timestamp": "时间", "account": "账户", "symbol": "标的", "action": "开平动作",
          "side": "方向", "quantity": "手数 / 份额", "signed_quantity": "带方向数量",
          "signal_time": "信号时间", "execution_time": "成交时间", "price": "成交价",
          "multiplier": "乘数", "margin_rate": "保证金率", "notional": "名义本金", "fee": "手续费",
          "position_before": "成交前持仓", "position_after": "成交后持仓", "reason": "原因",
          "equity": "总权益", "nav": "净值", "cash": "现金", "required_margin": "所需保证金",
          "available_equity": "保证金后余额", "gross_notional": "持仓名义本金", "margin_usage": "保证金占比",
          "fees": "当期费用", "pnl": "当期盈亏", "status": "状态", "weight_scale": "目标缩放比例",
          "trigger_margin": "强平前保证金", "trigger_available_equity": "强平前保证金后余额",
          "rows": "观测数量", "days": "交易日数", "start": "起始时间", "end": "结束时间"}
VALUES = {"open_long": "开多", "close_long": "平多", "open_short": "开空", "close_short": "平空",
          "buy": "买入", "sell": "卖出", "target_rebalance": "目标调仓", "margin_call": "爆仓强平",
          "end_of_backtest": "期末平仓", "executed": "已执行", "superseded": "被后续信号覆盖",
          "no_next_bar": "无下一行情", "stopped_by_margin_call": "爆仓后停止", "active": "运行中",
          "completed": "已完成", "blown_up": "已爆仓"}


class DataFrameModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.original = pd.DataFrame()
        self.frame = pd.DataFrame()

    def set_frame(self, frame):
        if not isinstance(frame.index, pd.RangeIndex):
            frame = frame.rename_axis(frame.index.name or "timestamp").reset_index()
        self.original = frame.copy()
        self.filter("")

    def filter(self, text):
        self.beginResetModel()
        if text:
            mask = pd.Series(False, index=self.original.index)
            for column in self.original:
                mask |= self.original[column].astype(str).str.contains(text, case=False, regex=False)
                if column in {"action", "side", "reason", "status"}:
                    mask |= self.original[column].map(VALUES).astype(str).str.contains(text, case=False, regex=False)
            self.frame = self.original.loc[mask]
        else:
            self.frame = self.original
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            name = str(self.frame.columns[section])
            return LABELS.get(name, name)
        return str(section + 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.frame.iloc[index.row(), index.column()]
        column = self.frame.columns[index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if pd.isna(value):
                return "—"
            if isinstance(value, (pd.Timestamp, np.datetime64)):
                return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(value, (int, np.integer)):
                return f"{value:,}"
            if isinstance(value, (float, np.floating)):
                if column in {"margin_rate", "margin_usage"}:
                    return f"{value:.2%}"
                return f"{value:,.4f}".rstrip("0").rstrip(".")
            return VALUES.get(str(value), str(value))
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (int, float, np.number)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and column == "pnl" and pd.notna(value):
            return QColor(UP if value > 0 else DOWN if value < 0 else TEXT)
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not 0 <= column < len(self.frame.columns):
            return
        self.layoutAboutToBeChanged.emit()
        self.frame = self.frame.sort_values(self.frame.columns[column], kind="stable",
                                            ascending=order == Qt.SortOrder.AscendingOrder, na_position="last")
        self.layoutChanged.emit()


def dataframe_view(parent=None):
    table = QTableView(parent)
    model = DataFrameModel(table)
    table.setModel(model)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(True)
    table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setDefaultSectionSize(36)
    table.verticalHeader().hide()
    table.horizontalHeader().setDefaultSectionSize(150)
    table.horizontalHeader().setStretchLastSection(True)
    table.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
    return table, model


class InlinePicker(QWidget):
    """File selection stays inside the window instead of a modal file dialog."""
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.destination = None
        self.directory_only = False
        layout = QVBoxLayout(self)
        self.title = QLabel("选择本地文件")
        layout.addWidget(self.title)
        row = QHBoxLayout()
        self.location = QLineEdit(str(self.root))
        self.location.returnPressed.connect(self.navigate)
        row.addWidget(self.location, 1)
        go = QPushButton("转到")
        go.clicked.connect(self.navigate)
        row.addWidget(go)
        layout.addLayout(row)
        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.setRootPath(str(self.root)))
        self.tree.setMinimumHeight(180)
        self.tree.setColumnWidth(0, 270)
        self.tree.hideColumn(1)
        self.tree.hideColumn(2)
        self.tree.hideColumn(3)
        self.tree.doubleClicked.connect(self.activate)
        layout.addWidget(self.tree)
        actions = QHBoxLayout()
        self.note = QLabel("")
        self.note.setWordWrap(True)
        actions.addWidget(self.note, 1)
        select = QPushButton("使用所选位置")
        select.clicked.connect(self.select)
        actions.addWidget(select)
        close = QPushButton("收起")
        close.clicked.connect(self.hide)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.hide()

    def open_for(self, destination, *, directory=False):
        self.destination, self.directory_only = destination, directory
        current = Path(destination.text()).expanduser() if destination.text().strip() else self.root
        folder = current if current.is_dir() else current.parent
        if not folder.is_dir():
            folder = self.root
        self.location.setText(str(folder))
        self.title.setText("选择本地目录" if directory else "选择本地文件")
        self.note.clear()
        self.navigate()
        self.show()

    def navigate(self):
        folder = Path(self.location.text()).expanduser()
        if not folder.is_dir():
            self.note.setText("目录不存在，请检查路径")
            return
        self.tree.setRootIndex(self.model.setRootPath(str(folder.resolve())))
        self.tree.setCurrentIndex(QModelIndex())

    def activate(self, index):
        path = Path(self.model.filePath(index))
        if path.is_dir():
            self.location.setText(str(path))
            self.navigate()
        elif not self.directory_only:
            self.select()

    def select(self):
        index = self.tree.currentIndex()
        path = Path(self.model.filePath(index)) if index.isValid() else Path(self.location.text())
        if self.directory_only and not path.is_dir():
            self.note.setText("请选择目录")
            return
        if not self.directory_only and not path.is_file():
            self.note.setText("请选择文件；新配置文件可直接在路径框填写名称")
            return
        self.destination.setText(str(path.resolve()))
        self.hide()


class ObservationAxis(pg.AxisItem):
    """Label actual observations without stretching overnight/weekend gaps."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.index = pd.DatetimeIndex([])

    def set_index(self, index):
        self.index = index.tz_convert("Asia/Shanghai")
        self.setTicks(None)

    def tickStrings(self, values, scale, spacing):
        output = []
        intraday = len(self.index) > 1 and (self.index[1] - self.index[0]) < pd.Timedelta(days=1)
        for value in values:
            pos = int(round(value))
            output.append(self.index[pos].strftime("%m-%d\n%H:%M" if intraday else "%Y-%m-%d")
                          if 0 <= pos < len(self.index) else "")
        return output


class ResultCharts(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.nav = self.plot("净值 · 初始 = 1")
        self.margin = self.plot("保证金占总权益 · %")
        self.margin.setXLink(self.nav)
        self.layout.addWidget(self.nav, 3)
        self.layout.addWidget(self.margin, 2)
        self.curve = self.nav.plot(pen=pg.mkPen(ACCENT, width=2.3), fillLevel=1,
                                   brush=pg.mkBrush(QColor(ACCENT).red(), QColor(ACCENT).green(), QColor(ACCENT).blue(), 18))
        self.margin_curve = self.margin.plot(pen=pg.mkPen("#007ea9", width=2))
        self.cross = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(MUTED, style=Qt.PenStyle.DashLine))
        self.nav.addItem(self.cross, ignoreBounds=True)
        self.cross.hide()
        self.data = pd.DataFrame()
        self.times = np.array([])
        self.proxy = pg.SignalProxy(self.nav.scene().sigMouseMoved, rateLimit=25, slot=self.hover)

    def plot(self, title):
        widget = pg.PlotWidget(axisItems={"bottom": ObservationAxis(orientation="bottom")}, background=PANEL)
        widget.setTitle(title, color=TEXT, size="12pt")
        widget.showGrid(x=True, y=True, alpha=0.13)
        widget.setMinimumSize(230, 180)
        widget.getAxis("bottom").setHeight(44)
        widget.setMenuEnabled(False)
        widget.setClipToView(True)
        widget.setDownsampling(auto=True, mode="peak")
        widget.getPlotItem().hideButtons()
        for key in ("bottom", "left"):
            axis = widget.getAxis(key)
            axis.setTextPen(MUTED)
            axis.setPen(pg.mkPen("#ccd9e4"))
            axis.setStyle(tickFont=QFont("Segoe UI", 9))
        return widget

    def set_account(self, account):
        self.data = account.equity
        self.times = np.arange(len(self.data), dtype=float)
        self.nav.getAxis("bottom").set_index(self.data.index)
        self.margin.getAxis("bottom").set_index(self.data.index)
        self.curve.setData(self.times, self.data.nav.to_numpy(), connect="finite")
        self.margin_curve.setData(self.times, self.data.margin_usage.to_numpy() * 100, connect="finite")
        self.nav.enableAutoRange()
        self.margin.enableAutoRange()
        self.cross.hide()

    def set_scale(self, large):
        for plot, title in ((self.nav, "净值 · 初始 = 1"), (self.margin, "保证金占总权益 · %")):
            plot.setTitle(title, color=TEXT, size="16pt" if large else "12pt")
            for side in ("bottom", "left"):
                plot.getAxis(side).setStyle(tickFont=QFont("Segoe UI", 12 if large else 9))
            plot.getAxis("bottom").setHeight(58 if large else 44)
        self.curve.setPen(pg.mkPen(ACCENT, width=3 if large else 2.3))
        self.margin_curve.setPen(pg.mkPen("#007ea9", width=2.6 if large else 2))

    def hover(self, event):
        point = event[0]
        if not len(self.times) or not self.nav.sceneBoundingRect().contains(point):
            return
        value = self.nav.plotItem.vb.mapSceneToView(point).x()
        pos = min(len(self.times) - 1, int(np.searchsorted(self.times, value)))
        if pos and abs(value - self.times[pos - 1]) < abs(value - self.times[pos]):
            pos -= 1
        self.cross.setPos(self.times[pos])
        self.cross.show()
        row = self.data.iloc[pos]
        self.nav.setToolTip(f"{self.data.index[pos]:%Y-%m-%d %H:%M}\n净值 {row.nav:.6f}\n总权益 {row.equity:,.2f}\n保证金 {row.required_margin:,.2f}")

    def resizeEvent(self, event):
        direction = QBoxLayout.Direction.TopToBottom if self.width() < 760 else QBoxLayout.Direction.LeftToRight
        self.layout.setDirection(direction)
        super().resizeEvent(event)
