from __future__ import annotations

from datetime import datetime
import fnmatch
import json
from pathlib import Path
import shutil
import uuid

import pandas as pd
from PySide6.QtCore import QDate, QTime, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit,
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from .analytics import read_continuous_snapshot, sha256
from .config import ROOT
from .report import chart_catalog, fmt
from .service import BasisService, METRICS, ROOTS
from .windows import WINDOW_FIELDS, normalize_windows, window_summary, chart_window_label
from .security_desktop import SecurityPage
from shared_data.io import file_lock
from shared_data.migration import copy_verified

STYLE = """
QMainWindow, QDialog {background:#f3f6fa; color:#1d3045;}
QWidget {font-family:'Microsoft YaHei'; font-size:10pt;}
QLabel#title {font-size:20pt; font-weight:600; color:#163652;}
QLabel#status {background:#e5edf5; padding:10px; border-radius:5px;}
QLabel#metric {font-size:17pt; font-weight:600; padding:8px; background:white;}
QLabel#hint {color:#586d80;}
QPushButton {padding:7px 12px; border:1px solid #bdcbd9; border-radius:4px; background:white;}
QPushButton:hover {background:#e8f0f8;}
QPushButton:disabled {color:#a0abb6; background:#f1f3f5;}
QPushButton#primary {background:#245c86; color:white; border:1px solid #245c86;}
QPushButton#primary:disabled {background:#dfe7ef; color:#8092a4; border-color:#d4dfe9;}
QComboBox, QLineEdit, QSpinBox, QDateEdit, QTimeEdit {padding:5px; background:white; border:1px solid #bdcbd9; border-radius:3px;}
QTableWidget {background:white; alternate-background-color:#f4f7fb; gridline-color:#e0e6ed; selection-background-color:#d5e8f9; selection-color:#142f48;}
QHeaderView::section {background:#e8eef5; color:#294761; padding:7px; border:0; border-right:1px solid #d9e2ec;}
QTabWidget::pane {border:1px solid #d4dfe9; background:white;}
QTabBar::tab {padding:10px 22px; background:#e5ebf3; margin-right:3px;}
QTabBar::tab:selected {background:white; color:#245c86; font-weight:600;}
QPlainTextEdit {background:white; border:1px solid #d4dfe9;}
"""


class Table(QTableWidget):
    def __init__(self, headers, stretch=False):
        super().__init__(0, len(headers))
        self.stretch = stretch
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(not stretch)
        self.verticalHeader().setDefaultSectionSize(34)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self.copy)

    def fill(self, rows):
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(str(value) if value is not None else "—")
                item.setToolTip(item.text())
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if j == 0 else Qt.AlignmentFlag.AlignRight))
                self.setItem(i, j, item)
        self.resizeColumnsToContents()
        for j in range(self.columnCount()):
            self.setColumnWidth(j, max(90, min(self.columnWidth(j) + 14, 450)))
        if self.stretch:
            self.horizontalHeader().setMinimumSectionSize(90)
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def copy(self):
        rows = sorted({i.row() for i in self.selectedIndexes()}) or list(range(self.rowCount()))
        lines = ["\t".join(self.horizontalHeaderItem(c).text() for c in range(self.columnCount()))]
        lines += ["\t".join(self.item(r, c).text() if self.item(r, c) else "" for c in range(self.columnCount())) for r in rows]
        QApplication.clipboard().setText("\n".join(lines))


class Task(QThread):
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation, self.result, self.error = operation, None, None

    def run(self):
        try:
            self.result = self.operation(self.progress.emit)
        except Exception as exc:
            self.error = str(exc)


class WindowProfileDialog(QDialog):
    def __init__(self, values, kind, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片时间窗口" if kind == "figures" else "Word及计算CSV时间窗口")
        self.setMinimumWidth(650)
        form = QFormLayout(self)
        hint = QLabel("单位：自然月，范围1—36。曲线填写显示月数；分位填写1—3个不同月数，用逗号分隔。\n"
                      "图片和Word分别保存。加长窗口后，F5或正式Word会增量补齐所需历史；绘图本身只读本地。")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.fields = {}
        for key, (label, default, count) in WINDOW_FIELDS.items():
            field = QSpinBox() if count == 1 else QLineEdit()
            if count == 1:
                field.setRange(1, 36)
                field.setSuffix(" 个月")
            self.fields[key] = field
            form.addRow(label, field)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#A83F31;")
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
                                  | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("恢复默认")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(lambda: self.set_values(None))
        form.addRow(buttons)
        self.set_values(values)

    def set_values(self, values):
        for key, value in normalize_windows(values).items():
            if isinstance(value, int):
                self.fields[key].setValue(value)
            else:
                self.fields[key].setText(", ".join(map(str, value)))
        self.error.clear()

    def values(self):
        return normalize_windows({key: field.value() if isinstance(field, QSpinBox) else field.text()
                                  for key, field in self.fields.items()})

    def accept(self):
        try:
            self.values()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        super().accept()


class Window(QMainWindow):
    ready = Signal()

    def __init__(self, service=None, auto_start=True):
        super().__init__()
        self.service = service or BasisService()
        self.worker = None
        self.query_result = None
        self.status_data = None
        self.image_path = None
        self.image_pixmap = QPixmap()
        self.closing = False
        self.ui_actions = []
        self.setWindowTitle("Delta1 股指基差工作台")
        self.setMinimumSize(980, 640)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1600, screen.width() - 50), min(960, screen.height() - 70))
        self.build()
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_active_page)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.query_active_page)
        if auto_start:
            QTimer.singleShot(0, self.startup)

    def button(self, text, action, primary=False):
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(action)
        self.ui_actions.append(button)
        return button

    def hint(self, text):
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def build(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 14)
        title_row = QHBoxLayout()
        title = QLabel("股指基差工作台")
        title.setObjectName("title")
        title_row.addWidget(title)
        title_row.addStretch()
        self.mode = QComboBox()
        for label, mode in [("Wind 正式数据", "wind"), ("离线研究快照", "offline"), ("合成演示", "demo")]:
            self.mode.addItem(label, mode)
        self.mode.setCurrentIndex(self.mode.findData(self.service.mode))
        self.mode.currentIndexChanged.connect(self.change_mode)
        title_row.addWidget(self.mode)
        title_row.addWidget(self.button("设置", self.settings))
        layout.addLayout(title_row)
        self.status_label = QLabel("正在读取本地数据…")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.build_data_tab()
        self.build_query_tab()
        self.build_charts_tab()
        self.build_exports_tab()
        self.security_page = SecurityPage(self)
        self.tabs.addTab(self.security_page, "行情分析")
        self.tabs.currentChanged.connect(lambda _: self.status_label.setVisible(self.tabs.currentWidget() is not self.security_page))
        self.refresh_window_profiles()
        footer = QHBoxLayout()
        self.progress_label = self.hint("就绪")
        footer.addWidget(self.progress_label, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(140)
        self.progress.setRange(0, 0)
        self.progress.hide()
        footer.addWidget(self.progress)
        self.cancel_button = QPushButton("停止更新")
        self.cancel_button.clicked.connect(lambda: self.service.cancel.set())
        self.cancel_button.hide()
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)
        self.setCentralWidget(widget)

    def tab(self, name):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        self.tabs.addTab(widget, name)
        return layout

    def build_data_tab(self):
        layout = self.tab("数据管理")
        actions = QHBoxLayout()
        self.sync_button = self.button("检查并补齐行情  F5", self.sync, True)
        actions.addWidget(self.sync_button)
        actions.addWidget(self.button("重取指定日期", self.repair))
        actions.addWidget(self.button("导入离线快照", self.import_snapshot))
        actions.addWidget(self.button("导入分红 Excel", self.import_dividend))
        actions.addStretch()
        actions.addWidget(self.button("打开分红目录", self.open_inputs))
        layout.addLayout(actions)
        layout.addWidget(self.hint("日线优先使用本地数据；检查并补齐只请求缺失部分。历史窗口默认12个月，已有历史长期保留。"))
        self.coverage = Table(["品种", "目标交易日数", "完整交易日数", "首个完整日期", "最新完整日期", "缺失日期数"], stretch=True)
        self.coverage.setMaximumHeight(200)
        layout.addWidget(self.coverage)
        self.dividend_label = self.hint("分红：读取公共分红目录中表内日期最新的 Excel；查询和导出时自动重新检查。")
        layout.addWidget(self.dividend_label)
        self.missing = Table(["日期", "品种", "缺失字段"])
        layout.addWidget(self.missing, 1)
        layout.addWidget(self.hint("同步记录与错误详情（下载中断后，已成功的批次可以复用）"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log)

    def build_query_tab(self):
        layout = self.tab("基差查询")
        controls = QHBoxLayout()
        self.root = QComboBox()
        self.root.addItems(ROOTS)
        self.root.setCurrentText("IC")
        self.slot = QComboBox()
        for i, name in enumerate(["00 当月", "01 次月", "02 季月一", "03 最远月"], 1):
            self.slot.addItem(name, i)
        self.slot.setCurrentIndex(3)
        self.metric_combo = QComboBox()
        for key, (label, unit) in METRICS.items():
            self.metric_combo.addItem(f"{label}（{unit}）", key)
        self.latest = QCheckBox("最新完整日")
        self.latest.setChecked(True)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setEnabled(False)
        self.latest.toggled.connect(lambda checked: self.date.setEnabled(not checked))
        for selector in (self.root, self.slot):
            selector.currentIndexChanged.connect(self.invalidate_query)
        self.metric_combo.currentIndexChanged.connect(self.change_metric)
        self.latest.toggled.connect(self.invalidate_query)
        self.date.dateChanged.connect(self.invalidate_query)
        for w in [self.root, self.slot, self.metric_combo, self.latest, self.date]:
            controls.addWidget(w)
        controls.addWidget(self.button("查询", self.query, True))
        layout.addLayout(controls)
        self.current = QLabel("选择品种和指标，查看本地统计")
        self.current.setObjectName("metric")
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        self.query_note = self.hint("IC 最远月表示 IC03 连续档位；同时显示当日对应实际合约。")
        layout.addWidget(self.query_note)
        self.stats = Table(["自然月窗口", "有效样本", "均值", "中位数", "当前百分位", "P5", "P25", "P75", "P95", "覆盖状态"], stretch=True)
        self.stats.setMaximumHeight(160)
        layout.addWidget(self.stats)
        layout.addWidget(self.hint("历史窗口不含截止日。单合约年化剔除不足5天样本；固定期限不外推；跨期按两到期日间隔年化。统计不用画图填充值，固定分红快照应用于整个窗口。"))
        row = QHBoxLayout()
        row.addWidget(self.button("复制统计", self.stats.copy))
        row.addWidget(self.button("导出本次查询 CSV", self.export_query))
        row.addStretch()
        row.addWidget(self.hint("下表为所选指标的日度明细，可选行后 Ctrl+C 复制"))
        layout.addLayout(row)
        self.history = Table(["日期", "实际合约", "数值", "到期日"], stretch=True)
        layout.addWidget(self.history, 1)

    def build_charts_tab(self):
        layout = self.tab("图表浏览")
        row = QHBoxLayout()
        self.chart = QComboBox()
        self.chart.addItems(chart_catalog(self.service.output_windows("figures")))
        self.chart.currentTextChanged.connect(self.update_chart_window_note)
        row.addWidget(self.chart, 1)
        row.addWidget(self.button("生成所选图", lambda: self.export("figures", [self.chart.currentText()]), True))
        row.addWidget(self.button("生成全部图片", lambda: self.export("figures")))
        row.addWidget(self.button("打开已有图片", self.choose_image))
        layout.addLayout(row)
        settings_row = QHBoxLayout()
        settings_row.addWidget(self.button("图片时间窗口…", lambda: self.edit_output_windows("figures")))
        self.chart_window_note = self.hint("")
        settings_row.addWidget(self.chart_window_note, 1)
        layout.addLayout(settings_row)
        row2 = QHBoxLayout()
        self.image_note = self.hint("选择图表和时间窗口后生成；已有图片保留生成时的日期与窗口。")
        row2.addWidget(self.image_note, 1)
        self.zoom = QComboBox()
        self.zoom.addItems(["适应窗口", "50%", "75%", "100%", "150%"])
        self.zoom.currentTextChanged.connect(self.scale_image)
        row2.addWidget(self.zoom)
        row2.addWidget(self.button("复制图片", self.copy_image))
        row2.addWidget(self.button("另存图片", self.save_image))
        layout.addLayout(row2)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label = QLabel("生成或打开一张图片后在此查看")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.image_label)
        layout.addWidget(self.scroll, 1)

    def build_exports_tab(self):
        layout = self.tab("报告与记录")
        row = QHBoxLayout()
        row.addWidget(self.button("生成 Word（尝试更新）", lambda: self.export("report"), True))
        row.addWidget(self.button("仅用本地生成 Word", lambda: self.export("report", refresh=False)))
        row.addWidget(self.button("导出全部计算数据 CSV", lambda: self.export("data")))
        row.addWidget(self.button("报告时间窗口…", lambda: self.edit_output_windows("report")))
        row.addWidget(self.button("刷新记录", self.refresh_artifacts))
        row.addStretch()
        row.addWidget(self.button("打开导出目录", self.open_exports))
        layout.addLayout(row)
        self.report_window_note = self.hint("")
        layout.addWidget(self.report_window_note)
        layout.addWidget(self.hint("Wind超时或缺数据时按本地缓存尽力生成，缺失图表/数值留空并注明数据日期。仅用本地生成不等待Wind；离线/演示也不联网。双击记录打开文件夹。"))
        self.export_table = Table(["生成时间", "行情截止日", "分红日期", "类型", "版本状态", "保存位置"])
        self.export_table.cellDoubleClicked.connect(self.open_artifact)
        layout.addWidget(self.export_table, 1)

    def update_chart_window_note(self):
        if hasattr(self, "chart_window_note"):
            self.chart_window_note.setText(chart_window_label(self.chart.currentText(), self.service.output_windows("figures"))
                                           + "。窗口修改后请重新生成；不影响Word。")

    def refresh_window_profiles(self):
        index = max(0, self.chart.currentIndex())
        self.chart.blockSignals(True)
        self.chart.clear()
        self.chart.addItems(chart_catalog(self.service.output_windows("figures")))
        self.chart.setCurrentIndex(index)
        self.chart.blockSignals(False)
        self.update_chart_window_note()
        self.report_window_note.setText("Word及计算CSV：" + window_summary(self.service.output_windows("report")))

    def edit_output_windows(self, kind):
        if self.worker:
            return
        dialog = WindowProfileDialog(self.service.output_windows(kind), kind, self)
        if dialog.exec():
            try:
                message = self.service.save_output_windows(kind, dialog.values())
                self.refresh_window_profiles()
                self.progress_label.setText(message)
            except (ValueError, OSError) as exc:
                self.progress_label.setText(str(exc))

    def run_task(self, text, operation, success, cancellable=False, failure=None):
        if self.worker is not None:
            return
        self.set_busy(True)
        self.cancel_button.setVisible(cancellable)
        self.progress_label.setText(text)
        worker = Task(operation, self)
        self.worker = worker
        worker.progress.connect(self.progress_label.setText)

        def finished():
            self.worker = None
            self.set_busy(False)
            if worker.error:
                self.progress_label.setText("未完成：" + worker.error)
                self.log.appendPlainText(worker.error)
                if failure and not self.closing:
                    failure(worker.error)
            else:
                self.progress_label.setText("已完成")
                try:
                    success(worker.result)
                except Exception as exc:
                    self.progress_label.setText(str(exc))
            worker.deleteLater()
            self.ready.emit()
            if self.closing:
                self.close()
        worker.finished.connect(finished)
        worker.start()

    def set_busy(self, busy):
        self.security_page.set_busy(busy)
        for action in self.ui_actions:
            action.setEnabled(not busy)
        for selector in [self.mode, self.root, self.slot, self.metric_combo, self.latest, self.chart]:
            selector.setEnabled(not busy)
        self.date.setEnabled(not busy and not self.latest.isChecked())
        self.progress.setVisible(busy)
        if not busy:
            self.cancel_button.hide()
            self.sync_button.setEnabled(self.service.mode == "wind")
            self.slot.setEnabled(self.metric_combo.currentData() not in
                {"fixed_60d", "fixed_90d", "calendar_02_00", "calendar_03_02"})

    def startup(self):
        auto = self.service.mode == "wind" and self.service.config["auto_sync"]
        self.load_local(after=lambda: QTimer.singleShot(0, self.sync) if auto else None)

    def change_mode(self):
        if self.worker:
            return
        try:
            self.service = BasisService(self.service.root, self.mode.currentData())
            self.security_page.change_identity()
            self.refresh_window_profiles()
            self.invalidate_query()
            self.dividend_label.setText("正在检查所选数据模式的分红来源…")
            self.image_pixmap = QPixmap()
            self.image_path = None
            self.image_label.clear()
            self.load_local()
        except Exception as exc:
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData(self.service.mode))
            self.mode.blockSignals(False)
            self.progress_label.setText(str(exc))

    def load_local(self, after=lambda: None):
        self.invalidate_query()
        # Capture widget state on the GUI thread; worker operations use plain values.
        root, slot, metric, end = self.query_args()
        def operation(progress):
            status = self.service.status()
            try:
                result, error = self.service.query(root, slot, metric, end), None
            except Exception as exc:
                result, error = None, str(exc)
            return status, result, error
        def done(payload):
            status, query, error = payload
            self.show_status(status)
            if query:
                self.show_query(query)
            elif error:
                self.current.setText("尚无可展示的查询结果")
                self.query_note.setText(error)
                self.progress_label.setText(error)
            self.refresh_artifacts()
            after()
        self.run_task("读取本地数据与分红…", operation, done)

    def show_status(self, status):
        self.status_data = status
        label = {"wind": "Wind 正式数据", "offline": "离线研究快照", "demo": "合成演示 · 非真实行情"}[self.service.mode]
        self.setWindowTitle("Delta1 股指基差工作台 · " + label)
        self.status_label.setText(f"{label}　|　共同完整截止日：{status['latest_complete'] or '暂无'}　|　目标截止：{status['requested_end']}"
            f"　|　缺失字段：{status['missing_fields']}　|　待检查日历日期：{status['calendar_unknown_days']}")
        self.coverage.fill([[r[k] for k in ("root", "expected_days", "complete_days", "first", "last", "missing_days")] for r in status["rows"]])
        self.missing.fill([[m["day"], r["root"], "、".join(m["fields"])] for r in status["rows"] for m in r["missing"]])
        self.log.setPlainText("\n".join(f"{r['started']} · {r['state']} · {r['message'] or '上次任务未正常结束；可重新补齐'}" for r in status["runs"]))
        if status["latest_complete"] and self.latest.isChecked():
            self.date.setDate(QDate.fromString(status["latest_complete"], "yyyy-MM-dd"))

    def as_of(self):
        return None if self.latest.isChecked() else self.date.date().toString("yyyy-MM-dd")

    def query_args(self):
        return self.root.currentText(), self.slot.currentData(), self.metric_combo.currentData(), self.as_of()

    def invalidate_query(self, *_args):
        self.query_result = None
        self.current.setText("请查询当前选择的品种和指标")
        self.stats.fill([])
        self.history.fill([])
        self.query_note.setText("重新查询后显示当前值、均值、中位数和分位点。")

    def change_metric(self, *_args):
        self.invalidate_query()
        self.slot.setEnabled(not self.worker and self.metric_combo.currentData() not in
            {"fixed_60d", "fixed_90d", "calendar_02_00", "calendar_03_02"})

    def query(self):
        if self.worker:
            return
        args = self.query_args()
        self.invalidate_query()
        self.run_task("计算所选指标…", lambda progress: self.service.query(*args), self.show_query)

    def refresh_active_page(self):
        if self.tabs.currentWidget() is self.security_page:
            self.security_page.query()
        else:
            self.sync()

    def query_active_page(self):
        if self.tabs.currentWidget() is self.security_page:
            self.security_page.query()
        else:
            self.query()

    def show_query(self, result):
        self.query_result = result
        self.current.setText(f"{result['title']}　当前 {fmt(result['current'])}{result['unit']}")
        info = result["provenance"]["dividends"]
        self.dividend_label.setText(f"分红日期：{info['snapshot_date']}　|　{info['path']}")
        explanation = ("统计对象为按实际到期日插值的固定期限序列。" if result["metric"].startswith("fixed_") else
            "统计对象为同日实际合约跨期年化序列，分母为现货指数，按两到期日间隔年化。"
            if result["metric"] in {"calendar_02_00", "calendar_03_02"} else "统计对象为连续档位历史。")
        self.query_note.setText(f"行情截至 {result['actual_end']}　|　实际合约：{result['current_contract']}　|　到期日：{result['expiry']}\n"
                               + explanation + "各窗口使用本次选中的固定分红假设。")
        rows = []
        for r in result["statistics"].itertuples():
            rows.append([f"{r.months}个月", r.n, fmt(r.mean), fmt(r.p50), fmt(r.percentile, 1) + "%" if pd.notna(r.percentile) else "—",
                         fmt(r.p05), fmt(r.p25), fmt(r.p75), fmt(r.p95), "完整" if r.complete else "覆盖不足"])
        self.stats.fill(rows)
        self.history.fill([[str(r.trade_date.date()), getattr(r, "instrument_id", "—"), fmt(r.value),
                            str(r.expiry_date.date()) if hasattr(r, "expiry_date") else "—"]
                           for r in result["series"].sort_values("trade_date", ascending=False).itertuples()])
        self.refresh_artifacts()

    def sync(self, checked=False, repair=None):
        if self.worker or self.service.mode != "wind":
            return
        self.invalidate_query()
        def operation(progress):
            try:
                outcome = self.service.sync(progress, repair=repair)
            except Exception as exc:
                outcome = {"message": str(exc), "state": "failed"}
            return outcome, self.service.status()
        def done(payload):
            outcome, status = payload
            self.show_status(status)
            self.progress_label.setText(outcome["message"])
            self.load_local(after=lambda: self.progress_label.setText(outcome["message"]))
        self.run_task("检查本地缺口…", operation, done, cancellable=True)

    def repair(self):
        if self.service.mode != "wind":
            self.progress_label.setText("重取日期仅用于 Wind 正式数据")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("重取指定日期")
        form = QFormLayout(dialog)
        end = QDate.fromString(self.service.window()[1], "yyyy-MM-dd")
        first, last = QDateEdit(end), QDateEdit(end)
        for w in (first, last):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
        form.addRow("开始", first)
        form.addRow("结束", last)
        form.addRow(self.hint("仅重取所选范围的已有行情；有效结果校验后替换，其他缺口仍会补齐。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            self.sync(repair=(first.date().toString("yyyy-MM-dd"), last.date().toString("yyyy-MM-dd")))

    def import_snapshot(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入离线行情快照", str(self.service.root.parent / "research/index_futures_basis/outputs"), "行情快照 (*.json *.csv)")
        if not path:
            return
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(self.mode.findData("offline"))
        self.mode.blockSignals(False)
        self.service = BasisService(self.service.root, "offline")
        self.security_page.change_identity()
        self.refresh_window_profiles()
        self.invalidate_query()
        self.status_label.setText("离线研究快照 · 正在校验导入文件")
        self.dividend_label.setText("查询后显示离线分红来源")
        self.image_pixmap, self.image_path = QPixmap(), None
        self.image_label.clear()
        self.run_task("导入并校验离线行情…", lambda progress: self.service.import_snapshot(path), lambda result: self.load_local())

    def open_inputs(self):
        path = self.service.dividend_directories()[0]
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def import_dividend(self):
        if self.service.mode == "demo":
            self.progress_label.setText("演示使用独立合成分红；请切换正式或离线模式后导入")
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择分红表", str(self.service.dividend_directories()[0]), "分红表 (*.xlsx)")
        if not path:
            return
        self.invalidate_query()
        def operation(progress):
            source = Path(path)
            if not fnmatch.fnmatch(source.name, "*基差情况_*.xlsx"):
                raise ValueError("文件名应为 基差情况_日期.xlsx 或 指数基差情况_日期.xlsx")
            _, info = read_continuous_snapshot(source, self.service.config["dividends"])
            dest = self.service.dividend_directories()[0] / source.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != dest.resolve():
                with file_lock(dest.parent / ".writer.lock"):
                    if dest.exists():
                        archive = self.service.dividend_archive / (sha256(dest) + ".xlsx")
                        with file_lock(self.service.dividend_archive / ".writer.lock"):
                            copy_verified(dest, archive)
                    tmp = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
                    try:
                        copy_verified(source, tmp, expected_sha256=info["sha256"])
                        tmp.replace(dest)
                    finally:
                        tmp.unlink(missing_ok=True)
            return str(dest)
        self.run_task("读取分红表…", operation, lambda result: self.load_local())

    def export(self, kind, selected=None, refresh=True):
        if self.worker:
            return
        end = self.as_of()
        windows = self.service.output_windows(kind)
        if kind == "report" and self.service.mode == "wind":
            self.invalidate_query()
        def done(folder):
            manifest = json.loads((Path(folder) / "run_manifest.json").read_text(encoding="utf-8"))
            check = manifest.get("market_update_check", {})
            message = f"已保存（行情截至{manifest['actual_end']}）：{folder}"
            if check.get("state") == "fallback":
                message = check["message"] + "；" + message
            if manifest.get("data_availability", {}).get("partial"):
                message = "已按可用数据输出，缺失部分留空；" + message
            self.refresh_artifacts()
            pictures = sorted((Path(folder) / "figures").glob("*.png"))
            if pictures:
                self.show_image(pictures[0])
            if kind == "figures":
                self.tabs.setCurrentIndex(2)
            def finish():
                self.progress_label.setText(message)
                if check.get("state") == "fallback" and not self.closing:
                    QMessageBox.warning(self, "报告已使用本地可用数据生成", message)
            self.load_local(after=finish)
        self.run_task("检查行情并准备报告…" if kind == "report" and refresh else "使用本地数据准备导出…",
            lambda progress: self.service.export(kind, selected, end, progress, windows=windows, refresh=refresh), done,
            cancellable=kind == "report" and self.service.mode == "wind",
            failure=(lambda error: QMessageBox.warning(self, "报告未生成", error)) if kind == "report" else None)

    def export_query(self):
        if not self.query_result:
            self.progress_label.setText("请先完成查询")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存本次查询统计", str(self.service.exports_root / "查询统计.csv"), "CSV (*.csv)")
        if not path:
            return
        result = self.query_result
        def operation(progress):
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            frame = result["statistics"].copy()
            frame["指标"] = result["title"]
            frame["单位"] = result["unit"]
            frame["行情截止日"] = result["actual_end"]
            frame["分红日期"] = result["provenance"]["dividends"]["snapshot_date"]
            frame["口径"] = "固定分红假设；历史不含截止日；连续档位"
            frame["数据模式"] = self.service.mode
            frame["实际合约"] = result["current_contract"]
            frame["计算版本"] = result["fingerprint"]
            frame["分红文件SHA256"] = result["provenance"]["dividends"]["sha256"]
            tmp = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                frame.to_csv(tmp, index=False, encoding="utf-8-sig")
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
            return str(target)
        self.run_task("导出查询…", operation, lambda result: self.progress_label.setText("已保存：" + result))

    def refresh_artifacts(self):
        fingerprint = self.query_result["fingerprint"] if self.query_result else None
        self.artifact_items = self.service.artifacts(fingerprint)
        self.export_table.fill([[r[k] for k in ("created", "as_of", "dividend_date", "kind", "state", "path")] for r in self.artifact_items])

    def open_artifact(self, row, column):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.artifact_items[row]["path"]))

    def open_exports(self):
        self.service.exports_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.exports_root)))

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开图片", str(self.service.exports_root), "图片 (*.png)")
        if path:
            self.show_image(path)

    def show_image(self, path):
        self.image_path = Path(path)
        self.image_pixmap = QPixmap(str(path))
        label = f"{self.image_path.name}　|　{self.image_path.parent.parent.name}"
        manifest = self.image_path.parent.parent / "run_manifest.json"
        if manifest.exists():
            try:
                info = json.loads(manifest.read_text(encoding="utf-8"))
                label = (f"{self.image_path.name}　|　行情 {info['actual_end']}　|　分红 {info['dividends']['snapshot_date']}"
                         f"　|　{info['mode']}　|　版本 {info['fingerprint'][:10]}")
                saved_windows = info.get("configuration", {}).get("windows")
                if saved_windows:
                    label += "\n生成时：" + chart_window_label(self.image_path.stem, saved_windows)
            except (ValueError, KeyError):
                pass
        self.image_note.setText(label)
        self.scale_image()

    def scale_image(self):
        if self.image_pixmap.isNull():
            return
        if self.zoom.currentIndex() == 0:
            pixmap = self.image_pixmap.scaled(self.scroll.viewport().size() * .97, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        else:
            scale = int(self.zoom.currentText().rstrip("%")) / 100
            pixmap = self.image_pixmap.scaled(self.image_pixmap.size() * scale, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "scroll"):
            self.scale_image()

    def copy_image(self):
        if not self.image_pixmap.isNull():
            QApplication.clipboard().setPixmap(self.image_pixmap)

    def save_image(self):
        if not self.image_path:
            return
        path, _ = QFileDialog.getSaveFileName(self, "另存图片", self.image_path.name, "PNG (*.png)")
        if path and Path(path).resolve() != self.image_path.resolve():
            shutil.copyfile(self.image_path, path)

    def settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("股指基差设置")
        dialog.setMinimumWidth(650)
        form = QFormLayout(dialog)
        config = self.service.config
        inputs = QLineEdit(config["dividends"]["directories"][0])
        wind = QLineEdit(config["wind_python"])
        wind.setPlaceholderText("留空：使用当前 swhy_delta1 Python")
        data = QLineEdit(config["data_directory"])
        exports = QLineEdit(config["exports_directory"])
        inputs.setToolTip(f"@shared 使用公共分红目录：{self.service.paths.dividend_inputs}")
        data.setToolTip(f"@shared 使用公共行情目录：{self.service.paths.root / 'market/index_futures'}")
        exports.setToolTip(f"@shared 使用公共导出目录：{self.service.paths.export('index_futures_basis')}")
        months = QSpinBox()
        months.setRange(12, 36)
        months.setValue(config["history_months"])
        daily_time = QTimeEdit(QTime(config["close_hour"], config.get("close_minute", 0)))
        daily_time.setDisplayFormat("HH:mm")
        daily_time.setTimeRange(QTime(15, 5), QTime(23, 59))
        auto = QCheckBox("正式模式启动后自动检查并补齐")
        auto.setChecked(config["auto_sync"])
        for label, control in [("分红主目录", inputs), ("Wind Python", wind), ("本地数据目录", data), ("导出目录", exports),
                               ("历史窗口（月）", months), ("当日日线检查时间（北京时间）", daily_time)]:
            form.addRow(label, control)
        form.addRow(auto)
        form.addRow(self.hint("日线门槛后仍须校验字段完整。保存后重新打开应用生效；演示设置与正式设置分开。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            try:
                message = self.service.save_settings({"wind_python": wind.text().strip(), "data_directory": data.text().strip(),
                    "exports_directory": exports.text().strip(), "history_months": months.value(),
                    "close_hour": daily_time.time().hour(), "close_minute": daily_time.time().minute(),
                    "auto_sync": auto.isChecked(), "dividends": {**config["dividends"], "directories": [inputs.text().strip()]}})
                self.progress_label.setText(message)
            except Exception as exc:
                self.progress_label.setText(str(exc))

    def closeEvent(self, event):
        self.closing = True
        self.security_page.name_timer.stop()
        if self.worker is not None or self.security_page.name_worker is not None:
            self.service.cancel.set()
            self.progress_label.setText("等待当前批次结束后关闭；已保存数据保留")
            event.ignore()
        else:
            event.accept()


def launch(service, capture=None, startup_check=False):
    app = QApplication.instance() or QApplication([])
    font = Path("C:/Windows/Fonts/msyh.ttc")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Microsoft YaHei", 10))
    window = Window(service)
    window.show()
    if capture or startup_check:
        def finish():
            if window.worker is not None:
                return
            window.tabs.setCurrentIndex(1)
            if capture:
                path = Path(capture)
                path.parent.mkdir(parents=True, exist_ok=True)
                QTimer.singleShot(150, lambda: (window.grab().save(str(path)), app.quit()))
            else:
                app.quit()
        window.ready.connect(finish)
    return app.exec()
