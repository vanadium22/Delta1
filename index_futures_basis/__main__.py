"""Native desktop entry, optional offline CLI exports and diagnostics."""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path
import sys

from .config import ROOT


def main():
    parser = argparse.ArgumentParser(description="Delta1 股指基差工作台")
    parser.add_argument("--demo", action="store_true", help="独立合成演示，不访问 Wind")
    parser.add_argument("--mode", choices=["wind", "offline", "demo"], default="wind")
    parser.add_argument("--import-snapshot", type=Path, help="导入 JSON/CSV 并切换离线模式")
    parser.add_argument("--export", choices=["report", "figures", "data"], help="导出后退出；正式Word先更新校验，图片/CSV只读本地")
    parser.add_argument("--as-of", help="指定报告截止日；缺失部分留空，不自动改写指定日期")
    parser.add_argument("--local-only", action="store_true", help="导出仅用本地缓存，不等待Wind；缺数据也尽力生成")
    parser.add_argument("--sync", action="store_true", help="检查并补齐 Wind 行情后退出")
    parser.add_argument("--diagnose", action="store_true", help="只检查当前解释器依赖，不调用 Wind")
    parser.add_argument("--capture", type=Path, help="演示/离线窗口截图后退出")
    parser.add_argument("--startup-check", action="store_true")
    args = parser.parse_args()
    if args.diagnose:
        print(json.dumps({"python": sys.executable, "libraries": {name: bool(importlib.util.find_spec(name))
            for name in ["PySide6", "pandas", "numpy", "matplotlib", "docx", "openpyxl", "WindPy"]}}, indent=2))
        return 0
    from .service import BasisService
    mode = "demo" if args.demo else "offline" if args.import_snapshot else args.mode
    service = BasisService(mode=mode)
    if args.import_snapshot:
        print(service.import_snapshot(args.import_snapshot))
    if args.sync:
        outcome = service.sync(print)
        print(outcome)
        return 0 if outcome["state"] == "complete" else 2
    elif args.export:
        print(service.export(args.export, as_of=args.as_of, progress=print, refresh=not args.local_only))
    else:
        if (args.capture or args.startup_check) and mode == "wind":
            raise ValueError("截图/启动检查请使用 --demo 或 --mode offline，避免意外访问 Wind")
        from .desktop import launch
        return launch(service, args.capture, args.startup_check)
    return 0


def run():
    try:
        return main()
    except Exception as exc:
        log = ROOT / "data/startup.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=log, encoding="utf-8", level=logging.ERROR, force=True)
        logging.exception("Basis App failed; Python=%s", sys.executable)
        if sys.platform == "win32" and sys.stderr is None:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动失败：{exc}\n详细日志：{log}\n缺少依赖时运行 install.cmd。", "股指基差工作台", 0x10)
        else:
            print(f"运行失败：{exc}；日志：{log}", file=sys.stderr)
        return 1


raise SystemExit(run())
