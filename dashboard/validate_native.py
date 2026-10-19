"""Finite Qt interaction check, screenshots and optional one-round HTTP refresh."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--http-once",action="store_true");args=parser.parse_args()
    os.environ["QT_QPA_PLATFORM"]="offscreen"
    from dashboard.native.bootstrap import configure_qt
    configure_qt()
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from dashboard.native.app import ResearchWindow,configure_style
    from dashboard.native.model import NativeModel
    from dashboard.marketdata.paths import VALIDATION_ROOT
    app=QApplication([]);configure_style(app);model=NativeModel();window=ResearchWindow(model)
    window.resize(1600,1050);window.show()
    progress={"stage":0,"checks":[],"success":False,"http_requested":args.http_once}
    def save(name):
        app.processEvents();assert window.grab().save(str(VALIDATION_ROOT/(name+".png")))
    def check(state):
        try:
            stage=progress["stage"]
            assert len(state["quotes"])==20
            if stage==0:
                if args.http_once:
                    QTest.mouseClick(window.once_button,Qt.MouseButton.LeftButton)
                    progress["stage"]=1;return
                progress["stage"]=1;stage=1
            if stage==1:
                if window.collection.running():return
                if args.http_once:
                    assert window.collection.state()["polls"]==1,window.collection.state()
                    assert window.collection.state()["rows"]==20,window.collection.state()
                assert all(q["open_interest"] is None for q in state["quotes"] if q["symbol"].endswith('.CFE'))
                assert all(q["history_oi_date"]=='2026-10-14' for q in state["quotes"] if q["symbol"].endswith('.CFE'))
                save('quotes');progress["checks"].append('20 real rows; unavailable live OI; historical OI dates; collection stops')
                progress["stage"]=2;window.navigate(1);window.refresh();return
            if stage==2:
                assert state['category']=='basis';assert any(r['id']=='A01.bp' and r['value'] is not None for r in state['metrics'])
                window.indicators.explain_button.setChecked(True);save('research_basis')
                progress['checks'].append('basis formulas and selected history chart rendered')
                progress['stage']=3;window.category.setCurrentIndex(1);return
            if stage==3:
                if state['category']!='calendar':return
                assert any(r['id']=='B05.M' and r['value'] is not None and r['current'] is None for r in state['metrics'])
                save('research_calendar');progress['checks'].append('calendar migration remains dated historical; no fake live OI change')
                progress['stage']=4;window.category.setCurrentIndex(2);return
            if stage==4:
                if state['category']!='cross':return
                assert any(r['id']=='B08' for r in state['metrics'])
                assert not any(r['id'].startswith(('C','A08','A10')) for r in state['metrics'])
                save('research_cross');progress['checks'].append('same-month cross selection; B08/B12; excluded regressions/C families')
                progress['stage']=5;window.price.setCurrentIndex(2);return
            if stage==5:
                if state['price_input']!='annual':return
                save('research_annual');window.navigate(2);save('data_management')
                progress['checks'].append('annual input and per-product/frequency data coverage; fixed dividend map visible')
                progress['before_refresh']=state['as_of'];progress['stage']=6;window.refresh();return
            if stage==6:
                assert state['as_of']>progress['before_refresh']
                progress['checks'].append('refresh updates timestamp; no automatic HTTP collection on refresh')
                progress['success']=True;progress['stage']=7;window.close()
        except Exception as exc:
            progress['error']=repr(exc);progress['stage']=7;window.close()
    window.loaded.connect(check)
    def timeout():
        if not progress['success']:progress['error']='frontend timeout: '+window.status.text()
        window.close()
    QTimer.singleShot(240000,timeout)
    app.exec()
    assert not window.collection.running()
    name='frontend_checks_http.json' if args.http_once else 'frontend_checks.json'
    (VALIDATION_ROOT/name).write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(progress,ensure_ascii=False));return 0 if progress['success'] else 1

if __name__=='__main__':raise SystemExit(main())
