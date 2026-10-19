"""Start Delta1 market dashboard."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys

from .bootstrap import configure_qt
from .branding import app_icon, configure_windows_identity
from .startup import activate_window, bind_activation, start_instance


def main(argv=None):
    parser = argparse.ArgumentParser(description="Delta1 市场看板")
    parser.add_argument("--demo", action="store_true", help="显示合成示例数据")
    parser.add_argument("--publish-root", help="市场数据快照目录；也可设置 DELTA1_DATA_ROOT")
    parser.add_argument("--local-root", help="本机运行目录")
    parser.add_argument("--capture", help="保存窗口 PNG 后退出")
    parser.add_argument("--capture-page", type=int, default=0, choices=range(3))
    parser.add_argument("--capture-width", type=int, default=1600)
    parser.add_argument("--capture-height", type=int, default=1050)
    parser.add_argument("--no-single-instance", action="store_true")
    parser.add_argument("--startup-check", action="store_true")
    args = parser.parse_args(argv)
    log_root = Path(args.local_root or Path(__file__).resolve().parents[1] / "runtime")
    log_root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("delta1.startup")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_root / "startup.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        return run(args, logger)
    except Exception:
        logger.exception("Application startup failed")
        print(f"启动失败，详情见 {log_root / 'startup.log'}", file=sys.stderr)
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()


def run(args, logger):
    if args.capture:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    configure_qt()
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from .public_app import Window, configure_style
        from .publication import ViewerModel, DEFAULT_PUBLISH_ROOT
    except ImportError as exc:
        print("请先运行 python -m pip install -r requirements.txt。", exc, file=sys.stderr)
        return 1
    bundled_demo = Path(__file__).resolve().parents[1] / "data"
    publish_root = args.publish_root or os.environ.get("DELTA1_DATA_ROOT") or os.environ.get("SWHY_DELTA1_PUBLISH_ROOT")
    if not publish_root:
        publish_root = bundled_demo if args.demo and (bundled_demo / "demo.json").is_file() else DEFAULT_PUBLISH_ROOT
    model = ViewerModel(publish_root=publish_root, local_root=args.local_root)
    configure_windows_identity("market")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Delta1 市场看板")
    app.setWindowIcon(app_icon())
    instance = start_instance(model.publish_root, edition="market", demo=args.demo,
                              enabled=not args.capture and not args.no_single_instance, logger=logger)
    if instance.forwarded:
        model.close()
        return 0
    configure_style(app)
    window = Window(model, demo=args.demo)
    if args.capture:
        window.resize(max(1120, args.capture_width), max(740, args.capture_height))
    if instance.server:
        bind_activation(instance.server, window, logger=logger)
    finished = {"ready": False}
    def ready(state):
        logger.info("First frame ready; synthetic=%s", state["demo"])
        if args.capture:
            if finished["ready"]:
                return
            finished["ready"] = True
            window.navigate(args.capture_page)
            def save():
                if window.busy:
                    QTimer.singleShot(100, save)
                    return
                path = Path(args.capture).resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(path)):
                    raise RuntimeError("PNG 保存失败")
                print(json.dumps({"capture": str(path), "module": args.capture_page,
                                  "synthetic": bool(state["demo"])}, ensure_ascii=False))
                window.close()
                app.quit()
            QTimer.singleShot(350, save)
        elif args.startup_check:
            finished["ready"] = True
            QTimer.singleShot(0, window.close)
    window.loaded.connect(ready)
    if args.startup_check or args.capture:
        QTimer.singleShot(20000, window.close)
    window.show()
    if not args.capture:
        QTimer.singleShot(0, lambda: activate_window(window))
    result = app.exec()
    if instance.server:
        instance.server.close()
    if args.capture and not Path(args.capture).is_file():
        return 1
    if args.startup_check and not finished["ready"]:
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
