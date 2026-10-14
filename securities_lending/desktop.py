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
    QSizePolicy, QVBoxLayout, QWidget, QLineEdit,
)

from .calculation import decimal_value, size_order
from .config import ROOT, today
from .desktop_settings import SettingsDialog
from .desktop_theme import STYLE
from .desktop_widgets import BatchDialog, ResultTable, TargetEdit
from .exporting import clipboard_text, quality, rate_text, source_description, write_export
from .inventory import normalize_code
from .service import InventoryService


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
        self.worker = None
        self.closing = False
        self.response = None
        self.items, self.messages = [], []
        self.target_texts, self.editors, self.batch_targets = {}, {}, {}
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
        self.rollover = QTimer(self)
        self.rollover.timeout.connect(self.check_date)
        self.rollover.start(30000)
        QTimer.singleShot(0, self.refresh)

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
        layout.setContentsMargins(16, 12, 16, 10)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("DELTA1", "brand"))
        top.addWidget(label("券源工作台", "title"))
        self.mode_label = label("合成演示 · 非真实业务数据" if self.service.demo else "正式模式", "mode")
        self.mode_label.setProperty("tone", "warning" if self.service.demo else "neutral")
        top.addWidget(self.mode_label)
        top.addStretch()
        self.refresh_button = self.button("同步当日券单  F5", self.refresh)
        self.folder_button = self.button("打开本地数据", self.open_local_data)
        self.settings_button = self.button("设置", self.settings)
        for button in (self.refresh_button, self.folder_button, self.settings_button):
            top.addWidget(button)
        layout.addLayout(top)

        states = QHBoxLayout()
        self.status_label = label("正在同步运行日券单…", "badge")
        self.wind_label = label("演示价格 · 不连接 Wind" if self.service.demo else "Wind · 尚未请求行情", "badge")
        states.addWidget(self.status_label)
        states.addWidget(self.wind_label)
        states.addStretch()
        self.source_button = self.button("文件与同步详情", self.show_source)
        states.addWidget(self.source_button)
        layout.addLayout(states)
        self.source_label = label("", "muted")
        self.source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.source_label)

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
        for heading in ("匹配 / 只", "库存 / 万股", "目标名本 / 万元", "库存不足 / 只"):
            summary.addWidget(label(heading, "muted"))
            value = label("—", "metric")
            self.metrics.append(value)
            summary.addWidget(value)
            summary.addSpacing(16)
        summary.addStretch()
        self.detail_button = self.button("券源明细", self.toggle_detail)
        self.detail_button.setCheckable(True)
        summary.addWidget(self.detail_button)
        layout.addLayout(summary)

        actions = QHBoxLayout()
        self.result_label = label("输入标的开始查询", "section")
        actions.addWidget(self.result_label, 1)
        self.copy_button = self.button("复制所选", self.copy_selected)
        self.export_button = self.button("导出…", self.export)
        self.calculate_button = self.button("刷新价格并计算  Ctrl+Enter", self.calculate, True)
        for button in (self.copy_button, self.export_button, self.calculate_button):
            button.setEnabled(False)
            actions.addWidget(button)
        layout.addLayout(actions)

        self.table = ResultTable(0, 9)
        self.table.setHorizontalHeaderLabels(["证券 / 代码", "行业", "最新价 / 元\n本次获取时间", "库存股数 / 股\n逐笔取小值再合计", "库存市值 / 万元\n按本次最新价", "出借费率", "目标名本\n万元 · 可编辑", "需求股数\n100 股向下取整", "校验结果"])
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
        for column, width in enumerate([126, 78, 108, 196, 122, 86, 114, 118, 225]):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(lambda *args: self.show_detail())
        self.table.copyRequested.connect(self.copy_selected)
        layout.addWidget(self.table, 1)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        self.detail.setPlaceholderText("选择标的，查看各笔数量、费率、期限、来源及计算依据。")
        self.detail.hide()
        layout.addWidget(self.detail)
        self.quote_note = label("目标名本单位：万元  ·  Tab / Enter 下一行，Shift+Tab / ↑ 上一行  ·  可粘贴一列名本  ·  Ctrl+C 复制所选行", "muted")
        self.quote_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.quote_note.setToolTip("目标名本每只股票分别输入；Ctrl+Enter 重新获取价格并计算。价格使用本次 Wind RT_LAST，盘后可能为最近成交价。")
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

    @property
    def busy(self):
        return self.worker is not None

    def update_controls(self):
        for control in (self.refresh_button, self.query_button, self.settings_button, self.symbols, self.batch_button, self.retry_button):
            control.setEnabled(not self.busy)
        for editor in self.editors.values():
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
        text = "；".join(self.messages)
        self.notice.setText(text[:180] + ("…" if len(text) > 180 else ""))
        self.notice.setToolTip("\n".join(self.messages))
        self.notice.setVisible(bool(self.messages))
        self.notice_button.setVisible(bool(self.messages))

    def show_status(self, status):
        self.last_status = status
        self.current_date = status["date"]
        names = {"ready": "本次同步成功", "cached": "使用当日缓存 · 本次同步失败", "unavailable": "当日券单不可用", "loading": "正在同步"}
        self.status_label.setText(f"{names[status['state']]}  |  {status['date']}（北京）")
        self.tone(self.status_label, {"ready": "ok", "cached": "warning", "unavailable": "error"}.get(status["state"], "neutral"))
        files = status["files"]
        names = "、".join(file["name"] for file in files) or "尚无成功下载文件"
        self.source_label.setText(f"文件：{names}   |   下载：{status.get('downloaded_at') or '—'}   |   {status['security_count']} 只 / {status['record_count']} 笔")
        self.source_label.setToolTip(self.source_text())
        policy = self.service.active_config()["quantity_policy"]
        self.table.horizontalHeaderItem(3).setText("库存股数 / 股\n" + ("逐笔取小值再合计" if policy == "minimum" else "可融数量列"))
        self.show_notices(status["warnings"])
        self.retry_button.setVisible(status["state"] in {"cached", "unavailable"})

    def source_text(self):
        status = self.last_status
        lines = [f"模式：{'合成演示' if status['mode'] == 'demo' else '正式'}",
                 f"库存日期：{status['date']}（北京时间） | 状态：{status['state']}",
                 f"来源目录：{status.get('source_dir', '尚未读取')}",
                 f"文件名规则：{self.service.active_config()['file_glob']}",
                 f"本次检查：{status.get('refreshed_at') or '—'}",
                 f"成功下载：{status.get('downloaded_at') or '—'}"]
        for file in status["files"]:
            lines.extend([f"\n文件：{file['name']}", f"共享源：{file['source']}", f"本地快照：{file['path']}",
                          f"大小：{file['size']:,} 字节 | {file['records']} 行 | 表头第 {file['header_row']} 行",
                          f"SHA256：{file['sha256']}"])
        lines.extend(["\n同步提示：", *status["warnings"]])
        return "\n".join(lines)

    def text_dialog(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(min(850, self.width()), min(520, self.height()))
        layout = QVBoxLayout(dialog)
        contents = QPlainTextEdit(text)
        contents.setReadOnly(True)
        layout.addWidget(contents)
        layout.addWidget(self.button("关闭", dialog.accept))
        dialog.exec()

    def show_source(self):
        self.text_dialog("文件与同步详情", self.source_text())

    def show_messages(self):
        self.text_dialog("操作提示", "\n\n".join(self.messages))

    def open_local_data(self):
        files = self.last_status.get("files", [])
        folder = Path(files[0]["path"]).parent if files else self.service.data_root
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))):
                raise OSError("系统未能打开文件夹")
            self.statusBar().showMessage(f"本地数据：{folder}")
        except OSError as exc:
            self.show_notices([f"打开本地数据失败：{exc}；路径：{folder}"])

    def clear_results(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            self.restore_code = self.items[row]["code"]
        self.response = None
        self.items, self.editors = [], {}
        self.table.setRowCount(0)
        self.detail.clear()
        for metric in self.metrics:
            metric.setText("—")
        self.update_controls()

    def refresh_done(self, status):
        self.show_status(status)
        self.result_label.setText("券单已就绪，输入标的查询" if status["state"] in {"ready", "cached"} else "请检查共享盘和当日文件，再同步重试")
        self.loaded.emit()

    def refresh(self):
        if self.busy:
            return
        self.retry_action = self.refresh
        self.clear_results()
        self.status_label.setText(f"正在下载并读取当日券单  |  {today()}")
        self.tone(self.status_label, "neutral")
        self.wind_label.setText("演示价格 · 不连接 Wind" if self.service.demo else "Wind · 等待下次查询")
        self.run_task("正在同步当日券单…", lambda progress: self.service.refresh(progress), self.refresh_done)

    def target_values(self):
        values = {}
        for code, text in self.target_texts.items():
            if text.strip():
                value = decimal_value(text)
                values[code] = str(value * 10000) if value is not None and 0 < value <= 10000000000 else "invalid"
        return values

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
            self.perform_query(" ".join(item["code"] for item in self.items), {})

    def perform_query(self, symbols, inputs):
        targets = self.target_values()
        self.retry_action = lambda: self.perform_query(symbols, inputs)
        self.clear_results()
        self.result_label.setText("正在匹配库存并获取本次价格…")
        self.wind_label.setText("合成价格 · 生成中" if self.service.demo else "Wind · 正在请求最新价")
        self.tone(self.wind_label, "neutral")
        self.run_task("正在查询…", lambda progress: self.service.query(symbols, targets, inputs, progress), self.render)

    def render(self, response):
        from PySide6.QtWidgets import QTableWidgetItem
        self.response = response
        self.show_status(response["status"])
        for code, value in response.get("targets", {}).items():
            amount = decimal_value(value)
            if amount is not None:
                self.target_texts[code] = format(amount / 10000, "f")
        self.batch_targets = {}
        self.items = []
        seen, unmatched = set(), []
        for group in response["results"]:
            if not group["matches"]:
                unmatched.append(group["input"])
                code = normalize_code(group["input"])
                if code and code not in seen:
                    quote = response["quotes"].get(code)
                    available = 0 if response["status"]["state"] in {"ready", "cached"} else None
                    self.items.append({"code": code, "name": "未匹配库存" if available is not None else "库存未就绪", "industry": response.get("industries", {}).get(code),
                        "quantity": available, "quantity_complete": available is not None, "nominal": None, "nominal_complete": False,
                        "rate_min": None, "rate_max": None, "rate_raw": [], "rows": [], "quote": quote,
                        "calculation": size_order(response.get("targets", self.target_values()).get(code), (quote or {}).get("price"), available, available is not None)})
                    seen.add(code)
            for item in group["matches"]:
                if item["code"] not in seen:
                    self.items.append(item)
                    seen.add(item["code"])
        notices = response["status"]["warnings"] + response["warnings"]
        if unmatched:
            notices.append(("当前已加载券单未匹配：" if response["status"]["state"] in {"ready", "cached"} else "库存未就绪，无法确认以下标的库存：") + "、".join(unmatched))
        self.show_notices(notices)
        self.table.setRowCount(len(self.items))
        self.editors = {}
        for row, item in enumerate(self.items):
            quote, calc = item["quote"] or {}, item["calculation"]
            retrieved = quote.get("retrieved_at", "")
            stock = number(item["quantity"], 0) + ("" if item["quantity_complete"] else "（已知）")
            stock = f"有效 {stock} / 上限 {number(calc['maximum_shares'], 0)}"
            if item.get("quantity_policy") == "minimum":
                stock += f"\n实际 {number(item.get('quantity_actual'), 0)}\n可融 {number(item.get('quantity_primary'), 0)}"
            market_value = item.get("inventory_market_value")
            nominal = number(market_value / 10000 if market_value is not None else None)
            if market_value is None:
                nominal += "\n无法估值"
            values = [f"{item['name']}\n{item['code']}", item["industry"] or "待补充",
                      number(quote.get("price"), 4) + (f"\n{retrieved[11:19]} 获取" if retrieved else "\n价格不可用"),
                      stock, nominal, rate_text(item) + ("" if item.get("rate_complete", False) else "\n费率缺失"),
                      "", number(calc["requested_shares"], 0), calc["message"]]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                cell.setTextAlignment((Qt.AlignmentFlag.AlignRight if column in (2, 3, 4, 5, 7) else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, cell)
            self.table.item(row, 3).setToolTip(f"券单原始合计：{number(item['quantity'], 4)} 股\n整百股上限：{number(calc['maximum_shares'], 0)} 股\n{quality(item)}")
            self.table.item(row, 4).setToolTip(f"库存市值 = 逐笔取较小值后的有效股数 × 本次最新价\n{number(market_value)} 元；不是目标名本。\n券单原始市值（仅参考）：{number(item['nominal'])} 元")
            self.paint_calculation(row)
            editor = TargetEdit(self.target_texts.get(item["code"], ""))
            editor.setObjectName("target")
            editor.setAlignment(Qt.AlignmentFlag.AlignRight)
            editor.setPlaceholderText("万元")
            editor.setToolTip("目标名本（万元）；Enter / Tab 下一行；Ctrl+Enter 刷新价格并计算。支持粘贴一列金额。")
            editor.focused.connect(lambda index=row: self.focus_row(index))
            editor.advance.connect(lambda step, index=row: self.move_editor(index, step))
            editor.pasteColumn.connect(lambda text, index=row: self.paste_targets(index, text))
            editor.textEdited.connect(lambda text, code=item["code"], index=row: self.target_edited(code, index, text))
            self.table.setCellWidget(row, 6, editor)
            self.editors[item["code"]] = editor
            self.table.setRowHeight(row, 62 if item.get("quantity_policy") == "minimum" else 48)
        self.update_metrics()
        wanted = next((i for i, item in enumerate(self.items) if item["code"] == self.restore_code), 0)
        if self.items:
            self.table.selectRow(wanted)
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
        self.retry_button.setVisible(valid < len(self.items) or response["status"]["state"] in {"cached", "unavailable"})
        if response["status"]["state"] in {"cached", "unavailable"}:
            self.retry_action = self.refresh
        self.update_controls()
        self.queried.emit()

    def paint_calculation(self, row):
        calc = self.items[row]["calculation"]
        cell = self.table.item(row, 8)
        text = calc["message"]
        if calc["status"] == "insufficient":
            text = f"库存不足\n需 {number(calc['requested_shares'], 0)} / 最多 {number(calc['maximum_shares'], 0)} 股"
        elif calc["status"] == "ok":
            text = f"可借 {number(calc['executable_shares'], 0)} 股\n取整名本 {number(calc['actual_nominal'])} 元"
        elif calc["status"] == "no_price":
            text = "价格不可用\n无法计算"
        elif calc["status"] == "unknown_inventory":
            text = "库存数量缺失 / 不完整\n无法确认上限"
        elif calc["status"] == "pending":
            text = "名本已修改\n待刷新价格并计算"
        cell.setText(text)
        cell.setToolTip(calc["message"])
        cell.setForeground(QColor("#166650" if calc["status"] == "ok" else "#a24032" if calc["status"] in {"insufficient", "invalid", "no_price", "unknown_inventory"} else "#677684"))

    def update_metrics(self):
        self.metrics[0].setText(str(self.response["summary"]["matched"]) if self.response else "—")
        total = self.response["summary"]["quantity"] if self.response else None
        partial = bool(self.response and not self.response["summary"]["quantity_complete"])
        self.metrics[1].setText(number(total / 10000 if total is not None else None) + ("（已知）" if partial and total is not None else ""))
        known = [value for item in self.items if (value := decimal_value(self.target_texts.get(item["code"], ""))) is not None and 0 < value <= 10000000000]
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
            self.show_notices(["请粘贴一列目标名本（万元），行数不能超过当前行至表尾；代码与名本两列请用“批量粘贴”。"])
            return
        parsed = [decimal_value(value) for value in values]
        if any(value is None or not 0 < value <= 10000000000 for value in parsed):
            self.show_notices(["整列未应用：名本须为有效正数（万元），请核对后重试。"])
            return
        for row, text in enumerate(values, start):
            code = self.items[row]["code"]
            self.editors[code].setText(text)
            self.target_edited(code, row, text)
        self.statusBar().showMessage(f"已填入 {len(values)} 行目标名本，请刷新价格并计算")

    def target_edited(self, code, row, text):
        self.target_texts[code] = text
        self.items[row]["calculation"] = {**self.items[row]["calculation"], "status": "pending", "message": "待刷新价格并计算", "requested_shares": None, "executable_shares": None, "actual_nominal": None, "unused_nominal": None, "target_nominal": None}
        self.table.item(row, 7).setText("—")
        self.paint_calculation(row)
        self.update_metrics()
        self.update_controls()
        self.show_detail()

    def toggle_detail(self):
        self.detail.setVisible(self.detail_button.isChecked())
        self.show_detail()

    def show_detail(self):
        row = self.table.currentRow()
        if not self.response or not 0 <= row < len(self.items):
            return
        item = self.items[row]
        quote, calc = item["quote"] or {}, item["calculation"]
        lines = [f"{item['name']}  {item['code']} | 行业：{item['industry'] or '待补充'}（{item.get('industry_source') or '无来源'}）",
                 f"价格：{quote.get('price', '缺失')} 元 | 来源：{quote.get('source', '无有效价格')} | 获取：{quote.get('retrieved_at', '—')}",
                 f"Wind 返回时间：{quote.get('wind_returned_at') or '未提供'}（不保证为逐笔成交时间）",
                 f"当前输入目标名本：{self.target_texts.get(item['code']) or '未填'} 万元 | 校验：{calc['message']}",
                 f"库存市值（本次最新价）：{number(item.get('inventory_market_value'))} 元；券单原始市值仅供追溯，不参与此计算。",
                 f"取整名本：{number(calc.get('actual_nominal'))} 元 | 未用名本：{number(calc.get('unused_nominal'))} 元 | 最大可借名本：{number(calc.get('maximum_nominal'))} 元",
                 f"数据完整性：{quality(item)}",
                 f"库存日期：{self.response['status']['date']} | 下载：{self.response['status'].get('downloaded_at') or '未同步'}",
                 "—— 逐笔券源（不同费率分别保留）——"]
        for source in item["rows"]:
            lines.extend([source_description(source), f"本地：{source.get('local_path', '—')}"])
        self.detail.setPlainText("\n".join(lines))

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
        default = self.service.root / "data" / "exports" / f"券源换算_{self.response['status']['mode']}_{self.current_date}.xlsx"
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
            self.refresh()

    def closeEvent(self, event):
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
