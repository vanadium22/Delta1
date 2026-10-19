"""Bounded UI check: annual continuous slots, local data only, no Z access."""
import os
from pathlib import Path
import sys


def main():
    os.environ['QT_QPA_PLATFORM']='offscreen'
    def deny_z(event,args):
        if event=='open' and args and str(args[0]).upper().startswith('Z:'):
            raise AssertionError('Runtime dashboard must not read Z:')
    sys.addaudithook(deny_z)
    from dashboard.native.bootstrap import configure_qt
    configure_qt()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from dashboard.native.app import ResearchWindow,configure_style
    from dashboard.native.model import NativeModel
    app=QApplication([]);configure_style(app)
    model=NativeModel();window=ResearchWindow(model);window.resize(1600,1050)
    done={'started':False,'saved':False}
    output=Path(__file__).resolve().parent/'runtime/history_backfill_annual.png'
    def loaded(state):
        if not done['started']:
            done['started']=True
            window.quotes.distribution.setCurrentIndex(window.quotes.distribution.findData('annual'))
            window.quotes.month.setCurrentIndex(window.quotes.month.findData(3))
            window.start_collection(False)
            return
        if done['saved'] or state['selection']['overview_slot']!=3:return
        if not all(r['chart']['unit']=='%' and r['chart']['kind']=='盘中观测' for r in state['overview']):return
        assert all(w['available'] for r in state['overview'] for w in r['chart']['rows'])
        assert all(r['dividend_inherited_from']==r['root']+'2703.CFE' for r in state['overview'])
        def save():
            app.processEvents()
            assert window.grab().save(str(output))
            done['saved']=True;window.close();app.quit()
        QTimer.singleShot(100,save)
    window.loaded.connect(loaded)
    QTimer.singleShot(90000,lambda:(window.close(),app.quit()))
    window.show();app.exec()
    assert done['saved'],'UI validation timed out'
    print(str(output))


if __name__=='__main__':main()
