"""Standalone native window for existing statistics, using the same local data."""
from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMainWindow

from script_making.desktop import app_icon
from script_making.desktop_theme import STYLE
from script_making.service import ReportService
from script_making.statistics_widgets import StatisticsPage


class StatisticsWindow(QMainWindow):
    def __init__(self, service, *, auto_generate=True):
        super().__init__()
        self._closing = False
        self.setWindowTitle("D1 统计工作台")
        self.setWindowIcon(app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1120, 720)
        self.page = StatisticsPage(service, self, auto_generate=auto_generate)
        self.page.finished.connect(self._finish_close)
        self.setCentralWidget(self.page)

    def closeEvent(self, event):
        if self.page.worker is not None:
            self._closing = True
            self.page.prepare_close()
            event.ignore()
            return
        self.page.prepare_close()
        event.accept()

    def _finish_close(self):
        if self._closing and self.page.worker is None:
            QTimer.singleShot(0, self.close)


def main(argv=None):
    parser = argparse.ArgumentParser(description="D1 统计工作台 · 原生桌面 App")
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parent.parent / "script_making",
                        help="原日报模块的本机配置及数据所在目录")
    parser.add_argument("--startup-check", action="store_true", help="检查窗口创建后退出，不生成统计")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("D1 统计工作台")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(STYLE)
    window = StatisticsWindow(ReportService(args.root), auto_generate=not args.startup_check)
    if args.startup_check:
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    if args.startup_check:
        QTimer.singleShot(0, app.quit)
    return app.exec()
