"""Shared light palette for the native daily-report workspace."""
from pathlib import Path

STYLE = """
QMainWindow, QDialog { background: #f3f6fa; color: #172b46; }
QWidget { color: #172b46; font-size: 13px; }
QFrame#sidebar { background: #152d49; border: none; }
QFrame#sidebar QLabel { color: #b6c8dc; background: transparent; }
QLabel#brand { color: white; font-size: 23px; font-weight: 700; }
QLabel#brandCaption { color: #83b5b2; font-size: 11px; letter-spacing: 2px; }
QPushButton#nav { background: transparent; border: none; text-align: left;
  padding: 16px 12px; color: #c3d1e1; border-radius: 8px; font-size: 14px; }
QPushButton#nav:checked { background: #284664; color: white; font-weight: 600; }
QPushButton#nav:hover { background: #203c59; }
QLabel#title { font-size: 25px; font-weight: 700; color: #142e4b; }
QLabel#eyebrow { font-size: 11px; color: #4a8583; font-weight: 700; letter-spacing: 2px; }
QLabel#dialogTitle { font-size: 21px; font-weight: 700; }
QLabel#muted { color: #718297; }
QLabel#sectionTitle { font-weight: 600; font-size: 14px; }
QLabel#count { color: #326f70; font-weight: 600; }
QLabel#notice { background: #e9f2f5; border: 1px solid #d5e6ec; border-radius: 6px;
  padding: 9px 12px; color: #406479; }
QLabel#error { background: #fff1ed; color: #a43b31; border-radius: 6px; padding: 8px; }
QLabel#pathPreview { background: #e8eef6; border-radius: 6px; padding: 12px; }
QFrame#card { background: white; border: 1px solid #dfe6ef; border-radius: 8px; }
QLineEdit, QComboBox { background: white; color: #19364d; border: 1px solid #cfd9e5;
  border-radius: 5px; min-height: 22px; padding: 5px 9px; selection-background-color: #cee7e5; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #328b87; }
QLineEdit:disabled, QComboBox:disabled { background: #f0f3f7; color: #8a98a9; }
QComboBox { padding-right: 25px; }
QComboBox::drop-down { width: 23px; border: none; }
QComboBox::down-arrow { image: url("{{ARROW}}"); width: 12px; height: 8px; }
QComboBox QAbstractItemView { background: white; color: #19364d; selection-background-color: #dcefed; }
QPushButton { background: white; color: #304d69; border: 1px solid #cbd7e4; border-radius: 5px;
  padding: 7px 13px; min-height: 19px; }
QPushButton:hover { background: #eef5f8; border-color: #94b5bc; }
QPushButton:pressed { background: #dcebe8; }
QPushButton:disabled { background: #f1f4f8; color: #a1adbc; border-color: #e1e7ef; }
QPushButton#primary { background: #187b76; color: white; border-color: #187b76; font-weight: 600; }
QPushButton#primary:hover { background: #126b67; }
QPushButton#primary:disabled { background: #b9cecd; border-color: #b9cecd; }
QPushButton#quiet { border-color: transparent; background: transparent; color: #53738b; }
QPushButton#quiet:hover { background: #eff5f7; }
QTableView { background: white; alternate-background-color: #f8fafc; border: none;
  selection-background-color: #dcefed; selection-color: #113c46; gridline-color: #edf1f6; }
QTableView::item { padding: 5px 10px; border-bottom: 1px solid #edf1f6; }
QHeaderView::section { background: #f0f4f9; color: #526b84; border: none;
  border-right: 1px solid #e5ebf3; border-bottom: 1px solid #dce5ef; padding: 10px 10px; font-weight: 600; }
QTableCornerButton::section { background: #f0f4f9; border: none; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QStatusBar { background: #eaf0f6; color: #6a7e94; border-top: 1px solid #dce5ef; }
QStatusBar::item { border: none; }
QProgressBar { border: none; background: #e3eeed; max-height: 4px; min-height: 4px; }
QProgressBar::chunk { background: #298e87; }
QListWidget { background: white; border: 1px solid #dfe6ef; border-radius: 5px; padding: 6px; }
QListWidget::item { padding: 7px; }
QToolTip { background: #18334f; color: white; border: none; padding: 7px; }
""".replace("{{ARROW}}", (Path(__file__).parent / "assets" / "chevron-down.svg").as_posix())
