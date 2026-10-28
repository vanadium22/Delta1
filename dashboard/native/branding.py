"""Shared identity for the native window, taskbar, and Windows shortcuts."""
from pathlib import Path
import sys

ICON_PATH = Path(__file__).resolve().parents[1] / "assets" / "company_overview.ico"
APP_ID = "Delta1.IndexDashboard.Native"


def configure_windows_identity(edition="developer"):
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID+"."+edition)
        except (AttributeError, OSError):
            # Branding is optional; it must never prevent the dashboard opening.
            pass


def app_icon():
    from PySide6.QtGui import QIcon
    return QIcon(str(ICON_PATH))
