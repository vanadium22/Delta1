from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .calculation import decimal_value, size_order
from .config import ROOT, today
from .desktop_settings import SettingsDialog
from .desktop_theme import STYLE
from .inventory import normalize_code
from .service import InventoryService


def number(value, digits=2):
    value = decimal_value(value)
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:,.0f}"


def rate_text(item):
    low, high = item["rate_min"], item["rate_max"]
    rate = "" if low is None else f"{number(low, 4)}%" if low == high else f"{number(low, 4)}–{number(high, 4)}%"
    return " / ".join([x for x in [rate, *item["rate_raw"]] if x]) or "—"


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def configure_style(app):
    # Qt's offscreen Windows plugin may not enumerate system fonts.
    if sys.platform == "win32":
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(STYLE)


class Task(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation()
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
        self.items = []
        self.target_texts = {}
        self.editors = {}
        self.current_date = today()
        self.setWindowTitle("Delta1 券源工作台" + (" · 合成演示" if self.service.demo else ""))
        self.setWindowIcon(QIcon(str(ROOT / "static" / "favicon.svg")))
        self.resize(1560, 1000)
        self.setMinimumSize(1100, 740)
        self.build_ui()
        self.rollover = QTimer(self)
        self.rollover.timeout.connect(self.check_date)
        self.rollover.start(30000)
        QTimer.singleShot(0, self.refresh)

    def build_ui(self):
        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.setCentralWidget(central)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(184)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 35, 20, 25)
        side.addWidget(label("DELTA1", "brand"))
        side.addWidget(label("SECURITIES FINANCE", "brandSub"))
        side.addSpacing(48)
        nav = QPushButton("券源与名本换算")
        nav.setObjectName("nav")
        nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        side.addWidget(nav)
        self.settings_button = QPushButton("数据与环境设置")
        self.settings_button.clicked.connect(self.settings)
        side.addWidget(self.settings_button)
        side.addStretch()
        side.addWidget(label("本地券单\nWind 最新价\n100 股向下取整", "sideText"))
        side.addSpacing(22)
        side.addWidget(label("NATIVE APP  /  v2.0", "brandSub"))
        shell.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(27, 25, 27, 15)
        content.setSpacing(12)
        shell.addLayout(content, 1)
        top = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(label("INVENTORY & NOTIONAL", "eyebrow"))
        title.addWidget(label("券源清晰，名本有数。", "title"))
        title.addWidget(label("查询库存与最新价格，为每只票输入目标名义本金。", "muted"))
        top.addLayout(title)
        top.addStretch()
        self.refresh_button = QPushButton("同步当日券单")
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        content.addLayout(top)
        self.status_label = label("正在同步运行日券单…", "status")
        self.status_label.setWordWrap(True)
        content.addWidget(self.status_label)
        self.notice = label("", "notice")
        self.notice.setWordWrap(True)
        self.notice.hide()
        content.addWidget(self.notice)
        search_card = QFrame()
        search_card.setObjectName("card")
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(18, 15, 18, 15)
        search_layout.addWidget(label("01   查询标的", "section"))
        search = QHBoxLayout()
        self.symbols = QLineEdit()
        self.symbols.setPlaceholderText("证券代码或名称，例如：600519  300750  平安银行")
        self.symbols.setMinimumHeight(42)
        self.symbols.returnPressed.connect(self.query)
        search.addWidget(self.symbols, 1)
        self.query_button = QPushButton("查询库存与最新价  →")
        self.query_button.setObjectName("primary")
        self.query_button.clicked.connect(self.query)
        search.addWidget(self.query_button)
        search_layout.addLayout(search)
        search_layout.addWidget(label("多个标的用空格、逗号分隔；在下表绿色输入框中填写各自目标名本，单位为万元。", "muted"))
        content.addWidget(search_card)
        metrics = QHBoxLayout()
        self.metrics = []
        for heading in ("匹配标的 / 只", "库存数量 / 万股", "目标名本 / 万元", "库存不足 / 只"):
            frame = QFrame()
            frame.setObjectName("card")
            box = QVBoxLayout(frame)
            box.setContentsMargins(18, 12, 18, 12)
            box.addWidget(label(heading, "metricTitle"))
            value = label("—", "metricValue")
            box.addWidget(value)
            self.metrics.append(value)
            metrics.addWidget(frame)
        content.addLayout(metrics)
        splitter = QSplitter(Qt.Orientation.Vertical)
        table_card = QFrame()
        table_card.setObjectName("card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        actions.setContentsMargins(18, 12, 18, 6)
        actions.addWidget(label("02   券源与名义本金换算", "section"))
        actions.addStretch()
        self.export_button = QPushButton("导出结果")
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        actions.addWidget(self.export_button)
        self.calculate_button = QPushButton("刷新价格并计算  →")
        self.calculate_button.setObjectName("primary")
        self.calculate_button.clicked.connect(self.calculate)
        self.calculate_button.setEnabled(False)
        actions.addWidget(self.calculate_button)
        table_layout.addLayout(actions)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["证券 / 代码", "行业", "最新价 / 元", "最大可借 / 股", "库存名本 / 万元", "出借费率", "目标名本 / 万元", "换算需求 / 股", "校验结果"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for column, width in enumerate([139, 94, 99, 116, 124, 92, 143, 118, 290]):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(85)
        self.table.itemSelectionChanged.connect(self.show_detail)
        table_layout.addWidget(self.table, 1)
        self.quote_note = label("价格以 Wind 本次返回为准；盘后可能为最近成交价。股数仅按当前券单库存校验。", "muted")
        self.quote_note.setContentsMargins(18, 9, 18, 12)
        self.quote_note.setWordWrap(True)
        table_layout.addWidget(self.quote_note)
        splitter.addWidget(table_card)
        detail_card = QFrame()
        detail_card.setObjectName("card")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(16, 12, 16, 10)
        detail_layout.addWidget(label("券源明细与计算依据", "section"))
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("选择一只标的，查看逐笔费率、库存来源、价格获取时间及取整余量。")
        detail_layout.addWidget(self.detail)
        splitter.addWidget(detail_card)
        splitter.setSizes([460, 130])
        content.addWidget(splitter, 1)
        self.statusBar().showMessage(f"运行环境：{sys.executable}")
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.calculate)

    @property
    def busy(self):
        return self.worker is not None

    def run_task(self, text, operation, success):
        if self.busy:
            return
        self.statusBar().showMessage(text)
        for control in (self.refresh_button, self.query_button, self.calculate_button, self.settings_button, self.export_button, self.symbols):
            control.setEnabled(False)
        self.table.setEnabled(False)
        worker = Task(operation, self)
        self.worker = worker
        def complete():
            self.worker = None
            self.table.setEnabled(True)
            for control in (self.refresh_button, self.query_button, self.settings_button, self.symbols):
                control.setEnabled(True)
            if worker.error:
                self.show_notices([worker.error])
                self.detail.setPlainText(worker.error)
            else:
                success(worker.result)
            self.calculate_button.setEnabled(bool(self.items))
            self.export_button.setEnabled(bool(self.response and self.items))
            self.statusBar().showMessage(f"运行环境：{sys.executable}")
            worker.deleteLater()
            if self.closing:
                self.close()
        worker.finished.connect(complete)
        worker.start()

    def show_notices(self, messages=()):
        entries = (["合成演示：券源、价格、费率均为示例，不代表实际行情或库存。"] if self.service.demo else []) + list(messages)
        self.notice.setText("\n".join(dict.fromkeys(entries))[:2500])
        self.notice.setVisible(bool(entries))

    def show_status(self, status):
        self.current_date = status["date"]
        names = {"ready": "当日券单已就绪", "cached": "正在使用当日缓存库存", "unavailable": "当日券单未就绪", "loading": "正在加载"}
        self.status_label.setText(f"●  {names[status['state']]}     |     {status['date']}     |     {status['security_count']} 只标的 · {status['record_count']} 笔券源")
        self.status_label.setToolTip(status.get("source_dir", ""))
        self.show_notices(status["warnings"])

    def clear_results(self):
        self.response = None
        self.items = []
        self.editors = {}
        self.table.setRowCount(0)
        self.detail.clear()
        for metric in self.metrics:
            metric.setText("—")
        self.export_button.setEnabled(False)
        self.calculate_button.setEnabled(False)

    def refresh(self):
        if self.busy:
            return
        self.clear_results()
        def done(status):
            self.show_status(status)
            lines = [f"来源目录：{status.get('source_dir', '未配置')}", f"库存下载时间：{status.get('downloaded_at') or '尚未成功同步'}"]
            lines += [f"{file['name']}\n本地缓存：{file['path']}\n已读取 {file['records']} 行，表头位于第 {file['header_row']} 行" for file in status["files"]]
            self.detail.setPlainText("\n\n".join(lines))
            self.loaded.emit()
        self.run_task("正在下载并读取运行日券单…", self.service.refresh, done)

    def target_values(self):
        values = {}
        for code, text in self.target_texts.items():
            if text.strip():
                value = decimal_value(text)
                values[code] = str(value * 10000) if value is not None else "invalid"
        return values

    def query(self):
        if self.busy:
            return
        symbols = self.symbols.text().strip()
        if not symbols:
            self.symbols.setFocus()
            self.show_notices(["请先输入证券代码或名称"])
            return
        targets = self.target_values()
        self.clear_results()
        self.run_task("正在匹配库存并获取 Wind 最新价…", lambda: self.service.query(symbols, targets), self.render)

    def calculate(self):
        if self.busy or not self.items:
            return
        codes = " ".join(item["code"] for item in self.items)
        targets = self.target_values()
        self.clear_results()
        self.run_task("正在重新获取 Wind 最新价并计算 100 股整数倍…", lambda: self.service.query(codes, targets), self.render)

    def render(self, response):
        self.response = response
        self.show_status(response["status"])
        self.items = []
        seen, unmatched = set(), []
        for group in response["results"]:
            if not group["matches"]:
                unmatched.append(group["input"])
                code = normalize_code(group["input"])
                if code and code not in seen:
                    quote = response["quotes"].get(code)
                    available = 0 if response["status"]["state"] in {"ready", "cached"} else None
                    self.items.append({"code": code, "name": "未匹配库存", "industry": response.get("industries", {}).get(code),
                        "quantity": available, "quantity_complete": available is not None, "nominal": None,
                        "rate_min": None, "rate_max": None, "rate_raw": [], "rows": [], "quote": quote,
                        "calculation": size_order(self.target_values().get(code), (quote or {}).get("price"), available, available is not None)})
                    seen.add(code)
            for item in group["matches"]:
                if item["code"] not in seen:
                    self.items.append(item)
                    seen.add(item["code"])
        notices = response["status"]["warnings"] + response["warnings"]
        if unmatched:
            notices.append("当日库存未匹配：" + "、".join(unmatched))
        self.show_notices(notices)
        self.table.setRowCount(len(self.items))
        self.editors = {}
        for row, item in enumerate(self.items):
            quote, calc = item["quote"] or {}, item["calculation"]
            retrieved = quote.get("retrieved_at", "")
            price = number(quote.get("price"), 4)
            values = [f"{item['name']}\n{item['code']}", item["industry"] or "待补充", price + (f"\n{retrieved[11:19]} 获取" if retrieved else "\n暂不可用"), number(calc["maximum_shares"], 0), number(item["nominal"] / 10000 if item["nominal"] is not None else None), rate_text(item), "", number(calc["requested_shares"], 0), calc["message"]]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                if column in (2, 3, 4, 7):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 8:
                    cell.setForeground(QColor("#24715e" if calc["status"] == "ok" else "#ad673f" if calc["status"] != "empty" else "#899984"))
                self.table.setItem(row, column, cell)
            self.table.item(row, 3).setToolTip(f"券单原始合计：{number(item['quantity'], 4)} 股\n最大可借数量按 100 股向下取整；库存不完整时不确认上限。")
            editor = QLineEdit(self.target_texts.get(item["code"], ""))
            editor.setObjectName("target")
            editor.setFixedHeight(36)
            editor.setPlaceholderText("输入万元")
            editor.setClearButtonEnabled(True)
            editor.setToolTip("目标名义本金，单位万元。按当前 Wind 最新价、100 股向下取整。")
            editor.textEdited.connect(lambda text, code=item["code"], index=row: self.target_edited(code, index, text))
            editor.returnPressed.connect(self.calculate)
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(7, 8, 7, 8)
            holder_layout.addWidget(editor)
            self.table.setCellWidget(row, 6, holder)
            self.editors[item["code"]] = editor
            self.table.setRowHeight(row, 60)
        self.update_metrics()
        if self.items:
            self.table.selectRow(0)
        self.queried.emit()

    def update_metrics(self):
        self.metrics[0].setText(str(self.response["summary"]["matched"]) if self.response else "—")
        total = self.response["summary"]["quantity"] if self.response else None
        self.metrics[1].setText(number(total / 10000 if total is not None else None))
        amounts = [decimal_value(self.target_texts.get(item["code"], "")) for item in self.items]
        known = [amount for amount in amounts if amount is not None and amount > 0]
        self.metrics[2].setText(number(sum(known)) if known else "—")
        self.metrics[3].setText(str(sum(item["calculation"]["status"] == "insufficient" for item in self.items)))

    def target_edited(self, code, row, text):
        self.target_texts[code] = text
        self.items[row]["calculation"] = {**self.items[row]["calculation"], "status": "pending", "message": "名本已修改，请刷新价格并计算", "requested_shares": None, "executable_shares": None, "actual_nominal": None, "unused_nominal": None, "target_nominal": None}
        self.table.item(row, 7).setText("—")
        self.table.item(row, 8).setText("待刷新价格并计算")
        self.export_button.setEnabled(False)
        self.update_metrics()
        self.show_detail()

    def show_detail(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.items):
            return
        item = self.items[row]
        quote, calc = item["quote"] or {}, item["calculation"]
        lines = [f"{item['name']}  {item['code']}  |  行业：{item['industry'] or '待补充'}",
                 f"价格：{quote.get('price', '缺失')} 元  |  来源：{quote.get('source', '无有效价格')}  |  本机获取时间：{quote.get('retrieved_at', '—')}",
                 f"Wind 返回时间：{quote.get('wind_returned_at') or '未提供'}（不是逐笔成交时间保证）",
                 f"校验：{calc['message']}",
                 f"取整后名本：{number(calc.get('actual_nominal'))} 元；未用名本：{number(calc.get('unused_nominal'))} 元；最大可借对应名本：{number(calc.get('maximum_nominal'))} 元",
                 f"库存日期：{self.response['status']['date']}  |  下载时间：{self.response['status'].get('downloaded_at') or '未同步'}",
                 "—— 原始券源 ——"]
        for source in item["rows"]:
            rate = f"{number(source['rate'], 4)}%" if source["rate"] is not None else source["rate_raw"] or "缺失"
            lines.append(f"{source['file']} : Excel 第 {source['row']} 行 | {number(source['quantity'], 0)} 股 | 名本 {number(source['nominal'])} 元（{source['nominal_source']}） | 费率 {rate} | 期限 {source['term'] or '未提供'}")
        self.detail.setPlainText("\n".join(lines))

    def settings(self):
        if self.busy:
            return
        dialog = SettingsDialog(self.service.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.clear_results()
            self.run_task("正在保存设置并同步库存…", lambda: self.service.update_config(dialog.config), self.show_status)

    def export(self):
        if not self.response or any(item["calculation"]["status"] == "pending" for item in self.items):
            return
        default = ROOT / "data" / f"券源换算_{self.response['status']['mode']}_{self.current_date}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "保存券源与换算结果", str(default), "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            self.export_to(Path(path))
            self.statusBar().showMessage(f"已保存：{path}")
        except OSError as exc:
            self.show_notices([f"导出失败：{exc}"])

    def export_to(self, path):
        headers = ["数据日期", "数据模式", "库存状态", "证券代码", "名称", "行业", "最新价（元）", "价格来源", "价格获取时间", "目标名本（元）", "换算需求（股）", "校验通过股数", "最大可借（股）", "取整名本（元）", "未用名本（元）", "校验结果", "券单原始数量（股）", "库存名本（元）", "出借费率"]
        def safe(value):
            text = "" if value is None else str(value)
            return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            for item in self.items:
                calc, quote = item["calculation"], item["quote"] or {}
                row = [self.current_date, self.response["status"]["mode"], self.response["status"]["state"], item["code"], item["name"], item["industry"], quote.get("price"), quote.get("source"), quote.get("retrieved_at"), calc.get("target_nominal"), calc.get("requested_shares"), calc.get("executable_shares"), calc.get("maximum_shares"), calc.get("actual_nominal"), calc.get("unused_nominal"), calc["message"], item["quantity"], item["nominal"], rate_text(item)]
                writer.writerow([safe(value) for value in row])

    def check_date(self):
        if not self.busy and today() != self.current_date:
            self.refresh()

    def closeEvent(self, event):
        if self.busy:
            self.closing = True
            self.statusBar().showMessage("正在等待当前读取完成后关闭…")
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
        def prepare():
            window.symbols.setText("600519 300750 000001 000858")
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
