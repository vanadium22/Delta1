from pathlib import Path
import os
import sys


def configure_qt():
    dependencies=Path(__file__).resolve().parents[2]/".deps"/"dashboard_native"
    if dependencies.is_dir():
        sys.path.insert(0,str(dependencies))
    os.environ.setdefault("PYQTGRAPH_QT_LIB","PySide6")
