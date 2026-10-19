"""The supported dashboard entry: current research UI, live quotes and history maintenance."""
import argparse
import logging
import os
from pathlib import Path
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(description='Delta1 股指看板与历史维护')
    parser.add_argument('--local-root',type=Path)
    parser.add_argument('--no-realtime',action='store_true',help='启动后暂不采集实时行情')
    parser.add_argument('--capture',type=Path,help='离屏截图后退出')
    parser.add_argument('--capture-page',type=int,choices=range(4),default=0)
    parser.add_argument('--startup-check',action='store_true')
    args=parser.parse_args(argv)
    log_root=Path(__file__).parent/'runtime/startup';log_root.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger('delta1.current.startup');logger.setLevel(logging.INFO)
    handler=logging.FileHandler(log_root/f'native_{os.getpid()}.log',encoding='utf8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));logger.addHandler(handler)
    if args.capture:os.environ['QT_QPA_PLATFORM']='offscreen'
    from .native.bootstrap import configure_qt
    configure_qt()
    from PySide6.QtCore import QTimer, QLockFile
    from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
    from .native.model import NativeModel
    from .native.app import ResearchWindow,configure_style
    from .native.branding import app_icon,configure_windows_identity
    from .native.startup import start_instance,bind_activation,activate_window
    model=NativeModel(args.local_root);model.config['dashboard_mode']='nonregression'
    logger.info('Settings root: %s',model.local_root)
    if args.capture or args.startup_check:model.config['history_maintenance_enabled']=False
    configure_windows_identity('research')
    app=QApplication(sys.argv[:1]);app.setApplicationName('Delta1 股指看板');app.setWindowIcon(app_icon());configure_style(app)
    app.setQuitOnLastWindowClosed(False)
    owner=QLockFile(str(model.local_root/'dashboard-session.lock'))
    owner.setStaleLockTime(0)
    owned=bool(args.capture or args.startup_check or owner.tryLock(0))
    instance=start_instance(model.local_root,edition='research',enabled=not args.capture,logger=logger)
    if instance.forwarded:
        model.close();logger.removeHandler(handler);handler.close();return 0
    if not owned:
        if instance.server:instance.server.close()
        QMessageBox.information(None,'Delta1','已有启动向导或看板正在运行。请使用已有窗口；不会重复采集。')
        model.close();logger.removeHandler(handler);handler.close();return 0
    verified=False
    if not args.capture and not args.startup_check:
        from .native.launch_wizard import LaunchWizard
        wizard=LaunchWizard(model)
        if instance.server:bind_activation(instance.server,wizard,logger=logger)
        logger.info('Startup wizard ready; collectors remain stopped')
        accepted=wizard.exec()==QDialog.DialogCode.Accepted
        if instance.server:instance.server.newConnection.disconnect()
        verified=accepted and wizard.realtime
        wizard.deleteLater()
        if not accepted:
            if instance.server:instance.server.close()
            model.close();owner.unlock();logger.removeHandler(handler);handler.close();return 0
    model.realtime_verified=verified
    window=ResearchWindow(model);window.setWindowTitle('Delta1 · 股指看板与数据维护')
    app.setQuitOnLastWindowClosed(True)
    if instance.server:bind_activation(instance.server,window,logger=logger)
    ready_once=False;saved=False
    def ready(state):
        nonlocal ready_once,saved
        if ready_once:return
        ready_once=True
        logger.info('First frame ready')
        if args.capture:
            window.navigate(args.capture_page)
            def capture():
                nonlocal saved
                from .marketdata.history_publication import maintenance_root
                if hasattr(window,'history_maintenance'):
                    if model.config.get('history_roots'):window.history_maintenance.root=maintenance_root(model.config['history_roots'])
                    window.maintenance_page.refresh()
                args.capture.parent.mkdir(parents=True,exist_ok=True);saved=window.grab().save(str(args.capture));window.close()
            QTimer.singleShot(300,capture)
        elif args.startup_check:QTimer.singleShot(0,window.close)
        elif verified and not args.no_realtime:QTimer.singleShot(0,lambda:window.start_collection(False))
    window.loaded.connect(ready);window.show()
    if not args.capture:QTimer.singleShot(0,lambda:activate_window(window))
    if args.capture or args.startup_check:QTimer.singleShot(90000,window.close)
    result=app.exec()
    if instance.server:instance.server.close()
    if owned:owner.unlock()
    logger.removeHandler(handler);handler.close()
    return result if ready_once and (not args.capture or saved) else 1


if __name__=='__main__':raise SystemExit(main())
