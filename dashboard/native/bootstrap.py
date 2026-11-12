from pathlib import Path
import os
import sys


def configure_qt():
    root=Path(__file__).resolve().parents[2]
    dependencies=root/".deps"/"dashboard_native"
    if dependencies.is_dir():
        sys.path.insert(0,str(dependencies))
    from dashboard.python_environment import active_overlay
    overlay=active_overlay(root)
    if overlay is not None:
        if str(overlay) not in sys.path:sys.path.insert(0,str(overlay))
        paths=os.environ.get('PYTHONPATH','').split(os.pathsep) if os.environ.get('PYTHONPATH') else []
        if str(overlay) not in paths:os.environ['PYTHONPATH']=os.pathsep.join([str(overlay),*paths])
        os.environ['DELTA1_APP_PYTHON']=sys.executable;os.environ['DELTA1_APP_OVERLAY']=str(overlay)
    os.environ.setdefault("PYQTGRAPH_QT_LIB","PySide6")
