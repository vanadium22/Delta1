"""Supported App entry. The main window owns all progress and settings."""
import argparse
import os
from pathlib import Path
import sys


def main(argv=None,*,window_class=None,title='Delta1 · 股指看板',icon=None,frozen=False,public=False):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path)
    parser.add_argument('--no-realtime',action='store_true',help='只读缓存，不运行任何网络或维护任务')
    parser.add_argument('--capture',type=Path)
    parser.add_argument('--capture-page',type=int,default=0)
    parser.add_argument('--startup-check',action='store_true')
    args=parser.parse_args(argv)
    quiet=bool(args.capture or args.startup_check)
    if quiet:os.environ['QT_QPA_PLATFORM']='offscreen'
    from .native.bootstrap import configure_qt
    configure_qt()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QLabel
    from .app_config import prepare_config
    from .native.model import NativeModel
    from .native.app import ResearchWindow,configure_style
    from .native.data_pipeline import DataPipeline,PipelinePage
    from .native.branding import configure_windows_identity
    app=QApplication(sys.argv[:1]);configure_style(app);configure_windows_identity('presentation' if public else 'development')
    model=NativeModel(prepare_config(args.local_root));model.config['dashboard_mode']='nonregression'
    model.realtime_verified=False
    instance=None
    if not (quiet or args.no_realtime or frozen):
        from .app_instance import InstanceLease
        instance=InstanceLease(Path(__file__).parent/'runtime',model.config,model.local_root)
        instance.acquire()
    window=(window_class or ResearchWindow)(model);window.setWindowTitle(title)
    window.instance_lease=instance
    if icon:window.setWindowIcon(icon())
    pipeline=window.pipeline=DataPipeline(window,enabled=not (quiet or args.no_realtime or frozen) and (instance is None or instance.owned))
    close_timer=QTimer(window);close_timer.setInterval(200)
    def check_replacement():
        if instance is not None and instance.stop_requested():
            close_timer.stop();window.close()
    close_timer.timeout.connect(check_replacement)
    if instance is not None:close_timer.start()
    window.pipeline_page=PipelinePage(pipeline);window.pages.addTab(window.pipeline_page,'数据更新 / 设置 / 诊断')
    window.pipeline_note=QLabel();window.pipeline_note.setWordWrap(True)
    window.centralWidget().layout().insertWidget(1,window.pipeline_note)
    def pipeline_note():
        trace=getattr(window,'applied_trace',{});calc=getattr(model,'refresh_trace',{});elapsed=''
        if window.busy and calc.get('calculation_started_monotonic'):
            import time
            elapsed=f" · 计算中 {time.monotonic()-calc['calculation_started_monotonic']:.1f}秒"
        window.pipeline_note.setText(pipeline.message+elapsed+
            (f" · 已显示行情序号 {trace.get('realtime_sequence',0)} · 计算 {trace.get('calculation_seconds',0):.2f}秒" if trace else ' · 已有数据正在后台读取'))
    pipeline.changed.connect(pipeline_note)
    ready=False;saved=False
    def loaded(state):
        nonlocal ready,saved
        if ready:return
        ready=True
        if args.capture:
            (window.timer if hasattr(window,'timer') else window.refresh_timer).stop()
            window.pending=False
            window.navigate(args.capture_page)
            def capture():
                nonlocal saved
                active_page=window.pages.currentWidget()
                if window.busy or window.pending or getattr(active_page,'busy',False):
                    QTimer.singleShot(100,capture);return
                args.capture.parent.mkdir(parents=True,exist_ok=True)
                saved=window.grab().save(str(args.capture));window.close()
            QTimer.singleShot(600,capture)
        elif args.startup_check:QTimer.singleShot(0,window.close)
    window.loaded.connect(loaded)
    window.show()
    if quiet:QTimer.singleShot(180000,window.close)
    try:result=app.exec()
    finally:
        close_timer.stop()
        if instance is not None:instance.close()
    return result if ready and (not args.capture or saved) else 1


if __name__=='__main__':raise SystemExit(main())
