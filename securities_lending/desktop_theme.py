STYLE = """
QWidget { font-family: 'Microsoft YaHei', 'Segoe UI'; font-size: 12px; color: #263d4a; }
QMainWindow, QDialog { background: #f2f5f7; }
QLabel#brand { color: #173f50; font-size: 22px; font-weight: 700; letter-spacing: 1px; }
QLabel#title { color: #263d4a; font-size: 17px; font-weight: 600; margin-right: 12px; }
QLabel#muted { color: #687c89; font-size: 11px; }
QLabel#mode, QLabel#badge { background: #e8eef3; color: #3f6176; border-radius: 4px; padding: 5px 9px; }
QLabel#badge[tone="ok"] { background: #e5f3eb; color: #22664e; }
QLabel#badge[tone="warning"], QLabel#mode[tone="warning"] { background: #fff1d6; color: #88540a; }
QLabel#badge[tone="error"] { background: #fbe6e2; color: #a13329; }
QLabel#notice { background: #fff1dc; color: #8b5818; padding: 6px 10px; border-radius: 4px; }
QLabel#error { color: #a13329; }
QLabel#section { font-weight: 600; }
QLabel#metric { color: #22495c; font-size: 17px; font-weight: 600; }
QPushButton { background: #ffffff; border: 1px solid #cbd6de; border-radius: 4px; padding: 6px 11px; min-height: 20px; }
QPushButton:hover { background: #eaf1f6; border-color: #90acbd; }
QPushButton:focus { border: 1px solid #27799d; }
QPushButton:checked { background: #dbeaf3; color: #174c68; }
QPushButton:disabled { color: #94a3ae; background: #f0f3f5; border-color: #dce3e8; }
QPushButton#primary { background: #205e7a; color: #ffffff; border-color: #205e7a; font-weight: 600; }
QPushButton#primary:hover { background: #16475e; }
QPushButton#primary:disabled { background: #9bacb7; border-color: #9bacb7; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: #ffffff; border: 1px solid #cbd6de; border-radius: 3px; padding: 6px; selection-background-color: #c4deee; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #287fa5; }
QLineEdit#target { background: #fff8e5; color: #5c4616; border: 1px solid #dfd4ad; border-radius: 2px; padding: 4px 9px; margin: 7px 6px; }
QLineEdit#target:focus { background: #fff0bf; border-color: #a98228; }
QTableWidget { border: 1px solid #d1dce3; background: #ffffff; alternate-background-color: #f6f9fb; gridline-color: #e4eaef; selection-background-color: #e0edf5; selection-color: #173f50; }
QHeaderView::section { background: #e7eef3; border: none; border-right: 1px solid #d5e0e7; border-bottom: 1px solid #c6d6e0; padding: 6px; color: #425f70; font-size: 11px; font-weight: 600; }
QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid #e6edf2; }
QTableWidget::item:selected { background: #deedf6; }
QTabWidget::pane { border: 1px solid #d4dfe6; background: #ffffff; }
QTabBar::tab { padding: 9px 15px; color: #637c8b; }
QTabBar::tab:selected { color: #1e5873; background: #e2eef5; }
QScrollArea { border: none; background: transparent; }
QCheckBox { spacing: 8px; }
QStatusBar { background: #e8eef2; color: #607989; font-size: 11px; }
QToolTip { background: #ffffff; color: #263d4a; border: 1px solid #b8cbd7; padding: 6px; }
QProgressBar { border: none; background: #d9e4eb; max-height: 4px; }
QProgressBar::chunk { background: #287b9e; }
"""
