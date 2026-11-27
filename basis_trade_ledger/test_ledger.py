from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from openpyxl import Workbook, load_workbook
from shared_data.paths import DataPaths

from .excel import workbook_preview
from .excel_exchange import export_exchange
from .hedge import hedge_size, projected_borrow
from .model import SHANGHAI, calculate, group_config, now, revalue, trade_data
from .portfolio import borrow_capacity, daily_trades, daily_trades_text, filtered, group_rollup, index_section, portfolio_values
from .quotes import MarketQuotes, compatible_marks, local_closes
from .store import Ledger, data_paths
from .wind_close import WIND_CLOSE, download_closes


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

    def test_revalue_keeps_trade_details_and_costs(self):
        initial = calculate(self.config, [posted('卖基差', amount=24000, price=100)], {})
        updated = revalue(self.config, initial, {'etf': mark(230), 'futures': mark(105)})
        self.assertIs(initial['rows'], updated['rows'])
        self.assertEqual(updated['rows'][0]['basis_detail']['etf_points'], 120)
        self.assertEqual(updated['rows'][0]['basis'], 20)
        self.assertEqual(updated['floating'], 2000)


class HedgeSizeTest(unittest.TestCase):
    def test_borrow_projection_counts_only_incremental_shorts_after_rounding(self):
        size = hedge_size('futures', etf_price='3.6', basis_price='103.25', multiplier=100,
                          quantity=2, direction='卖基差')
        projection = projected_borrow(size.etf, 700, 1500, 6000)
        self.assertEqual(projection, {'change': 5000, 'used': 6500, 'available': 0, 'excess': 500})
        self.assertEqual(projected_borrow(-500, 700, 1500, 6000)['change'], 0)
        self.assertEqual(projected_borrow(4000, -1200, 1500, 6000)['used'], 300)
        self.assertIsNone(projected_borrow(-1, 0, 0, None)['excess'])
        self.assertEqual(projected_borrow(200, -1000, 1900, 1000)['excess'], 700)

    def test_both_basis_directions_keep_anchor_and_round_etf(self):
        market = dict(etf_price='3.6', basis_price='103.25', multiplier=100, quantity=2)
        buy = hedge_size('futures', **market)
        sell = hedge_size('futures', direction='卖基差', **market)
        self.assertEqual((buy.etf, buy.futures, buy.residual), (5700, -2, -130))
        self.assertEqual((sell.etf, sell.futures, sell.residual), (-5700, 2, 130))
        self.assertEqual(round(buy.raw_etf, 3), Decimal('5736.111'))

    def test_integer_futures_and_signed_current_position_adjustments(self):
        market = dict(etf_price='4.2', basis_price=140, multiplier=100)
        size = hedge_size('etf', quantity=10000, **market)
        self.assertEqual((size.etf, size.futures, size.residual), (10000, -3, 0))
        position = hedge_size('adjust_futures', current_etf=10000, current_futures=-1, **market)
        self.assertEqual((position.etf, position.futures, position.residual), (0, -2, 0))
        other = hedge_size('adjust_etf', etf_price='3.6', basis_price='103.25', multiplier=100,
                           current_etf=-5500, current_futures=2)
        self.assertEqual((other.etf, other.futures, other.residual), (-200, 0, 130))
        close = hedge_size('adjust_etf', current_etf=-1000, current_futures=0, etf_step=1, **market)
        self.assertEqual((close.etf, close.futures, close.residual), (1000, 0, 0))

    def test_half_step_and_missing_market_inputs(self):
        tie = hedge_size('futures', etf_price=2, basis_price=1, multiplier=100, quantity=1, direction='卖基差')
        self.assertEqual((tie.raw_etf, tie.etf), (-50, -100))
        with self.assertRaisesRegex(ValueError, '待补齐'):
            hedge_size('futures', etf_price=2, basis_price=None, multiplier=100, quantity=1)
        with self.assertRaisesRegex(ValueError, 'ETF 份额步长'):
            hedge_size('futures', etf_price=2, basis_price=1, multiplier=100, quantity=1, etf_step=0)


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'basis_trade_ledger' / 'ledger.sqlite'
        self.db = Ledger(self.path)

    def test_rename_persists_group_id_and_leaves_positions_and_drafts_intact(self):
        first, second = self.db.create(CONFIG), self.db.create(CONFIG)
        self.db.save_trade(first, fills('卖基差'), 'posted')
        self.db.save_trade(first, {'direction': '买基差', 'lots': 1}, 'draft')
        self.db.update_plan(first, {'plan_lots': 8})
        self.assertEqual(self.db.rename_group(first, '  跨日对冲  '), '跨日对冲')
        reopened = Ledger(self.path)
        self.assertEqual(reopened.recent(), second)
        self.assertEqual({g['id']: g['name'] for g in reopened.groups()}, {first: '跨日对冲', second: CONFIG['name']})
        cfg, rows, quotes, _ = reopened.open_group(first)
        self.assertEqual((cfg['plan_lots'], rows[1]['status'], calculate(cfg, rows, quotes)['futures'].quantity), ('8', 'draft', 2))
        self.assertEqual(self.db.exchange_groups(first)[0]['config']['name'], '跨日对冲')
        with self.assertRaises(ValueError):
            self.db.rename_group(first, '   ')

    def test_edit_symbols_keeps_draft_and_only_keeps_matching_quotes(self):
        group = self.db.create(dict(CONFIG, name=''))
        config, _, _, _ = self.db.open_group(group)
        draft = self.db.save_trade(group, fills('卖基差'), 'draft')
        self.db.set_marks(group, [dict(code=CONFIG[leg], price=6) for leg in ('etf', 'futures')], 'manual')
        self.db.update_group(group, dict(etf=' 510500.sh ', index='000905.sh', multiplier=200), expected=config)
        reopened = Ledger(self.path)
        cfg, trades, quotes, _ = reopened.open_group(group)
        self.assertEqual((cfg['name'], cfg['etf'], cfg['index'], cfg['multiplier'], cfg['plan_lots']),
                         ('510500.SH / IF2912.CFE', '510500.SH', '000905.SH', '200', '4'))
        self.assertEqual(trades[0]['id'], draft)
        self.assertIsNone(quotes['etf'])
        self.assertEqual(quotes['futures']['price'], 6)
        self.assertEqual([row['code'] for row in reopened.exchange_groups(group)[0]['marks']], [CONFIG['futures']])
        with self.assertRaisesRegex(ValueError, '另一窗口'):
            self.db.save_trade(group, fills('卖基差'), 'posted', expected=config)
        self.db.save_trade(group, fills('卖基差'), 'posted', trade_id=draft, version=1, expected=cfg)
        for change in (dict(etf='510300.SH'), dict(futures='IC2912.CFE'), dict(multiplier=100)):
            with self.assertRaisesRegex(ValueError, '已锁定'):
                reopened.update_group(group, change)
        reopened.update_group(group, dict(name='指数更新', index='000300.SH'))
        self.assertEqual(reopened.groups()[0]['index'], '000300.SH')

    def test_delete_trade_and_group_excludes_them_from_replay_and_exchange(self):
        group, other = self.db.create(CONFIG), self.db.create(CONFIG)
        first = self.db.save_trade(group, fills('卖基差'), 'posted')
        second = self.db.save_trade(group, fills('ETF买入', shares=50, amount=200), 'posted')
        self.db.save_trade(group, fills('卖基差', amount=700), 'posted', trade_id=first, version=1, reason='更正金额')
        self.db.save_trade(other, fills('期货买入'), 'posted')
        with self.assertRaisesRegex(ValueError, '另一窗口'):
            self.db.delete_trade(group, first, 1)
        self.db.delete_trade(group, first, 2)
        reopened = Ledger(self.path)
        cfg, rows, quotes, _ = reopened.open_group(group)
        self.assertEqual([row['id'] for row in rows], [second])
        result = calculate(cfg, rows, quotes)
        self.assertEqual((result['etf'].quantity, result['futures'].quantity, result['realized']), (50, 0, 0))
        exported, = reopened.exchange_groups(group)
        self.assertEqual([row['id'] for row in exported['trades']], [second])
        self.assertEqual(exported['revisions'], [])
        with self.db.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM revisions WHERE trade_id=?', (first,)).fetchone()[0], 1)
            deleted = con.execute('SELECT deleted FROM trades WHERE id=?', (first,)).fetchone()[0]
            self.assertEqual(json.loads(deleted)['config']['etf'], CONFIG['etf'])
        self.db.delete_group(group)
        self.assertIsNone(reopened.recent())
        self.assertEqual([row['config']['id'] for row in reopened.portfolio()], [other])
        self.assertEqual([row['id'] for row in reopened.exchange_groups()], [other])
        with self.assertRaisesRegex(ValueError, '已在另一窗口删除'):
            self.db.save_trade(group, fills('卖基差'), 'draft')

    def test_v1_upgrade_and_deleted_import_can_be_imported_again(self):
        path = self.root / 'legacy.sqlite'
        preview = Mock(config=group_config(CONFIG), key='workbook', audit={'sheet': '旧表'},
                       trades=[posted('买基差')], revisions={}, marks=[], quotes={})
        with closing(sqlite3.connect(path)) as con, con:
            Ledger._create_schema(con)
            group = Ledger._insert_group(con, preview.config, preview.key, preview.audit)
            Ledger._insert_trade(con, group, preview.trades[0])
            Ledger._set_recent(con, group)
            con.execute('PRAGMA user_version=1')
        db = Ledger(path)
        self.assertEqual(db.recent(), group)
        self.assertEqual(db.open_group(group)[1][0]['direction'], '买基差')
        self.assertEqual(db.import_groups([preview]), ([], 1))
        db.delete_group(group)
        new, skipped = db.import_groups([preview])
        self.assertNotEqual(new, [group])
        self.assertEqual(skipped, 0)
        self.assertEqual(db.import_groups([preview]), ([], 1))
        self.assertEqual(db.open_group(new[0])[3]['sheet'], '旧表')
        with db.connection() as con:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(con.execute('SELECT count(*) FROM trades').fetchone()[0], 2)

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

    def test_standard_workbook_round_trip_and_formula_text(self):
        a, b = self.db.create(CONFIG), self.db.create(dict(CONFIG, name='空组'))
        original = fills('卖基差', time='2026-11-24 14:59')
        trade_id = self.db.save_trade(a, original, 'posted')
        self.db.save_trade(a, dict(original, amount='400.123456789012345678', note='=1+2'), 'posted',
                           trade_id=trade_id, version=1, reason='改原成交金额')
        self.db.save_trade(a, {'direction': '期货买入', 'lots': 1}, 'draft')
        for kind, price in (('manual', '6.3'), ('local', '5.2')):
            self.db.set_marks(a, [dict(code=CONFIG['etf'], price=price, source=kind, time='2026-11-24')], kind)
        path = self.root / 'standard.xlsx'
        export_exchange(path, self.db.exchange_groups())
        with closing(load_workbook(path)) as workbook:
            rows = workbook['成交流水']
            self.assertEqual(rows['M2'].data_type, 's')
            self.assertEqual(rows.freeze_panes, 'B2')
            self.assertTrue(rows.auto_filter.ref)
        previews, errors = workbook_preview(path)
        self.assertFalse(errors)
        copied, skipped = self.db.import_groups(previews)
        self.assertEqual((len(copied), skipped), (2, 0))
        self.assertEqual(self.db.import_groups(previews), ([], 2))
        cfg, trades, marks, audit = self.db.open_group(copied[0])
        self.assertEqual((trades[0]['amount'], trades[0]['version'], trades[0]['note']),
                         ('400.123456789012345678', 2, '=1+2'))
        self.assertEqual((trades[1]['status'], trades[1]['time'], trades[0]['origin']),
                         ('draft', self.db.open_group(a)[1][1]['time'], '成交流水!2'))
        self.assertEqual(len(self.db.exchange_groups(b)[0]['trades']), 0)
        self.assertEqual(marks['etf']['kind'], 'manual')
        self.assertEqual(audit['sheet'], '交易组!2')
        revision, = self.db.revisions(copied[0], trades[0]['id'])
        self.assertEqual((revision['amount'], revision['reason']), ('400', '改原成交金额'))
        self.assertEqual(cfg['futures'], CONFIG['futures'])

    def test_empty_standard_template_and_invalid_group_order(self):
        path = self.root / 'template.xlsx'
        export_exchange(path, [])
        self.assertEqual(workbook_preview(path), ([], []))
        with closing(load_workbook(path)) as workbook:
            workbook['交易组'].append(['desk-1', '组', datetime(2026, 11, 24), CONFIG['etf'], CONFIG['futures'], 100])
            entry = ['desk-1', 1, None, 'ETF卖出', '已入账', 100, '金额', None, 400]
            workbook['成交流水'].append(entry)
            workbook['成交流水'].append(entry)
            workbook.save(path)
        with self.assertRaisesRegex(ValueError, '成交流水!3.*顺序重复'):
            workbook_preview(path)

    def test_manual_save_stamps_beijing_time_without_replacing_explicit_input(self):
        clock = datetime(2026, 11, 24, 13, 50, 25, tzinfo=SHANGHAI)
        group = self.db.create(CONFIG)
        with patch('basis_trade_ledger.store.now', return_value=clock):
            self.db.save_trade(group, fills('ETF买入', time=''), 'posted')
            self.db.save_trade(group, fills('ETF卖出', time='2026-11-23 14:55'), 'draft')
        saved = self.db.open_group(group)[1]
        self.assertEqual(saved[0]['time'], '2026-11-24 13:50:25')
        self.assertEqual(saved[0]['updated'], '2026-11-24T13:50:25+08:00')
        self.assertEqual(saved[1]['time'], '2026-11-23 14:55:00')


class PortfolioTest(unittest.TestCase):
    def test_copy_daily_trades_formats_each_group_and_keeps_buy_and_sell_separate(self):
        day = '2026-11-27'
        cfg = dict(group_config(dict(CONFIG, name='第一组', etf='510500.SH', futures='IC2612.CFE')), id=1)
        example = trade_data(dict(direction='买基差', shares=3170822, etf_price='6.337808',
                                  lots=16, futures_price='6274.5', time=day), 'posted')
        records = [group_rollup(cfg, [example], {}, {})]
        records.append(group_rollup(dict(cfg, id=2, name='第二组'), [
            posted('期货买入', lots=1, price='6200.2', time=day),
            posted('期货买入', lots=3, price='6200.6', time=day),
            posted('期货卖出', lots=4, price=6201, time=day),
            posted('ETF买入', shares=100, amount='600.1', time=day),
            posted('ETF买入', shares=300, amount='1800.9', time=day),
            posted('ETF卖出', time='2026-11-26'),
            dict(posted('ETF卖出', time=day), status='draft'),
        ], {}, {}))
        valued, _ = portfolio_values(records)
        rows, _ = daily_trades(valued, day)
        self.assertEqual(daily_trades_text(rows),
                         '第一组\n510500 买入@6.337808  3170822份；ic2612  卖出 16 手 @6274.5\n\n'
                         '第二组\n510500 买入@6.002500  400份；ic2612  买入 4 手 @6200.5；ic2612  卖出 4 手 @6201')

    def test_daily_trades_counts_dated_postings_and_values_full_remaining_positions(self):
        cfg = dict(group_config(CONFIG), id=1)
        today = '2026-11-27'
        records = [group_rollup(cfg, [posted('卖基差', amount=500, lots=2, price=100, time=today),
            posted('ETF买入', amount=650, time=today + ' 15:01'), posted('期货买入', lots=1, price=30, time=today),
            posted('ETF买入', time='10:00'), dict(posted('ETF买入', time=today), entry_type='结算'),
            posted('ETF买入', time='2026-11-26'), dict(posted('卖基差', time=today), status='draft')],
            {'etf': mark(4)}, {})]
        records.append(group_rollup(dict(cfg, id=2), [posted('ETF买入', time='2026-11-26')], {'etf': mark(4)}, {}))
        valued, positions = portfolio_values(records)
        rows, totals = daily_trades(valued, today)
        self.assertEqual(totals, dict(count=3, turnover=24150, net=23150, undated=1))
        self.assertEqual([(row['config']['id'], row['etf'], row['futures'], row['position_net']) for row in rows],
                         [(1, 150, 23000, None)])
        self.assertIsNone(positions['gross'])
        self.assertEqual(valued[1]['net'], 400)
        self.assertEqual(daily_trades(valued, '2026-11-28')[0], [])

    def test_index_classification_and_open_or_closed_date_filters(self):
        first = dict(group_config(dict(CONFIG, opened='2026-11-20', futures='IC2612.CFE', index='')), id=1)
        second = dict(group_config(dict(CONFIG, opened='2026-11-20')), id=2)
        third = dict(group_config(dict(CONFIG, opened=None)), id=3)
        opened = [posted('买基差', time='2026-11-24 14:30')]
        closed = [posted('ETF买入', time='2026-11-23 10:00'), posted('ETF卖出', time='2026-11-25 10:30')]
        draft = [trade_data({'direction': '期货卖出', 'time': '09:40:13.264'}, 'draft')]
        reports = [group_rollup(cfg, trades, {}, {}) for cfg, trades in zip((first, second, third), (opened, closed, draft))]
        self.assertEqual(index_section(first), '000905.SH')
        self.assertEqual([row['config']['id'] for row in filtered(reports, 'active')], [1, 3])
        self.assertEqual([row['config']['id'] for row in filtered(reports, 'closed')], [2])
        self.assertEqual([row['config']['id'] for row in filtered(reports, period=('2026-11-24', '2026-11-24'))], [1])
        self.assertEqual([row['config']['id'] for row in filtered(reports, period=('', '2026-11-24'), section='000300.SH')], [2])

    def test_aggregates_signed_and_absolute_exposure_and_keeps_missing_valuation(self):
        cfg = dict(group_config(CONFIG), id=1)
        priced = group_rollup(cfg, [posted('买基差')], {'etf': mark(5), 'futures': mark(110)}, {})
        _rows, totals = portfolio_values([priced])
        self.assertEqual(totals, {'realized': 0, 'floating': 500, 'total': 500, 'net': -21500, 'gross': 22500})
        missing = group_rollup(dict(cfg, id=2), [posted('ETF买入', fee=3)], {}, {})
        rows, totals = portfolio_values([priced, missing])
        self.assertEqual(totals, {'realized': -3, 'floating': None, 'total': None, 'net': None, 'gross': None})
        self.assertEqual(rows[1]['quality'], '待估值')

    def test_actual_positions_keep_each_leg_and_opposing_groups_separate(self):
        cfg = dict(group_config(dict(CONFIG, futures='IC2612.CFE', index='', multiplier=200)), id=1)
        marked = group_rollup(cfg, [posted('卖基差'), posted('ETF买入', shares=25, amount=100)],
                              {'etf': mark(5), 'futures': mark(110)}, {})
        unpriced = group_rollup(dict(cfg, id=2), [posted('ETF买入')], {}, {})
        empty = group_rollup(dict(cfg, id=3), [posted('ETF买入'), posted('ETF卖出')], {}, {})
        rows, _ = portfolio_values([marked, unpriced, empty])
        etf, futures = rows[0]['positions']
        self.assertEqual((etf['index'], etf['code'], etf['quantity'], etf['exposure']),
                         ('000905.SH', cfg['etf'], -75, -375))
        self.assertEqual((futures['code'], futures['quantity'], futures['exposure']),
                         ('IC2612.CFE', 2, 44000))
        self.assertEqual((rows[1]['positions'][0]['quantity'], rows[1]['positions'][0]['exposure']), (100, None))
        self.assertEqual(rows[2]['positions'], [])

    def test_borrow_capacity_counts_uncovered_shorts_across_indices_and_sessions(self):
        etf = '510500.SH'
        cfg = dict(group_config(dict(CONFIG, etf=etf, index='000905.SH')), id=1)
        reports = [
            group_rollup(cfg, [posted('卖基差', shares=1300, time='2026-11-23 10:00'),
                               posted('ETF买入', shares=300, time='2026-11-24 10:00')], {}, {}),
            group_rollup(dict(cfg, id=2, index='000300.SH'), [posted('ETF卖出', shares=500)], {}, {}),
            group_rollup(dict(cfg, id=3), [posted('ETF买入', shares=800)], {}, {}),
            group_rollup(dict(cfg, id=4, etf='512500.SH'), [posted('ETF卖出', shares=200)], {}, {}),
            group_rollup(dict(cfg, id=5), [trade_data(fills('ETF卖出', shares=200), 'draft')], {}, {}),
        ]
        capacity = borrow_capacity(reports, {etf: dict(index='000905.SH', limit=2000)}, '000905.SH')
        caps = {row['etf']: row for row in capacity}
        self.assertEqual((caps[etf]['used'], caps[etf]['available'], caps[etf]['excess']), (1500, 500, 0))
        self.assertEqual((caps['512500.SH']['used'], caps['512500.SH']['available']), (200, None))
        caps = borrow_capacity(reports, {etf: dict(index='000905.SH', limit=0)}, '000300.SH')
        self.assertEqual((caps[0]['used'], caps[0]['available'], caps[0]['excess']), (1500, 0, 1500))

    def test_borrow_limit_preserves_zero_and_reopens_with_the_same_setting(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.sqlite'
            values = dict(etf='510500.sh', index='000905.SH', limit='1,250,000')
            Ledger(path).set_borrow_limit(values)
            restored = Ledger(path)
            self.assertEqual(restored.borrow_limits(), {'510500.SH': {'index': '000905.SH', 'limit': 1250000}})
            for invalid in ('-1', '2.5', 'abc'):
                with self.assertRaises(ValueError):
                    restored.set_borrow_limit(dict(values, limit=invalid))
            restored.set_borrow_limit(dict(values, limit='0'))
            self.assertEqual(restored.borrow_limits()['510500.SH']['limit'], 0)
            restored.set_borrow_limit(dict(values, limit=''))
            self.assertEqual(Ledger(path).borrow_limits(), {})

    def test_same_index_accepts_separate_etfs_and_add_cannot_replace_a_limit(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.sqlite'
            ledger = Ledger(path)
            first = dict(etf='510500.SH', index='000905.SH', limit=1000)
            second = dict(first, etf='159922.SZ', limit=3500)
            ledger.set_borrow_limit(first, create=True)
            ledger.set_borrow_limit(second, create=True)
            with self.assertRaisesRegex(ValueError, '已设置额度'):
                ledger.set_borrow_limit(dict(first, limit=2000), create=True)
            with self.assertRaisesRegex(ValueError, '填写可融券上限'):
                ledger.set_borrow_limit(dict(first, etf='510510.SH', limit=''), create=True)
            capacity = borrow_capacity([], Ledger(path).borrow_limits(), '000905.SH')
            self.assertEqual({row['etf']: row['available'] for row in capacity}, {'510500.SH': 1000, '159922.SZ': 3500})


class RealtimeTest(unittest.TestCase):
    CODES = [CONFIG['etf'], CONFIG['futures']]
    CLOCK = datetime(2026, 11, 24, 10, 0, 8, tzinfo=SHANGHAI)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = DataPaths.for_repo(root)
        self.path = self.paths.root / 'market' / 'index_futures' / 'dashboard' / 'realtime' / 'live' / 'quotes.sqlite3'
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TABLE quotes(sequence INTEGER PRIMARY KEY, symbol TEXT, source_symbol TEXT,
                close REAL, source_event_time TEXT, received_at TEXT, date_status TEXT)''')
            con.execute('CREATE INDEX quotes_symbol_sequence ON quotes(symbol, sequence)')

    def add(self, symbol, price, seconds=1, actual=None):
        observed = (self.CLOCK - timedelta(seconds=seconds)).isoformat()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('INSERT INTO quotes VALUES (NULL,?,?,?,?,?,?)',
                        (symbol, actual or symbol, price, observed, observed, 'receipt_date_inferred_unverified'))

    def market(self, factory, continuous=True):
        market = MarketQuotes(self.paths, clock=lambda: self.CLOCK, client_factory=factory,
                              phase=lambda _: {'continuous': continuous})
        self.addCleanup(market.close)
        return market

    def test_fresh_dashboard_marks_avoid_http_and_require_pair_alignment(self):
        self.add(self.CODES[0], 4.2)
        self.add(self.CODES[1], 112, seconds=6)
        factory = Mock()
        result = self.market(factory).refresh(self.CODES, force=True)
        self.assertEqual(set(result.live), set(self.CODES))
        self.assertFalse(compatible_marks(*result.live.values()))
        factory.assert_not_called()

    def test_partial_dashboard_cache_published_before_timed_out_direct_call(self):
        self.add(self.CODES[0], 4.2)
        self.add(self.CODES[1], 112, seconds=40)
        client = Mock()
        partial = []

        def check(symbols):
            self.assertEqual(set(symbols), set(self.CODES))
            self.assertEqual(list(partial[0].live), [self.CODES[0]])
            return dict(status='timeout')

        client.fetch.side_effect = check
        market = self.market(Mock(return_value=client))
        result = market.refresh(self.CODES, on_cached=partial.append)
        self.assertEqual(result.reference[self.CODES[1]]['kind'], 'reference')
        self.assertEqual(list(result.live), [self.CODES[0]])
        market.refresh(self.CODES)
        client.fetch.assert_called_once()

    def test_locked_channel_registers_exact_codes_and_reads_shared_updates_during_backoff(self):
        from dashboard.session_guard import network_lease
        from index_strategy.instant_dld.consumer_quotes import requested_codes

        local = self.paths.repo_root / 'dashboard' / 'localsetting' / 'numeric_excel'
        local.mkdir(parents=True)
        config = {'history_roots': [str(self.paths.root / 'history')], 'realtime_root': str(self.path.parent.parent)}
        (local / 'native.json').write_text(json.dumps(config), encoding='utf-8')
        self.add(self.CODES[0], 4.2, seconds=40)
        factory = Mock()
        market = self.market(factory)
        root = self.path.parent.parent
        with network_lease(config):
            result = market.refresh(self.CODES)
            self.assertIn('行情通道正在使用', result.message)
            self.assertIn('已登记看板订阅', result.message)
            for code in self.CODES:
                self.assertIn(code, result.message)
            self.assertEqual(market.refresh(self.CODES).message, result.message)
            self.assertEqual(set(requested_codes(root, self.CLOCK)), set(self.CODES))
            self.assertEqual(requested_codes(root, self.CLOCK + timedelta(seconds=19)), [])
            self.add(self.CODES[0], 4.3)
            self.add(self.CODES[1], 113)
            live = market.refresh(self.CODES).live
            self.assertEqual(set(live), set(self.CODES))
            self.assertTrue(all(mark['source'] == '网厅 · 看板实时' for mark in live.values()))
        factory.assert_not_called()
        market.close()
        self.assertEqual(requested_codes(root, self.CLOCK), [])

    def test_direct_batch_matching_receipt_and_out_of_session_cache(self):
        self.add(self.CODES[0], 4.2)
        self.add(self.CODES[1], 112, actual='IF3001.CFE')
        client = Mock()
        client.fetch.return_value = dict(status='success', received_at=self.CLOCK.isoformat(), response={'data': {
            self.CODES[0]: dict(securityId=self.CODES[0], latestPrice=4.3, quoteTimestamp=100007),
            self.CODES[1]: dict(securityId=self.CODES[1], latestPrice=114, quoteTimestamp=100007),
        }})
        with patch.dict('os.environ', SWHY_DASHBOARD_LOCAL_ROOT=str(self.paths.repo_root / 'dashboard')):
            result = self.market(Mock(return_value=client)).refresh(self.CODES)
            self.assertTrue(compatible_marks(*result.live.values()))
            self.assertTrue(all(mark['source'] == '网厅 · 实时直连' for mark in result.live.values()))
            offline = self.market(Mock(), continuous=False).refresh(self.CODES, force=True)
            self.assertFalse(offline.live)
            self.assertEqual(list(offline.reference), [self.CODES[0]])

    def test_after_close_queries_wind_once_and_reuses_persisted_same_day_close(self):
        clock = self.CLOCK.replace(hour=15, minute=10)
        fetch = Mock(return_value=({self.CODES[0]: 4.4, self.CODES[1]: 109.2}, ''))
        market = MarketQuotes(self.paths, clock=lambda: clock, wind_fetcher=fetch)
        self.addCleanup(market.close)
        first = market.refresh(self.CODES)
        self.assertFalse(first.live)
        self.assertEqual({mark['code']: mark['price'] for mark in first.closes},
                         {self.CODES[0]: Decimal('4.4'), self.CODES[1]: Decimal('109.2')})
        self.assertTrue(all(mark['time'] == '2026-11-24' and mark['source'] == WIND_CLOSE for mark in first.closes))
        saved = {mark['code']: mark for mark in first.closes}
        self.assertFalse(market.refresh(self.CODES, saved_closes=saved).closes)
        fresh_instance = MarketQuotes(self.paths, clock=lambda: clock, wind_fetcher=fetch)
        self.addCleanup(fresh_instance.close)
        self.assertFalse(fresh_instance.refresh(self.CODES, saved_closes=saved).closes)
        fetch.assert_called_once()

    def test_wind_waits_for_completed_session_and_backs_off_on_missing_quotes(self):
        clock = self.CLOCK.replace(hour=15, minute=5)
        fetch = Mock(return_value=({}, 'Wind 测试缺项'))
        market = MarketQuotes(self.paths, clock=lambda: clock, wind_fetcher=fetch)
        self.addCleanup(market.close)
        self.assertIn('等候', market.refresh(self.CODES).message)
        fetch.assert_not_called()
        clock = self.CLOCK.replace(hour=15, minute=12)
        self.assertIn('Wind 测试缺项', market.refresh(self.CODES).message)
        self.assertFalse(market.refresh(self.CODES).closes)
        fetch.assert_called_once()
        market.refresh(self.CODES, force=True)
        self.assertEqual(fetch.call_count, 2)

    def test_wind_worker_validates_daily_identity_and_filters_missing_close(self):
        sdk = self.paths.repo_root / 'WindPy.py'
        sdk.write_text('''from datetime import date
from types import SimpleNamespace as R
class Wind:
    def start(self, **kwargs):
        return R(ErrorCode=0)
    def wsd(self, codes, field, start, end, options):
        assert field == 'close' and start == end and 'PriceAdj=U' in options and 'Fill=Blank' in options
        return R(ErrorCode=0, Codes=codes.split(',')[::-1], Times=[date.fromisoformat(start)], Fields=['CLOSE'], Data=[[108, None]])
    def stop(self):
        pass
w = Wind()
''', encoding='utf-8')
        with patch.dict('os.environ', PYTHONPATH=str(sdk.parent)):
            values, error = download_closes(self.CODES, '2026-11-24', {'overview_wind_python': sys.executable}, sdk.parent)
        self.assertFalse(error)
        self.assertEqual(values, {self.CODES[1]: 108})
