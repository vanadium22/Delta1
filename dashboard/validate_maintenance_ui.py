"""Bounded offscreen Qt check of the real maintenance page and live collector."""
import json
import os
from pathlib import Path
import sys
import time


def main():
    os.environ['QT_QPA_PLATFORM']='offscreen'
    def guard(event,args):
        if event=='open' and args and str(args[0]).upper().startswith('Z:'):
            raise AssertionError('UI attempted Z drive I/O')
    sys.addaudithook(guard)
    from dashboard.native.bootstrap import configure_qt
    configure_qt()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from dashboard.native.app import ResearchWindow,configure_style
    from dashboard.native.model import NativeModel
    app=QApplication([]);configure_style(app)
    root=Path(__file__).resolve().parent
    local=root/'runtime/maintenance_ui_settings';local.mkdir(parents=True,exist_ok=True)
    config=json.loads((root/'localsetting/native.json').read_text(encoding='utf8'))
    config['realtime_root']=str(root/'runtime/maintenance_ui_realtime')
    (local/'native.json').write_text(json.dumps(config,ensure_ascii=False),encoding='utf8')
    model=NativeModel(local);window=ResearchWindow(model);window.resize(1600,1050)
    output=Path(__file__).resolve().parent/'runtime/history_maintenance.png'
    results={'started':False,'saved':False,'heartbeats':0};beats=[]
    heartbeat=QTimer();heartbeat.setInterval(100)
    def beat():results['heartbeats']+=1;beats.append(time.monotonic())
    heartbeat.timeout.connect(beat);heartbeat.start()
    def loaded(state):
        if results['started']:return
        results['started']=True
        window.start_collection(False);window.pages.setCurrentIndex(3)
        QTimer.singleShot(15000,capture)
    def capture():
        window.maintenance_page.refresh();app.processEvents()
        page=window.maintenance_page
        page.turn_page(1)
        assert page.page==1
        page.filter.setText('IF2703')
        assert page.gaps.rowCount() and all('IF2703' in page.gaps.item(i,0).text() for i in range(page.gaps.rowCount()))
        page.filter.clear()
        results['collector']=window.collection.state()['status']
        results['polls']=window.collection.state()['polls']
        results['history']=window.history_maintenance.state().get('state')
        results['coverage_rows']=window.maintenance_page.coverage.rowCount()
        results['gap_rows']=window.maintenance_page.gaps.rowCount()
        results['max_ui_gap_seconds']=round(max((b-a for a,b in zip(beats,beats[1:])),default=0),3)
        results['saved']=window.grab().save(str(output))
        window.close()
    window.loaded.connect(loaded);window.show()
    QTimer.singleShot(90000,window.close)
    app.exec()
    (output.parent/'history_maintenance_ui.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    assert results['saved'] and results['coverage_rows'] and results['gap_rows'],results
    assert results['polls']>=2,results
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':main()
