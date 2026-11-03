"""Standalone Qt workbench; no collector, remote source, or live trading session."""
# ruff: noqa: E402 -- Qt imports follow the existing local dependency bootstrap.
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import threading
import uuid

from ..native.bootstrap import configure_qt
configure_qt()

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter,
                               QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)
import pandas as pd
import pyqtgraph as pg

from ..native.branding import app_icon, configure_windows_identity
from ..native.theme import ACCENT, BACKGROUND, BORDER, DOWN, MUTED, PANEL, STYLE, TEXT, UP
from . import BacktestCancelled, BacktestConfig, DataConfig, load_result
from .__main__ import load_job
from .configuration import data_declaration, relative_data_path
from .desktop_service import data_manifest_text, execute_job, inspect_job
from .desktop_widgets import InlinePicker, ResultCharts, dataframe_view
from .io import write_json


REPOSITORY = Path(__file__).resolve().parents[2]
MODES = [("全市场共用资金", "portfolio"), ("同品种共用资金", "product"), ("单标的独立账户", "symbol"),
         ("每合约与对冲腿独立账户", "contract_pair")]


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, *, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if primary:
        widget.setObjectName("primary")
        widget.setStyleSheet(f"QPushButton {{background-color:{ACCENT};color:white;border:1px solid {ACCENT};}}"
                            "QPushButton:disabled {background-color:#b6cbdc;color:#eff4f8;border-color:#b6cbdc;}")
    return widget


def combo(choices):
    widget = QComboBox()
    for title, value in choices:
        widget.addItem(title, value)
    return widget


def spin(value, *, maximum=100, decimals=4, minimum=0):
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setGroupSeparatorShown(True)
    widget.setKeyboardTracking(False)
    return widget


class TaskSignals(QObject):
    progress = Signal(object)
    success = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = TaskSignals()
        self.cancel_event = threading.Event()

    def run(self):
        try:
            self.signals.success.emit(self.function(self.cancel_event, self.signals.progress.emit))
        except BacktestCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.signals.finished.emit()


class BacktestWindow(QMainWindow):
    completed = Signal(object)
    inspected = Signal(object)

    def __init__(self, *, config_path=None, result_path=None):
        super().__init__()
        self.result = None
        self.inspection = None
        self.task = None
        self.closing = False
        self._base_data = {}
        self._base_config = {}
        self._band = None
        self._config_path = Path(config_path) if config_path else REPOSITORY / "dashboard/localsetting/backtest/job.local.json"
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle("Delta1 · 大表回测")
        self.setWindowIcon(app_icon())
        self.resize(1720, 1040)
        self.setMinimumSize(1120, 760)
        self._build()
        if self._config_path.is_file():
            self.load_config(self._config_path)
        if result_path:
            QTimer.singleShot(0, lambda: self.open_result(result_path))

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        body = QVBoxLayout(root)
        body.setContentsMargins(22, 16, 22, 16)
        body.setSpacing(14)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.addWidget(label("Δ  DELTA1  /  大表回测", "title"))
        heading.addWidget(label("股指期货与现货 · 从目标比例到实际开平仓", "muted"))
        header.addLayout(heading, 1)
        self.execution_badge = label("次时点成交  ·  日结权益", "badge")
        header.addWidget(self.execution_badge)
        header.addWidget(button("打开配置", lambda: self.show_location("load_config")))
        header.addWidget(button("保存配置", lambda: self.show_location("save_config")))
        header.addWidget(button("打开历史结果", lambda: self.show_location("open_result")))
        body.addLayout(header)
        self.location_bar = QWidget()
        location = QHBoxLayout(self.location_bar)
        location.setContentsMargins(0, 0, 0, 0)
        self.location_title = label("配置文件")
        self.location_path = QLineEdit()
        self.location_apply = button("读取", self.apply_location)
        location.addWidget(self.location_title)
        location.addWidget(self.location_path, 1)
        location.addWidget(button("选择", self.browse_location))
        location.addWidget(self.location_apply)
        location.addWidget(button("收起", self.location_bar.hide))
        body.addWidget(self.location_bar)
        self.location_bar.hide()

        self.split = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(self.split, 1)
        self.left = QFrame()
        self.left.setObjectName("panel")
        self.left.setMinimumWidth(380)
        left = QVBoxLayout(self.left)
        left.setContentsMargins(16, 16, 16, 16)
        caption = QHBoxLayout()
        caption.addWidget(label("回测设置", "section"))
        caption.addStretch()
        caption.addWidget(label("仅本地数据", "muted"))
        left.addLayout(caption)
        self.forms = QTabWidget()
        left.addWidget(self.forms, 1)
        self.fields = {}
        self.picker = InlinePicker(REPOSITORY)
        self.picker.setMaximumHeight(300)
        self._parameter_page()
        self._data_page()
        from .desktop_strategy import build_strategy_page
        build_strategy_page(self)
        self.forms.tabBar().moveTab(1, 0)
        self.forms.tabBar().moveTab(2, 1)
        self.forms.tabBar().moveTab(3, 2)
        left.addWidget(self.picker)
        self.risk_note = label("", "risk")
        self.risk_note.setWordWrap(True)
        left.addWidget(self.risk_note)
        actions = QHBoxLayout()
        self.inspect_button = button("检查数据", self.inspect)
        self.run_button = button("开始回测", self.run_backtest, primary=True)
        self.cancel_button = button("取消", self.cancel)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.inspect_button)
        actions.addWidget(self.run_button, 1)
        actions.addWidget(self.cancel_button)
        left.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        left.addWidget(self.progress)
        self.status = label("设置目标指令表与数据位置后，检查并运行回测。", "muted")
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        self.split.addWidget(self.left)

        right = QWidget()
        view = QVBoxLayout(right)
        view.setContentsMargins(10, 0, 0, 0)
        view.setSpacing(12)
        results = QHBoxLayout()
        results.addWidget(label("回测结果", "section"))
        self.result_note = label("尚未运行", "muted")
        results.addWidget(self.result_note, 1)
        results.addWidget(label("查看账户", "muted"))
        self.account = QComboBox()
        self.account.setMinimumWidth(180)
        self.account.setEnabled(False)
        self.account.currentIndexChanged.connect(self.select_account)
        results.addWidget(self.account)
        view.addLayout(results)
        metrics = QGridLayout()
        self.metrics = {}
        for i, (key, title) in enumerate((("return", "总收益率"), ("drawdown", "最大回撤"),
                                           ("fees", "累计手续费"), ("orders", "开平仓记录"))):
            card = QFrame()
            card.setObjectName("metricCard")
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 12, 16, 12)
            box.addWidget(label(title, "muted"))
            value = label("—", "metric")
            box.addWidget(value)
            self.metrics[key] = value
            metrics.addWidget(card, 0, i)
        view.addLayout(metrics)
        self.source_note = label("价格、保证金率与交易指令都以本轮实际输入为准。", "muted")
        self.source_note.setWordWrap(True)
        view.addWidget(self.source_note)

        self.result_split = QSplitter(Qt.Orientation.Vertical)
        self.chart_stack = QStackedWidget()
        empty = QFrame()
        empty.setObjectName("panel")
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_layout.addWidget(label("运行后查看净值与保证金", "emptyTitle"), alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(label("设置目标表  →  核对数据与保证金  →  查看净值和实际成交", "muted"),
                               alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.chart_stack.addWidget(empty)
        self.charts = ResultCharts()
        self.chart_stack.addWidget(self.charts)
        self.chart_stack.setMinimumHeight(260)
        self.result_split.addWidget(self.chart_stack)
        detail = QWidget()
        tables_layout = QVBoxLayout(detail)
        tables_layout.setContentsMargins(0, 6, 0, 0)
        tools = QHBoxLayout()
        self.table_count = label("暂无明细", "muted")
        tools.addWidget(self.table_count, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索合约、开平动作或时间")
        self.search.setMaximumWidth(340)
        tools.addWidget(self.search)
        tools.addWidget(button("复制成交表路径", self.copy_orders_path))
        tables_layout.addLayout(tools)
        self.tables = QTabWidget()
        self.models = {}
        for key, title in (("actual_orders", "开平仓指令"), ("positions", "实际持仓"), ("equity", "账户明细"),
                           ("schedule", "信号执行"), ("instructions", "目标指令"), ("coverage", "数据检查")):
            table, model = dataframe_view()
            table.setObjectName(key)
            self.models[key] = model
            self.tables.addTab(table, title)
        self.tables.currentChanged.connect(self.refresh_table)
        tables_layout.addWidget(self.tables, 1)
        self.result_split.addWidget(detail)
        self.result_split.setSizes([400, 380])
        view.addWidget(self.result_split, 1)
        footer = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setReadOnly(True)
        self.output_path.setPlaceholderText("运行后在这里显示实际结果保存位置")
        footer.addWidget(self.output_path, 1)
        footer.addWidget(button("打开结果目录", self.open_output_folder))
        view.addLayout(footer)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.filter_table)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.minimum.valueChanged.connect(self.update_risk_note)
        self.basis.currentIndexChanged.connect(self.update_risk_note)
        self.update_risk_note()

    def page(self, title):
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(1, 12, 5, 8)
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.forms.addTab(scroll, title)
        return form

    def path_row(self, form, title, key, *, directory=False, placeholder=""):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setToolTip(title)
        edit.textChanged.connect(edit.setToolTip)
        layout.addWidget(edit, 1)
        layout.addWidget(button("选择", lambda: self.picker.open_for(edit, directory=directory)))
        form.addRow(title, row)
        self.fields[key] = edit
        return edit

    def _parameter_page(self):
        form = self.page("回测执行参数")
        self.path_row(form, "目标指令表", "instructions_path", placeholder="时间 × 合约的目标比例表")
        self.mode = combo(MODES)
        form.addRow("账户分组", self.mode)
        self.weight_mode = combo([("目标资金占用比例 · 兼容旧输入", "capital"),
                                  ("合约等价手数权重 · 每品种和为零", "neutral_units")])
        form.addRow("权重与对冲模式", self.weight_mode)
        self.precision = combo([("日频 · 收盘检查爆仓", "1d"), ("自动 · 对齐输入，逐时点风控", "auto")])
        form.addRow("回测精度 · 权益统一每日收盘输出", self.precision)
        self.workers = QSpinBox()
        self.workers.setRange(0, 64)
        self.workers.setSpecialValueText("自动 · 最多 4 进程")
        form.addRow("计算进程 · 1 为串行", self.workers)
        self.d0 = QSpinBox()
        self.d0.setRange(0, 3650)
        self.d0.setSuffix(" 天")
        form.addRow("临期强平 · T≤d0 当天收盘", self.d0)
        self.expiry_enabled = QCheckBox("启用临期强平 · 默认到期日（d0=0）")
        self.expiry_enabled.setChecked(True)
        form.addRow(self.expiry_enabled)
        self.on_change = QCheckBox("仅目标变化时调仓 · 中途保持实际手数")
        form.addRow(self.on_change)
        self.preserve_pair_lots = QCheckBox("同品种其他pair开平时，保持未变pair的手数")
        form.addRow(self.preserve_pair_lots)
        dates = QWidget()
        row = QHBoxLayout(dates)
        row.setContentsMargins(0, 0, 0, 0)
        self.start, self.end = QLineEdit(), QLineEdit()
        self.start.setPlaceholderText("开始：自动")
        self.end.setPlaceholderText("结束：自动")
        row.addWidget(self.start)
        row.addWidget(label("至", "muted"))
        row.addWidget(self.end)
        form.addRow("回测区间 · YYYY-MM-DD", dates)
        self.capital = spin(10_000_000, maximum=1e14, minimum=1, decimals=0)
        form.addRow("初始资金 · 元 / 每账户", self.capital)
        row_widget = QWidget()
        row = QGridLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        self.fee, self.usage = spin(3, maximum=10000), spin(99, maximum=100, minimum=0.0001)
        row.addWidget(label("每边手续费 · 万分之", "muted"), 0, 0)
        row.addWidget(label("最大占用 · %", "muted"), 0, 1)
        row.addWidget(self.fee, 1, 0)
        row.addWidget(self.usage, 1, 1)
        form.addRow("资金与成本", row_widget)
        self.basis = combo([("账户总权益 · 默认", "equity"), ("保证金后余额 · 自选", "available_equity")])
        form.addRow("爆仓比较项", self.basis)
        self.minimum = spin(1, maximum=1e8)
        form.addRow("爆仓阈值 · 保证金的万分之", self.minimum)
        self.liquidate = QCheckBox("回测结束时平仓并收取手续费")
        form.addRow(self.liquidate)
        self.path_row(form, "结果根目录 · 每次新建运行子目录", "output_root", directory=True)
        self.fields["output_root"].setText(str(REPOSITORY / "outputs/backtest"))

    def _data_page(self):
        form = self.page("数据配置")
        self.source = combo([("已有看板数据 / 共享 data", "history"), ("自己的 close 大表", "wide")])
        form.addRow("行情来源", self.source)
        self.path_row(form, "数据根目录 · 相对文件位置以此为基准", "data_root", directory=True)
        self.path_row(form, "显式旧看板配置适配 · 不自动发现", "dashboard_config_path")
        self.path_row(form, "只读导入清单 · SHA核验", "source_manifest_path")
        self.allow_z_import = QCheckBox("使用已授权的Z只读导入快照")
        form.addRow(self.allow_z_import)
        self.data_controls = {}
        for key, title, default in (("dataset_id", "数据集标识", "unversioned_local"),
                                    ("data_version", "数据版本", "unversioned"), ("source_id", "来源标识", "explicit_local"),
                                    ("daily_label_time", "日线日期标签时刻 · 上海时间", "15:00")):
            self.data_controls[key] = QLineEdit(default)
            form.addRow(title, self.data_controls[key])
        self.data_manifest_view = QPlainTextEdit()
        self.data_manifest_view.setReadOnly(True)
        self.data_manifest_view.setMaximumHeight(180)
        self.data_manifest_view.setPlaceholderText("检查或运行后显示最终绝对路径、版本和覆盖区间")
        form.addRow("本轮实际数据清单", self.data_manifest_view)
        self.path_row(form, "原始 close 大表", "close_path")
        self.path_row(form, "分钟 close 大表 · 可选", "minute_close_path")
        self.path_row(form, "日线 close 大表 · 分钟缺失时回退", "daily_close_path")
        self.path_row(form, "剩余自然日大表 · 可选，优先校验合约参考", "days_to_expiry_path")
        self.margin_source = combo([("历史保证金率表", "history"), ("固定比例假设", "fixed")])
        self.margin_source.setCurrentIndex(1)
        form.addRow("保证金来源", self.margin_source)
        self.path_row(form, "历史保证金率大表 · 小数比例", "margin_rate_path")
        fixed = QWidget()
        grid = QGridLayout(fixed)
        grid.setContentsMargins(0, 0, 0, 0)
        self.rates = {}
        for i, root in enumerate(("IF", "IH", "IC", "IM")):
            item = spin(100, maximum=100)
            item.setSpecialValueText("未设置")
            item.setSuffix(" %")
            grid.addWidget(label(root), 2 * (i // 2), i % 2)
            grid.addWidget(item, 2 * (i // 2) + 1, i % 2)
            self.rates[root] = item
        form.addRow("固定比例 · 仅选择假设时使用", fixed)
        self.path_row(form, "分红调整价大表 · 可选", "adjusted_close_path")
        self.path_row(form, "分红点数大表 · 与调整价二选一", "dividend_points_path")
        self.dividend_mode = combo([("需要明确分红输入 · 缺失保留缺失", "required"), ("研究显式忽略分红 · D=0", "ignore")])
        form.addRow("因子分红假设", self.dividend_mode)
        self.path_row(form, "逐日分红版本 JSON", "dividend_records_path")
        self.path_row(form, "逐日分红缓存 · 旧适配器", "dividend_store_root", directory=True)
        self.path_row(form, "交易日历 CSV/JSON", "calendar_path")
        self.path_row(form, "合约挂牌 / 到期参考 · 临期强平需要", "reference_path")
        self.path_row(form, "乘数大表 · 默认使用品种标准", "multiplier_path")
        self.dividend_policy = combo([("不使用单日快照", "none"), ("快照日后的分红参考", "asof_snapshot"),
                                      ("固定分红情景", "fixed_scenario")])
        form.addRow("单日分红快照", self.dividend_policy)
        self.path_row(form, "分红快照目录 · 可选", "dividend_root", directory=True)
        self.history_roots = QPlainTextEdit()
        self.history_roots.setPlaceholderText("需要直接指定注册行情数据集时，每行一个目录")
        self.history_roots.setMaximumHeight(85)
        form.addRow("直接指定行情集 · 可选", self.history_roots)
        self.history_versions = QPlainTextEdit("{}")
        self.history_versions.setMaximumHeight(85)
        form.addRow("注册集版本 · JSON {目录:版本}，空对象冻结当前", self.history_versions)
        self.revised = QCheckBox("允许使用历史发布时间未知的修订历史")
        self.revised.setChecked(True)
        form.addRow(self.revised)
        self.trusted = QCheckBox("允许读取本机可信的 pkl 文件")
        form.addRow(self.trusted)
        self.nan_policy = combo([("空值报错", "error"), ("空值按零目标平仓", "zero")])
        form.addRow("指令中的空值", self.nan_policy)
        self.epoch = combo([("日期 / 时间字符串", None), ("Unix 秒", "s"), ("Unix 毫秒", "ms"),
                            ("Unix 微秒", "us"), ("Unix 纳秒", "ns")])
        form.addRow("指令时间格式", self.epoch)
        self.date_at = QLineEdit("15:00")
        form.addRow("日期标签对应时刻 · 上海时间", self.date_at)

    def update_risk_note(self):
        basis = "总权益" if self.basis.currentData() == "equity" else "保证金后余额"
        self.risk_note.setText(f"爆仓条件：{basis} < 持仓所需保证金 × {self.minimum.value() / 10000:g}")

    def job(self):
        data = {**self._base_data}
        for key in ("data_root", "dashboard_config_path", "close_path", "minute_close_path", "daily_close_path", "days_to_expiry_path", "margin_rate_path", "reference_path",
                    "multiplier_path", "adjusted_close_path", "dividend_points_path", "dividend_root", "dividend_records_path",
                    "dividend_store_root", "calendar_path", "source_manifest_path"):
            data[key] = self.fields[key].text().strip() or None
        if self.source.currentData() != "wide":
            data["close_path"] = None
            data["minute_close_path"] = None
            data["daily_close_path"] = None
        elif not any(data[k] for k in ("close_path", "minute_close_path", "daily_close_path")):
            raise ValueError("请选择原始 close、分钟或日线大表")
        data["history_roots"] = tuple(s.strip() for s in self.history_roots.toPlainText().splitlines() if s.strip())
        data["history_versions"] = json.loads(self.history_versions.toPlainText() or "{}")
        data.update({key: widget.text().strip() for key, widget in self.data_controls.items()})
        data["dividend_mode"] = self.dividend_mode.currentData()
        data["allow_readonly_z_import"] = self.allow_z_import.isChecked()
        if self.margin_source.currentData() == "fixed":
            rates = {k: v for k, v in data.get("margin_rates", {}).items() if k not in self.rates}
            rates.update({k: s.value() / 100 for k, s in self.rates.items() if s.value() > 0})
            data.update(margin_rates=rates, margin_rate_path=None)
        else:
            data["margin_rates"] = {}
        data.update(dividend_policy=self.dividend_policy.currentData(),
                    allow_unverified_availability=self.revised.isChecked(), trusted_pickle=self.trusted.isChecked())
        config = {**self._base_config, "initial_capital": self.capital.value(), "mode": self.mode.currentData(),
                  "weight_mode": self.weight_mode.currentData(),
                  "precision": self.precision.currentData(), "workers": self.workers.value(),
                  "d0": self.d0.value() if self.expiry_enabled.isChecked() else None,
                  "rebalance_on_change_only": self.on_change.isChecked(),
                  "preserve_pair_lots": self.preserve_pair_lots.isChecked(),
                  "start": self.start.text().strip() or None, "end": self.end.text().strip() or None,
                  "commission_rate": self.fee.value() / 10000, "max_capital_usage": self.usage.value() / 100,
                  "minimum_margin_ratio": self.minimum.value() / 10000, "margin_call_basis": self.basis.currentData(),
                  "liquidate_at_end": self.liquidate.isChecked(), "nan_policy": self.nan_policy.currentData(),
                  "timestamp_unit": self.epoch.currentData(), "date_at": self.date_at.text().strip()}
        config, data = BacktestConfig(**config), DataConfig(**data)
        output_root = self.fields["output_root"].text().strip()
        if not output_root:
            raise ValueError("请设置结果根目录")
        identifier = pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        from .desktop_strategy import strategy_settings
        return dict(instructions_path=self.fields["instructions_path"].text().strip() or None,
                    data=data_declaration(data), backtest=asdict(config),
                    output_dir=str(Path(output_root).expanduser().resolve() / ("run_" + identifier)),
                    ui=dict(output_root=str(Path(output_root).expanduser().resolve())), **strategy_settings(self))

    def load_config(self, path):
        try:
            job = load_job(path)
            options = dict(job.get("backtest", {}))
            if "precision" not in options and "precision" in job.get("factors", {}):
                options["precision"] = job["factors"]["precision"]
            if "workers" not in options and "workers" in job.get("factors", {}):
                options["workers"] = job["factors"]["workers"]
            data, config = DataConfig(**job.get("data", {})), BacktestConfig(**options)
            self._base_data, self._base_config = asdict(data), asdict(config)
            for key, field in self.fields.items():
                if key not in {"instructions_path", "output_root"}:
                    value = getattr(data, key)
                    field.setText(str((relative_data_path(value, data.data_root) if key != "data_root" else value) or ""))
            self.fields["instructions_path"].setText(str(job.get("instructions_path") or ""))
            ui_root = job.get("ui", {}).get("output_root")
            output = ui_root or (str(Path(job["output_dir"]).parent) if job.get("output_dir") else str(REPOSITORY / "outputs/backtest"))
            self.fields["output_root"].setText(str((Path(path).resolve().parent / Path(output).expanduser()).resolve()))
            for widget, value in ((self.mode, config.mode), (self.precision, config.precision),
                                  (self.weight_mode, config.weight_mode), (self.dividend_mode, data.dividend_mode),
                                  (self.basis, config.margin_call_basis), (self.dividend_policy, data.dividend_policy),
                                  (self.epoch, config.timestamp_unit), (self.nan_policy, config.nan_policy),
                                  (self.source, "wide" if data.close_path or data.minute_close_path or data.daily_close_path else "history"),
                                  (self.margin_source, "fixed" if data.margin_rates and not data.margin_rate_path else "history")):
                widget.setCurrentIndex(widget.findData(value))
            self.capital.setValue(config.initial_capital)
            self.workers.setValue(config.workers)
            self.expiry_enabled.setChecked(config.d0 is not None)
            self.d0.setValue(config.d0 or 0)
            self.on_change.setChecked(config.rebalance_on_change_only)
            self.preserve_pair_lots.setChecked(config.preserve_pair_lots)
            self.fee.setValue(config.commission_rate * 10000)
            self.usage.setValue(config.max_capital_usage * 100)
            self.minimum.setValue(config.minimum_margin_ratio * 10000)
            self.liquidate.setChecked(config.liquidate_at_end)
            self.revised.setChecked(data.allow_unverified_availability)
            self.trusted.setChecked(data.trusted_pickle)
            self.allow_z_import.setChecked(data.allow_readonly_z_import)
            self.start.setText(str(config.start or ""))
            self.end.setText(str(config.end or ""))
            self.date_at.setText(config.date_at)
            declarations = data_declaration(data)
            self.history_roots.setPlainText("\n".join(declarations["history_roots"]))
            self.history_versions.setPlainText(json.dumps(declarations["history_versions"], ensure_ascii=False, indent=2))
            for key, widget in self.data_controls.items():
                widget.setText(str(getattr(data, key)))
            from .desktop_strategy import apply_strategy_settings
            apply_strategy_settings(self, job)
            for root, field in self.rates.items():
                field.setValue(data.margin_rates.get(root, 0) * 100)
            self.factor_result = None
            self._config_path = Path(path).resolve()
            self.show_status(f"已读取配置：{self._config_path}")
        except (ValueError, TypeError, OSError) as exc:
            self.show_error(str(exc))

    def show_location(self, operation):
        self.location_operation = operation
        self.location_title.setText("结果目录" if operation == "open_result" else "配置文件")
        self.location_apply.setText("保存" if operation == "save_config" else "读取")
        self.location_path.setText(self.output_path.text() if operation == "open_result" else str(self._config_path))
        self.location_bar.show()

    def browse_location(self):
        self.picker.open_for(self.location_path, directory=self.location_operation == "open_result")

    def apply_location(self):
        path = self.location_path.text().strip()
        if not path:
            self.show_error("请输入配置文件或结果目录位置")
            return
        if self.location_operation == "load_config":
            self.load_config(path)
        elif self.location_operation == "open_result":
            self.open_result(path)
        else:
            try:
                job = self.job()
                destination = Path(path).expanduser().resolve()
                if not destination.name.endswith(".local.json"):
                    raise ValueError("本机配置请使用 .local.json 文件名")
                destination.parent.mkdir(parents=True, exist_ok=True)
                write_json(destination, job)
                self._config_path = destination
                self.show_status(f"配置已保存：{destination}")
            except (ValueError, TypeError, OSError) as exc:
                self.show_error(str(exc))

    def submit(self, function, callback):
        if self.task is not None or self.closing:
            return
        self.forms.setEnabled(False)
        self.run_button.setEnabled(False)
        self.inspect_button.setEnabled(False)
        self.location_bar.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.task = Task(function)
        self.task.signals.progress.connect(self.on_progress)
        self.task.signals.success.connect(callback)
        self.task.signals.failed.connect(self.show_error)
        self.task.signals.cancelled.connect(lambda: self.show_status("本轮已取消；未发布新的回测结果。"))
        self.task.signals.finished.connect(self.task_finished)
        self.pool.start(self.task)

    def task_finished(self):
        self.task = None
        self.forms.setEnabled(True)
        self.run_button.setEnabled(True)
        self.inspect_button.setEnabled(True)
        self.location_bar.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        if self.closing:
            QTimer.singleShot(0, self.close)

    def on_progress(self, info):
        if info.get("stage") in {"loading_parallel", "simulating_parallel"}:
            value = info["done"] / max(info["total"], 1)
            self.progress.setRange(0, 100)
            self.progress.setValue(int(value * 100))
            stage = "读取日/分钟行情" if info["stage"] == "loading_parallel" else "计算独立账户"
            self.show_status(f"正在{stage} · {info['workers']} 进程 · {info['done']}/{info['total']}")
        elif info.get("stage") == "simulating":
            total = info["total"] or 1
            value = (info["account_index"] + info["done"] / total) / info["accounts"]
            self.progress.setRange(0, 100)
            self.progress.setValue(int(value * 100))
            self.show_status(f"正在回测 {info['account']}  ·  {info['timestamp']}  ·  {int(value * 100)}%")
        else:
            self.show_status(info.get("message", "正在处理本地数据…"))
        if info.get("stage") == "saving":
            self.cancel_button.setEnabled(False)

    def inspect(self):
        try:
            job = self.job()
            self.submit(lambda cancel, progress: inspect_job(job, cancel_event=cancel, progress=progress), self.display_inspection)
        except (ValueError, TypeError, OSError) as exc:
            self.show_error(str(exc))

    def run_backtest(self):
        try:
            job = self.job()
            self.inspection = None
            self.submit(lambda cancel, progress: execute_job(job, cancel_event=cancel, progress=progress), self.display_result)
        except (ValueError, TypeError, OSError) as exc:
            self.show_error(str(exc))

    def cancel(self):
        if self.task:
            self.task.cancel_event.set()
            self.show_status("正在取消，等待当前文件读取或安全写出结束…")
            self.cancel_button.setEnabled(False)

    def open_result(self, path):
        self.submit(lambda cancel, progress: load_result(path), self.display_result)

    def display_inspection(self, payload):
        self.inspection = payload
        report = payload["report"]
        self.data_manifest_view.setPlainText(data_manifest_text(report))
        instruction = report["instructions"]
        missing = report["required_missing"]
        message = (f"指令 {instruction['rows']:,} 行 / {len(instruction['symbols'])} 个标的；"
                   f"行情 {len(report['coverage'])} 个标的。")
        if missing:
            message += " 待补充：" + "；".join(missing)
        else:
            message += " 可以开始基础回测。"
        if report["optional_missing"]:
            message += " 分红调整价尚未齐备，可继续使用原始 close 核算。"
        self.show_status(message)
        self.tables.setCurrentIndex(5)
        self.refresh_table()
        self.inspected.emit(payload)

    def display_result(self, result):
        self.result = result
        self.inspection = None
        self.account.blockSignals(True)
        self.account.clear()
        for name in result.accounts:
            self.account.addItem(name)
        self.account.blockSignals(False)
        self.account.setEnabled(True)
        self.output_path.setText(result.output_paths.get("output_dir", ""))
        self.output_path.setToolTip(self.output_path.text())
        self.result_note.setText(f"{len(result.accounts)} 个账户  ·  {len(result.actual_orders):,} 条开平仓记录")
        source = result.metadata.get("market_data", {})
        self.data_manifest_view.setPlainText(data_manifest_text(source))
        rates = source.get("margin_source")
        description = []
        if isinstance(rates, dict) and rates:
            description.append("固定保证金假设：" + " · ".join(f"{k} {v:.2%}" for k, v in rates.items()))
        elif isinstance(rates, str):
            description.append("保证金：历史输入表")
        if source.get("warnings"):
            description.append("数据限制详见本轮 metadata.json")
        settings = result.metadata.get("config", {})
        if settings.get("hedges"):
            ratios = sorted({f"{r['primary'][:2]} {abs(r['quantity_ratio'])}" for r in settings["hedges"]})
            description.append("每手期货反向指数单位：" + " · ".join(ratios))
        basis = "总权益" if settings.get("margin_call_basis", "equity") == "equity" else "保证金后余额"
        description.append(f"本轮爆仓：{basis} < 保证金 × {settings.get('minimum_margin_ratio', 0.0001):g}")
        if settings.get("d0") is not None:
            description.append(f"临期收盘强平 T≤{settings['d0']} 天")
        precision = result.metadata.get("precision")
        if precision:
            description.append("日频收盘风控" if precision["requested"] == "1d" else "自动对齐输入 · 逐时点风控")
        self.source_note.setText("  ｜  ".join(description) or "本轮参数和数据版本已记录在结果目录。")
        self.select_account()
        self.tables.setCurrentIndex(0)
        self.refresh_table()
        performance = result.metadata.get("performance", {})
        if "engine_seconds" in performance:
            days = max(len(account.equity) for account in result.accounts.values())
            self.show_status(f"完成 {days} 天日结 · 核算 {performance['engine_seconds']:.3f} 秒 · "
                             f"账户估值 {performance['evaluated_events']:,} 次；可查看明细并复制成交表位置。")
        else:
            self.show_status("回测结果已就绪；可切换账户、查看明细或复制实际成交表位置。")
        self.completed.emit(result)

    def select_account(self):
        if not self.result or self.account.currentText() not in self.result.accounts:
            return
        account = self.result.accounts[self.account.currentText()]
        summary = account.summary
        self.metrics["return"].setText(f"{summary['total_return']:+.2%}")
        self.metrics["return"].setStyleSheet(f"color:{UP if summary['total_return'] > 0 else DOWN};")
        self.metrics["drawdown"].setText(f"{summary['max_drawdown']:.2%}")
        self.metrics["fees"].setText(f"{summary['total_fees']:,.2f}")
        self.metrics["orders"].setText(f"{summary['order_count']:,}")
        self.charts.set_account(account)
        self.chart_stack.setCurrentWidget(self.charts)
        self.search.clear()
        self.refresh_table()

    def refresh_table(self):
        key = self.tables.currentWidget().objectName()
        frame = pd.DataFrame()
        if key == "coverage" and self.inspection:
            frame = pd.DataFrame(self.inspection["report"]["coverage"])
        elif key == "instructions" and self.inspection:
            frame = self.inspection["instructions"]
        elif self.result and self.account.currentText() in self.result.accounts:
            account = self.result.accounts[self.account.currentText()]
            if key == "instructions":
                source = self.result.input_instructions
                columns = source.columns.intersection(account.positions.columns, sort=False) if source is not None else []
                frame = source.loc[:, columns] if source is not None and len(columns) else source if source is not None else account.target_weights
            elif key != "coverage":
                frame = getattr(account, key)
        if key == "actual_orders" and not frame.empty:
            priority = ["execution_time", "symbol", "action", "quantity", "price", "fee", "signal_time"]
            frame = frame.loc[:, priority + [c for c in frame if c not in priority]]
        self.models[key].set_frame(frame)
        table = self.tables.currentWidget()
        for i, column in enumerate(self.models[key].frame.columns):
            if column in {"timestamp", "signal_time", "execution_time", "start", "end"}:
                table.setColumnWidth(i, 270 if self._band else 210)
            elif column in {"action", "side", "quantity"}:
                table.setColumnWidth(i, 125 if self._band else 100)
        self.filter_table()

    def filter_table(self):
        key = self.tables.currentWidget().objectName()
        model = self.models[key]
        model.filter(self.search.text().strip())
        self.table_count.setText(f"显示 {len(model.frame):,} / {len(model.original):,} 行")

    def copy_orders_path(self):
        path = ""
        if self.result:
            path = self.result.output_paths.get("accounts", {}).get(self.account.currentText(), {}).get("actual_orders", "")
            path = path or self.result.output_paths.get("actual_orders", "")
        if path:
            QApplication.clipboard().setText(path)
            self.show_status(f"已复制实际开平仓表位置：{path}")
        else:
            self.show_status("先完成回测或打开已有结果目录。")

    def open_output_folder(self):
        if self.output_path.text():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_path.text()))

    def show_status(self, message):
        self.status.setStyleSheet("")
        self.status.setText(message)
        self.status.setToolTip(message)

    def show_error(self, message):
        self.status.setStyleSheet(f"color:{UP};")
        self.status.setText("未完成：" + message)
        self.status.setToolTip(message)

    def resizeEvent(self, event):
        if not hasattr(self, "left"):
            return super().resizeEvent(event)
        large = self.width() >= 2800
        if large != self._band:
            self._band = large
            font_size = 19 if large else 15
            self.setStyleSheet(STYLE + f"""
                QWidget {{font-size:{font_size}px;}}
                QMainWindow {{background:{BACKGROUND};}}
                QFrame#panel, QFrame#metricCard {{background:{PANEL};border:1px solid {BORDER};border-radius:10px;}}
                QFrame#metricCard QLabel {{background:transparent;}}
                QLabel#title {{font-size:{34 if large else 27}px;font-weight:700;}}
                QLabel#section {{font-size:{25 if large else 20}px;font-weight:650;}}
                QLabel#metric {{font-size:{38 if large else 28}px;font-family:'Segoe UI';font-weight:600;}}
                QLabel#emptyTitle {{font-size:{30 if large else 23}px;font-weight:600;color:{ACCENT};}}
                QLabel#muted {{color:{MUTED};}}
                QLabel#badge {{background:#dcecf7;color:{ACCENT};padding:9px 14px;border-radius:8px;}}
                QLabel#risk {{background:#edf4fa;color:{ACCENT};padding:10px;border-radius:6px;}}
                QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{min-height:{34 if large else 27}px;background:{PANEL};
                    border:1px solid {BORDER};padding:5px 8px;border-radius:5px;}}
                QComboBox::down-arrow {{image:url("{(REPOSITORY / 'dashboard/native/assets/chevron_down.svg').as_posix()}");width:13px;height:13px;}}
                QPlainTextEdit {{background:{PANEL};border:1px solid {BORDER};}}
                QPushButton {{min-height:28px;padding:7px 12px;border-radius:6px;border:1px solid {BORDER};}}
                QPushButton#primary {{background:{ACCENT};color:white;border-color:{ACCENT};font-weight:600;}}
                QTabBar::tab {{padding:9px 12px;font-size:{font_size}px;}}
                QTabBar::tab:selected {{background:#dcecf7;color:{ACCENT};}}
                QTableView {{background:{PANEL};alternate-background-color:#f6f9fc;border:1px solid {BORDER};
                    gridline-color:#e9eff4;selection-background-color:#dcecf7;selection-color:{TEXT};}}
                QHeaderView::section {{background:#eaf1f7;color:{MUTED};padding:9px;border:0;}}
                QProgressBar {{border:0;background:#e4edf5;}}
                QProgressBar::chunk {{background:{ACCENT};}}
            """)
            self.left.setMaximumWidth(880 if large else 620)
            self.split.setSizes([660 if large else 440, max(640, self.width() - (720 if large else 500))])
            self.charts.set_scale(large)
            self.refresh_table()
        super().resizeEvent(event)

    def closeEvent(self, event):
        if self.task is not None:
            self.closing = True
            self.cancel()
            event.ignore()
            return
        self.pool.waitForDone()
        event.accept()


def configure_style(app):
    import os
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        if (fonts / name).is_file():
            QFontDatabase.addApplicationFont(str(fonts / name))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    pg.setConfigOptions(antialias=True, foreground=MUTED, background=PANEL, useOpenGL=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Delta1 本地大表回测桌面窗口")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    configure_windows_identity("Backtest")
    app = QApplication.instance() or QApplication([])
    configure_style(app)
    window = BacktestWindow(config_path=args.config, result_path=args.result)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
