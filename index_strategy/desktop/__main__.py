"""Console and pythonw entry point; keep startup failures visible."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Delta1 原生桌面应用：数据下载与实时采集")
    parser.parse_args()
    log_path = Path(__file__).resolve().parents[2] / "localsetting/desktop_error.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=log_path, encoding="utf-8", level=logging.WARNING,
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.WARNING)
        from .app import Delta1App
        app = Delta1App()
        app.mainloop()
    except Exception as exc:
        logging.exception("Desktop startup failed")
        detail = f"{type(exc).__name__}: {exc}\n\n错误日志：{log_path}"
        if isinstance(exc, ModuleNotFoundError):
            detail += "\n\n请先在 swhy_delta1 环境安装 index_strategy/env/requirements.txt 中的依赖。"
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("Delta1 启动失败", detail, parent=root)
            root.destroy()
        except Exception:
            if sys.stderr is not None:
                print(detail, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
