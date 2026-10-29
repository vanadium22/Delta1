"""Native Windows report workspace. No browser, WebView or HTTP listener."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QTimer, Qt, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout,
                              QLineEdit, QMainWindow, QProgressBar, QScrollArea,
                              QStackedWidget, QVBoxLayout, QWidget, QComboBox)

from .desktop_theme import STYLE
from .desktop_widgets import (ColumnsDialog, CopyTable, DetailDialog, FilterRow,
                              PresetMappingDialog, ReportModel, SettingsDialog, button, default_visible, label)
from .bookkeeping import BookkeepingStore
from .bookkeeping_report import report_target_candidates
from .bookkeeping_widgets import BookkeepingDialog, report_ref
from .candidate_widgets import CandidateDialog, TargetPicker
from .query import read_table
from .service import ALL_REPORTS, ReportService
from .storage import REPORTS, ReportError
from .downloads import DOWNLOADS
from .download_widgets import DownloadsDialog, open_location

QUICK_FIELDS = {
    "标的物代码": ("标的物代码", "标的代码", "标的"),
    "标的物名称": ("标的物名称", "标的名称", "标的"),
    "交易对手名称": ("交易对手名称", "交易对手"),
    "交易确认书编号": ("交易确认书编号",),
    "合约编号": ("合约编号",),
    "交易达成日": ("交易达成日",),
    "起始日": ("起始日", "交易起始日"),
}


class Worker(QThread):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self.outcome = None

    def run(self):
        try:
            self.outcome = (True, self.job[1]())
        except Exception as exc:
            if isinstance(exc, ReportError):
                message = str(exc)
            elif isinstance(exc, PermissionError):
                message = "文件访问被拒绝，请检查文件占用和目录权限。"
            elif isinstance(exc, FileNotFoundError):
                message = "本地文件不存在，请刷新目录或重新同步。"
            else:
                message = f"读取或解析失败（{type(exc).__name__}）：{exc}"
            self.outcome = (False, message)


def app_icon():
    canvas = QPixmap(64, 64)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#152d49"))
    painter.drawRoundedRect(0, 0, 64, 64, 14, 14)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", 23, QFont.Weight.Bold))
    painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "D1")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#5fc4b0"))
    painter.drawEllipse(48, 10, 8, 8)
    painter.end()
    return QIcon(canvas)


class Window(QMainWindow):
    def __init__(self, service: ReportService, auto_start=True):
        super().__init__()
        self.service = service
        self.kind = "swap"
        self.catalog_data = None
        self.columns, self.visible, self.filters = [], [], []
        self.result = None
        self.page, self.sort = 1, None
        self.worker, self._pending = None, None
        self._generation = 0
        self._closing = self._syncing = False
        self._startup_done = self._startup_error = False
        self._auto_sync_pending = auto_start
        self.preferences = QSettings(str(service.settings.root / "ui.local.ini"), QSettings.Format.IniFormat)
        self.setWindowTitle("D1 日报工作台")
        self.setWindowIcon(app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1120, 720)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(350)
        self.debounce.timeout.connect(self.query)
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(250)
        self.sync_timer.timeout.connect(self.poll_sync)
        self.download_timer = QTimer(self)
        self.download_timer.setInterval(400)
        self.download_timer.timeout.connect(self.poll_downloads)
        self._build()
        geometry = self.preferences.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self._update_controls()
        if auto_start:
            QTimer.singleShot(0, self.refresh_catalog)

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(192)
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(16, 29, 16, 20)
        sidebar.setSpacing(12)
        sidebar.addWidget(label("D1 交易工作台", "brand"))
        sidebar.addWidget(label("DELTA ONE", "brandCaption"))
        sidebar.addSpacing(30)
        sidebar.addWidget(label("交易前查询"))
        self.nav = {}
        for kind, caption in (("swap", "收益互换日报"), ("review", "日报复核表")):
            control = button(caption, lambda checked=False, key=kind: self.switch_kind(key), "nav")
            control.setCheckable(True)
            control.setChecked(kind == self.kind)
            self.nav[kind] = control
            sidebar.addWidget(control)
        self.bookkeeping_button = button("人工簿记", self.open_bookkeeping, "nav")
        sidebar.addWidget(self.bookkeeping_button)
        sidebar.addSpacing(12)
        sidebar.addWidget(label("日报管理"))
        self.download_button = button("日报下载", self.open_downloads, "nav")
        self.query_button = button("查询全部日报", self.open_query, "nav")
        sidebar.addWidget(self.download_button)
        sidebar.addWidget(self.query_button)
        self.download_notice = label("四类日报 · 本地归档", "muted", True)
        sidebar.addWidget(self.download_notice)
        sidebar.addStretch()
        sidebar.addWidget(label("本地工作区\n\n按报表日期查阅\n原始文件保存在本机", wrap=True))
        layout.addWidget(side)
        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(24, 23, 24, 16)
        outer.setSpacing(13)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(5)
        title_box.addWidget(label("DAILY REPORTS", "eyebrow"))
        self.title = label("存续合约查询", "title")
        title_box.addWidget(self.title)
        title_box.addWidget(label("选择 Excel、日期和工作表，查询全部已保存日报。", "muted"))
        heading.addLayout(title_box, 1)
        self.import_button = button("导入 Excel", self.choose_import)
        self.settings_button = button("数据与同步", self.open_settings)
        self.sync_button = button("同步前一交易日", self.sync_current, "primary")
        for control in (self.import_button, self.settings_button, self.sync_button):
            heading.addWidget(control)
        outer.addLayout(heading)
        self.notice = label("正在读取本地目录…", "notice", True)
        outer.addWidget(self.notice)
        dataset, line = self._card(QHBoxLayout)
        line.setSpacing(12)
        self.report_combo = QComboBox()
        for key, spec in ALL_REPORTS.items():
            self.report_combo.addItem(spec["label"], key)
        self.report_combo.setMinimumWidth(155)
        self.report_combo.currentIndexChanged.connect(lambda: self.switch_kind(self.report_combo.currentData()))
        line.addWidget(self.report_combo)
        self.date_combo, self.sheet_combo = QComboBox(), QComboBox()
        self.date_combo.setMinimumWidth(148)
        self.sheet_combo.setMinimumWidth(170)
        self.sheet_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.origin = label("", "muted")
        self.epsilon = QLineEdit("1e-8")
        self.epsilon.setFixedWidth(95)
        self.epsilon.setToolTip("绝对容差：|x| ≤ ε 为近似零；范围和比较边界同样使用 ε。")
        for control in (label("报表日期"), self.date_combo, label("工作表"), self.sheet_combo):
            line.addWidget(control)
        line.addStretch()
        self.origin.hide()
        line.addWidget(label("容差 ε"))
        line.addWidget(self.epsilon)
        outer.addWidget(dataset)
        filters_card, filtering = self._card(QVBoxLayout)
        filtering.setSpacing(9)
        search_line = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("在全部字段中模糊搜索…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("全字段模糊搜索")
        self.clear_button = button("清空条件", self.clear_filters, "quiet")
        search_line.addWidget(self.search, 1)
        search_line.addWidget(self.clear_button)
        filtering.addLayout(search_line)
        quick_line = QHBoxLayout()
        quick_line.setSpacing(6)
        quick_line.addWidget(label("快捷添加", "sectionTitle"))
        self.quick_buttons = {}
        for name in QUICK_FIELDS:
            control = button(name, lambda checked=False, field=name: self.add_quick_filter(field), "quickField")
            self.quick_buttons[name] = control
            quick_line.addWidget(control)
        quick_line.addStretch()
        filtering.addLayout(quick_line)
        filter_heading = QHBoxLayout()
        filter_heading.setSpacing(6)
        filter_heading.addWidget(label("预设条件", "sectionTitle"))
        self.preset_amount = button("", name="preset")
        self.preset_amount.setCheckable(True)
        self.preset_amount.setChecked(True)
        self.preset_owner = button("", name="preset")
        self.preset_owner.setCheckable(True)
        self.preset_owner.setChecked(False)
        self.preset_amount.toggled.connect(self._preset_toggled)
        self.preset_owner.toggled.connect(self._preset_toggled)
        filter_heading.addWidget(self.preset_amount)
        filter_heading.addWidget(self.preset_owner)
        self.preset_mapping_button = button("映射列…", self.open_preset_mapping)
        self.preset_mapping_button.setToolTip("为当前工作表明确选择预设对应的列。")
        filter_heading.addWidget(self.preset_mapping_button)
        filter_heading.addStretch()
        filter_heading.addWidget(label("按列筛选", "sectionTitle"))
        self.add_button = button("＋ 添加条件", self.add_filter, "quiet")
        filter_heading.addWidget(self.add_button)
        filtering.addLayout(filter_heading)
        self.filter_scroll = QScrollArea()
        self.filter_scroll.setWidgetResizable(True)
        self.filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.filter_layout = QVBoxLayout(holder)
        self.filter_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_layout.setSpacing(6)
        self.filter_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.filter_scroll.setWidget(holder)
        self.filter_scroll.setFixedHeight(40)
        filtering.addWidget(self.filter_scroll)
        filtering.addWidget(label("预设与必须条件均需满足；任一 OR 至少满足一条。标的模糊/包含可用空格或分号分隔多个值。", "muted", True))
        outer.addWidget(filters_card)
        self.error = label("", "error", True)
        self.error.hide()
        outer.addWidget(self.error)
        results_card, results = self._card(QVBoxLayout)
        results.setSpacing(9)
        toolbar = QHBoxLayout()
        self.table_title = label("存续合约估值", "sectionTitle")
        self.count = label("等待读取", "count")
        toolbar.addWidget(self.table_title)
        toolbar.addWidget(self.count)
        toolbar.addStretch()
        self.selection_info = label("双击记录查看详情", "muted")
        toolbar.addWidget(self.selection_info)
        self.back_search_button = button("查找背对", self.open_candidates)
        self.back_search_button.setToolTip("在结果中先选中一行，确定目标合约，再查找相同标的的内部交易台候选。")
        self.back_search_button.setEnabled(False)
        toolbar.addWidget(self.back_search_button)
        self.copy_cell_button = button("复制单元格", lambda: self.table.copy_cell())
        self.copy_cell_button.setToolTip("先单击要复制的值，再点击此按钮；也可右键或按 Ctrl+Shift+C")
        self.copy_cell_button.setEnabled(False)
        self.copy_button = button("复制选中行", lambda: self.table.copy())
        self.columns_button = button("显示列", self.choose_columns)
        toolbar.addWidget(self.copy_cell_button)
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(self.columns_button)
        results.addLayout(toolbar)
        self.table = CopyTable()
        self.model = ReportModel(self.table)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(self.sort_column)
        self.table.doubleClicked.connect(self.show_detail)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.selectionModel().currentChanged.connect(self._selection_changed)
        self.table.cell_copied.connect(lambda name: self.statusBar().showMessage(f"已复制「{name}」的原始值", 5000))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        self.empty = label("正在读取本地目录…", "muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty)
        empty_layout.addStretch()
        self.stack.addWidget(empty)
        self.stack.setCurrentIndex(1)
        results.addWidget(self.stack, 1)
        pagination = QHBoxLayout()
        self.file_caption = label("", "muted")
        pagination.addWidget(self.file_caption, 1)
        self.location_button = button("打开保存位置", self.open_current_location, "quiet")
        pagination.addWidget(self.location_button)
        self.refresh_button = button("刷新本地", self.refresh_catalog, "quiet")
        pagination.addWidget(self.refresh_button)
        pagination.addWidget(label("每页"))
        self.page_size = QComboBox()
        self.page_size.addItems(["50", "100", "200"])
        pagination.addWidget(self.page_size)
        self.previous = button("上一页", lambda: self.turn_page(-1))
        self.page_label = label("1 / 1")
        self.next = button("下一页", lambda: self.turn_page(1))
        for control in (self.previous, self.page_label, self.next):
            pagination.addWidget(control)
        results.addLayout(pagination)
        outer.addWidget(results_card, 1)
        self.content = QStackedWidget()
        self.query_page = body
        self.statistics_page = None
        self.content.addWidget(body)
        layout.addWidget(self.content, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.setTextVisible(False)
        self.statusBar().addPermanentWidget(label("Excel 原始值读取 · 不重算公式", "muted"))
        self.statusBar().addPermanentWidget(self.progress)
        self.date_combo.currentIndexChanged.connect(self.load_report)
        self.sheet_combo.currentIndexChanged.connect(self.change_sheet)
        self.search.textChanged.connect(self.schedule_query)
        self.epsilon.textChanged.connect(self.schedule_query)
        self.page_size.currentIndexChanged.connect(self.schedule_query)

    @staticmethod
    def _card(layout_type):
        frame = QFrame()
        frame.setObjectName("card")
        layout = layout_type(frame)
        layout.setContentsMargins(13, 11, 13, 11)
        return frame, layout

    def _clear_result(self, message="正在查询…"):
        self.result = None
        self.model.set_result(columns=self.columns)
        self.empty.setText(message)
        self.stack.setCurrentIndex(1)
        self.count.setText("等待查询")
        self.page_label.setText("—")
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.copy_cell_button.setEnabled(False)
        self.selection_info.setText("双击记录查看详情")

    def _invalidate(self):
        self._generation += 1
        self._pending = None
        self._clear_result()

    def _submit(self, operation, on_success, message, mutation=False):
        self._generation += 1
        job = (self._generation, operation, on_success, message, mutation)
        self.error.hide()
        if self.worker is not None:
            self._pending = job
        else:
            self._start_job(job)

    def _start_job(self, job):
        self.worker = Worker(job, self)
        self.worker.finished.connect(self._finish_job)
        self.statusBar().showMessage(job[3])
        self._update_controls()
        self.worker.start()

    @Slot()
    def _finish_job(self):
        worker = self.worker
        self.worker = None
        pending, self._pending = self._pending, None
        if not self._closing and worker.job[0] == self._generation:
            ok, value = worker.outcome
            if ok:
                worker.job[2](value)
            else:
                self._show_error(value)
        worker.deleteLater()
        if pending and pending[0] == self._generation and not self._closing:
            self._start_job(pending)
        self._update_controls()
        self._finish_close()

    def _show_error(self, message):
        self._startup_done = self._startup_error = True
        self._clear_result("操作未完成，请调整条件或检查本地文件后重试。")
        self.error.setText(message)
        self.error.show()
        self.count.setText("查询未完成")
        self.statusBar().showMessage(message)

    def _update_controls(self):
        busy = self.worker is not None
        mutation = busy and self.worker.job[4]
        downloading = self.service.downloads_running()
        self.progress.setVisible(busy or self._syncing or downloading)
        for control in (self.settings_button, self.import_button, self.refresh_button):
            control.setEnabled(not busy and not self._syncing and not self._closing)
        stats_busy = bool(self.statistics_page and self.statistics_page.worker)
        self.settings_button.setEnabled(not busy and not stats_busy and not self._syncing and not downloading and not self._closing)
        self.download_button.setEnabled(not self._closing)
        self.query_button.setEnabled(not mutation and not self._closing)
        self.report_combo.setEnabled(not mutation and not self._closing)
        current_running = (self.service.download_status(self.kind)["state"] == "running"
                           if self.kind in DOWNLOADS else self._syncing)
        self.sync_button.setEnabled(not busy and not current_running and not self._closing)
        self.sync_button.setText("正在同步…" if current_running else
                                 "检查并同步" if self.kind in DOWNLOADS else "同步前一交易日")
        for control in (self.search, self.add_button, self.clear_button, self.epsilon,
                        self.filter_scroll, self.page_size, self.columns_button, self.preset_mapping_button):
            control.setEnabled(bool(self.columns) and not mutation and not self._closing)
        self._update_quick_controls(not mutation and not self._closing)
        self.date_combo.setEnabled(self.date_combo.count() > 0 and not mutation and not self._closing)
        self.sheet_combo.setEnabled(self.sheet_combo.count() > 0 and not mutation and not self._closing)
        for control in self.nav.values():
            control.setEnabled(not mutation and not self._closing)

    def refresh_catalog(self, *_args, preferred=None):
        self.debounce.stop()
        self._invalidate()
        day = preferred or self.date_combo.currentData()
        self._submit(self.service.query_catalog, lambda data: self._catalog_loaded(data, day), "正在读取本地目录…")

    def _catalog_loaded(self, data, preferred):
        self.catalog_data = data
        self.epsilon.blockSignals(True)
        self.epsilon.setText(str(data["settings"]["epsilon"]))
        self.epsilon.blockSignals(False)
        self._fill_dates(preferred)
        if self._auto_sync_pending:
            self._auto_sync_pending = False
            for kind in DOWNLOADS:
                self.start_download(kind)
            QTimer.singleShot(0, lambda: self.start_sync(only_missing=True))

    def _fill_dates(self, preferred=None):
        self.date_combo.blockSignals(True)
        self.date_combo.clear()
        for item in (self.catalog_data or {}).get("dates", []):
            if self.kind in item["files"]:
                self.date_combo.addItem(item["date"] + (" · 未齐" if self.kind in REPORTS and not item["complete"] else ""), item["date"])
        if preferred:
            self.date_combo.setCurrentIndex(max(0, self.date_combo.findData(preferred)))
        self.date_combo.blockSignals(False)
        self.load_report()

    def switch_kind(self, kind):
        self.content.setCurrentWidget(self.query_page)
        if self.kind == kind:
            if kind in self.nav:
                self.nav[kind].setChecked(True)
            return
        self.kind = kind
        self.report_combo.blockSignals(True)
        self.report_combo.setCurrentIndex(self.report_combo.findData(kind))
        self.report_combo.blockSignals(False)
        for key, control in self.nav.items():
            control.setChecked(key == kind)
        self.title.setText(ALL_REPORTS[kind]["label"] + "查询")
        if self.catalog_data is None:
            self.refresh_catalog()
        else:
            self._fill_dates(self.date_combo.currentData())

    def _remove_filters(self):
        for row in self.filters:
            self.filter_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.filters = []
        self.filter_scroll.setFixedHeight(40)

    def _reset_dataset(self):
        self.debounce.stop()
        self._invalidate()
        self.columns, self.visible = [], []
        self.page, self.sort = 1, None
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._remove_filters()
        self.model.set_result()
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self._update_controls()

    def load_report(self, *_):
        self._reset_dataset()
        kind, day = self.kind, self.date_combo.currentData()
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.blockSignals(False)
        self.table_title.setText(ALL_REPORTS[kind]["sheet"])
        self._provenance()
        if not day:
            self._clear_result("尚未保存日报\n\n在「数据与同步」中配置路径并同步，或选择「导入 Excel」。")
            self.count.setText("0 条记录")
            self._startup_done = True
            self._update_controls()
            return
        self._submit(lambda: self.service.sheets(kind, day), self._sheets_loaded, "正在读取工作表列表…")

    def _sheets_loaded(self, names):
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.addItems(names)
        self.sheet_combo.setCurrentIndex(max(0, self.sheet_combo.findText(ALL_REPORTS[self.kind]["sheet"])))
        self.sheet_combo.blockSignals(False)
        self.query(first=True)

    def change_sheet(self, *_):
        self._reset_dataset()
        self.query(first=True)

    def _provenance(self):
        day = self.date_combo.currentData()
        item = next((d for d in (self.catalog_data or {}).get("dates", []) if d["date"] == day), None)
        info = item["files"].get(self.kind) if item else None
        self.origin.setText(info["origin"] if info else "等待本地数据")
        self.file_caption.setText(info["name"] if info else "尚未保存报表")
        self.file_caption.setToolTip(info["path"] if info else "")
        if not info:
            message = "尚未保存日报。请配置共享来源并同步，或导入已有 Excel。"
        elif self.kind in REPORTS and not item["complete"]:
            message = f"当前显示 {day}，该日期仅保存了一份报表，请补齐另一份。"
        elif self.kind in DOWNLOADS:
            message = f"当前显示 {day} 的{ALL_REPORTS[self.kind]['label']}。点击「检查并同步」重查此来源，或在「日报下载」查看全部文件。"
        elif info["origin"] != "共享目录下载":
            message = f"当前显示 {day} 的{info['origin']}。连接公司网络后，可同步前一交易日报表。"
        else:
            message = f"当前显示 {day} 报表，来源为共享目录下载。同步选择早于今日的最新日期文件夹。"
        self.notice.setText(message)

    def _column_for(self, names):
        for name in names:
            matches = [column for column in self.columns if column["name"] == name]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                return None
        return None

    def _preset_mapping_key(self):
        return f"preset_mapping/{self.kind}/{self.sheet_combo.currentText()}"

    def _preset_mappings(self):
        raw = self.preferences.value(self._preset_mapping_key(), "{}")
        try:
            mappings = json.loads(raw)
            if not isinstance(mappings, dict) or any(key not in ("amount", "owner") for key in mappings):
                raise ValueError("invalid preset mapping")
            return mappings
        except (ValueError, TypeError):
            # Do not quietly restore automatic selection over a damaged saved mapping.
            return {"amount": {"name": "金额"}, "owner": {"name": "我的开仓"}}

    def _preset_column(self, key, names):
        mappings = self._preset_mappings()
        if key not in mappings:
            return self._column_for(names), False
        saved = mappings[key]
        if isinstance(saved, dict):
            matches = [column for column in self.columns
                       if column["id"] == saved.get("id") and column["name"] == saved.get("name")]
            if len(matches) == 1:
                return matches[0], False
        return None, True

    def open_preset_mapping(self):
        dialog = PresetMappingDialog(self.columns, self._preset_mappings(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            def available(key, names):
                if key not in dialog.mappings:
                    return self._column_for(names) is not None
                saved = dialog.mappings[key]
                return any(column["id"] == saved["id"] and column["name"] == saved["name"]
                           for column in self.columns)
            count = (len(self.filters)
                     + int(self.preset_amount.isChecked() and available("amount", ("标的名义本金额",)))
                     + int(self.preset_owner.isChecked() and available("owner", ("开仓操作人员",))))
            if count > 30:
                self.statusBar().showMessage("最多可组合 30 个条件，请先移除一条条件。")
                return
            key = self._preset_mapping_key()
            previous = self.preferences.value(key, "{}")
            self.preferences.setValue(key, json.dumps(dialog.mappings, ensure_ascii=False))
            self.preferences.sync()
            if self.preferences.status() != QSettings.Status.NoError:
                self.preferences.setValue(key, previous)
                self._update_quick_controls()
                self.error.setText("无法保存映射，请检查本机设置目录的写入权限。")
                self.error.show()
                return
            self._update_quick_controls()
            self.schedule_query()

    def _update_quick_controls(self, ready=True):
        for name, control in self.quick_buttons.items():
            column = self._column_for(QUICK_FIELDS[name])
            control.setEnabled(bool(column) and ready)
            control.setToolTip(("添加「" + column["name"] + "」筛选条件，输入值后生效。")
                               if column else "当前工作表缺少对应列或存在多个同名列，请手动选择。")
        for key, control, names, title, description in (
            ("amount", self.preset_amount, ("标的名义本金额",), "标的名义本金额 > 0.1",
             "严格大于 0.1，不使用 ε；空值和非数字不匹配。"),
            ("owner", self.preset_owner, ("开仓操作人员",), "我的开仓",
             "按我的工号精确匹配所选开仓人员列。"),
        ):
            column, stale = self._preset_column(key, names)
            control.setEnabled(bool(column) and ready)
            if key == "amount" and column:
                current_name = column["name"]
                title = (current_name if len(current_name) <= 12 else current_name[:12] + "…") + " > 0.1"
            if key == "owner" and column and column["name"] != "开仓操作人员":
                title = "我的开仓（需筛类型）"
                description = "仅按工号精确匹配所选列，不判断是否开仓；请另行筛选交易类型。"
            if self.columns and not column:
                mark = "需重配 · " if stale else "未映射 · "
            else:
                mark = "已开 · " if control.isChecked() else "未开 · "
            control.setText(mark + title)
            control.setToolTip((description + " 当前列：" + column["name"]) if column else
                               "原映射列已变化，请点击「映射列」重新选择。" if stale else
                               "当前工作表缺少或存在多个「" + names[0] + "」列；点击「映射列」选择。")

    def _preset_conditions(self):
        amount, _ = self._preset_column("amount", ("标的名义本金额",))
        owner, _ = self._preset_column("owner", ("开仓操作人员",))
        conditions = []
        if self.preset_amount.isChecked() and amount:
            conditions.append({"column": amount["id"], "value_type": "number", "op": "strict_gt",
                               "value": "0.1", "join": "must"})
        if self.preset_owner.isChecked() and owner:
            conditions.append({"column": owner["id"], "value_type": "text", "op": "eq",
                               "value": "201464", "join": "must"})
        return conditions

    def _preset_toggled(self, checked):
        if checked and len(self.filters) + len(self._preset_conditions()) > 30:
            control = self.sender()
            control.blockSignals(True)
            control.setChecked(False)
            control.blockSignals(False)
            self.statusBar().showMessage("最多可组合 30 个条件，请先移除一条条件。")
            self._update_quick_controls()
            return
        self._update_quick_controls()
        self.schedule_query()

    def add_quick_filter(self, name):
        column = self._column_for(QUICK_FIELDS[name])
        if not column:
            return
        row = self.add_filter(selected=column["id"])
        if row:
            self.filter_scroll.ensureWidgetVisible(row)
            row.value.setFocus()

    def add_filter(self, *_args, selected=None, schedule=True):
        if not self.columns:
            return
        if len(self.filters) + len(self._preset_conditions()) >= 30:
            self.statusBar().showMessage("最多可组合 30 个列条件。")
            return
        if selected is None:
            selected = next((c["id"] for c in self.columns if c["name"] in ("交易对手名称", "交易对手")), None)
        row = FilterRow(self.columns, selected, self)
        self.filters.append(row)
        self.filter_layout.addWidget(row)
        self._filter_height()
        row.changed.connect(self.schedule_query)
        row.removed.connect(self.remove_filter)
        if schedule:
            self.schedule_query()
        return row

    def remove_filter(self, row):
        self.filters.remove(row)
        self.filter_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._filter_height()
        self.schedule_query()

    def _filter_height(self):
        limit = 176 if self.height() >= 850 else 42
        self.filter_scroll.setFixedHeight(min(limit, max(40, len(self.filters) * 42)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "filter_scroll"):
            self._filter_height()

    def clear_filters(self):
        self._remove_filters()
        for control in (self.preset_amount, self.preset_owner):
            control.blockSignals(True)
            control.setChecked(False)
            control.blockSignals(False)
        self._update_quick_controls()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.sort = None
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.add_filter(schedule=False)
        self.schedule_query()

    def schedule_query(self, *_):
        self.page = 1
        self._invalidate()
        if self.columns and not self._closing:
            self.debounce.start()

    def query(self, *_args, first=False):
        self.debounce.stop()
        day, sheet = self.date_combo.currentData(), self.sheet_combo.currentText()
        if not day or not sheet or self._closing:
            return
        request = {"kind": self.kind, "date": day, "sheet": sheet,
                   "filters": self._preset_conditions() + [row.condition() for row in self.filters],
                   "search": self.search.text(), "epsilon": self.epsilon.text(),
                   "sort": self.sort, "page": self.page, "page_size": int(self.page_size.currentText())}
        self.table_title.setText(sheet)
        self._clear_result("正在读取工作表…" if first else "正在查询…")
        self._submit(lambda: self.service.query(request), lambda result: self._queried(result, first),
                     "正在读取工作表…" if first else "正在筛选记录…")

    def _queried(self, result, first):
        self.page, self.columns = result["page"], result["columns"]
        if first:
            try:
                stored = json.loads(self.preferences.value(self._columns_key(), "[]"))
            except (ValueError, TypeError):
                stored = []
            self.visible = [c["id"] for c in self.columns if c["id"] in stored] if isinstance(stored, list) else []
            if not self.visible:
                self.visible = default_visible(self.columns, self.kind)
            self.add_filter(schedule=False)
            # The first pass obtains columns; never display rows before applying
            # the enabled presets using those columns' actual IDs.
            if self._preset_conditions():
                self.query()
                return
        self.result = result
        self.model.set_result(result)
        self._apply_columns()
        self.stack.setCurrentIndex(0 if result["matched"] else 1)
        self.empty.setText("没有匹配的记录\n\n可缩短关键词，切换内容格式，或调整筛选范围。")
        self.count.setText(f"匹配 {result['matched']:,} / 共 {result['total']:,} 条")
        self.page_label.setText(f"{result['page']} / {result['pages']}")
        self.previous.setEnabled(result["page"] > 1)
        self.next.setEnabled(result["page"] < result["pages"])
        self.statusBar().showMessage("查询完成 · 右键或 Ctrl+Shift+C 复制单元格；Ctrl+C 复制选中行")
        if result.get("layout") == "grid":
            self.statusBar().showMessage("此工作表按原始单元格展示 · 列名为 Excel 列字母 · 合并单元格内容位于左上角")
        self._startup_done = True
        self._startup_error = False

    def _columns_key(self):
        return f"columns/{self.kind}/{self.sheet_combo.currentText()}"

    def _apply_columns(self):
        for index, column in enumerate(self.columns):
            self.table.setColumnHidden(index, column["id"] not in self.visible)
            self.table.setColumnWidth(index, min(280, max(130, len(column["name"]) * 15 + 30)))
        self.columns_button.setText(f"显示列 {len(self.visible)} / {len(self.columns)}")
        self._selection_changed()

    def choose_columns(self):
        dialog = ColumnsDialog(self.columns, self.visible, self.kind, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.visible = dialog.selected()
            self.preferences.setValue(self._columns_key(), json.dumps(self.visible))
            self._apply_columns()

    def turn_page(self, step):
        if self.result:
            self.page += step
            self.query()

    def sort_column(self, index):
        if index >= len(self.columns):
            return
        column = self.columns[index]["id"]
        direction = "desc" if self.sort == {"column": column, "direction": "asc"} else "asc"
        self.sort = {"column": column, "direction": direction}
        self.table.horizontalHeader().setSortIndicator(index, Qt.SortOrder.DescendingOrder if direction == "desc" else Qt.SortOrder.AscendingOrder)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.schedule_query()

    def _selection_changed(self, *_):
        count = len(self.table.selectionModel().selectedRows()) if self.result else 0
        self.selection_info.setText(f"已选 {count} 条 · Ctrl+C 复制" if count else "双击记录查看详情")
        self.copy_button.setEnabled(count > 0)
        self.copy_cell_button.setEnabled(bool(self.result) and self.table.can_copy_cell())
        self.back_search_button.setEnabled(count == 1)

    def _bookkeeping_store(self):
        return BookkeepingStore(self.service.settings.paths.root / "bookkeeping" / "manual.sqlite3")

    def open_bookkeeping(self):
        BookkeepingDialog(self._bookkeeping_store(), parent=self).exec()

    def open_candidates(self):
        selected = self.table.selectionModel().selectedRows() if self.result else []
        if len(selected) != 1:
            self.statusBar().showMessage("请先选中一行，确定目标合约。")
            return
        row = self.result["rows"][selected[0].row()]
        try:
            path = self.service.path_for(self.kind, self.result["date"])
            table = read_table(path, self.result["sheet"])
            source = {"date": self.result["date"], "filename": self.result["filename"],
                      "sheet": self.result["sheet"], "kind": self.kind}
            if self.kind != "swap" or self.result["sheet"] != "存续合约估值":
                selected_from = report_ref(table["columns"], row, source)["source"]
                target_path = self.service.path_for("swap", self.result["date"])
                target_table = read_table(target_path, "存续合约估值")
                proposed = report_target_candidates(table, row, target_table)
                if proposed["state"] != "matched":
                    raise ReportError("当前行未能在同日期的存续合约表中找到明确编号候选；请在存续合约表搜索并选择目标。")
                picker = TargetPicker(proposed, target_table["columns"], self)
                if picker.exec() != QDialog.DialogCode.Accepted:
                    return
                row, table = picker.selected_row, target_table
                source = {"date": self.result["date"], "filename": target_path.name,
                          "sheet": "存续合约估值", "kind": "swap", "selected_from": selected_from}
            CandidateDialog(self._bookkeeping_store(), table, row, source, self.preferences, self).exec()
        except Exception as exc:
            self.error.setText(str(exc) or "无法读取当前报表。")
            self.error.show()

    def show_detail(self, index):
        if self.result and index.isValid():
            DetailDialog(self.columns, self.result["rows"][index.row()],
                         f"{self.result['date']} · {self.result['sheet']}", self).exec()

    def open_settings(self):
        try:
            dialog = SettingsDialog(self.service.settings, self)
        except ReportError as exc:
            self._show_error(str(exc))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._invalidate()
            self._submit(lambda: self.service.update_settings(dialog.values),
                         lambda _: self._settings_saved(), "正在保存设置…", mutation=True)

    def _settings_saved(self):
        self.refresh_catalog()
        if self.statistics_page:
            self.statistics_page.refresh_dates()

    def open_current_location(self):
        try:
            day = self.date_combo.currentData()
            entry = next((d for d in (self.catalog_data or {}).get("dates", []) if d["date"] == day), {})
            path = entry.get("files", {}).get(self.kind, {}).get("path")
            open_location(path or self.service.settings.data_path())
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def open_downloads(self):
        DownloadsDialog(self.service, self.start_download, self).exec()

    def open_query(self):
        self.content.setCurrentWidget(self.query_page)
        self.report_combo.setFocus()
        self.report_combo.showPopup()

    def open_statistics(self):
        from .statistics_widgets import StatisticsPage
        try:
            if self.statistics_page is None:
                self.statistics_page = StatisticsPage(self.service, self)
                self.statistics_page.finished.connect(self._finish_close)
                self.statistics_page.busy_changed.connect(self._update_controls)
                self.content.addWidget(self.statistics_page)
            self.content.setCurrentWidget(self.statistics_page)
            for control in self.nav.values():
                control.setChecked(False)
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def sync_current(self):
        if self.kind in DOWNLOADS:
            self.start_download(self.kind)
        else:
            self.start_sync()

    def start_download(self, kind):
        if self._closing:
            return
        if kind in REPORTS:
            self.start_sync()
            return
        self.service.start_download(kind)
        self.download_timer.start()
        self.poll_downloads()

    def poll_downloads(self):
        states = [self.service.download_status(kind)["state"] for kind in DOWNLOADS]
        if "running" in states:
            self.download_notice.setText("正在检查新增日报…")
        else:
            self.download_timer.stop()
            self.download_notice.setText("部分同步未完成，点击查看" if any(s in ("error", "partial") for s in states)
                                         else "日报检查完成，点击查看")
            if not self._closing:
                self.refresh_catalog()
        self._update_controls()
        self._finish_close()

    def choose_import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "导入已有日报", str(self.service.settings.root), "Excel 日报 (*.xlsx)")
        if paths:
            self.import_paths([Path(path) for path in paths])

    def import_paths(self, paths):
        self._invalidate()
        self._submit(lambda: self.service.import_files(paths),
                     lambda results: self.refresh_catalog(preferred=max(item["date"] for item in results)),
                     "正在校验并保存 Excel…", mutation=True)

    def start_sync(self, *, only_missing=False):
        if self._closing:
            return
        try:
            if only_missing:
                self.service.start_sync(only_missing=True)
            else:
                self.service.start_sync()
        except ReportError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.error.hide()
        self._syncing = True
        self.statusBar().showMessage("正在检查前一交易日报表，缺失时自动同步…" if only_missing else "正在连接共享来源并校验两份报表…")
        self.sync_timer.start()
        self._update_controls()

    def poll_sync(self):
        state = self.service.sync_status()
        if state["state"] == "running":
            return
        self._syncing = False
        self.sync_timer.stop()
        if not self._closing:
            if state["state"] == "success":
                self.refresh_catalog(preferred=state["result"]["date"])
            else:
                self.error.setText(state.get("error", "同步未完成，请重试。"))
                self.error.show()
                self.statusBar().showMessage("同步未完成，本地报表可继续查询。")
        self._update_controls()
        self._finish_close()

    def closeEvent(self, event):
        if (self.worker is not None or self._syncing or self.service.downloads_running()
                or (self.statistics_page and self.statistics_page.worker)):
            self._closing = True
            self._generation += 1
            self._pending = None
            self.debounce.stop()
            if self.statistics_page:
                self.statistics_page.prepare_close()
            self.statusBar().showMessage("正在结束当前任务，完成后自动关闭…")
            self._update_controls()
            event.ignore()
            return
        self.debounce.stop()
        self.sync_timer.stop()
        self.download_timer.stop()
        if self.statistics_page:
            self.statistics_page.prepare_close()
        self.preferences.setValue("window/geometry", self.saveGeometry())
        self.preferences.sync()
        event.accept()

    def _finish_close(self):
        if (self._closing and self.worker is None and not self._syncing and not self.service.downloads_running()
                and not (self.statistics_page and self.statistics_page.worker)):
            QTimer.singleShot(0, self.close)


def main(argv=None):
    parser = argparse.ArgumentParser(description="D1 日报工作台 · 原生桌面 App")
    parser.add_argument("--root", type=Path, default=Path(__file__).parent,
                        help="本机配置与数据所在的模块目录")
    parser.add_argument("--startup-check", action="store_true", help="完成本地启动检查后退出")
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("D1 日报工作台")
    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    application.setStyleSheet(STYLE)
    window = Window(ReportService(args.root))
    if args.startup_check:
        window._auto_sync_pending = False
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    if args.startup_check:
        timer = QTimer(window)
        timer.setInterval(100)

        def check():
            if window._startup_done and window.worker is None:
                timer.stop()
                window.close()
                application.exit(1 if window._startup_error else 0)

        timer.timeout.connect(check)
        timer.start()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
