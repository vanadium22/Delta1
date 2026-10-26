"""Offscreen layout and navigation checks; never contacts any real feed."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from dashboard.native.app import configure_style
from dashboard.native.editions_current import PresentationWindow, freeze_window
from dashboard.native.market_overview import quote_card, futures_values
from dashboard.native.overview_instruments import etfs
from dashboard.native.instruments import UNDERLYINGS
from dashboard.marketdata.overview_contributions import contributions
from dashboard.marketdata.overview_reference import ROOTS
from tests.test_market_overview import NOW, observation


APP=QApplication.instance() or QApplication([])
configure_style(APP)


def pump(seconds=.05):
    end=time.monotonic()+seconds
    while time.monotonic()<end:APP.processEvents();time.sleep(.002)


def state():
    live={s:observation() for s,_,_ in UNDERLYINGS.values()}
    indices=[quote_card(s,n,r,live,{},NOW,'2026-10-23') for r,(s,n,_) in UNDERLYINGS.items()]
    funds=[]
    for e in etfs({}):
        live[e['symbol']]=observation(4,4)
        row=quote_card(e['symbol'],e['name'],e['root'],live,{},NOW,'2026-10-23')
        row.update(iopv=None,premium_bp=None,iopv_source_at=None,premium_reason='未提供IOPV')
        funds.append(row)
    futures=[]
    for r,(_,n,_) in UNDERLYINGS.items():
        for slot,month in enumerate(('2611','2612','2703','2706')):
            s=r+month+'.CFE';live[s]=observation()
            row=quote_card(s,n,r,live,{},NOW,'2026-10-23');row['slot']=slot
            expiries={'2611':'2026-11-20','2612':'2026-12-18','2703':'2027-03-19','2706':'2027-06-18'}
            futures_values(row,live,{}, {s:dict(expiry_date=expiries[month])},NOW)
            futures.append(row)
    for row in [*indices,*funds,*futures]:
        row['series']=[dict(x=i,value=.1+i*.01,source_at=f'2026-10-26T10:00:0{i}+08:00',session='am') for i in range(3)]
    return dict(as_of=NOW.isoformat(),versions={},overview=[],entities=[],selection=dict(overview_slot=0),
                market_overview=dict(schema='market-overview-v1',indices=indices,etfs=funds,futures=futures,
                                     previous_session='2026-10-23',errors=[]))


class OverviewUiTests(unittest.TestCase):
    def window(self, payload=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        model=SimpleNamespace(local_root=Path(tmp.name),config={},close=Mock())
        p=patch('dashboard.native.market_overview.capture',return_value=state());p.start();self.addCleanup(p.stop)
        net=patch('requests.sessions.Session.request',side_effect=AssertionError('No real network in UI tests'))
        net.start();self.addCleanup(net.stop)
        cls=PresentationWindow
        if payload:
            class Frozen(PresentationWindow):frozen_payload=payload
            cls=Frozen
        w=cls(model);w.timer.stop();w.show();pump(.1)
        self.addCleanup(lambda:(w.close(),pump(.1)))
        return w

    def test_three_pages_resize_scroll_and_nonoverlapping_card_contents(self):
        w=self.window()
        for width,height in ((860,620),(1100,760),(1440,900),(1920,1080)):
            w.resize(width,height);pump()
            self.assertEqual(w.width(),width)
            for index,kind in enumerate(('indices','etfs','futures')):
                w.quotes.tabs.setCurrentIndex(index);pump()
                page=w.quotes.views[kind]
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(),0)
                for row in page.visible_rows:
                    c=page.cards[row['symbol']]
                    self.assertTrue(page.body.isAncestorOf(c))
                    self.assertFalse(c.isWindow())
                    position=c.mapTo(page.body,c.rect().topLeft())
                    self.assertLessEqual(position.x()+c.width(),page.body.width())
                    if kind=='futures':
                        widgets=[c.heading,c.price,c.basis_value,c.annual_value,c.rank_value,c.clock]
                    elif kind=='indices':widgets=[c.heading,c.price,c.clock]
                    else:widgets=[c.heading,c.price,c.iopv,c.scale,c.activity,c.clock]
                    rects=[x.geometry() if x.parent() is c and x.isVisible() else None for x in widgets]
                    for a,b in zip(rects,rects[1:]):
                        if a is not None and b is not None:self.assertLess(a.bottom(),b.top())
                page.scroll.verticalScrollBar().setValue(page.scroll.verticalScrollBar().maximum());pump()

    def test_future_filter_keeps_contract_identity_and_valid_zero(self):
        w=self.window();w.quotes.tabs.setCurrentIndex(2);pump()
        page=w.quotes.views['futures'];self.assertEqual(len(page.visible_rows),4)
        page.products['IC'].click();pump()
        self.assertEqual(len(page.visible_rows),4)
        self.assertTrue(all(r['symbol'].startswith('IC') for r in page.visible_rows))
        self.assertEqual([r['symbol'] for r in page.visible_rows],['IC2611.CFE','IC2612.CFE','IC2703.CFE','IC2706.CFE'])
        self.assertIn('+0.0点',page.cards['IC2612.CFE'].basis_value.text())
        self.assertEqual([p['days'] for p in page.curve_points],[25,53,144,235])
        self.assertTrue(all(p['symbol'].startswith('IC') for p in page.curve_points))
        self.assertFalse(page.empty_curve.isVisible())
        page.more.click();pump();self.assertEqual(page.volume_table.item(1,0).text(),'IC2612')
        page.render([],[],{});pump()
        self.assertEqual(page.curve_points,[]);self.assertTrue(page.empty_curve.isVisible())
        self.assertTrue(all(c.price.text()=='—' for c in page.contract_cards))
        self.assertEqual(page.volume_table.rowCount(),0)

    def test_freeze_preserves_new_overview_and_original_source_time(self):
        payload=freeze_window(state());self.assertIn('market_overview',payload['snapshots'][0])
        w=self.window(payload)
        self.assertEqual(w.quotes.state['market_overview']['indices'][0]['source_at'],NOW.isoformat())
        self.assertFalse(w.timer.isActive())

    def test_index_click_and_industry_selection_keep_member_identity(self):
        from PySide6.QtTest import QTest
        from tests.test_overview_details import reference,equity_snapshot
        payload=state();details={}
        for i,(root,symbol) in enumerate(ROOTS.items()):
            group=reference()['indices']['IF'];group['index_id']=symbol
            snapshot=equity_snapshot();snapshot['quotes'][symbol]=snapshot['quotes']['000300.SH']
            for r in group['rows']:r['name']=root+' '+r['name']
            details[root]=contributions(group,snapshot,dict(symbol=symbol),NOW,'2026-10-23','v1')
        payload['market_overview']['index_details']=details
        w=self.window(freeze_window(payload));page=w.quotes.views['indices']
        QTest.mouseClick(page.cards['000016.SH'],Qt.MouseButton.LeftButton);pump()
        self.assertEqual(page.selected_root,'IH');self.assertIn('上证50',page.heading.text())
        page.industries.cellClicked.emit(1,0);pump()
        self.assertEqual(page.selected_industry['IH'],'银行')
        self.assertIn('IH',page.stocks.item(0,0).text())
        self.assertIn('银行',page.stock_panel.title.text())
        page.weights.clicked.emit('煤炭');pump()
        self.assertIn('煤炭',page.stock_panel.title.text())
        self.assertEqual(page.stocks.item(0,3).text(),'+0.00')

    def test_etf_three_cards_change_together_and_missing_data_clears_previous_values(self):
        payload=state();groups={}
        for root in ROOTS:
            base=next(r for r in payload['market_overview']['etfs'] if r['root']==root)
            groups[root]=dict(ranking=dict(as_of='2026-10-23',source='fixture'),flow={},rows=[dict(base,
                symbol=f'{510300+list(ROOTS).index(root)*10+i:06}.SH',name=root+'测试ETF'+str(i),
                rank=i+1,aum_cny=(3-i)*1e8,aum_share_pct=(3-i)*10,aum_date='2026-10-23',
                iopv=4,premium_bp=0,premium_source_at=NOW.isoformat()) for i in range(3)])
        payload['market_overview']['etf_groups']=groups
        w=self.window(freeze_window(payload));w.quotes.tabs.setCurrentIndex(1);pump();page=w.quotes.views['etfs']
        for root in ROOTS:
            page.products[root].click();pump()
            self.assertEqual(len(page.visible_rows),3)
            self.assertTrue(all(root in c.heading.text() for c in page.fund_cards))
            self.assertTrue(all('+0.0 bp' in c.premium.text() for c in page.fund_cards))
            self.assertEqual(page.fund_cards[0].badge.text(),'规模 #1')
        page.render(payload['market_overview']['etfs'],{},{});pump()
        self.assertTrue(all(c.badge.text()=='待排名' for c in page.fund_cards))
        self.assertTrue(all(c.premium.text()=='折溢价 —' for c in page.fund_cards))
        self.assertTrue(page.empty_plot.isVisible());self.assertFalse(page.plot.isVisible())


if __name__=='__main__':unittest.main()
