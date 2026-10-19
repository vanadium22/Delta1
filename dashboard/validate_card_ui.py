"""Bounded, network-denied Qt card interaction check using existing local data."""
import json
import os
import socket
import traceback


def main():
    os.environ['QT_QPA_PLATFORM']='offscreen'
    attempts=[]
    def denied(*args,**kwargs):
        attempts.append(str(args[:1]));raise AssertionError('Network is forbidden in the offline card check')
    socket.socket.connect=denied;socket.create_connection=denied;socket.getaddrinfo=denied
    from dashboard.native.bootstrap import configure_qt
    configure_qt()
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QTableWidget,QPushButton
    from dashboard.native.app import ResearchWindow,configure_style
    from dashboard.native.model import NativeModel
    from dashboard.marketdata.paths import VALIDATION_ROOT
    output=VALIDATION_ROOT/'continuous_cards';output.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);configure_style(app);model=NativeModel();window=ResearchWindow(model)
    window.resize(1600,1050);window.show()
    progress=dict(stage=0,checks=[],success=False,network_attempts=attempts)
    def save(name):
        app.processEvents();assert window.grab().save(str(output/(name+'.png')))
    def select(combo,key):
        i=combo.findData(key);assert i>=0,(key,[combo.itemData(j) for j in range(combo.count())]);combo.setCurrentIndex(i)
    def check(state):
        try:
            stage=progress['stage'];assert len(state['overview'])==4;assert not attempts
            assert not window.collection.running();assert window.collection.state()['polls']==0
            if stage==0:
                assert len(state['quotes'])==20
                assert not window.quotes.findChildren(QTableWidget)
                assert all(r['current']['bp'] is None for r in state['overview'])
                assert all(r['chart']['kind']=='历史' for r in state['overview'])
                assert all(all(w['complete'] for w in r['chart']['rows']) for r in state['overview'])
                assert all(r['alias']==r['root']+'02.CFE' for r in state['overview'])
                save('overview');progress['checks'].append('four large quote cards; dated cache; no stale basis; continuous-slot quantile boxes')
                progress['stage']=1;select(window.quotes.distribution,'annual');return
            if stage==1:
                assert all(r['chart']['unit']=='%' for r in state['overview']);save('overview_annual')
                progress['stage']=2;select(window.quotes.month,0);return
            if stage==2:
                if state['selection']['overview_month']!='2610':return
                assert all(r['current']['annual_pct'] is None for r in state['overview'])
                assert all(r['days']==0 for r in state['overview']);save('overview_expiry')
                progress['checks'].append('annual switch; expiry current hidden; historical marker retains its own date')
                window.navigate(1);save('research_cards')
                assert 'IF2612.CFE D=' in window.dividend_banner.toolTip()
                assert 'IF2610.CFE D=' not in window.dividend_banner.toolTip()
                assert 'A03.percentile' not in window.indicators.cards
                assert 'A01' not in window.indicators.cards
                QTest.mouseClick(window.indicators.cards['A03.z'].open_button,Qt.MouseButton.LeftButton)
                assert window.indicators.stack.currentIndex()==1;assert len(window.indicators.plots)==4
                save('research_four_charts')
                window.indicators.detail_tabs.setCurrentIndex(1);save('research_formula')
                assert '前20个值' in window.indicators.details.toPlainText()
                window.indicators.details.verticalScrollBar().setValue(200)
                before=window.indicators.details.verticalScrollBar().value();window.indicators.draw_detail()
                assert window.indicators.details.verticalScrollBar().value()==before
                window.indicators.detail_tabs.setCurrentIndex(2);save('research_data_status')
                assert 'IF2612.CFE' in window.indicators.data_details.toPlainText()
                for key in window.indicators.groups:
                    window.indicators.open_group(key)
                    for i in range(window.indicators.submetric.count()):
                        window.indicators.submetric.setCurrentIndex(i)
                        assert '何时不可用' in window.indicators.details.toPlainText(),(key,i)
                window.indicators.open_group('A03.z');window.indicators.detail_tabs.setCurrentIndex(0)
                select(window.indicators.view,'overlay');assert len(window.indicators.plots)==1;save('research_overlay')
                select(window.indicators.view,'facets');select(window.indicators.window,20)
                QTest.mouseClick(window.indicators.back,Qt.MouseButton.LeftButton)
                progress['checks'].append('deduplicated indicator families; click drill-down; four charts; formula; overlay; window; back')
                progress['stage']=3;QTest.mouseClick(window.category_buttons.button(1),Qt.MouseButton.LeftButton);return
            if stage==3:
                if state['category']!='calendar':return
                assert len(state['entities'])==4
                assert all(any(r['id']=='B05.M' and r['current'] is None for r in e['metrics']) for e in state['entities'])
                window.indicators.open_group('B05');save('calendar_migration')
                window.indicators.detail_tabs.setCurrentIndex(1);save('calendar_formula')
                assert '迁移' in window.indicators.details.toPlainText()
                progress['checks'].append('calendar four fixed pairs; no fake live migration')
                progress['stage']=4;QTest.mouseClick(window.category_buttons.button(2),Qt.MouseButton.LeftButton);return
            if stage==4:
                if state['category']!='cross':return
                assert len(state['entities'])==6
                assert all(e['left'][2:]==e['right'][2:] for e in state['entities'])
                window.indicators.open_group('A06');assert len(window.indicators.plots)==6;save('cross_six_pairs')
                assert not window.price.model().item(0).isEnabled()
                progress['stage']=5;select(window.cross_pair,'IM/IC');return
            if stage==5:
                if len(state['entities'])!=1:return
                assert state['entities'][0]['left']=='IM2612.CFE'
                window.indicators.open_group('B08');save('cross_selected_pair')
                progress['checks'].append('six same-month cross pairs; pair filter; B08; raw cross-price input disabled')
                progress['stage']=6;select(window.price,'annual');return
            if stage==6:
                if state['price_input']!='annual':return
                save('research_annual');window.navigate(2);save('data_management')
                progress['checks'].append('annual input; separate data settings preserved')
                progress['stage']=7;select(window.quotes.month,3);return
            if stage==7:
                if state['selection']['overview_slot']!=3:return
                window.navigate(0);save('overview_far_slot')
                assert 'IF03' in window.quotes.cards['IF'].heading.text() and 'IF2703' in window.quotes.cards['IF'].heading.text()
                window.quotes.cards['IF'].detail_button.setChecked(True);save('continuous_mapping')
                assert 'IF2509.CFE' in window.quotes.cards['IF'].details.text() or 'IF2603.CFE' in window.quotes.cards['IF'].details.text()
                window.quotes.cards['IF'].detail_button.setChecked(False)
                window.resize(1180,800);save('overview_small_window')
                assert window.quotes.width()>1000
                assert all(c.value_columns==2 for c in window.quotes.cards.values())
                progress['before_refresh']=state['as_of'];progress['stage']=8
                button=next(b for b in window.findChildren(QPushButton) if b.text()=='刷新')
                QTest.mouseClick(button,Qt.MouseButton.LeftButton);return
            if stage==8:
                assert state['as_of']>progress['before_refresh'];assert not attempts
                progress['checks'].append('small-window scroll layout; explicit refresh; no network or background collector')
                progress['success']=True;window.close()
        except Exception:
            progress['error']=traceback.format_exc();save('failure');window.close()
    window.loaded.connect(check)
    def timeout():
        if not progress['success']:progress['error']='timeout: '+window.status.text()
        window.close()
    QTimer.singleShot(240000,timeout)
    app.exec()
    assert not window.collection.running()
    (output/'frontend_checks.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(progress,ensure_ascii=False));return 0 if progress['success'] else 1


if __name__=='__main__':raise SystemExit(main())
