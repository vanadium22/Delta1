from datetime import timedelta
import sqlite3

from shared_data.readers import LocalData

from .model import now, number


def local_closes(paths, codes):
    end = now().date()
    start = end - timedelta(days=35)
    found, problems = {}, []
    for mode, source in (('wind', 'Wind 本地收盘'), ('offline', '离线库收盘')):
        try:
            data = LocalData(paths).daily_quotes(start.isoformat(), end.isoformat(), codes=codes,
                                                 fields=['close'], mode=mode)
        except sqlite3.Error as exc:
            problems.append(f'{source}：{exc}')
            continue
        for row in data['records']:
            symbol, day = row['code'], row['day']
            try:
                price = number(row['value'], '本地收盘价')
            except ValueError:
                continue
            if price and (symbol not in found or day > found[symbol]['time']):
                found[symbol] = dict(code=symbol, time=day, price=price, source=source)
    return list(found.values()), problems
