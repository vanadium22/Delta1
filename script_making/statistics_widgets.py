"""Native statistics workspace and editable mail draft settings."""
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                              QFormLayout, QHBoxLayout, QLineEdit, QTabWidget,
                              QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from .desktop_widgets import button, label
from .download_widgets import open_location
from .statistics import (DEFAULT_CONFIG, FIELDS, build_snapshot, load_config,
                         save_config, validated_config)
from .statistics_export import export_bundle, mail_content, render_pages, save_image
from .storage import ReportError


class ConfigurationDialog(QDialog):
    def __init__(self, values, snapshot=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("统计设置与邮件正文")
        self.resize(860, 720)
        self.values = dict(values)
        self.snapshot = snapshot
        body = QVBoxLayout(self)
        tabs = QTabWidget()
        body.addWidget(tabs)
        rule = QWidget()
        rule_layout = QVBoxLayout(rule)
        rule_layout.addWidget(label("永久剔除代码（每行一个完整 Wind 代码，可增删；只保存在本机）", wrap=True))
        rule_layout.addWidget(label("预置：159001.SZ 保证金；511660.OF / .SH 现金添益；511850.SH 财富宝；511990.SH 添益。", "muted", True))
        self.exclusions = QTextEdit("\n".join(values["exclusions"]))
        self.exclusions.setAcceptRichText(False)
        rule_layout.addWidget(self.exclusions)
        rule_layout.addWidget(label("指数组：000016.SH、000300.SH、000905.SH、000852.SH 及 IF/IH/IC/IM 股指期货。其余识别到的个股和ETF归第二组。", "muted", True))
        tabs.addTab(rule, "永久剔除名单")
        mail = QWidget()
        layout = QVBoxLayout(mail)
        form = QFormLayout()
        self.entries = {}
        for key, caption in (("to", "收件人"), ("cc", "抄送"), ("subject", "邮件主题")):
            edit = QLineEdit(values[key])
            form.addRow(caption, edit)
            self.entries[key] = edit
        layout.addLayout(form)
        layout.addWidget(label("地址用逗号分隔。正文可编辑；{{pnl1}}、{{risk}}、{{dates}} 在导出时替换为本次统计。", "muted", True))
        self.template = QTextEdit()
        self.template.setAcceptRichText(False)
        self.template.setPlainText(values["template"])
        layout.addWidget(self.template, 1)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(label("本次正文预览（附件包含两张统计图片和两张年度历史图）", "muted"))
        layout.addWidget(self.preview, 1)
        tabs.addTab(mail, "邮件正文与地址")
        self.template.textChanged.connect(self.update_preview)
        self.entries["subject"].textChanged.connect(self.update_preview)
        self.error = label("", "error", True)
        self.error.hide()
        body.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)
        self.update_preview()

    def candidate(self):
        return {**self.values, **{key: widget.text() for key, widget in self.entries.items()},
                "template": self.template.toPlainText(), "exclusions": self.exclusions.toPlainText()}

    def update_preview(self):
        if self.snapshot:
            subject, body = mail_content(self.snapshot, self.candidate())
            self.preview.setPlainText(subject + "\n\n" + body)
        else:
            self.preview.setPlainText("生成统计后，此处显示实际正文与数值。")

    def save(self):
        try:
            self.values = validated_config(self.candidate())
        except ReportError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()


class StatisticsWorker(QThread):
    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.outcome = None

    def run(self):
        try:
            self.outcome = (True, self.operation())
        except Exception as exc:
            self.outcome = (False, str(exc))


class StatisticsBrowser(QTextBrowser):
    """Fit the embedded pnl1 figure without changing the full-resolution export."""
    def setHtml(self, html):
        super().setHtml(html)
        self.fit_images()

    def fit_images(self):
        width = min(1500, max(1, self.viewport().width() - 24))
        block = self.document().begin()
        edits = []
        while block.isValid():
            item = block.begin()
            while not item.atEnd():
                fragment = item.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    fmt = fragment.charFormat().toImageFormat()
                    if abs(fmt.width() - width) > 1:
                        fmt.setHeight(width * 780 / 1600)
                        fmt.setWidth(width)
                        edits.append((fragment.position(), fragment.length(), fmt))
                item += 1
            block = block.next()
        for position, length, fmt in edits:
            cursor = QTextCursor(self.document())
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(fmt)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_images()


class StatisticsPage(QWidget):
    finished = Signal()
    busy_changed = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.snapshot = None
        self.pages = None
        self.worker = None
        self._closing = False
        config_error = ""
        try:
            self.config = load_config(service.settings.root)
        except ReportError as exc:
            self.config = validated_config(DEFAULT_CONFIG)
            config_error = str(exc)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 23, 24, 16)
        layout.addWidget(label("统计", "title"))
        layout.addWidget(label("每份日报按自己的报表日期统计；原始 Excel 保持不变。", "muted"))
        sources = QHBoxLayout()
        self.dates = {}
        self.source_buttons = []
        self.catalog_data = service.query_catalog()
        for kind, caption in (("pnl", "盈亏统计"), ("swap", "收益互换日报"), ("strategy", "D1策略台日报")):
            box = QVBoxLayout()
            box.addWidget(label(caption, "sectionTitle"))
            row = QHBoxLayout()
            combo = QComboBox()
            for entry in self.catalog_data["dates"]:
                if kind in entry["files"]:
                    combo.addItem(entry["date"], entry["date"])
            if not combo.count():
                combo.addItem("尚无本地日报", None)
            self.dates[kind] = combo
            row.addWidget(combo, 1)
            reveal = button("打开位置", lambda checked=False, key=kind: self.reveal(key))
            self.source_buttons.append(reveal)
            row.addWidget(reveal)
            box.addLayout(row)
            sources.addLayout(box, 1)
        layout.addLayout(sources)
        controls = QHBoxLayout()
        controls.addWidget(label("pnl1 上期"))
        self.previous = QComboBox()
        self.previous.setMinimumWidth(135)
        controls.addWidget(self.previous)
        controls.addWidget(label("观察 |字段| ≥"))
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(FIELDS[2:])
        self.metric_combo.setCurrentText(self.config["metric"])
        controls.addWidget(self.metric_combo)
        self.threshold = QLineEdit(self.config["threshold"])
        self.threshold.setMaximumWidth(120)
        controls.addWidget(self.threshold)
        self.configure_button = button("剔除名单 / 邮件设置", self.configure)
        self.generate_button = button("生成并记录统计", self.generate, "primary")
        controls.addStretch()
        layout.addLayout(controls)
        actions = QHBoxLayout()
        actions.addWidget(label("pnl1 收益图：当年最近30份 · 截止所选日期", "muted"), 1)
        self.refresh_button = button("刷新本地日期", self.refresh_dates)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.configure_button)
        actions.addWidget(self.generate_button)
        layout.addLayout(actions)
        self.notice = label("请选择日期并生成统计。", "notice", True)
        layout.addWidget(self.notice)
        self.tabs = QTabWidget()
        self.browsers = []
        for caption in ("组内收益 · pnl1", "风险观察 · 两份日报"):
            browser = StatisticsBrowser()
            browser.setOpenLinks(False)
            self.browsers.append(browser)
            self.tabs.addTab(browser, caption)
        layout.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        self.image_button = button("保存本页完整图片", self.export_image)
        self.export_button = button("导出两图和邮件草稿", self.export, "primary")
        self.folder_button = button("打开统计保存位置", self.reveal_output)
        for widget in (self.image_button, self.export_button, self.folder_button):
            bottom.addWidget(widget)
        bottom.addStretch()
        layout.addLayout(bottom)
        self.error = label(config_error, "error", True)
        self.error.setVisible(bool(config_error))
        layout.addWidget(self.error)
        self.fill_previous()
        self.dates["pnl"].currentIndexChanged.connect(self.fill_previous)
        for combo in self.dates.values():
            combo.currentIndexChanged.connect(self.invalidate)
        self.previous.currentIndexChanged.connect(self.invalidate)
        self.metric_combo.currentIndexChanged.connect(self.invalidate)
        self.threshold.textChanged.connect(self.invalidate)
        self.invalidate()
        if not config_error and any(combo.currentData() for combo in self.dates.values()):
            QTimer.singleShot(0, self.generate)

    def fill_previous(self):
        day = self.dates["pnl"].currentData()
        self.previous.blockSignals(True)
        self.previous.clear()
        for entry in self.catalog_data["dates"]:
            if day and entry["date"] < day and "pnl" in entry["files"]:
                self.previous.addItem(entry["date"], entry["date"])
        self.previous.addItem("无上期报表", None)
        self.previous.blockSignals(False)

    def refresh_dates(self):
        if self.worker:
            return
        try:
            self.catalog_data = self.service.query_catalog()
            for kind, combo in self.dates.items():
                selected = combo.currentData()
                combo.blockSignals(True)
                combo.clear()
                for entry in self.catalog_data["dates"]:
                    if kind in entry["files"]:
                        combo.addItem(entry["date"], entry["date"])
                if not combo.count():
                    combo.addItem("尚无本地日报", None)
                if selected and combo.findData(selected) >= 0:
                    combo.setCurrentIndex(combo.findData(selected))
                combo.blockSignals(False)
            self.fill_previous()
            self.invalidate()
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def current_config(self):
        return {**self.config, "metric": self.metric_combo.currentText(), "threshold": self.threshold.text()}

    def invalidate(self, *_):
        self.snapshot = self.pages = None
        for browser in self.browsers:
            browser.setPlainText("条件已选择或变更，请生成统计。")
        self.notice.setText("生成统计后可导出完整页面图片和邮件草稿。")
        self.image_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def set_busy(self, busy):
        for widget in (*self.dates.values(), *self.source_buttons, self.previous, self.metric_combo,
                       self.threshold, self.configure_button, self.generate_button, self.refresh_button):
            widget.setEnabled(not busy and not self._closing)

    def generate(self):
        if self.worker or self._closing:
            return
        self.invalidate()
        self.error.clear()
        self.error.hide()
        try:
            self.config = save_config(self.service.settings.root, self.current_config())
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        selections = {key: combo.currentData() for key, combo in self.dates.items()}
        selections["previous"] = self.previous.currentData()
        values = dict(self.config)
        self.worker = StatisticsWorker(lambda: build_snapshot(self.service, selections, values), self)
        self.worker.finished.connect(self.generated)
        self.set_busy(True)
        self.busy_changed.emit()
        self.notice.setText("正在读取缓存值、核对来源并记录统计…")
        self.worker.start()

    def generated(self):
        worker, self.worker = self.worker, None
        ok, result = worker.outcome
        worker.deleteLater()
        self.set_busy(False)
        self.busy_changed.emit()
        if self._closing:
            self.finished.emit()
            return
        if not ok:
            self.error.setText(result)
            self.error.show()
            self.notice.setText("统计未完成，请核对来源或条件后重试。")
            return
        self.snapshot = result
        self.pages = render_pages(result)
        for browser, html in zip(self.browsers, self.pages):
            browser.setHtml(html)
        self.image_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.notice.setText("统计已记录。可导出完整页面；邮件为本机草稿，可在邮件客户端检查后发送。")
        if result["errors"]:
            self.error.setText("部分未生成：" + "；".join(result["errors"].values()))
            self.error.show()
        history_errors = sum(len(h["errors"]) for h in result["history"].values())
        if history_errors:
            self.error.setText(self.error.text() + f" 历史图有 {history_errors} 份文件解析失败，相关日期未补零，详见统计记录。")
            self.error.show()

    def configure(self):
        try:
            values = validated_config(self.current_config())
            dialog = ConfigurationDialog(values, self.snapshot, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            previous_exclusions = values["exclusions"]
            self.config = save_config(self.service.settings.root, dialog.values)
            if previous_exclusions != self.config["exclusions"]:
                self.invalidate()
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def output_base(self):
        return self.service.settings.data_path() / "statistics" / "exports"

    def export_image(self):
        if not self.pages:
            return
        try:
            self.output_base().mkdir(parents=True, exist_ok=True)
            index = self.tabs.currentIndex()
            names = ("pnl1", "risk")
            default = self.output_base() / (f"{names[index]}-{self.snapshot['id'][:10]}.png")
            path, _ = QFileDialog.getSaveFileName(self, "保存完整统计图片", str(default), "PNG (*.png)")
            if path:
                save_image(self.pages[index], Path(path))
                self.notice.setText("完整图片已保存：" + path)
        except (OSError, ReportError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def export(self):
        if not self.snapshot:
            return
        try:
            folder = export_bundle(self.output_base(), self.snapshot, self.pages, self.config)
            self.notice.setText("pnl1（含收益图）、风险汇总、正文和邮件草稿已保存：" + str(folder))
            open_location(folder)
        except (OSError, ReportError, ValueError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def reveal(self, kind):
        try:
            day = self.dates[kind].currentData()
            open_location(self.service.path_for(kind, day) if day else self.service.settings.data_path())
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def reveal_output(self):
        try:
            base = self.service.settings.data_path() / "statistics"
            base.mkdir(parents=True, exist_ok=True)
            open_location(base)
        except (ReportError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()

    def prepare_close(self):
        self._closing = True
        self.set_busy(True)
        self.image_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.notice.setText("正在完成本次读取，随后关闭…")
