"""Browse cached daily index data without downloading or reading dividends."""
import pandas as pd

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from .analytics import ROOTS, NAMES
from .market_view import COLUMNS, HEADERS, export_market_data
from .security_desktop import FrameTable


class MarketDataPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window, self.result = window, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        row = QHBoxLayout()
        self.root = QComboBox()
        self.root.addItem("全部品种", None)
        for r in ROOTS:
            self.root.addItem(f"{r} {NAMES[r]}", r)
        self.kind = QComboBox()
        for label, value in [("期货和现货", "all"), ("股指期货", "futures"), ("现货指数", "spot")]:
            self.kind.addItem(label, value)
        self.code = QLineEdit()
        self.code.setPlaceholderText("代码筛选：IC00.CFE / IC2612.CFE / 000905.SH")
        row.addWidget(self.root)
        row.addWidget(self.kind)
        row.addWidget(self.code, 1)
        row.addWidget(window.button("读取本地数据", self.query, True))
        layout.addLayout(row)
        dates = QHBoxLayout()
        self.all_dates = QCheckBox("全部已下载日期")
        self.all_dates.setChecked(True)
        self.start, self.end = QDateEdit(QDate.currentDate().addMonths(-3)), QDateEdit(QDate.currentDate())
        for date in (self.start, self.end):
            date.setCalendarPopup(True)
            date.setDisplayFormat("yyyy-MM-dd")
            date.setEnabled(False)
        dates.addWidget(self.all_dates)
        dates.addWidget(self.start)
        dates.addWidget(window.hint("至"))
        dates.addWidget(self.end)
        dates.addStretch()
        self.table = FrameTable()
        dates.addWidget(window.button("复制表格", self.table.copy))
        self.export_button = window.button("导出查询 CSV", self.export)
        dates.addWidget(self.export_button)
        layout.addLayout(dates)
        layout.addWidget(window.hint("日频原始下载数据，不加回分红。按实际代码显示，连续档位随日期变化；缺少分红、到期日或其他品种不影响查看。F5 / Ctrl+Enter 在本页仅读缓存。"))
        self.info = window.hint("")
        layout.addWidget(self.info)
        layout.addWidget(self.table, 1)
        for selector in (self.root, self.kind):
            selector.currentIndexChanged.connect(self.clear)
        self.code.textChanged.connect(self.clear)
        self.start.dateChanged.connect(self.clear)
        self.end.dateChanged.connect(self.clear)
        self.all_dates.toggled.connect(self.dates_changed)
        self.clear()

    def clear(self, *_):
        self.result = None
        self.table.fill(pd.DataFrame(columns=COLUMNS), HEADERS)
        self.info.setText("选择筛选条件后读取本地行情；不会调用Wind，也不会重写原始数据。")
        self.info.setToolTip("")
        self.export_button.setEnabled(False)

    def dates_changed(self):
        self.clear()
        self.set_busy(self.window.worker is not None)

    def set_busy(self, busy):
        for selector in (self.root, self.kind, self.code, self.all_dates):
            selector.setEnabled(not busy)
        for date in (self.start, self.end):
            date.setEnabled(not busy and not self.all_dates.isChecked())
        self.export_button.setEnabled(not busy and self.result is not None and not self.result["data"].empty)

    def query(self):
        if self.window.worker:
            return
        args = dict(root=self.root.currentData(), kind=self.kind.currentData(), code=self.code.text(),
            start=None if self.all_dates.isChecked() else self.start.date().toString("yyyy-MM-dd"),
            end=None if self.all_dates.isChecked() else self.end.date().toString("yyyy-MM-dd"))
        self.clear()
        service = self.window.service
        self.window.run_task("读取已下载的股指行情…", lambda progress: service.local_market_data(**args), self.show_result)

    def show_result(self, result):
        self.result = result
        self.table.fill(result["data"], HEADERS)
        p = result["provenance"]
        label = {"demo": "合成演示，非真实行情", "wind": "Wind本地缓存", "offline": "离线导入行情"}[p["source_mode"]]
        self.info.setText(f"{label} · {p['rows']}条 · 实际日期 {p['actual_start'] or '暂无'} 至 {p['actual_end'] or '暂无'}\n"
                          "缺失字段留空，持仓不适用于现货指数。悬停查看本地来源路径。")
        self.info.setToolTip(p["source_database"])
        self.set_busy(False)

    def export(self):
        if self.window.worker or self.result is None or self.result["data"].empty:
            return
        result, parent = self.result, self.window.service.exports_root
        def done(folder):
            self.window.progress_label.setText("原始数据及来源已保存：" + folder)
            self.window.refresh_artifacts()
        self.window.run_task("导出本地行情CSV…", lambda progress: export_market_data(result, parent), done)
