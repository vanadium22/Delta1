"""Readable card UI styling; the legacy/public viewer keeps its own theme."""
from .theme import STYLE, ACCENT, BORDER, TEXT, MUTED, THEME
from pathlib import Path

ARROW=(Path(__file__).parent/'assets'/'chevron_down.svg').as_posix()

CARD_STYLE=STYLE+f"""
QWidget {{font-size:16px;}}
QLabel#title {{font-size:26px;font-weight:700;}}
QLabel#section {{font-size:20px;font-weight:600;}}
QLabel#muted {{font-size:15px;color:{MUTED};}}
QLabel#pill, QLabel#banner {{font-size:15px;padding:9px;}}
QPushButton {{font-size:16px;font-weight:600;padding:9px 16px;border:1px solid {BORDER};border-radius:7px;}}
QPushButton:hover {{border:1px solid {ACCENT};color:{ACCENT};}}
QPushButton:checked {{background:{ACCENT};color:#0b1825;border-color:{ACCENT};}}
QPushButton#action {{color:{ACCENT};border:1px solid {ACCENT};}}
QComboBox {{font-size:16px;padding:8px 28px 8px 10px;min-height:22px;}}
QComboBox::drop-down {{width:24px;}}
QComboBox::down-arrow {{image:url("{ARROW}");width:18px;height:18px;}}
QTabBar::tab {{font-size:18px;font-weight:600;padding:12px 24px;margin:2px 5px 4px 0;border:1px solid {BORDER};border-radius:7px;}}
QTabBar::tab:selected {{color:#0b1825;background:{ACCENT};border-color:{ACCENT};}}
QTabBar::tab:hover {{border-color:{ACCENT};}}
QTextBrowser, QPlainTextEdit, QTableWidget {{font-size:16px;}}
QHeaderView::section {{font-size:16px;padding:9px;}}
QScrollBar:vertical {{width:14px;}}
QLabel#formula {{font-size:21px;font-weight:600;color:{TEXT};padding:10px;}}
"""
if THEME=='public':CARD_STYLE=CARD_STYLE.replace('color:#0b1825','color:#ffffff')
