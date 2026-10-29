"""Offscreen layout and navigation checks; never contacts any real feed."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import pandas as pd

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from dashboard.native.app import configure_style
from dashboard.native.editions_current import PresentationWindow, freeze_window
from dashboard.native.market_overview import quote_card
from dashboard.native.overview_instruments import etfs
from dashboard.native.instruments import UNDERLYINGS
from dashboard.marketdata.overview_contributions import contributions
from dashboard.marketdata.overview_reference import ROOTS
from tests.test_market_overview import NOW, observation,futures_values,ZERO_DIVIDENDS


APP=QApplication.instance() or QApplication([])
configure_style(APP)


def pump(seconds=.05):
    end=time.monotonic()+seconds
    while time.monotonic()<end:APP.processEvents();time.sleep(.002)


def state():
    from tests.test_overview_percentiles import metadata,daily_data,prepare
    from dashboard.marketdata.overview_percentiles import apply
    meta=metadata();history=daily_data(meta,day='2026-10-26')
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
            apply(row,prepare(r,slot,meta,history,'2026-10-26'))
            futures.append(row)
    for row in [*indices,*funds,*futures]:
        row['series']=[dict(x=i,value=.1+i*.01,source_at=f'2026-10-26T10:00:0{i}+08:00',session='am') for i in range(3)]
    from dashboard.native.futures_overview import details
    groups=details(futures,indices,live,pd.DataFrame(),NOW,dividends=ZERO_DIVIDENDS)
    return dict(as_of=NOW.isoformat(),versions={},overview=[],entities=[],selection=dict(overview_slot=0),
                market_overview=dict(schema='market-overview-v1',indices=indices,etfs=funds,futures=futures,
                                     previous_session='2026-10-23',errors=[],futures_details=groups))


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
                w.pages.setCurrentIndex(index+1);pump()
                page=w.quotes.views[kind]
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(),0)
                for row in page.visible_rows:
                    c=page.cards[row['symbol']]
                    self.assertTrue(page.body.isAncestorOf(c))
                    self.assertFalse(c.isWindow())
                    position=c.mapTo(page.body,c.rect().topLeft())
                    self.assertLessEqual(position.x()+c.width(),page.body.width())
                    if kind=='futures':
                        widgets=[c.heading,c.price,c.basis_value,c.annual_value,c.rank_value,c.rank60_value,c.clock]
                    elif kind=='indices':widgets=[c.heading,c.price,c.clock]
                    else:widgets=[c.heading,c.price,c.iopv,c.scale,c.activity,c.clock]
                    rects=[x.geometry() if x.parent() is c and x.isVisible() else None for x in widgets]
                    for a,b in zip(rects,rects[1:]):
                        if a is not None and b is not None:self.assertLess(a.bottom(),b.top())
                page.scroll.verticalScrollBar().setValue(page.scroll.verticalScrollBar().maximum());pump()

    def test_twenty_card_summary_and_flat_navigation_keep_clear_large_cards(self):
        w=self.window();summary=w.quotes
        self.assertEqual([w.pages.tabText(i) for i in range(w.pages.count())],['概览','指数','ETF','股指期货','行情分析'])
        self.assertEqual(len(summary.index_cards),4);self.assertEqual(len(summary.cards),16)
        self.assertEqual(w.pages.currentIndex(),0)
        for width,height in ((860,620),(1440,900),(1920,1080)):
            w.resize(width,height);pump()
            self.assertEqual(summary.scroll.horizontalScrollBar().maximum(),0)
            for root,group in summary.products.items():
                self.assertEqual(len(group.futures),4)
                for card in group.futures:
                    self.assertTrue(card.heading.text().startswith(root))
                    self.assertEqual(card.captions[1].text(),'去分红年化基差')
                    self.assertEqual(card.captions[2].text(),'较昨日基差变化')
                    self.assertTrue(card.clock.isHidden())
                    self.assertGreaterEqual(card.price.font().pixelSize(),30)
            summary.scroll.verticalScrollBar().setValue(summary.scroll.verticalScrollBar().maximum());pump()
        summary.products['IH'].index.clicked.emit('IH');pump()
        self.assertEqual(w.pages.currentIndex(),1);self.assertEqual(summary.views['indices'].selected_root,'IH')

    def test_per_contract_yesterday_change_and_empty_snapshot_clear_summary(self):
        payload=state()
        for row in payload['market_overview']['futures']:row['basis_change_previous']=row['slot']+0.5
        w=self.window(freeze_window(payload))
        for card in w.quotes.cards.values():self.assertIn(str(card.row['slot']+0.5),card.previous_value.text())
        cleared=dict(payload,market_overview=dict(indices=[],futures=[],etfs=[]))
        w.render(cleared);pump()
        self.assertEqual(w.quotes.cards,{})
        self.assertTrue(all(c.price.text()=='—' for g in w.quotes.products.values() for c in g.futures))
        self.assertTrue(all(c.previous_value.text()=='—' for g in w.quotes.products.values() for c in g.futures))
        self.assertTrue(all(c.price.text()=='—' for c in w.quotes.index_cards.values()))
        self.assertIn('等待行情',w.status.text())

    def test_analysis_complete_field_and_unit_form_reflows_inside_narrow_window(self):
        window=self.window();page=window.query_page;window.pages.setCurrentWidget(page)
        page.code.setText('510300.SH')
        for key in ('open','high','low','volume','amt'):page.fields[key].setChecked(True)
        for width in (1580,860,1100):
            window.resize(width,620)
            for volume in range(page.volume_unit.count()):
                page.volume_unit.setCurrentIndex(volume)
                page.amount_unit.setCurrentIndex(page.amount_unit.count()-1);pump(.025)
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(),0)
        page.code.setText('IF00');self.assertEqual(page.frequency.currentData(),'1d')
        self.assertFalse(page.twap.isEnabled());self.assertFalse(page.vwap.isEnabled())
        self.assertFalse(page.volume_unit.isEnabled());self.assertFalse(page.amount_unit.isEnabled())

    def test_status_uses_data_clock_not_repaint_and_shows_only_active_provider(self):
        from dashboard.native.overview_status import status
        payload=state();data=payload['market_overview'];first,_=status(data,now=NOW)
        payload['as_of']=(NOW+pd.Timedelta(seconds=10)).isoformat()
        second,_=status(data,now=NOW)
        self.assertEqual(first,second)
        pipeline=SimpleNamespace(history=SimpleNamespace(process=None),overview_reference=SimpleNamespace(running=lambda:True),overview_dividends=None)
        text,detail=status(data,pipeline,now=NOW)
        self.assertIn('Wind更新中',text);self.assertNotIn('DDB更新中',text)
        self.assertIn('IF2611.CFE',detail)
        text,_=status(data,now=NOW+pd.Timedelta(seconds=31))
        self.assertNotIn('实时',text)

    def test_future_filter_keeps_contract_identity_and_valid_zero(self):
        w=self.window();w.pages.setCurrentIndex(3);pump()
        page=w.quotes.views['futures'];self.assertEqual(len(page.visible_rows),4)
        page.products['IC'].click();pump()
        self.assertEqual(len(page.visible_rows),4)
        self.assertTrue(all(r['symbol'].startswith('IC') for r in page.visible_rows))
        self.assertEqual([r['continuous_percentiles']['alias'] for r in page.visible_rows],['IC00.CFE','IC01.CFE','IC02.CFE','IC03.CFE'])
        self.assertTrue(all(page.cards[r['symbol']].rank60_value.text()=='50.0%' for r in page.visible_rows))
        self.assertEqual([r['symbol'] for r in page.visible_rows],['IC2611.CFE','IC2612.CFE','IC2703.CFE','IC2706.CFE'])
        self.assertIn('+0.0点',page.cards['IC2612.CFE'].basis_value.text())
        self.assertEqual([p['days'] for p in page.curve_points],[25,53,144,235])
        self.assertTrue(all(p['symbol'].startswith('IC') for p in page.curve_points))
        self.assertFalse(page.empty_curve.isVisible())
        page.more.click();pump();self.assertEqual(page.volume_table.item(1,0).text(),'IC2612')
        page.render([],[],{});pump()
        self.assertEqual(page.curve_points,[]);self.assertTrue(page.empty_curve.isVisible())
        self.assertTrue(all(c.price.text()=='—' for c in page.contract_cards))
        self.assertTrue(all(c.rank60_value.text()!='50.0%' for c in page.contract_cards))
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
        w=self.window(freeze_window(payload));w.pages.setCurrentIndex(2);pump();page=w.quotes.views['etfs']
        for root in ROOTS:
            page.products[root].click();pump()
            self.assertEqual(len(page.visible_rows),3)
            self.assertTrue(all(root in c.heading.text() for c in page.fund_cards))
            self.assertTrue(all('+0.0 bp' in c.premium.text() for c in page.fund_cards))
            self.assertEqual(page.fund_cards[0].badge.text(),'规模 #1')
        page.render(payload['market_overview']['etfs'],{},{});pump()
        self.assertTrue(all(c.badge.text()=='待排名' for c in page.fund_cards))
        self.assertTrue(all(c.premium.text()=='盘中折溢价 —' for c in page.fund_cards))
        self.assertTrue(page.empty_plot.isVisible());self.assertFalse(page.plot.isVisible())


if __name__=='__main__':unittest.main()
