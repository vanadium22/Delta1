from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook

from .excel import workbook_preview
from .model import calculate, group_config, now, trade_data
from .quotes import local_closes
from .store import Ledger, data_paths


CONFIG = dict(name='验证组', etf='123456.SH', futures='IF2912.CFE', index='000300.SH',
              multiplier=100, base_shares=1000, plan_lots=4, opened='2026-11-24')


def fills(direction, *, shares=100, amount=400, lots=2, price=112, fee=0, time=None):
    return dict(direction=direction, shares=shares, amount=amount, lots=lots, futures_price=price, fee=fee, time=time)


def posted(direction, **values):
    return trade_data(fills(direction, **values), 'posted')


def mark(price):
    return {'price': price}


class LedgerMathTest(unittest.TestCase):
    def setUp(self):
        self.config = group_config(CONFIG)

    def test_amount_or_average_and_draft(self):
        price_trade = trade_data(dict(direction='ETF买入', shares='125', etf_price='6.125'), 'posted')
        self.assertEqual(price_trade['amount'], Decimal('765.625'))
        self.assertEqual(price_trade['etf_price'], Decimal('6.125'))
        self.assertEqual(trade_data(fills('ETF买入'), 'posted')['etf_price'], 4)
        draft = trade_data(dict(direction='卖基差', shares='125'), 'draft')
        result = calculate(self.config, [draft], {})
        self.assertEqual(result['etf'].quantity, 0)
        self.assertEqual(result['realized'], 0)
        with self.assertRaises(ValueError):
            trade_data({'direction': '卖基差', 'shares': 10}, 'posted')
        with self.assertRaises(ValueError):
            trade_data(fills('期货买入', lots='1.5'), 'posted')

    def test_partial_close_reverse_and_fees(self):
        trades = [posted('卖基差', fee=2), posted('ETF卖出', amount=600, fee=3),
                  posted('ETF买入', shares=50, amount=225), posted('期货卖出', lots=1, price=116)]
        r = calculate(self.config, trades, {})
        self.assertEqual((r['etf'].quantity, r['etf'].price), (-150, 5))
        self.assertEqual((r['futures'].quantity, r['futures'].price), (1, 112))
        self.assertEqual(r['realized'], 420)
        self.assertIsNone(r['total'])
        self.assertEqual(r['basis']['卖基差'], -110)
        extra = [posted('ETF买入', shares=200, amount=600), posted('期货卖出', lots=3, price=115)]
        r = calculate(self.config, trades + extra, {'etf': mark(4), 'futures': mark(114), 'index': mark(125)})
        self.assertEqual((r['etf'].quantity, r['etf'].price), (50, 3))
        self.assertEqual((r['futures'].quantity, r['futures'].price), (-2, 115))
        self.assertEqual((r['realized'], r['floating'], r['total']), (1020, 250, 1270))
        self.assertEqual((r['plan_value'], r['plan_shares'], r['base_value']), (50000, 12500, 4000))
        self.assertEqual((r['cost_basis'], r['market_basis']), (Decimal('-114.25'), -113))

    def test_net_basis_zero_weight_and_single_leg(self):
        trades = [posted('买基差', amount=24000, price=100), posted('卖基差', amount=26000, price=100),
                  posted('期货买入', lots=1, price=99)]
        r = calculate(self.config, trades, {})
        self.assertEqual(r['basis'], {'买基差': 20, '卖基差': 30, 'all': 25, 'net': None})
        self.assertIsNone(r['cost_basis'])
        self.assertIsNone(r['etf'].price)
        self.assertIsNone(r['floating'])


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'basis_trade_ledger' / 'ledger.sqlite'
        self.db = Ledger(self.path)

    def test_reopen_two_groups_cross_day_and_correction(self):
        a, b = self.db.create(CONFIG), self.db.create(CONFIG)
        opening = self.db.save_trade(a, fills('卖基差', time='2026-11-24 14:58'), 'posted')
        draft = self.db.save_trade(a, {'direction': '买基差', 'lots': 1}, 'draft')
        self.db.save_trade(b, fills('ETF买入', shares=20, amount=100), 'posted')
        self.db.open_group(a)
        reopened = Ledger(self.path)
        self.assertEqual(reopened.recent(), a)
        config, trades, quotes, _ = reopened.open_group(a)
        self.assertEqual(trades[1]['status'], 'draft')
        self.assertEqual(calculate(config, trades, quotes)['etf'].quantity, -100)
        tomorrow = fills('买基差', shares=40, amount=120, lots=1, price=118, fee=1, time='2026-11-25 09:42')
        reopened.save_trade(a, tomorrow, 'posted', trade_id=draft, version=1)
        after = calculate(*reopened.open_group(a)[:3])
        self.assertEqual((after['etf'].quantity, after['etf'].price, after['realized']), (-60, 4, 639))
        with self.assertRaises(ValueError):
            reopened.save_trade(a, fills('卖基差', amount=500), 'posted', trade_id=opening, version=1)
        reopened.save_trade(a, fills('卖基差', amount=500, time='2026-11-24 14:58'), 'posted',
                            trade_id=opening, version=1, reason='成交单价更正')
        after = calculate(*Ledger(self.path).open_group(a)[:3])
        self.assertEqual((after['etf'].quantity, after['etf'].price, after['realized']), (-60, 5, 679))
        self.assertEqual([row['time'] for row in after['rows']], ['2026-11-24 14:58:00', '2026-11-25 09:42:00'])
        revision, = reopened.revisions(a, opening)
        self.assertEqual((revision['amount'], revision['reason']), ('400', '成交单价更正'))
        self.assertEqual(calculate(*reopened.open_group(b)[:3])['etf'].quantity, 20)
        with self.assertRaisesRegex(ValueError, '另一窗口'):
            self.db.save_trade(a, fills('卖基差'), 'posted', trade_id=opening, version=1, reason='过期更正')

    def test_price_source_fallback_and_group_matches(self):
        group = self.db.create(CONFIG)
        source = dict(code=CONFIG['etf'], time='2026-11-24', source='Excel')
        self.db.set_marks(group, [dict(source, price=5)], 'excel')
        self.db.set_marks(group, [dict(source, price=6, source='Wind 本地收盘')], 'local')
        self.db.set_marks(group, [dict(source, price=7, source='手填估值')], 'manual')
        self.assertEqual(self.db.open_group(group)[2]['etf']['price'], 7)
        self.db.set_marks(group, [], 'manual', clear=[CONFIG['etf']])
        self.assertEqual(self.db.open_group(group)[2]['etf']['price'], 6)
        with self.assertRaises(ValueError):
            self.db.set_marks(group, [dict(source, code='ABCD', price=5)], 'excel')

    def test_public_local_quote_reader(self):
        paths = data_paths(self.root)
        for mode in ('wind', 'offline'):
            db = paths.basis(mode) / 'market.sqlite'
            db.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db)) as con, con:
                con.execute('CREATE TABLE quotes (code, day, field, value)')
                day = now().date() - timedelta(days=1 if mode == 'offline' else 2)
                con.execute('INSERT INTO quotes VALUES (?,?,?,?)', (CONFIG['etf'], day.isoformat(), 'close', 6.1))
        marks, problems = local_closes(paths, [CONFIG['etf'], CONFIG['futures']])
        self.assertFalse(problems)
        self.assertEqual([(m['code'], m['time'], m['source']) for m in marks],
                         [(CONFIG['etf'], day.isoformat(), '离线库收盘')])

    def test_preview_is_read_only_and_selected_import_is_idempotent(self):
        book = Workbook()
        sheet = book.active
        sheet.title = '示例交易组'
        book.create_sheet('说明')
        cells = {'B14': '交易方向', 'K14': '录入状态', 'B7': CONFIG['etf'], 'B8': CONFIG['futures'], 'B10': 100,
                 'B15': '卖基差', 'C15': 100, 'E15': 320, 'F15': 2, 'G15': 120, 'K15': '已入账',
                 'A17': datetime(2026, 11, 25, 9, 42), 'B17': 'ETF买入', 'C17': 10, 'D17': 2.5, 'K17': '已入账',
                 'E8': 120, 'P4': 'IF2701.CFE', 'P3': CONFIG['etf'], 'Q3': 3.2, 'G7': 0}
        for cell, value in cells.items():
            sheet[cell] = value
        path = self.root / 'fixture.xlsx'
        book.save(path)
        book.close()
        groups, skipped = workbook_preview(path)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(skipped), 1)
        g = groups[0]
        self.assertEqual([trade['origin'] for trade in g.trades], ['示例交易组!15', '示例交易组!17'])
        self.assertEqual([trade['time'] for trade in g.trades], [None, '2026-11-25 09:42:00'])
        self.assertEqual(g.quotes['etf']['price'], Decimal('3.2'))
        self.assertNotIn('futures', g.quotes)
        self.assertIn('示例交易组!G7', {row['cell'] for row in g.audit['differences']})
        self.assertFalse(self.db.groups())
        ids, skipped_count = self.db.import_groups(groups)
        self.assertEqual((len(ids), skipped_count), (1, 0))
        self.assertEqual(self.db.import_groups(groups), ([], 1))
        self.assertEqual(calculate(*self.db.open_group(ids[0])[:3])['etf'].quantity, -90)

    def test_legacy_settlements_keep_source_rows_and_flag_mismatched_pairs(self):
        book = Workbook()
        sheet = book.active
        sheet.title = '旧版示例'
        cells = {'R7': CONFIG['etf'], 'T7': CONFIG['futures'], 'H7': 100,
                 'E17': 'etf', 'F17': '成交份额', 'F18': 100, 'G18': 4, 'H18': 400, 'J18': '卖出', 'M18': 3,
                 'E22': '结算', 'F22': 100, 'G22': 3.5, 'H22': 350, 'J22': '买平',
                 'E23': '结算收益', 'H23': 50, 'E24': '期货', 'F24': '成交数量',
                 'F25': 2, 'G25': 120, 'J25': '买入', 'E29': '结算', 'F29': 2, 'G29': 119, 'J29': '卖平',
                 'E30': '结算收益', 'H30': -200, 'L34': -150}
        for cell, value in cells.items():
            sheet[cell] = value
        matched = book.copy_worksheet(sheet)
        matched['M18'] = 2
        path = self.root / 'legacy.xlsx'
        book.save(path)
        book.close()
        (pending, matched), skipped = workbook_preview(path)
        self.assertFalse(skipped)
        for group in (pending, matched):
            result = calculate(group.config, group.trades, group.quotes)
            self.assertEqual((result['etf'].quantity, result['futures'].quantity, result['realized']), (0, 0, -150))
            self.assertEqual([row['origin'].split('!')[-1] for row in group.audit['legacy']], ['18', '22', '25', '29'])
            self.assertFalse(group.audit['differences'])
        self.assertIn('待核配对', pending.audit['warnings'][0])
        self.assertFalse(calculate(pending.config, pending.trades, pending.quotes)['basis'])
        self.assertEqual(calculate(matched.config, matched.trades, matched.quotes)['basis']['卖基差'], -118)
