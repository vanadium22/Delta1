"""Supported App entry. The main window owns all progress and settings."""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main(argv=None,*,window_class=None,title='Delta1 · 股指看板',icon=None,frozen=False,public=False):
    started=time.monotonic();origin=started;startup=dict(clock_scope='app_main')
    try:
        candidate=float(os.environ.get('DELTA1_PROCESS_STARTED_MONOTONIC',''))
        if 0<candidate<=started:
            origin=candidate;startup.update(clock_scope='shared_interpreter_start',
                preflight_seconds=float(os.environ['DELTA1_PREFLIGHT_SECONDS']))
    except (ValueError,KeyError):pass
    startup['app_main_seconds']=round(started-origin,6)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path)
    parser.add_argument('--no-realtime',action='store_true',help='只读缓存，不运行任何网络或维护任务')
    parser.add_argument('--capture',type=Path)
    parser.add_argument('--capture-page',type=int,default=0)
    parser.add_argument('--startup-check',action='store_true')
    parser.add_argument('--first-setup',action='store_true',help='打开本机账号配置')
    parser.add_argument('--download-dividends',action='store_true',help='从公盘补收分红 Excel')
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
    model.startup_timing=startup
    model.realtime_verified=False
    instance=None
    handover_started=time.monotonic()
    profile=model.config.get('history_connection_file')
    first_launch=os.environ.get('DELTA1_PORTABLE')=='1' and not (profile and Path(profile).is_file())
    if first_launch:
        package=Path(__file__).resolve().parents[1]/'PACKAGE-MANIFEST.json'
        try:
            from datetime import date
            coverage=json.loads(package.read_text(encoding='utf8'))['history']
            model.portable_history_day=min(date.fromisoformat(row['frequencies']['1d']['last'])
                                           for row in coverage).isoformat()
        except (OSError,ValueError,KeyError,TypeError):
            pass
    readonly=quiet or args.no_realtime or frozen or args.first_setup or args.download_dividends or first_launch
    if not readonly:
        from .app_instance import InstanceLease
        instance=InstanceLease(Path(__file__).parent/'runtime',model.config,model.local_root)
        instance.acquire()
    startup['handover_seconds']=round(time.monotonic()-handover_started,6)
    window=(window_class or ResearchWindow)(model);window.setWindowTitle(title)
    window.instance_lease=instance
    if icon:window.setWindowIcon(icon())
    pipeline=window.pipeline=DataPipeline(window,enabled=not readonly and (instance is None or instance.owned))
    if getattr(window,'query_page',None) is not None and not pipeline.enabled:window.query_page.set_readonly()
    close_timer=QTimer(window);close_timer.setInterval(200)
    def check_replacement():
        if instance is not None and instance.stop_requested():
            close_timer.stop();window.close()
    close_timer.timeout.connect(check_replacement)
    if instance is not None:close_timer.start()
    window.pipeline_page=PipelinePage(pipeline);window.pages.addTab(window.pipeline_page,'数据更新 / 设置')
    if (args.first_setup or args.download_dividends) and not frozen:
        window.pages.setCurrentWidget(window.pipeline_page)
        window.pipeline_page.settings.accounts.setVisible(args.first_setup)
    if args.download_dividends and not (quiet or frozen):
        QTimer.singleShot(0,pipeline.refresh_dividends)
    if getattr(model,'portable_history_day',None) and not (args.first_setup or args.download_dividends):
        window.pipeline_page.settings.notice.setText('首次启动先显示随包历史。配置本人账号后，可补齐收盘或更新报价。')
    compact=hasattr(window,'update_overview_status')
    window.pipeline_note=window.status if compact else QLabel()
    if not compact:
        window.pipeline_note.setWordWrap(True);window.centralWidget().layout().insertWidget(1,window.pipeline_note)
    def pipeline_note():
        if compact:window.update_overview_status();return
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
        startup['first_result_seconds']=round(time.monotonic()-origin,6)
        pipeline.write_report()
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
    startup['window_shown_seconds']=round(time.monotonic()-origin,6)
    if quiet:QTimer.singleShot(180000,window.close)
    try:result=app.exec()
    finally:
        close_timer.stop()
        if instance is not None:instance.close()
    return result if ready and (not args.capture or saved) else 1


if __name__=='__main__':raise SystemExit(main())
