"""Desktop shell for the three market observation pages."""
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from .branding import app_icon
from .market_view import MarketPages
from .theme import ACCENT, MUTED, PANEL, STYLE
from .widgets import label
from .presentation import AUTO_REFRESH,RELEASE_NAME,MODULE_TITLES


class Signals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            self.signals.completed.emit(self.function())
        except Exception as exc:
            self.signals.failed.emit(f"数据更新失败：{type(exc).__name__}")


class Window(QMainWindow):
    loaded = Signal(object)

    def __init__(self, model, *, demo=False):
        super().__init__()
        self.model = model
        self.demo = demo
        self.state = None
        self.frequency = model.config.get("frequency", "1m")
        self.as_of = None
        self.busy = False
        self.pending = False
        self.closing = False
        self.generation = 0
        self.active_task = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle("Delta1 · 市场看板 · "+RELEASE_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1560, 1040)
        self.setMinimumSize(1120, 740)
        self.setStyleSheet(STYLE)
        self.build()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2500)
        self.refresh_timer.timeout.connect(self.periodic)
        if AUTO_REFRESH: self.refresh_timer.start()
        QTimer.singleShot(0, self.refresh)

    def build(self):
        root = QWidget()
        self.setCentralWidget(root)
        body = QVBoxLayout(root)
        body.setContentsMargins(24, 20, 24, 14)
        body.setSpacing(12)
        header = QHBoxLayout()
        logo = label("Δ  DELTA1")
        logo.setStyleSheet(f"color:{ACCENT};font-size:23px;font-weight:650;")
        header.addWidget(logo)
        header.addWidget(label("股指期货 · "+RELEASE_NAME, "muted"))
        header.addStretch()
        self.mode = label("数据待接入", "pill")
        header.addWidget(self.mode)
        self.demo_button = None
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("refresh_button")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        body.addLayout(header)
        navigation = QHBoxLayout()
        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        for index, title in enumerate(MODULE_TITLES):
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.navigation.addButton(button, index)
            navigation.addWidget(button, 1)
        self.navigation.idClicked.connect(self.navigate)
        body.addLayout(navigation)
        self.pages = QStackedWidget()
        self.market_pages = MarketPages(self)
        self.dashboard = self.market_pages.overview
        for page in self.market_pages.pages:
            self.pages.addWidget(page)
        body.addWidget(self.pages, 1)
        self.status = label("正在加载指标…", "muted")
        self.status.setWordWrap(True)
        body.addWidget(self.status)

    def request(self):
        return {"demo": self.demo, "product": self.product.currentText(),
                "frequency": self.frequency, "as_of": None, "save": False}

    def refresh(self, *_, automatic=False):
        if self.closing:
            return
        if self.busy:
            self.pending = True
            return
        self.busy = True
        self.generation += 1
        generation = self.generation
        request = self.request()
        function = self.model.auto_snapshot if automatic else self.model.snapshot
        self.status.setText("正在更新市场数据…")
        task = Task(lambda: function(request))
        self.active_task = task
        task.signals.completed.connect(lambda value: self.finish(value, generation))
        task.signals.failed.connect(lambda error: self.finish(None, generation, error=error))
        self.pool.start(task)

    def finish(self, state, generation, *, error=None):
        self.busy = False
        self.active_task = None
        if self.closing:
            return
        if error:
            self.status.setText(error)
        elif state is not None and generation == self.generation:
            self.render(state)
        elif state is None:
            self.status.setText("数据时刻未变化 · 保留当前观察结果")
        if self.pending:
            self.pending = False
            self.refresh()

    def render(self, state):
        self.state = state
        self.market_pages.render(state)
        self.loaded.emit(state)

    def navigate(self, index):
        if 0 <= index < self.pages.count():
            self.pages.setCurrentIndex(index)
            if self.navigation.button(index):
                self.navigation.button(index).setChecked(True)

    def selection_changed(self, *_):
        self.refresh()

    def frequency_changed(self, index):
        self.frequency = ("1d", "1m", "1s")[index]
        self.refresh()

    def periodic(self):
        if not self.busy and not self.closing:
            self.refresh(automatic=True)

    def toggle_demo(self):
        self.demo = not self.demo
        self.refresh()

    def closeEvent(self, event):
        self.refresh_timer.stop()
        if self.busy:
            self.pending = False
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        self.closing = True
        self.model.close()
        event.accept()


def configure_style(app):
    import os
    font_root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        path = font_root / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    pg.setConfigOptions(antialias=True, foreground=MUTED, background=PANEL, useOpenGL=False)
