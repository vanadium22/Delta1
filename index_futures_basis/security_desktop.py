"""Independent security-analysis page hosted by the basis application's task runner."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QDateTime, QModelIndex, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateTimeEdit,
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QTabWidget, QTableView, QVBoxLayout, QWidget)

from .config import SHANGHAI
from .security_chart import plot_result
from .security_data import SecurityService, export_result
from .security_model import AMOUNT_UNITS, FIELDS, VOLUME_UNITS, SecurityQuery, field_label


def display(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "—"
    return f"{value:,.6f}".rstrip("0").rstrip(".") if isinstance(value, (int, float)) else str(value)


class FrameModel(QAbstractTableModel):
    def __init__(self, frame=None, headers=None, parent=None):
        super().__init__(parent)
        self.frame = frame if frame is not None else pd.DataFrame()
        self.headers = headers or list(self.frame.columns)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return display(self.frame.iat[index.row(), index.column()])

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section] if orientation == Qt.Orientation.Horizontal else section + 1


class FrameTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setModel(FrameModel(parent=self))
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self.copy)

    def fill(self, frame, headers=None):
        old = self.model()
        self.setModel(FrameModel(frame, headers, self))
        old.deleteLater()
        metrics = self.fontMetrics()
        for i, label in enumerate(self.model().headers):
            width = max(metrics.horizontalAdvance(line) for line in str(label).split("\n")) + 30
            self.setColumnWidth(i, max(245 if i == 0 and "time" in frame.columns else 110, min(width, 320)))
        self.horizontalHeader().setMinimumHeight(46 if any("\n" in str(h) for h in self.model().headers) else 32)

    def copy(self):
        model = self.model()
        rows = sorted({i.row() for i in self.selectedIndexes()})
        frame = model.frame.iloc[rows] if rows else model.frame
        QApplication.clipboard().setText(frame.to_csv(index=False, sep="\t", header=model.headers))


class SecurityPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window, self.result, self.png = window, None, b""
        self.pixmap = QPixmap()
        layout = QVBoxLayout(self)
        self.controls = QWidget()
        grid = QGridLayout(self.controls)
        grid.setContentsMargins(0, 0, 0, 0)
        self.code = QLineEdit("600519.SH")
        self.code.setPlaceholderText("沪深股票 / ETF / 指数 Wind代码")
        self.code.setMaximumWidth(180)
        self.frequency = QComboBox()
        for label, key in (("日频", "1d"), ("分钟频", "minute"), ("最新（单值）", "snapshot")):
            self.frequency.addItem(label, key)
        self.bar = QComboBox()
        for value in (1, 5, 15, 30, 60):
            self.bar.addItem(f"{value}分钟", f"{value}m")
        now = datetime.now(SHANGHAI).replace(tzinfo=None, second=0, microsecond=0)
        self.start = QDateTimeEdit(QDateTime(now).addDays(-30))
        self.end = QDateTimeEdit(QDateTime(now))
        for control in (self.start, self.end):
            control.setCalendarPopup(True)
            control.setMinimumWidth(205)
        top_row = QHBoxLayout()
        for control in (QLabel("标的"), self.code, self.frequency, self.bar):
            top_row.addWidget(control)
        top_row.addStretch()
        top_row.addWidget(QLabel("沪深股票 / ETF / 指数"))
        grid.addLayout(top_row, 0, 0)
        time_row = QHBoxLayout()
        for control in (QLabel("开始"), self.start, QLabel("结束"), self.end):
            time_row.addWidget(control)
        time_row.addStretch()
        grid.addLayout(time_row, 1, 0)
        fields_row = QHBoxLayout()
        self.fields = {}
        for field, label in FIELDS.items():
            control = QCheckBox(f"{label} {field}")
            control.setChecked(field == "close")
            control.toggled.connect(self.invalidate)
            self.fields[field] = control
            fields_row.addWidget(control)
        fields_row.addStretch()
        grid.addLayout(fields_row, 2, 0)
        options = QHBoxLayout()
        self.twap, self.vwap = QCheckBox("分钟采样 TWAP"), QCheckBox("区间 VWAP（自动补量额）")
        options.addWidget(self.twap)
        options.addWidget(self.vwap)
        self.volume_unit, self.amount_unit = QComboBox(), QComboBox()
        for key, (label, _) in VOLUME_UNITS.items():
            self.volume_unit.addItem(label, key)
        for key, (label, _) in AMOUNT_UNITS.items():
            self.amount_unit.addItem(label, key)
        options.addWidget(QLabel("原始成交量单位"))
        options.addWidget(self.volume_unit)
        options.addWidget(QLabel("成交额单位"))
        options.addWidget(self.amount_unit)
        options.addStretch()
        grid.addLayout(options, 3, 0)
        layout.addWidget(self.controls)
        buttons = QHBoxLayout()
        self.query_button = QPushButton("查询 / 补齐缓存")
        self.query_button.setObjectName("primary")
        self.query_button.clicked.connect(lambda: self.query())
        self.refresh_button = QPushButton("重取所选范围")
        self.refresh_button.clicked.connect(lambda: self.query(force=True))
        self.export_button = QPushButton("导出数据与图表")
        self.export_button.clicked.connect(self.export)
        self.cache_button = QPushButton("缓存管理")
        self.cache_button.clicked.connect(self.show_cache)
        self.copy_button = QPushButton("复制数据")
        self.copy_button.clicked.connect(lambda: self.data_table.copy())
        for button in (self.query_button, self.refresh_button, self.copy_button, self.export_button, self.cache_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(QLabel("北京时间 · 不复权"))
        layout.addLayout(buttons)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.info.setStyleSheet("background:#eaf1f7; padding:8px; color:#294761;")
        layout.addWidget(self.info)
        self.metrics = QLabel()
        self.metrics.setWordWrap(True)
        self.metrics.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.metrics)
        self.tabs = QTabWidget()
        self.data_table, self.stats_table = FrameTable(), FrameTable()
        self.tabs.addTab(self.data_table, "原始数据")
        self.scroll = QScrollArea()
        self.image = QLabel("查询后显示图表")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.image)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_page = QWidget()
        chart_layout = QVBoxLayout(chart_page)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_tools = QHBoxLayout()
        self.zoom = QComboBox()
        self.zoom.addItems(["适应宽度", "适应窗口", "100%", "150%"])
        self.zoom.currentIndexChanged.connect(self.scale_image)
        chart_tools.addWidget(self.zoom)
        chart_tools.addWidget(QLabel("可滚动查看整图；导出保留原始清晰度"))
        chart_tools.addStretch()
        chart_layout.addLayout(chart_tools)
        chart_layout.addWidget(self.scroll, 1)
        self.tabs.addTab(chart_page, "图表")
        self.tabs.addTab(self.stats_table, "统计")
        layout.addWidget(self.tabs, 1)
        self.note = QLabel("历史查询优先复用缓存；最新每次重新取值。TWAP为分钟收盘价采样近似；VWAP需选择Wind原始单位。")
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self.frequency.currentIndexChanged.connect(self.change_frequency)
        for control in (self.volume_unit, self.amount_unit):
            control.currentIndexChanged.connect(self.invalidate)
        self.bar.currentIndexChanged.connect(self.change_identity)
        for control in (self.twap, self.vwap):
            control.toggled.connect(self.invalidate)
        self.start.dateTimeChanged.connect(self.invalidate)
        self.end.dateTimeChanged.connect(self.invalidate)
        self.code.textChanged.connect(self.change_identity)
        self.tabs.currentChanged.connect(self.scale_image)
        self.change_frequency()

    @property
    def service(self):
        basis = self.window.service
        return SecurityService(basis.paths, basis.config, basis.mode, basis.cancel)

    def frequency_key(self):
        return self.bar.currentData() if self.frequency.currentData() == "minute" else self.frequency.currentData()

    def change_frequency(self, *_):
        minute, snapshot = self.frequency.currentData() == "minute", self.frequency.currentData() == "snapshot"
        self.bar.setVisible(minute)
        self.start.setEnabled(not snapshot)
        self.end.setEnabled(not snapshot)
        for control in (self.start, self.end):
            control.setDisplayFormat("yyyy-MM-dd HH:mm" if minute else "yyyy-MM-dd")
        if not minute:
            self.twap.setChecked(False)
        self.twap.setEnabled(minute)
        if snapshot:
            self.vwap.setChecked(False)
        self.vwap.setEnabled(not snapshot)
        for field, control in self.fields.items():
            control.setText(f"{field_label(field, self.frequency_key())} {field}")
        self.change_identity()

    def change_identity(self, *_):
        # Do not silently carry WSD units to WSI/WSQ or to another instrument.
        self.volume_unit.setCurrentIndex(0)
        self.amount_unit.setCurrentIndex(0)
        self.invalidate()

    def invalidate(self, *_):
        self.result, self.png = None, b""
        self.pixmap = QPixmap()
        self.data_table.fill(pd.DataFrame())
        self.stats_table.fill(pd.DataFrame())
        self.image.clear()
        self.image.setText("查询后显示图表")
        self.metrics.clear()
        self.info.setText("输入沪深证券 Wind 代码并查询。离线可读已有历史查询缓存，演示使用独立合成数据。")
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)

    def set_busy(self, busy):
        self.controls.setEnabled(not busy)
        for button in (self.query_button, self.cache_button):
            button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy and self.window.service.mode != "offline")
        for button in (self.export_button, self.copy_button):
            button.setEnabled(not busy and self.result is not None)

    def query(self, force=False):
        if self.window.worker:
            return
        self.invalidate()
        try:
            query = SecurityQuery(self.code.text(), self.frequency_key(),
                tuple(f for f, checkbox in self.fields.items() if checkbox.isChecked()),
                self.start.dateTime().toString("yyyy-MM-dd HH:mm:00"), self.end.dateTime().toString("yyyy-MM-dd HH:mm:00"),
                self.twap.isChecked(), self.vwap.isChecked(), self.volume_unit.currentData(), self.amount_unit.currentData())
        except ValueError as exc:
            self.info.setText(str(exc))
            return
        service = self.service
        def operation(progress):
            result = service.query(query, progress, force=force)
            service.check_cancel()
            return result, plot_result(result)
        self.window.run_task("查询证券行情…", operation, self.show_result, cancellable=True,
                             failure=lambda error: self.info.setText("查询未完成：" + error))

    def show_result(self, payload):
        result, self.png = payload
        self.result = result
        q, meta = result.query, result.metadata
        headers = ["时间 / Wind返回时间"]
        for f in q.required_fields:
            unit = VOLUME_UNITS[q.volume_unit][0] if f == "volume" else AMOUNT_UNITS[q.amount_unit][0] if f == "amt" else "原始报价"
            headers.append(field_label(f, q.frequency) + f" ({f})\n" + ("Wind原始单位未确认" if unit == "未确认" else unit))
        self.data_table.fill(result.frame, headers)
        stats = pd.DataFrame(result.summary["statistics"]).drop(columns="field")
        self.stats_table.fill(stats, ["字段", "有效数", "缺失数", "均值", "中位数", "最小值", "最大值", "合计"])
        actual = ("最新单次快照" if q.frequency == "snapshot" else
                  f"{meta['actual_start'][:16]} 至 {meta['actual_end'][:16]}" if meta['actual_start'] else "窗口无有效数据")
        coverage = f"{meta['complete_rows']:,}/{len(result.frame):,}完整行" if q.frequency != "snapshot" else "1行"
        self.info.setText(f"{q.code} · {meta['name']} · {meta['source']} | {actual} | {coverage}\n"
                          f"本次接口请求 {meta['requests']} 次 | 最近采集 {meta['received_at']} | 不复权")
        metric_text = "    ".join(f"{key.upper()} {value:.6f}" for key, value in result.summary["metrics"].items())
        notes = list(dict.fromkeys(result.summary["notes"] + meta["notes"]))
        if q.frequency == "snapshot":
            metric_text = "    ".join(f"{field_label(f, q.frequency)}  {display(result.frame.iloc[0][f])}" for f in q.fields)
            notes.append("显示Wind返回时间及采集时间；不代表逐笔成交时间，休市/停牌时可能为上次报价。")
        self.metrics.setText(metric_text or "统计见下方页签；成交量及成交额保留 Wind 原始单位。")
        self.note.setText("\n".join(notes) if notes else "数据已缓存。图表与统计仅使用本次窗口；单位选择会写入导出清单。")
        self.pixmap = QPixmap()
        if self.png:
            self.pixmap.loadFromData(self.png)
            self.scale_image()
        else:
            self.image.setText("最新为单值快照，无历史曲线")
        self.set_busy(False)

    def scale_image(self, *_):
        if not self.pixmap.isNull():
            if self.zoom.currentIndex() == 0:
                scaled = self.pixmap.scaledToWidth(max(200, self.scroll.viewport().width() - 20), Qt.TransformationMode.SmoothTransformation)
            elif self.zoom.currentIndex() == 1:
                scaled = self.pixmap.scaled(self.scroll.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
            else:
                factor = 1. if self.zoom.currentIndex() == 2 else 1.5
                scaled = self.pixmap.scaled(self.pixmap.size() * factor, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
            self.image.setPixmap(scaled)
            self.image.resize(scaled.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "scroll"):
            self.scale_image()

    def export(self):
        if self.result is None or self.window.worker:
            return
        result, png = self.result, self.png
        base = self.window.service.exports_root / "security_query"
        base.mkdir(parents=True, exist_ok=True)
        selected = QFileDialog.getExistingDirectory(self, "选择导出所在目录（自动新建本次批次）", str(base))
        if not selected:
            return
        folder = Path(selected) / (datetime.now(SHANGHAI).strftime("%Y%m%d_%H%M%S") + "_" + result.query.code + "_" + uuid.uuid4().hex[:6])
        def operation(progress):
            export_result(result, folder)
            if png:
                (folder / "chart.png").write_bytes(png)
            return folder
        self.window.run_task("导出行情与计算结果…", operation,
            lambda path: self.window.progress_label.setText("已保存：" + str(path)))

    def show_cache(self):
        service, frequency = self.service, self.frequency_key()
        try:
            inventory = service.inventory(frequency)
            _, root = service.cache(frequency)
            plan = service.prune(frequency)
        except Exception as exc:
            self.info.setText(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("行情查询缓存 · " + frequency)
        dialog.resize(850, 520)
        layout = QVBoxLayout(dialog)
        label = QLabel(f"{root}\n{len(inventory)}个文件，合计 {sum(x['bytes'] for x in inventory)/1024/1024:.2f} MB。\n"
                       "按下载日期保留最近7个自然日；仅点清理才删除过期分区，行情交易日不决定过期时间。")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        table = FrameTable()
        table.fill(pd.DataFrame(inventory, columns=["date", "file", "bytes"]), ["下载日期", "文件", "字节数"])
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        open_button = buttons.addButton("打开缓存目录", QDialogButtonBox.ButtonRole.ActionRole)
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))))
        clear = buttons.addButton(f"清理过期分区（{len(plan['partitions'])}个）", QDialogButtonBox.ButtonRole.ActionRole)
        clear.setEnabled(bool(plan["partitions"]) and service.mode != "offline")
        def prune():
            if QMessageBox.question(dialog, "清理临时行情缓存", "删除预览中的过期下载分区？导出和永久行情库不受影响。") != QMessageBox.StandardButton.Yes:
                return
            try:
                service.prune(frequency, apply=True)
                dialog.accept()
            except Exception as exc:
                label.setText(str(exc))
        clear.clicked.connect(prune)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
