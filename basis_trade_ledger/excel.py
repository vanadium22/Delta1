from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from .model import DIRECTIONS, LEGS, calculate, code, group_config, now, number, trade_data


@dataclass
class Preview:
    key: str
    config: dict
    trades: list
    quotes: dict
    audit: dict


def _source_trade(sheet, row, values, status='posted', **extra):
    return dict(trade_data(values, status), origin=f'{sheet.title}!{row}', **extra)


def _snapshot(symbol, price, source, imported):
    if not symbol or price is None or price == '' or isinstance(price, str) and price.startswith('#'):
        return None
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    return dict(code=symbol, price=number(price, '快照价'), source=source, time=None, imported=imported)


def _differences(sheet, expected):
    differences = []
    for label, cell, current, precision in expected:
        original = sheet[cell].value
        comparable = Decimal(str(original)) if isinstance(original, (int, float)) else None
        error = isinstance(original, str) and original != ''
        if error or (comparable is None) != (current is None) or (
                comparable is not None and abs(comparable - Decimal(current)) >= Decimal(precision) / 2):
            differences.append(dict(label=label, cell=f'{sheet.title}!{cell}', original=original,
                                    current=current, digits=len(precision.split('.')[-1]) if '.' in precision else 0))
    return differences


def _modern(sheet, imported):
    def value(cell):
        return sheet[cell].value

    config = group_config(dict(name=sheet.title, etf=value('B7'), futures=value('B8'), index=value('B9'),
                               multiplier=value('B10'), base_shares=value('D10'), plan_lots=value('F10')))
    trades, warnings, running = [], [], []
    for line, cells in enumerate(sheet.iter_rows(min_row=15, max_col=23, values_only=True), 15):
        time, direction, shares, etf_price, amount, lots, price, fee, _, _, status, note = cells[:12]
        if direction or any(item not in (None, '') for item in (time, shares, etf_price, amount, lots, price, fee, status, note)):
            direction = str(direction or '').strip().replace(' ', '')
            if direction not in DIRECTIONS:
                raise ValueError(f'第 {line} 行交易方向无法识别')
            try:
                trades.append(_source_trade(sheet, line, dict(time=time, direction=direction, shares=shares,
                    etf_price=etf_price, amount=amount, lots=lots, futures_price=price, fee=fee, note=note),
                    'posted' if status == '已入账' else 'draft', source_status=str(status or '原表状态空白')))
            except ValueError as exc:
                raise ValueError(f'第 {line} 行：{exc}') from exc
        running.append((line, any(cell is not None for cell in cells[16:20])))
    first = int(trades[0]['origin'].rsplit('!', 1)[1]) if trades else sheet.max_row + 1
    last = max((line for line, has_values in running if has_values), default=0)
    missing = [str(line) for line, has_values in running if first <= line <= last and not has_values]
    if missing:
        warnings.append('原表持仓或成本结果缺失，工作表行号 ' + '、'.join(missing))

    quotes = {}
    for leg, row, mark_row in zip(LEGS, range(7, 10), range(3, 6)):
        symbol = config[leg]
        if symbol and symbol == code(value(f'P{mark_row}')):
            quote = _snapshot(symbol, value(f'E{row}'), f'Excel {sheet.title}!E{row} · {value(f"F{row}") or "估值快照"}', imported)
            if not quote:
                quote = _snapshot(symbol, value(f'Q{mark_row}'), f'Excel {sheet.title}!Q{mark_row} · 原表快照', imported)
            if quote:
                quotes[leg] = quote
        elif symbol and value(f'E{row}'):
            warnings.append(f'{symbol} 的估值代码未匹配快照代码，已留空')
    result = calculate(config, trades, quotes)
    metrics = [('ETF 净仓', 'G7', result['etf'].quantity, '1'),
               ('期货净仓', 'G8', result['futures'].quantity, '1'),
               ('ETF 持仓均价', 'H7', result['etf'].price, '0.000001'),
               ('期货持仓均价', 'H8', result['futures'].price, '0.0001'),
               ('ETF 已实现（费前）', 'I7', result['etf'].realized, '0.01'),
               ('期货已实现（费前）', 'I8', result['futures'].realized, '0.01'),
               ('已实现（扣费后）', 'A3', result['realized'], '0.01'),
               ('累计费用', 'H9', result['fees'], '0.01'),
               ('浮动盈亏', 'D3', result['floating'], '0.01'), ('总盈亏', 'G3', result['total'], '0.01'),
               ('持仓成本基差', 'J3', result['cost_basis'], '0.0001'),
               ('持仓市值基差', 'J5', result['market_basis'], '0.0001')]
    for label, key, cell in (('买入基差', '买基差', 'A5'), ('卖出基差', '卖基差', 'D5'),
                             ('全部成交基差', 'all', 'G5'), ('净成交基差', 'net', 'J9')):
        metrics.append((label, cell, result['basis'].get(key), '0.0001'))
    return config, trades, quotes, dict(warnings=warnings, differences=_differences(sheet, metrics), legacy=[])


LEGACY_DIRECTIONS = {'买入': '买入', '卖出': '卖出', '买平': '买入', '卖平': '卖出',
                     '买开': '买入', '卖开': '卖出'}


def _legacy_leg(sheet, start, stop, leg):
    trades, records, openings = [], [], {}
    for line in range(start + 1, stop):
        kind, quantity, price, amount, _, direction = [sheet.cell(line, col).value for col in range(5, 11)]
        if kind in ('汇总', '结算收益') or quantity in (None, '', 0):
            continue
        if direction not in LEGACY_DIRECTIONS:
            raise ValueError(f'第 {line} 行旧表成交方向无法识别')
        entry_type = '结算' if kind == '结算' else '成交'
        values = dict(direction=leg + LEGACY_DIRECTIONS[direction])
        if leg == 'ETF':
            values.update(shares=quantity, etf_price=price, amount=amount)
        else:
            values.update(lots=quantity, futures_price=price)
        trade = _source_trade(sheet, line, values, entry_type=entry_type)
        trades.append(trade)
        equiv_lots = sheet[f'M{line}'].value if leg == 'ETF' and entry_type == '成交' else None
        record = dict(origin=trade['origin'], type=entry_type, leg=leg, direction=direction,
                      quantity=quantity, price=price, amount=amount, equiv_lots=equiv_lots,
                      source_basis=sheet[f'O{line}'].value if equiv_lots else None, match='')
        records.append(record)
        if entry_type == '成交':
            openings[line - start] = (trade, record)
    return trades, records, openings


def _legacy(sheet, imported):
    def value(cell):
        return sheet[cell].value

    config = group_config(dict(name=sheet.title, etf=value('R7'), futures=value('T7'), index=value('S7'),
                               multiplier=value('H7'), base_shares=value('F9'),
                               plan_lots=value('J9') if value('J9') is not None else value('I10')))
    future_header = next(row for row in range(18, sheet.max_row + 1)
                         if value(f'E{row}') == '期货' and value(f'F{row}') == '成交数量')
    etf_trades, etf_records, etf_openings = _legacy_leg(sheet, 17, future_header, 'ETF')
    futures_trades, futures_records, futures_openings = _legacy_leg(sheet, future_header, sheet.max_row + 1, '期货')
    warnings = []
    for offset in sorted(etf_openings.keys() | futures_openings.keys()):
        etf_trade, etf_record = etf_openings.get(offset, (None, None))
        future_trade, future_record = futures_openings.get(offset, (None, None))
        if (etf_trade and future_trade and etf_record['equiv_lots'] == future_trade['lots']
                and DIRECTIONS[etf_trade['direction']][0] == -DIRECTIONS[future_trade['direction']][1]):
            pair = etf_trade['origin'] + ' / ' + future_trade['origin']
            for trade, record in ((etf_trade, etf_record), (future_trade, future_record)):
                trade.update(pair=pair, pair_lots=future_trade['lots'], source_status='原表手数匹配')
                record['match'] = pair
        else:
            rows = []
            for trade, record in ((etf_trade, etf_record), (future_trade, future_record)):
                if trade:
                    trade['source_status'] = record['match'] = '待核配对'
                    rows.append(trade['origin'])
            numbers = ''
            if etf_record and future_trade:
                numbers = f"（ETF 折算 {etf_record['equiv_lots'] or '缺失'} 手 / 期货 {future_trade['lots']} 手）"
            warnings.append('待核配对 · ' + ' / '.join(rows) + numbers)
    quotes = {}
    for leg, col in zip(LEGS, 'RTS'):
        quote = _snapshot(config[leg], value(f'{col}9'), f'Excel {sheet.title}!{col}9 · 原表现价', imported)
        if quote:
            quotes[leg] = quote
    trades = etf_trades + futures_trades
    result = calculate(config, trades, quotes)
    summaries = [('原表实际损益', 'L34', result['realized'], '0.01')]
    for line in range(18, sheet.max_row + 1):
        if value(f'E{line}') == '结算收益':
            leg = 'etf' if line < future_header else 'futures'
            summaries.append(('ETF 结算收益' if leg == 'etf' else '期货结算收益', f'H{line}', result[leg].realized, '0.01'))
    settlement = [dict(label=label, cell=f'{sheet.title}!{cell}', original=value(cell), current=current, digits=2)
                  for label, cell, current, _ in summaries]
    audit = dict(warnings=warnings, differences=_differences(sheet, summaries),
                 legacy=etf_records + futures_records, settlement=settlement)
    return config, trades, quotes, audit


def workbook_preview(path):
    from openpyxl import load_workbook

    path = Path(path)
    content = path.read_bytes()
    fingerprint = sha256(content).hexdigest()
    imported = now().isoformat(timespec='seconds')
    groups, skipped = [], []
    with closing(load_workbook(BytesIO(content), data_only=True, keep_links=False)) as workbook:
        for sheet in workbook:
            try:
                if sheet['B14'].value == '交易方向' and sheet['K14'].value == '录入状态':
                    config, trades, quotes, audit = _modern(sheet, imported)
                elif str(sheet['E17'].value).lower() == 'etf' and sheet['F17'].value == '成交份额':
                    config, trades, quotes, audit = _legacy(sheet, imported)
                else:
                    skipped.append(f'{sheet.title}：未识别的表格布局')
                    continue
                audit.update(file=path.name, sheet=sheet.title, digest=fingerprint, imported=imported)
                groups.append(Preview(f'{fingerprint}:{sheet.title}', config, trades, quotes, audit))
            except (ValueError, StopIteration) as exc:
                skipped.append(f'{sheet.title}：{exc or "缺少期货成交区"}')
    return groups, skipped
