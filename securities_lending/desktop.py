from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget, QLineEdit, QComboBox, QSplitter,
)

from .calculation import decimal_value
from .config import ROOT, today
from .desktop_settings import SettingsDialog
from .desktop_contacts import ContactsDialog
from .desktop_theme import STYLE
from .desktop_widgets import BatchDialog, EmphasisDelegate, ResultTable, TargetEdit
from .exporting import clipboard_text, quality, rate_text, source_description, source_note, write_export
from .inventory import normalize_code
from .service import InventoryService
from .trader_contacts import contact_description, contact_for, contacts_path, load_contacts


def number(value, digits=2):
    value = decimal_value(value)
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:,.0f}"


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def configure_style(app):
    if sys.platform == "win32":
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(STYLE)


class Task(QThread):
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation, self.result, self.error = operation, None, None

    def run(self):
        try:
            self.result = self.operation(self.progress.emit)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"


class Window(QMainWindow):
    loaded = Signal()
    queried = Signal()

    def __init__(self, service=None, demo=False):
        super().__init__()
        self.service = service or InventoryService(demo=demo)
        self.contacts_path = contacts_path(self.service.root, self.service.demo)
        self.contacts, self.contacts_error = load_contacts(self.contacts_path)
        self.worker = None
        self.closing = False
        self.response = None
        self.items, self.messages = [], []
        self.target_texts, self.editors, self.batch_targets = {}, {}, {}
        self.target_modes, self.mode_editors = {}, {}
        self.restore_focus = None
        self.batch_text = ""
        self.restore_code = None
        self.current_date = today()
        self.last_status = self.service.state
        self.retry_action = self.refresh
        self.setWindowTitle("Delta1 券源工作台" + (" · 合成演示" if self.service.demo else ""))
        self.setWindowIcon(QIcon(str(ROOT / "static" / "favicon.svg")))
        self.setMinimumSize(940, 560)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1720, screen.width() - 40), min(920, screen.height() - 60))
        self.build_ui()
        self.auto_calculate = QTimer(self)
        self.auto_calculate.setSingleShot(True)
        self.auto_calculate.setInterval(900)
        self.auto_calculate.timeout.connect(self.calculate)
        self.rollover = QTimer(self)
        self.rollover.timeout.connect(self.check_date)
        self.rollover.start(30000)
        QTimer.singleShot(0, self.load_today)

    def button(self, text, callback, primary=False):
        button = QPushButton(text)
        button.clicked.connect(callback)
        if primary:
            button.setObjectName("primary")
        return button

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 8, 12, 6)
        layout.setSpacing(5)
        top = QHBoxLayout()
        top.addWidget(label("DELTA1", "brand"))
        top.addWidget(label("券源工作台", "title"))
        self.mode_label = label("合成演示 · 非真实业务数据" if self.service.demo else "正式模式", "mode")
        self.mode_label.setProperty("tone", "warning" if self.service.demo else "neutral")
        top.addWidget(self.mode_label)
        top.addStretch()
        self.refresh_button = self.button("同步当日券单  F5", self.refresh)
        self.refresh_button.setToolTip("强制从共享目录重新下载当日券单；普通启动优先读取已校验的当日本地副本。")
        self.folder_button = self.button("打开下载位置", self.open_local_data)
        self.folder_button.setToolTip("直接打开本次下载的 Excel 所在文件夹；读取失败时也可查看原文件。")
        self.settings_button = self.button("设置", self.settings)
        for button in (self.refresh_button, self.folder_button, self.settings_button):
            top.addWidget(button)
        layout.addLayout(top)

        states = QHBoxLayout()
        self.status_label = label("正在检查当日本地券单…", "badge")
        self.wind_label = label("演示价格 · 不连接 Wind" if self.service.demo else "Wind · 尚未请求行情", "badge")
        states.addWidget(self.status_label)
        states.addWidget(self.wind_label)
        states.addStretch()
        self.contacts_button = self.button("行业联系表…", self.edit_contacts)
        states.addWidget(self.contacts_button)
        self.source_button = self.button("文件与同步详情", self.show_source)
        states.addWidget(self.source_button)
        layout.addLayout(states)
        self.source_label = label("", "muted")
        self.source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        source_info = QHBoxLayout()
        source_info.addWidget(self.source_label, 1)
        self.contact_group = label("", "contactGroup")
        self.contact_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        source_info.addWidget(self.contact_group, 1)
        layout.addLayout(source_info)

        notices = QHBoxLayout()
        self.notice = label("", "notice")
        self.notice.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.notice_button = self.button("查看提示", self.show_messages)
        self.retry_button = self.button("重试", lambda: self.retry_action())
        for widget in (self.notice, self.notice_button, self.retry_button):
            widget.hide()
            notices.addWidget(widget, 1 if widget is self.notice else 0)
        layout.addLayout(notices)

        search = QHBoxLayout()
        self.symbols = QLineEdit()
        self.symbols.setPlaceholderText("输入代码或名称，空格/逗号分隔，例如：600519 300750 平安银行")
        self.symbols.setClearButtonEnabled(True)
        self.symbols.returnPressed.connect(self.query)
        search.addWidget(self.symbols, 1)
        self.batch_button = self.button("批量粘贴…", self.batch)
        self.query_button = self.button("查询库存与最新价", self.query, True)
        search.addWidget(self.batch_button)
        search.addWidget(self.query_button)
        layout.addLayout(search)

        summary = QHBoxLayout()
        self.metrics = []
        for heading in ("券单匹配", "库存 / 万股", "金额 / 万元", "不足"):
            summary.addWidget(label(heading, "muted"))
            value = label("—", "metric")
            self.metrics.append(value)
            summary.addWidget(value)
            summary.addSpacing(8)
        self.metrics[2].setToolTip("仅合计金额模式输入的目标名本；不包含股数模式的估算金额。")
        summary.addStretch()
        self.detail_button = self.button("券源明细", self.toggle_detail)
        self.detail_button.setCheckable(True)
        summary.addWidget(self.detail_button)
        actions = summary
        self.result_label = label("输入标的开始查询", "section")
        self.result_label.setParent(central)
        self.result_label.hide()
        self.copy_button = self.button("复制所选", self.copy_selected)
        self.export_button = self.button("导出…", self.export)
        self.calculate_button = self.button("刷新价格并计算  Ctrl+Enter", self.calculate, True)
        for button in (self.copy_button, self.export_button, self.calculate_button):
            button.setEnabled(False)
            actions.addWidget(button)
        layout.addLayout(actions)

        self.table = ResultTable(0, 10)
        self.table.setHorizontalHeaderLabels(["标的识别 / 库存", "行业", "最新价 / 元\n本次获取时间", "有效库存 / 股\n整百股上限", "库存市值\n万元", "参考费率", "要求金额 / 股数\n逐票选择单位", "需求 / 股", "可融判断 / 自有覆盖", "询券联系人\n群内 @"])
        self.table.setItemDelegate(EmphasisDelegate(self.table))
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(180)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for column, width in enumerate([140, 78, 104, 120, 86, 82, 125, 90, 260, 112]):
            self.table.setColumnWidth(column, width)
        # Keep the established logical calculation/editor columns; display contacts beside industry.
        self.table.horizontalHeader().moveSection(9, 2)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(lambda *args: self.show_detail(auto_expand=True))
        self.table.copyRequested.connect(self.copy_selected)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(7)
        self.splitter.addWidget(self.table)
        layout.addWidget(self.splitter, 1)

        self.detail_panel = QWidget()
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(4)
        detail_top = QHBoxLayout()
        self.detail_title = label("逐笔券源 · 选择股票查看", "section")
        self.detail_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        detail_top.addWidget(self.detail_title, 1)
        self.copy_detail_button = self.button("复制明细", self.copy_detail)
        detail_top.addWidget(self.copy_detail_button)
        detail_top.addWidget(self.button("计算与追溯", lambda: self.text_dialog("计算依据与原始券源", self.detail.toPlainText())))
        detail_layout.addLayout(detail_top)
        self.detail_verdict = label("", "verdict")
        self.detail_verdict.setWordWrap(True)
        detail_layout.addWidget(self.detail_verdict)
        self.detail_table = ResultTable(0, 8)
        self.detail_table.setHorizontalHeaderLabels(["来源", "期限", "出借费率", "有效库存 / 股", "实际可融 / 股", "可融股数 / 股", "券源说明", "文件 / Excel 行号"])
        self.detail_table.verticalHeader().hide()
        self.detail_table.setShowGrid(False)
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.detail_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_table.setWordWrap(False)
        self.detail_table.setMinimumHeight(70)
        self.detail_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for column, width in enumerate([120, 80, 90, 120, 114, 114, 250, 220]):
            self.detail_table.setColumnWidth(column, width)
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.detail_table.copyRequested.connect(self.copy_detail)
        detail_layout.addWidget(self.detail_table, 1)
        self.detail_panel.hide()
        self.splitter.addWidget(self.detail_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([310, 300])
        # Keep the complete calculation/provenance text available in its own dialog.
        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.hide()
        self.quote_note = label("金额：万元，向下取整至100股  ·  股数：100的正整数倍  ·  停止输入后自动刷新行情  ·  拖动中间分隔条调整明细", "muted")
        self.quote_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.quote_note.setToolTip("目标名本/股数每只股票分别输入；Ctrl+Enter 立即刷新价格并计算。数量结论仅依据当前券单，未分配具体费率/期限。价格使用本次 Wind RT_LAST，盘后可能为最近成交价。")
        layout.addWidget(self.quote_note)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(100)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("就绪 · 库存及名本仅供查询校验")
        self.statusBar().setToolTip(f"App Python：{sys.executable}")
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.calculate)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.symbols.setFocus())
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.batch)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.export)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        self.update_contacts()

    @property
    def busy(self):
        return self.worker is not None

    def update_controls(self):
        for control in (self.refresh_button, self.query_button, self.settings_button, self.contacts_button, self.symbols, self.batch_button, self.retry_button):
            control.setEnabled(not self.busy)
        for editor in self.editors.values():
            editor.setEnabled(not self.busy)
        for editor in self.mode_editors.values():
            editor.setEnabled(not self.busy)
        ready = bool(self.items and self.response) and not self.busy
        pending = any(item["calculation"]["status"] == "pending" for item in self.items)
        self.calculate_button.setEnabled(ready)
        self.export_button.setEnabled(ready and not pending)
        self.copy_button.setEnabled(ready and not pending)

    def run_task(self, message, operation, success):
        if self.busy:
            return
        self.statusBar().showMessage(message)
        self.progress.show()
        self.retry_button.hide()
        worker = Task(operation, self)
        self.worker = worker
        self.update_controls()
        worker.progress.connect(self.statusBar().showMessage)

        def complete():
            self.worker = None
            self.progress.hide()
            if worker.error:
                self.show_notices([worker.error])
                if self.response is None:
                    self.result_label.setText("操作失败 · 核对提示后重试")
                    self.wind_label.setText("行情 · 本次操作未完成")
                self.retry_button.show()
                self.statusBar().showMessage("操作失败，可点击重试")
            else:
                self.statusBar().showMessage("就绪 · " + ("合成演示数据" if self.service.demo else "使用本次查询结果"))
                success(worker.result)
            self.update_controls()
            worker.deleteLater()
            if self.closing:
                self.close()
        worker.finished.connect(complete)
        worker.start()

    def tone(self, widget, tone):
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def show_notices(self, messages=()):
        self.messages = list(dict.fromkeys(str(message) for message in messages if message))
        text = "；".join(self.messages).replace("\n", " ")
        self.notice.setText(text[:180] + ("…" if len(text) > 180 else ""))
        self.notice.setToolTip("\n".join(self.messages))
        self.notice.setVisible(bool(self.messages))
        self.notice_button.setVisible(bool(self.messages))

    def show_status(self, status):
        self.last_status = status
        self.current_date = status["date"]
        names = {"ready": "本次同步成功", "local": "使用当日本地券单 · 未重新下载", "cached": "使用当日缓存 · 本次同步失败", "unavailable": "当日券单不可用", "loading": "正在检查券单"}
        if status["state"] == "unavailable" and status.get("downloaded_files"):
            names["unavailable"] = "已下载 · 读取失败" if any(file.get("read_error") for file in status["downloaded_files"]) else "已下载 · 同步未完成"
        self.status_label.setText(f"{names[status['state']]}  |  {status['date']}（北京）")
        self.tone(self.status_label, {"ready": "ok", "local": "ok", "cached": "warning", "unavailable": "error"}.get(status["state"], "neutral"))
        files = status["files"]
        if not files and status.get("downloaded_files"):
            names = "、".join(file["name"] for file in status["downloaded_files"])
            self.source_label.setText(f"已下载待核查：{names}   |   下载：{status['attempt_downloaded_at']}   |   未作为库存使用")
        else:
            names = "、".join(file["name"] for file in files) or "尚无成功下载文件"
            kind = "缓存文件" if status["state"] == "cached" else "当日本地文件" if status["state"] == "local" else "文件"
            self.source_label.setText(f"{kind}：{names}   |   原下载时间：{status.get('downloaded_at') or '—'}   |   {status['security_count']} 只 / {status['record_count']} 笔")
        self.source_label.setToolTip(self.source_text())
        policy = self.service.active_config()["quantity_policy"]
        self.table.horizontalHeaderItem(3).setText("库存股数 / 股\n" + ("逐笔取小值汇总" if policy == "minimum" else "可融数量列"))
        self.show_notices(status["warnings"])
        self.retry_button.setVisible(status["state"] in {"cached", "unavailable"})

    def source_text(self):
        status = self.last_status
        lines = [f"模式：{'合成演示' if status['mode'] == 'demo' else '正式'}",
                 f"库存日期：{status['date']}（北京时间） | 状态：{status['state']}",
                 f"来源目录：{status.get('source_dir', '尚未读取')}",
                 f"文件名规则：{self.service.active_config()['file_glob']}",
                 f"读取方式：{'最新一份（按修改时间）' if self.service.active_config()['file_selection'] == 'latest' else '合并独立券源'}",
                 f"要求的 Sheet：{status.get('sheet_name', self.service.active_config()['sheet_name'])}",
                 f"本次检查：{status.get('refreshed_at') or '—'}",
                 f"本次文件下载：{status.get('attempt_downloaded_at') or '—'}",
                 f"当前有效库存的下载时间：{status.get('downloaded_at') or '—'}"]
        if status["state"] == "local":
            lines.append("本次读取：已校验当日本地副本；未访问共享目录，未检查公盘是否更新。需要更新请点击“同步当日券单”或 F5。")
        if status["state"] != "ready" and status.get("downloaded_files"):
            lines.append("\n本次下载文件（同步未完成，不作为当前库存；打开下载位置将定位这里）：")
            for file in status["downloaded_files"]:
                lines.extend([f"\n文件：{file['name']}", f"共享源：{file['source']}", f"本地文件：{file['path']}",
                              f"大小：{file['size']:,} 字节", f"SHA256：{file['sha256']}"])
                if file.get("source_sha256") == file["sha256"]:
                    lines.append("复制校验：共享源与本地副本 SHA256 一致")
                if "available_sheets" in file:
                    lines.append("实际 Sheet：" + "、".join(file["available_sheets"]))
                if file.get("read_error"):
                    lines.append("读取错误：" + file["read_error"])
        if status["files"]:
            lines.append("\n当前使用的有效库存" + ("（当日缓存）：" if status["state"] == "cached" else "："))
        for file in status["files"]:
            lines.extend([f"\n文件：{file['name']}", f"共享源：{file['source']}", f"本地快照：{file['path']}",
                          f"大小：{file['size']:,} 字节 | {file['records']} 行 | 表头第 {file['header_row']} 行",
                          f"SHA256：{file['sha256']}"])
        lines.append("\n本地按日期和批次保留完整 Excel 快照；这些目录不是 Excel 被拆开的内容。")
        lines.extend(["\n同步提示：", *status["warnings"]])
        return "\n".join(lines)

    def text_dialog(self, title, text, actions=()):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(min(850, self.width()), min(520, self.height()))
        layout = QVBoxLayout(dialog)
        contents = QPlainTextEdit(text)
        contents.setReadOnly(True)
        layout.addWidget(contents)
        buttons = QHBoxLayout()
        buttons.addWidget(self.button("复制全部详情", lambda: QApplication.clipboard().setText(text)))
        for caption, callback in actions:
            buttons.addWidget(self.button(caption, callback))
        buttons.addStretch()
        buttons.addWidget(self.button("关闭", dialog.accept))
        layout.addLayout(buttons)
        dialog.exec()

    def show_source(self):
        actions = [("打开下载位置", self.open_local_data)]
        files = self.local_files()
        if files:
            actions.append(("打开本地 Excel" if len(files) == 1 else "打开首个 Excel", self.open_local_excel))
        self.text_dialog("文件与同步详情", self.source_text(), actions)

    def show_messages(self):
        self.text_dialog("操作提示", "\n\n".join(self.messages))

    def local_files(self):
        return self.last_status.get("downloaded_files") or self.last_status.get("files", [])

    def open_local_excel(self):
        files = self.local_files()
        if not files:
            return
        path = Path(files[0]["path"])
        try:
            if not path.is_file():
                raise OSError("本地文件已不存在，请重新同步")
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
                raise OSError("系统未能打开 Excel 文件")
        except OSError as exc:
            self.show_notices([f"打开 Excel 失败：{exc}；路径：{path}"])

    def open_local_data(self):
        files = self.local_files()
        folder = Path(files[0]["path"]).parent if files else self.service.data_root
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))):
                raise OSError("系统未能打开文件夹")
            self.statusBar().showMessage(f"本地数据：{folder}")
        except OSError as exc:
            self.show_notices([f"打开本地数据失败：{exc}；路径：{folder}"])

    def clear_results(self):
        self.auto_calculate.stop()
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            self.restore_code = self.items[row]["code"]
        self.response = None
        self.items, self.editors, self.mode_editors = [], {}, {}
        self.table.setRowCount(0)
        self.detail.clear()
        self.detail_table.setRowCount(0)
        self.detail_title.setText("逐笔券源 · 选择股票查看")
        self.detail_verdict.clear()
        self.detail_panel.hide()
        self.detail_button.setChecked(False)
        for metric in self.metrics:
            metric.setText("—")
        self.update_controls()

    def refresh_done(self, status):
        self.show_status(status)
        message = ("使用当日本地券单，输入标的查询；需要公盘最新版本时按 F5" if status["state"] == "local" else
                   "券单已就绪，输入标的查询" if status["state"] == "ready" else
                   "使用当日缓存 · 本次同步失败，可查看提示后重试" if status["state"] == "cached" else
                   "已下载但读取失败 · 打开文件与同步详情，核对文件名和 Sheet" if any(file.get("read_error") for file in status.get("downloaded_files", [])) else
                   "已下载但同步未完成 · 查看提示后重试" if status.get("downloaded_files") else
                   "请检查共享盘和当日文件，再同步重试")
        self.result_label.setText(message)
        self.statusBar().showMessage(message)
        self.loaded.emit()

    def load_today(self):
        self.load_inventory(self.service.load_today, "正在检查当日本地券单…")

    def refresh(self):
        self.load_inventory(self.service.refresh, "正在下载并读取当日券单…")

    def load_inventory(self, operation, message):
        if self.busy:
            return
        self.retry_action = self.refresh
        self.clear_results()
        self.status_label.setText(f"{message}  |  {today()}")
        self.tone(self.status_label, "neutral")
        self.wind_label.setText("演示价格 · 不连接 Wind" if self.service.demo else "Wind · 等待下次查询")
        self.run_task(message, operation, self.refresh_done)

    def target_values(self):
        values = {}
        for code, text in self.target_texts.items():
            if text.strip() and self.target_modes.get(code, "amount") == "amount":
                value = decimal_value(text)
                values[code] = str(value * 10000) if value is not None and 0 < value <= 10000000000 else "invalid"
        return values

    def share_values(self):
        return {code: text for code, text in self.target_texts.items() if self.target_modes.get(code) == "shares"}

    def batch(self):
        if self.busy:
            return
        dialog = BatchDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            symbols, self.batch_targets = dialog.result_data
            self.batch_text = " ".join(symbols)
            self.symbols.setText(self.batch_text)
            self.query()

    def query(self):
        if self.busy:
            return
        symbols = self.symbols.text().strip()
        if not symbols:
            self.symbols.setFocus()
            self.show_notices(["请先输入证券代码或名称"])
            return
        inputs = dict(self.batch_targets) if symbols == self.batch_text else {}
        self.perform_query(symbols, inputs)

    def calculate(self):
        if not self.busy and self.items:
            focused = QApplication.focusWidget()
            self.restore_focus = next(((code, editor.cursorPosition()) for code, editor in self.editors.items() if editor is focused), None)
            self.perform_query(" ".join(item["code"] for item in self.items), {})

    def perform_query(self, symbols, inputs):
        targets = self.target_values()
        share_targets = self.share_values()
        self.retry_action = lambda: self.perform_query(symbols, inputs)
        self.clear_results()
        self.result_label.setText("正在匹配库存并获取本次价格…")
        self.wind_label.setText("合成价格 · 生成中" if self.service.demo else "Wind · 正在请求最新价")
        self.tone(self.wind_label, "neutral")
        self.run_task("正在查询…", lambda progress: self.service.query(symbols, targets, inputs, progress, **({"share_targets": share_targets} if share_targets else {})), self.render)

    def render(self, response):
        from PySide6.QtWidgets import QTableWidgetItem
        self.response = response
        self.show_status(response["status"])
        for code, value in response.get("targets", {}).items():
            amount = decimal_value(value)
            if amount is not None:
                self.target_texts[code] = format(amount / 10000, "f")
                self.target_modes[code] = "amount"
        for code, value in response.get("share_targets", {}).items():
            self.target_texts[code] = str(value)
            self.target_modes[code] = "shares"
        self.batch_targets = {}
        self.items = []
        seen = set()
        for group in response["results"]:
            for item in group.get("securities", group["matches"]):
                if item["code"] not in seen:
                    self.items.append(item)
                    seen.add(item["code"])
        notices = response["status"]["warnings"] + response["warnings"]
        self.show_notices(notices)
        self.table.setRowCount(len(self.items))
        self.editors = {}
        for row, item in enumerate(self.items):
            quote, calc = item["quote"] or {}, item["calculation"]
            retrieved = quote.get("retrieved_at", "")
            stock = number(item["quantity"], 0) + ("" if item["quantity_complete"] else "（已知）")
            stock = f"{stock}\n上限 {number(calc['maximum_shares'], 0)}"
            market_value = item.get("inventory_market_value")
            nominal = number(market_value / 10000 if market_value is not None else None)
            if market_value is None:
                nominal += "\n无法估值"
            multiple = len(item["rows"]) > 1
            identity = item.get("identification", "已识别")
            availability = item.get("inventory_message", "")
            values = [f"{item['name']}\n{item['code'] if normalize_code(item['code']) else '代码未确认'}\n{availability}" if item.get("identified") else f"{item['name']}\n{item['code'] if normalize_code(item['code']) else '代码未确认'}\n未确认标的身份", item["industry"] or "待补充",
                      number(quote.get("price"), 4) + (f"\n{retrieved[11:19]} 获取" if retrieved else "\n价格不可用"),
                      stock, nominal, rate_text(item) + ("\n逐笔见明细" if multiple else "") + ("" if item.get("rate_complete", False) else "\n费率缺失"),
                      "", number(calc["requested_shares"], 0), calc["message"]]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                cell.setTextAlignment((Qt.AlignmentFlag.AlignRight if column in (2, 3, 4, 5, 7) else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, cell)
                if column != 6:
                    cell.setData(Qt.ItemDataRole.UserRole, True)
            self.table.item(row, 0).setToolTip(f"{identity} · {item.get('identity_source') or 'Wind 未确认'}\n{availability}\n输入：{item.get('query_input', item['code'])}")
            if item.get("inventory_status") in {"absent", "zero"}:
                for column in (0, 3, 8):
                    self.table.item(row, column).setBackground(QColor("#fff0ed"))
                    self.table.item(row, column).setForeground(QColor("#b33a2d"))
            self.table.item(row, 3).setToolTip(f"有效库存合计：{number(item['quantity'], 4)} 股\n整百股上限：{number(calc['maximum_shares'], 0)} 股\n两列原始合计：实际可融 {number(item.get('quantity_actual'), 4)} 股 / 可融 {number(item.get('quantity_primary'), 4)} 股\n{quality(item)}")
            self.table.item(row, 4).setToolTip(f"库存市值 = 逐笔取较小值后的有效股数 × 本次最新价\n{number(market_value)} 元；不是目标名本。\n券单原始市值（仅参考）：{number(item['nominal'])} 元")
            self.paint_calculation(row)
            editor = TargetEdit(self.target_texts.get(item["code"], ""))
            editor.setObjectName("target")
            editor.setAlignment(Qt.AlignmentFlag.AlignRight)
            mode = self.target_modes.get(item["code"], "amount")
            editor.setPlaceholderText("股 · 100的倍数" if mode == "shares" else "万元")
            editor.setToolTip("每只票选择金额或股数；停止输入0.9秒后自动请求新价格。Enter / Tab 下一行；Ctrl+Enter 立即刷新计算。")
            editor.focused.connect(lambda index=row: self.focus_row(index))
            editor.advance.connect(lambda step, index=row: self.move_editor(index, step))
            editor.pasteColumn.connect(lambda text, index=row: self.paste_targets(index, text))
            editor.textEdited.connect(lambda text, code=item["code"], index=row: self.target_edited(code, index, text))
            container = QWidget()
            inputs = QVBoxLayout(container)
            inputs.setContentsMargins(5, 4, 5, 4)
            inputs.setSpacing(3)
            selector = QComboBox()
            selector.addItem("金额 / 万元", "amount")
            selector.addItem("数量 / 股", "shares")
            selector.setCurrentIndex(1 if mode == "shares" else 0)
            selector.currentIndexChanged.connect(lambda _value, code=item["code"], index=row: self.mode_changed(code, index))
            inputs.addWidget(selector)
            inputs.addWidget(editor)
            self.table.setCellWidget(row, 6, container)
            self.mode_editors[item["code"]] = selector
            self.editors[item["code"]] = editor
            self.table.setRowHeight(row, 78)
        self.update_contacts()
        self.update_metrics()
        wanted = next((i for i, item in enumerate(self.items) if item["code"] == self.restore_code), 0)
        if self.items:
            self.table.selectRow(wanted)
        self.show_detail(auto_expand=True)
        valid = sum(bool(item["quote"]) for item in self.items)
        times = [(item["quote"] or {}).get("retrieved_at", "") for item in self.items]
        latest = max(times, default="")
        if self.service.demo:
            self.wind_label.setText(f"合成价格 · {valid}/{len(self.items)} 只可用")
            self.tone(self.wind_label, "warning")
        else:
            self.wind_label.setText(f"Wind · 本次 {valid}/{len(self.items)} 只价格可用" + (f" · {latest[11:19]} 获取" if latest else ""))
            self.tone(self.wind_label, "ok" if valid and valid == len(self.items) else "warning" if valid else "error")
        self.wind_label.setToolTip("仅表示本次请求结果，不代表持续连接。价格获取时间见各行；Wind返回时间见券源明细。")
        self.result_label.setText(f"结果 {len(self.items)} 只 · 需求不自动缩减" if self.items else "无匹配结果 · 请核对代码或名称")
        expected_prices = sum(bool(normalize_code(item["code"])) for item in self.items)
        self.retry_button.setVisible(valid < expected_prices or response["status"]["state"] in {"cached", "unavailable"})
        if response["status"]["state"] in {"cached", "unavailable"}:
            self.retry_action = self.refresh
        self.update_controls()
        if self.restore_focus:
            code, position = self.restore_focus
            if code in self.editors:
                self.editors[code].setFocus()
                self.editors[code].setCursorPosition(position)
            self.restore_focus = None
        self.queried.emit()

    def paint_calculation(self, row):
        item = self.items[row]
        calc, coverage = item["calculation"], item.get("coverage", {})
        cell = self.table.item(row, 8)
        maximum = decimal_value(calc.get("maximum_nominal"))
        headline = coverage.get("message", calc["message"])
        if item.get("inventory_status") in {"absent", "zero"}:
            headline = "库存没有 · 当前不可融"
        text = headline + f"\n自有 {number(coverage.get('own_shares'), 0)} / 其他 {number(coverage.get('other_shares'), 0)} 股"
        text += f"\n最多 {number(calc.get('maximum_shares'), 0)} 股 · " + (f"约 {number(maximum / 10000)} 万元" if maximum is not None else "金额无法估算")
        if calc["status"] == "pending":
            text = "需求已修改 · 正在等待新行情\n待自动刷新价格并计算"
        cell.setText(text)
        cell.setToolTip(f"{calc['message']}\n{coverage.get('message', '')}\n自有缺口：{number(coverage.get('other_needed_shares'), 0)} 股；合计缺口：{number(coverage.get('shortage_shares'), 0)} 股\n仅依据当前券单，其他来源需询券确认；不同费率/期限未自动分配。")
        tone = "#166650" if coverage.get("status") == "own" else "#8b5918" if coverage.get("status") in {"other", "combined"} else "#b33a2d" if calc["status"] in {"insufficient", "invalid", "no_price", "unknown_inventory"} or item.get("inventory_status") in {"zero", "absent"} else "#526b7b"
        cell.setForeground(QColor(tone))

    def update_metrics(self):
        self.metrics[0].setText(str(self.response["summary"]["matched"]) if self.response else "—")
        total = self.response["summary"]["quantity"] if self.response else None
        partial = bool(self.response and not self.response["summary"]["quantity_complete"])
        self.metrics[1].setText(number(total / 10000 if total is not None else None) + ("（已知）" if partial and total is not None else ""))
        known = [value for item in self.items if self.target_modes.get(item["code"], "amount") == "amount" and (value := decimal_value(self.target_texts.get(item["code"], ""))) is not None and 0 < value <= 10000000000]
        self.metrics[2].setText(number(sum(known)) if known else "—")
        self.metrics[3].setText(str(sum(item["calculation"]["status"] == "insufficient" for item in self.items)))

    def focus_row(self, row):
        self.table.setCurrentCell(row, 6)
        self.show_detail()

    def move_editor(self, row, step):
        next_row = row + step
        if 0 <= next_row < len(self.items):
            editor = self.editors[self.items[next_row]["code"]]
            self.table.scrollToItem(self.table.item(next_row, 6))
            editor.setFocus()
            editor.selectAll()
        else:
            self.calculate_button.setFocus()

    def paste_targets(self, start, text):
        if self.busy:
            return
        values = [line.strip() for line in text.strip().splitlines()]
        if not values or any("\t" in value for value in values) or start + len(values) > len(self.items):
            self.show_notices(["请粘贴一列数值，按各行所选单位填写，行数不能超过当前行至表尾；代码与金额两列请用“批量粘贴”。"])
            return
        parsed = [decimal_value(value) for value in values]
        if any(value is None or not 0 < value <= 10000000000 or
               (self.target_modes.get(self.items[row]["code"]) == "shares" and value % 100)
               for row, value in enumerate(parsed, start)):
            self.show_notices(["整列未应用：请按各行单位输入正数；数量须为100股的整数倍。"])
            return
        for row, text in enumerate(values, start):
            code = self.items[row]["code"]
            self.editors[code].setText(text)
            self.target_edited(code, row, text)
        self.statusBar().showMessage(f"已按各行单位填入 {len(values)} 行需求，等待自动刷新价格并计算")

    def mode_changed(self, code, row):
        self.target_modes[code] = self.mode_editors[code].currentData()
        editor = self.editors[code]
        editor.clear()  # Do not reinterpret a monetary amount as a share count.
        editor.setPlaceholderText("股 · 100的倍数" if self.target_modes[code] == "shares" else "万元")
        self.target_edited(code, row, "")
        editor.setFocus()

    def target_edited(self, code, row, text):
        self.target_texts[code] = text
        self.items[row]["calculation"] = {**self.items[row]["calculation"], "status": "pending", "message": "待刷新价格并计算", "requested_shares": None, "executable_shares": None, "actual_nominal": None, "unused_nominal": None, "target_nominal": None}
        self.items[row]["coverage"] = {"status": "pending", "message": "需求已修改，待自动刷新价格并计算"}
        self.table.item(row, 7).setText("—")
        self.paint_calculation(row)
        self.update_metrics()
        self.update_controls()
        self.show_detail()
        self.auto_calculate.start()

    def toggle_detail(self):
        self.detail_panel.setVisible(self.detail_button.isChecked())
        self.show_detail()

    def show_detail(self, auto_expand=False):
        from PySide6.QtWidgets import QTableWidgetItem
        row = self.table.currentRow()
        if not self.response or not 0 <= row < len(self.items):
            return
        item = self.items[row]
        if auto_expand:
            self.detail_button.setChecked(True)
        self.detail_panel.setVisible(self.detail_button.isChecked())
        title = f"{item['name']} {item['code']} · {len(item['rows'])} 笔券源 · 有效库存合计 {number(item['quantity'], 0)} 股" + ("（仅已知部分）" if not item["quantity_complete"] else "")
        self.detail_title.setText(title)
        self.detail_title.setToolTip(title + "；不同费率、期限、来源逐笔保留，不自动分配需求。")
        coverage, calc = item.get("coverage", {}), item["calculation"]
        self.detail_verdict.setText(self.table.item(row, 8).text().replace("\n", "  ·  "))
        self.tone(self.detail_verdict, "ok" if coverage.get("status") == "own" else "error" if item.get("inventory_status") in {"zero", "absent"} or coverage.get("status") == "insufficient" else "warning")
        self.detail_verdict.setToolTip(self.table.item(row, 8).toolTip())
        self.detail_table.setRowCount(len(item["rows"]))
        for index, source in enumerate(item["rows"]):
            values = [source.get("source") or "未提供", source["term"] or "未提供",
                      number(source["rate"], 4) + "%" if source["rate"] is not None else source["rate_raw"] or "未提供",
                      number(source["quantity"], 4), number(source.get("quantity_actual"), 4), number(source.get("quantity_primary"), 4),
                      source_note(source) or "—", f"{source['file']} · 第 {source['row']} 行"]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment((Qt.AlignmentFlag.AlignRight if column in (2, 3, 4, 5) else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
                cell.setToolTip(source_description(source) + f"\n本地：{source.get('local_path', '—')}")
                if source_note(source) and column in (0, 6):
                    cell.setForeground(QColor("#166650"))
                if column in (2, 3, 4, 5) or source_note(source) and column in (0, 6):
                    font = cell.font()
                    font.setBold(True)
                    font.setPixelSize(14)
                    cell.setFont(font)
                self.detail_table.setItem(index, column, cell)
            self.detail_table.setRowHeight(index, 38)
        self.copy_detail_button.setEnabled(bool(item["rows"]))
        quote, calc = item["quote"] or {}, item["calculation"]
        lines = [f"{item['name']}  {item['code']} | 行业：{item['industry'] or '待补充'}（{item.get('industry_source') or '无来源'}）",
                 contact_description(item["contact"]),
                 f"价格：{quote.get('price', '缺失')} 元 | 来源：{quote.get('source', '无有效价格')} | 获取：{quote.get('retrieved_at', '—')}",
                 f"Wind 返回时间：{quote.get('wind_returned_at') or '未提供'}（不保证为逐笔成交时间）",
                 f"标的识别：{item.get('identification', '—')}（{item.get('identity_source') or '未确认'}） | {item.get('inventory_message', '')}",
                 f"当前输入：{self.target_texts.get(item['code']) or '未填'} {'股' if self.target_modes.get(item['code']) == 'shares' else '万元'} | 校验：{calc['message']}",
                 f"券源覆盖：{coverage.get('message', '—')} | 自有上限 {number(coverage.get('own_shares'), 0)} 股 | 其他来源上限 {number(coverage.get('other_shares'), 0)} 股",
                 f"自有缺口 {number(coverage.get('other_needed_shares'), 0)} 股 | 合计仍缺 {number(coverage.get('shortage_shares'), 0)} 股；仅按当前券单校验，不代表成交承诺。",
                 f"库存市值（本次最新价）：{number(item.get('inventory_market_value'))} 元；券单原始市值仅供追溯，不参与此计算。",
                 f"取整名本：{number(calc.get('actual_nominal'))} 元 | 未用名本：{number(calc.get('unused_nominal'))} 元 | 最大可借名本：{number(calc.get('maximum_nominal'))} 元",
                 f"数据完整性：{quality(item)}",
                 f"库存日期：{self.response['status']['date']} | 下载：{self.response['status'].get('downloaded_at') or '未同步'}",
                 "—— 逐笔券源（不同费率分别保留）——"]
        for source in item["rows"]:
            lines.extend([source_description(source), f"本地：{source.get('local_path', '—')}"])
        self.detail.setPlainText("\n".join(lines))

    def copy_detail(self):
        row = self.table.currentRow()
        if not self.response or not 0 <= row < len(self.items):
            return
        item = self.items[row]
        rows = sorted({index.row() for index in self.detail_table.selectionModel().selectedRows()}) or list(range(len(item["rows"])))
        QApplication.clipboard().setText(clipboard_text([item], self.response["status"], detail_indices=rows))
        self.statusBar().showMessage(f"已复制 {len(rows)} 笔券源明细（含期限、来源与文件行号）")

    def update_contacts(self):
        from PySide6.QtWidgets import QTableWidgetItem
        group, note = self.contacts["group"], self.contacts["note"]
        text = "联系表读取失败 · 点击「行业联系表」修复" if self.contacts_error else f"询券微信群：{group or '未设置'}" + (f" · {note}" if note else "")
        self.contact_group.setText(text)
        origin = str(self.contacts_path) if self.contacts_path.exists() else "随 App 提供的照片暂读初稿"
        self.contact_group.setToolTip(f"{text}\n来源：{origin}\n{self.contacts_error}\n可在「行业联系表」中修改；没有明确映射的行业留空。")
        self.table.horizontalHeaderItem(9).setToolTip(self.contact_group.toolTip())
        for row, item in enumerate(self.items):
            contact = contact_for(item.get("industry"), self.contacts)
            item["contact"] = contact
            cell = QTableWidgetItem("\n".join("@" + name for name in contact["traders"]))
            cell.setToolTip(contact_description(contact) + f"\n联系表来源：{origin}")
            font = cell.font()
            font.setBold(True)
            font.setPixelSize(13)
            cell.setFont(font)
            cell.setForeground(QColor("#205e7a"))
            self.table.setItem(row, 9, cell)

    def edit_contacts(self):
        if self.busy:
            return
        pending = self.auto_calculate.isActive()
        self.auto_calculate.stop()
        dialog = ContactsDialog(self.contacts, self.contacts_path, self, self.contacts_error)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.contacts, self.contacts_error = dialog.book, ""
            self.update_contacts()
            self.show_detail()
            self.statusBar().showMessage("行业联系表已保存并应用；当前需求和计算结果保留。")
        if pending:
            self.auto_calculate.start()

    def settings(self):
        if self.busy:
            return
        dialog = SettingsDialog(self.service.config, self, demo=self.service.demo)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.retry_action = self.refresh
            self.clear_results()
            self.run_task("正在保存设置并同步库存…", lambda progress: self.service.update_config(dialog.config, progress), self.refresh_done)

    def export_ready(self):
        return bool(self.response and self.items) and not self.busy and not any(item["calculation"]["status"] == "pending" for item in self.items)

    def copy_selected(self):
        if not self.export_ready():
            self.statusBar().showMessage("请先完成查询；名本修改后须刷新价格并计算")
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows:
            self.statusBar().showMessage("请先选择需要复制的行，可使用 Ctrl / Shift 多选")
            return
        QApplication.clipboard().setText(clipboard_text([self.items[row] for row in rows], self.response["status"]))
        self.statusBar().showMessage(f"已复制 {len(rows)} 行（含表头、单位、状态与来源），可直接粘贴到 Excel")

    def export(self):
        if not self.export_ready():
            return
        default = self.service.exports_root / f"券源换算_{self.response['status']['mode']}_{self.current_date}.xlsx"
        path, selected = QFileDialog.getSaveFileName(self, "导出结果与券源明细", str(default), "Excel 工作簿 (*.xlsx);;CSV 汇总 (*.csv);;CSV 券源明细 (*.csv)")
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix(".xlsx" if selected.startswith("Excel") else ".csv")
        items, status = list(self.items), self.response["status"]
        self.retry_action = self.export
        self.run_task("正在导出结果与来源…", lambda progress: write_export(destination, items, status, "券源明细" in selected),
                      lambda result: self.statusBar().showMessage(f"已保存：{destination}"))

    def export_to(self, path, detail_only=False):
        if not self.export_ready():
            raise ValueError("结果尚未就绪或名本已修改，请刷新价格并计算")
        write_export(path, self.items, self.response["status"], detail_only)

    def check_date(self):
        if not self.busy and today() != self.current_date:
            self.load_today()

    def closeEvent(self, event):
        self.auto_calculate.stop()
        if self.busy:
            self.closing = True
            self.statusBar().showMessage("正在等待当前后台操作完成后关闭…")
            event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="Delta1 原生券源与名本换算 App")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--capture", help="保存原生窗口演示截图后退出")
    parser.add_argument("--startup-check", action="store_true")
    args = parser.parse_args()
    if args.capture:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Delta1.SecuritiesLending")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Delta1 券源工作台")
    configure_style(app)
    window = Window(demo=args.demo)
    if args.capture:
        window.resize(1720, 920)
        def prepare():
            window.symbols.setText("600519 300750 000001 000858 601318 600036 688981")
            window.target_texts.update({"600519.SH": "500", "300750.SZ": "5000", "000001.SZ": "100", "000858.SZ": "100"})
            window.query()
        def capture():
            path = Path(args.capture).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(path)):
                raise RuntimeError("无法保存截图")
            print(f"Native App screenshot: {path}")
            window.close()
        window.loaded.connect(prepare)
        window.queried.connect(lambda: QTimer.singleShot(200, capture))
        QTimer.singleShot(60000, window.close)
    elif args.startup_check:
        window.loaded.connect(window.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
