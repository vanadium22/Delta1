"""Native App entry point; record errors even when launched using pythonw."""
import logging
import sys
from .config import ROOT


def run():
    try:
        from .desktop import main
        return main()
    except Exception:
        log = ROOT / "data" / "startup.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=log, encoding="utf-8", level=logging.ERROR, force=True)
        logging.exception("Native App failed; Python=%s", sys.executable)
        if sys.platform == "win32" and sys.stderr is None:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"App 启动失败。请先运行 install.cmd。\n详细日志：{log}\nPython：{sys.executable}", "Delta1 券源工作台", 0x10)
        else:
            import traceback
            traceback.print_exc()
        return 1


raise SystemExit(run())
