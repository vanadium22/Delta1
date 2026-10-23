"""Public and private palettes; shared layout and calculation remain identical."""
import os
from pathlib import Path
BACKGROUND = "#181a1e"
PANEL = "#202329"
SURFACE = "#282c33"
BORDER = "#383d46"
TEXT = "#edeff3"
MUTED = "#a7afb9"
ACCENT = "#e6c27e"
ACCENT_BACKGROUND = "#393327"
UP = "#f59195"
DOWN = "#7dccb1"
CHART_COLORS = [ACCENT, "#94b8d5", DOWN, "#c0a5da"]

_settings=Path(__file__).resolve().parents[1]/'localsetting'
THEME=os.environ.get('DELTA1_THEME') or ('private' if (_settings/'native.json').is_file() and not (_settings/'numeric_excel/native.json').is_file() else 'public')
if THEME=='public':
    BACKGROUND='#f4f7fa';PANEL='#ffffff';SURFACE='#eaf1f7';BORDER='#ccd9e4'
    TEXT='#17334f';MUTED='#526779';ACCENT='#08457e';ACCENT_BACKGROUND='#dcecf7'
    UP='#b12b40';DOWN='#08745b';CHART_COLORS=[ACCENT,'#007ea9',DOWN,'#815399']

STYLE = f"""
QWidget {{ background: {BACKGROUND}; color: {TEXT}; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }}
QMainWindow {{ background: {BACKGROUND}; }}
QFrame#sidebar {{ background: #141619; border-right: 1px solid {BORDER}; }}
QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 5px; }}
QFrame#panel QLabel, QFrame#panel QWidget {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#title {{ font-size: 23px; font-weight: 650; }}
QLabel#section {{ font-size: 15px; font-weight: 600; }}
QLabel#metric {{ font-family: 'Segoe UI'; font-size: 27px; font-weight: 600; color: {ACCENT}; }}
QLabel#pill {{ background: {ACCENT_BACKGROUND}; color: {ACCENT}; padding: 5px 10px; border-radius: 4px; }}
QLabel#banner {{ background: #373027; color: #ebc784; border: 1px solid #574a33; padding: 8px 12px; border-radius: 4px; }}
QPushButton {{ background: {SURFACE}; border: 1px solid #454b56; border-radius: 4px; padding: 7px 12px; }}
QPushButton:hover {{ background: #333842; border-color: #86734f; }}
QPushButton:checked, QPushButton#primary {{ background: {ACCENT_BACKGROUND}; color: {ACCENT}; border-color: #aa8c53; }}
QPushButton:disabled {{ color: #727a85; background: #24272c; border-color: #343840; }}
QPushButton#nav {{ text-align: left; border: none; background: transparent; padding: 12px; }}
QPushButton#nav:checked {{ background: {ACCENT_BACKGROUND}; color: {ACCENT}; }}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{ background: #191c21; border: 1px solid #454b56; border-radius: 4px; padding: 6px; selection-background-color: #665333; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: #51452f; }}
QTableWidget {{ background: {PANEL}; alternate-background-color: #24282e; border: 1px solid {BORDER}; gridline-color: {BORDER}; border-radius: 4px; }}
QTableWidget::item {{ padding: 5px; }}
QTableWidget::item:selected {{ background: {ACCENT_BACKGROUND}; color: {TEXT}; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; padding: 8px; border: none; border-right: 1px solid {BORDER}; }}
QListWidget {{ background: #1b1e23; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px; }}
QListWidget::item {{ padding: 12px; border-radius: 3px; }}
QListWidget::item:selected {{ background: {ACCENT_BACKGROUND}; color: {ACCENT}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {SURFACE}; padding: 7px 14px; }}
QTabBar::tab:selected {{ background: {ACCENT_BACKGROUND}; color: {ACCENT}; }}
QScrollArea {{ border: none; background: {BACKGROUND}; }}
QScrollBar:vertical {{ width: 9px; background: #191c21; }}
QScrollBar::handle:vertical {{ background: #515966; min-height: 30px; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 5px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; background: {ACCENT}; border-radius: 7px; }}
QCheckBox {{ spacing: 8px; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid #86734f; padding: 7px; }}
"""

if THEME=='public':
    # Map legacy literal control colors into the same light palette.
    for old,new in {'#141619':BACKGROUND,'#373027':'#e5f2fa','#ebc784':ACCENT,'#574a33':BORDER,
                    '#454b56':BORDER,'#333842':'#dcecf7','#86734f':ACCENT,'#aa8c53':ACCENT,
                    '#727a85':'#778b9a','#24272c':SURFACE,'#343840':BORDER,'#191c21':PANEL,
                    '#665333':'#bfdaed','#51452f':'#bfdaed','#24282e':'#f3f7fa','#1b1e23':PANEL,
                    '#515966':'#a4becf'}.items():STYLE=STYLE.replace(old,new)
