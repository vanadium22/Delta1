from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re


SHANGHAI = timezone(timedelta(hours=8), 'Asia/Shanghai')
ZERO = Decimal(0)
DIRECTIONS = {
    '买基差': (1, -1), '卖基差': (-1, 1),
    'ETF买入': (1, 0), 'ETF卖出': (-1, 0),
    '期货买入': (0, 1), '期货卖出': (0, -1),
}
NUMBERS = {
    'shares': 'ETF 份额', 'etf_price': 'ETF 均价', 'amount': 'ETF 金额',
    'lots': '期货手数', 'futures_price': '期货均价', 'fee': '费用',
}
LEGS = ('etf', 'futures', 'index')


def now():
    return datetime.now(SHANGHAI)


def number(value, label, *, zero=False, integer=False):
    if value is None or value == '':
        return None
    try:
        result = Decimal(str(value).strip().replace(',', ''))
    except InvalidOperation:
        raise ValueError(f'{label}必须为数字') from None
    if not result.is_finite() or result < 0 or (not zero and not result):
        raise ValueError(f'{label}必须为{"非负" if zero else "正"}数')
    if result > 10**18 or (result and result < Decimal('1e-18')):
        raise ValueError(f'{label}超出支持范围')
    if integer and result != result.to_integral_value():
        raise ValueError(f'{label}必须为整数')
    return result


def code(value):
    return str(value or '').strip().upper()


def date_time(value):
    value = str(value or '').strip()
    if not value:
        return None
    if re.fullmatch(r'\d{2}:\d{2}(:\d{2}(\.\d+)?)?', value):
        return time.fromisoformat(value).isoformat()
    if len(value) == 10:
        return date.fromisoformat(value).isoformat()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo:
        parsed = parsed.astimezone(SHANGHAI).replace(tzinfo=None)
    return parsed.isoformat(sep=' ')


def group_config(values):
    result = {key: code(values.get(key)) for key in LEGS}
    for key, label in zip(LEGS, ('ETF', '期货', '跟踪指数')):
        symbol = result[key]
        if key == 'index' and not symbol:
            continue
        if not re.fullmatch(r'[A-Z0-9]+(?:\.[A-Z0-9]+)?', symbol):
            raise ValueError(f'请填写有效的{label}代码')
    result['multiplier'] = number(values.get('multiplier'), '合约乘数', integer=True)
    if result['multiplier'] is None:
        raise ValueError('请填写合约乘数')
    result.update(plan_config(values))
    result['name'] = str(values.get('name') or '').strip() or f"{result['etf']} / {result['futures']}"
    opened = values.get('opened')
    result['opened'] = date.fromisoformat(str(opened)).isoformat() if opened else None
    return result


def plan_config(values):
    return {key: number(values.get(key), label, integer=True, zero=True)
            for key, label in (('base_shares', '参考底仓'), ('plan_lots', '计划手数'))}


def trade_data(values, status):
    if status not in {'draft', 'posted'}:
        raise ValueError('未知录入状态')
    direction = values.get('direction')
    if direction not in DIRECTIONS:
        raise ValueError('请选择交易方向')
    etf, futures = DIRECTIONS[direction]
    active = ('shares', 'etf_price', 'amount') if etf else ()
    active += ('lots', 'futures_price') if futures else ()
    method = values.get('etf_input') or ('amount' if values.get('amount') not in (None, '') else 'etf_price')
    if method not in {'etf_price', 'amount'}:
        raise ValueError('请选择 ETF 金额或均价')
    derived = 'etf_price' if method == 'amount' else 'amount'
    fields = {key: number(values.get(key), NUMBERS[key], zero=key == 'fee', integer=key in {'lots', 'shares'})
              for key in (*active, 'fee') if key != derived}
    if etf:
        fields[derived] = None
        if fields['shares'] and fields[method]:
            fields[derived] = (fields[method] / fields['shares'] if method == 'amount'
                               else fields[method] * fields['shares'])
    if status == 'posted':
        required = (('shares', method) if etf else ()) + (('lots', 'futures_price') if futures else ())
        missing = [NUMBERS[key] for key in required if fields[key] is None]
        if missing:
            raise ValueError('请填写' + '、'.join(missing))
    try:
        timestamp = date_time(values.get('time'))
    except ValueError:
        raise ValueError('成交时间请用 YYYY-MM-DD HH:MM，缺失可留空') from None
    return dict(fields, status=status, direction=direction, etf_input=method, time=timestamp,
                note=str(values.get('note') or '').strip())


@dataclass
class Position:
    quantity: Decimal = ZERO
    price: Decimal | None = None
    realized: Decimal = ZERO

    def apply(self, change, price, multiplier):
        previous = self.quantity
        self.quantity += change
        if not previous or previous * change > 0:
            self.price = (abs(previous) * (self.price or ZERO) + abs(change) * price) / abs(self.quantity)
            return ZERO
        gain = min(abs(previous), abs(change)) * (1 if previous > 0 else -1) * (price - self.price) * multiplier
        self.realized += gain
        if not self.quantity:
            self.price = None
        elif previous * self.quantity < 0:
            self.price = price
        return gain

    def floating(self, mark, multiplier):
        if not self.quantity:
            return ZERO
        if mark is not None:
            return self.quantity * (mark - self.price) * multiplier
        return None


def calculate(config, trades, quotes):
    etf, futures = Position(), Position()
    multiplier = Decimal(config['multiplier'])
    fees = ZERO
    basis_totals = defaultdict(lambda: [ZERO, ZERO])
    legacy_pairs = defaultdict(list)
    rows = []

    def add_basis(direction, amount, lots, price):
        points = amount / (lots * multiplier)
        basis = points - price
        for key, weight in ((direction, lots), ('all', lots), ('net', lots * DIRECTIONS[direction][0])):
            basis_totals[key][0] += basis * weight
            basis_totals[key][1] += weight
        return dict(value=basis, amount=amount, lots=lots, futures_price=price,
                    etf_points=points, multiplier=multiplier)

    for trade in trades:
        row = dict(trade, basis=None, realized=None)
        rows.append(row)
        if trade['status'] != 'posted':
            continue
        etf_sign, futures_sign = DIRECTIONS[trade['direction']]
        price, shares, amount, lots, futures_price, fee = (
            Decimal(trade[key]) if trade.get(key) is not None else ZERO
            for key in ('etf_price', 'shares', 'amount', 'lots', 'futures_price', 'fee'))
        fees += fee
        row['realized'] = -fee
        if etf_sign:
            row['realized'] += etf.apply(shares * etf_sign, price, 1)
        if futures_sign:
            row['realized'] += futures.apply(lots * futures_sign, futures_price, multiplier)
        if etf_sign and futures_sign:
            row['basis_detail'] = add_basis(trade['direction'], amount, lots, futures_price)
            row['basis'] = row['basis_detail']['value']
        elif trade.get('pair'):
            legacy_pairs[trade['pair']].append((row, etf_sign, futures_sign, amount, lots, futures_price))

    for pair in legacy_pairs.values():
        if len(pair) == 2:
            etf_row, future_row = sorted(pair, key=lambda leg: not leg[1])
            row, etf_sign, _, amount, _, _ = etf_row
            fut, _, futures_sign, _, lots, price = future_row
            if etf_sign and etf_sign == -futures_sign and lots == Decimal(row['pair_lots']):
                row['basis_detail'] = add_basis('买基差' if etf_sign > 0 else '卖基差', amount, lots, price)
                row['basis'] = row['basis_detail']['value']
                row['basis_detail']['future_origin'] = fut.get('origin')

    return revalue(config, dict(etf=etf, futures=futures, rows=rows, fees=fees,
                   realized=etf.realized + futures.realized - fees,
                   basis={key: total / weight if weight else None for key, (total, weight) in basis_totals.items()}), quotes)


def revalue(config, result, quotes):
    etf, futures = result['etf'], result['futures']
    multiplier = Decimal(config['multiplier'])
    etf_mark, futures_mark, index_mark = (Decimal(quotes[key]['price']) if quotes.get(key) else None for key in LEGS)
    etf_float, futures_float = etf.floating(etf_mark, 1), futures.floating(futures_mark, multiplier)
    floating = None if None in (etf_float, futures_float) else etf_float + futures_float
    realized = result['realized']
    cost_basis = market_basis = None
    if etf.quantity * futures.quantity < 0:
        ratio = abs(etf.quantity) / (abs(futures.quantity) * multiplier)
        cost_basis = ratio * etf.price - futures.price
        if etf_mark is not None and futures_mark is not None:
            market_basis = ratio * etf_mark - futures_mark
    base = config.get('base_shares')
    plan = config.get('plan_lots')
    base_value = Decimal(base) * etf_mark if base is not None and etf_mark else None
    plan_value = Decimal(plan) * multiplier * index_mark if plan is not None and index_mark else None
    return dict(result, floating=floating,
                total=None if floating is None else realized + floating,
                etf_float=etf_float, futures_float=futures_float, cost_basis=cost_basis, market_basis=market_basis,
                base_value=base_value, base_lots=base_value / (multiplier * index_mark)
                if base_value is not None and index_mark else None, plan_value=plan_value,
                plan_shares=plan_value / etf_mark if plan_value is not None and etf_mark else None)
