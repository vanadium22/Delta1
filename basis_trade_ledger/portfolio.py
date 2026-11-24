from datetime import date, timedelta
from decimal import Decimal

from dashboard.native.instruments import UNDERLYINGS

from .model import LEGS, ZERO, calculate, now, revalue
from .quotes import effective_marks
from .wind_close import WIND_CLOSE, WIND_LOCAL_CLOSE


ALL_GROUPS = '*'
INDEX_NAMES = {value[0]: value[1] for value in UNDERLYINGS.values()}


def index_section(config):
    reference = UNDERLYINGS.get(config['futures'][:2], ('',))
    return config.get('index') or reference[0]


def section_title(section):
    if section == ALL_GROUPS:
        return '全部交易组'
    return INDEX_NAMES.get(section, section or '未配置指数')


def group_rollup(config, trades, quotes, closes):
    result = calculate(config, trades, {})
    result.pop('rows')
    posted = sum(trade['status'] == 'posted' for trade in trades)
    draft = len(trades) - posted
    active = bool(result['etf'].quantity or result['futures'].quantity or draft or not posted)
    days = {stamp[:10] for trade in trades if (stamp := trade.get('time') or '')[4:5] == '-' and stamp[7:8] == '-'}
    if config.get('opened'):
        days.add(config['opened'])
    return dict(config=config, result=result, quotes=quotes, closes=closes, active=active, dates=days)


def date_filter(preset, start='', end='', today=None):
    today = today or now().date()
    match preset:
        case 'today':
            return today.isoformat(), today.isoformat()
        case 'week':
            return (today - timedelta(days=6)).isoformat(), today.isoformat()
        case 'month':
            return today.replace(day=1).isoformat(), today.isoformat()
        case 'custom':
            try:
                low = date.fromisoformat(start).isoformat() if start else ''
                high = date.fromisoformat(end).isoformat() if end else ''
            except ValueError:
                raise ValueError('筛选日期请用 YYYY-MM-DD') from None
            if low and high and low > high:
                raise ValueError('筛选起始日期不得晚于结束日期')
            return low, high
        case _:
            return '', ''


def filtered(records, status='all', period=('', ''), section=ALL_GROUPS):
    low, high = period
    return [record for record in records if (section == ALL_GROUPS or section == index_section(record['config']))
            and (status == 'all' or record['active'] == (status == 'active'))
            and (not (low or high) or any((not low or day >= low) and (not high or day <= high) for day in record['dates']))]


def portfolio_values(records, market=None, recent_quotes=None, at=None):
    at = at or now()
    recent_quotes = recent_quotes or {}
    rows = []
    for record in records:
        config = record['config']
        old = recent_quotes.get(config['id'])
        quotes = dict(record['quotes'])
        for update in (old, market):
            quotes = effective_marks(config, quotes, update, at)
        marks = revalue(config, record['result'], quotes)
        exposure = {}
        held = []
        for leg in LEGS[:2]:
            position = marks[leg].quantity
            mark = quotes.get(leg)
            multiplier = Decimal(config['multiplier']) if leg == 'futures' else 1
            exposure[leg] = ZERO if not position else position * Decimal(str(mark['price'])) * multiplier if mark else None
            if position:
                held.append(mark)
        incomplete = any(v is None for v in exposure.values())
        quality = ('空仓' if not held else '待估值' if incomplete else '实时估值'
                   if all(mark.get('kind') == 'live' for mark in held) else 'Wind 收盘'
                   if all(mark.get('source') in (WIND_CLOSE, WIND_LOCAL_CLOSE) for mark in held) else '参考估值')
        rows.append(dict(record, realized=marks['realized'], floating=marks['floating'], total=marks['total'],
                         etf_exposure=exposure['etf'], futures_exposure=exposure['futures'], quality=quality,
                         net=None if incomplete else sum(exposure.values(), ZERO),
                         gross=None if incomplete else sum(map(abs, exposure.values()), ZERO)))
    totals = {key: None if any(row[key] is None for row in rows) else sum((row[key] for row in rows), ZERO)
              for key in ('realized', 'floating', 'total', 'net', 'gross')}
    return rows, totals
