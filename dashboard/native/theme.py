"""Single Graphite Gold palette shared by both native editions."""
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
