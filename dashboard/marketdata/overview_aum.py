"""Dated ETF assets. Missing observations never become zero or forward fills."""
from calendar import monthrange
from datetime import date, datetime
import math
import re

SCHEMA = 'etf-aum-history-v1'


def start_day(day):
    value = date.fromisoformat(day)
    month = value.year * 12 + value.month - 1 - 3
    year, month = divmod(month, 12)
    return date(year, month + 1, min(value.day, monthrange(year, month + 1)[1])).isoformat()


def validate(history, fetched_at):
    if not isinstance(history, dict) or history.get('schema') != SCHEMA or not isinstance(history.get('rows'), dict) or len(history['rows']) > 12:
        raise ValueError('ETF规模历史格式无效')
    limit = datetime.fromisoformat(fetched_at).date().isoformat()
    observed=datetime.fromisoformat(history.get('fetched_at') or fetched_at)
    if observed.tzinfo is None or observed>datetime.fromisoformat(fetched_at):raise ValueError('ETF规模历史取得时间无效')
    first, last = history.get('requested_start'), history.get('requested_day')
    if not isinstance(first, str) or not isinstance(last, str) or date.fromisoformat(first).isoformat() != first or date.fromisoformat(last).isoformat() != last or first > last or last > limit:
        raise ValueError('ETF规模历史窗口无效')
    for symbol, row in history['rows'].items():
        if not re.fullmatch(r'(?:5[0-9]{5}\.SH|1[56][0-9]{4}\.SZ)', symbol) or not isinstance(row, dict) or row.get('symbol') != symbol or not row.get('source'):
            raise ValueError('ETF规模历史代码或来源无效')
        points = row.get('points')
        if not isinstance(points, list) or len(points) > 100:
            raise ValueError('ETF规模历史行数无效')
        previous = ''
        for point in points:
            if not isinstance(point, dict):raise ValueError('ETF规模历史观测无效')
            day, amount = point.get('as_of'), point.get('aum_cny')
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or not first <= day <= last or day <= previous:
                raise ValueError('ETF规模历史日期无效')
            if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount) or amount <= 0:
                raise ValueError('ETF规模历史数值无效')
            previous = day
    return history
