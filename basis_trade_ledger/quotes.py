from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import sqlite3
from time import monotonic

from shared_data.readers import LocalData

from .model import SHANGHAI, now, number


POLL_MS = 3000
SUPPORTED = re.compile(r'(?:[0-9]{6}\.(?:SH|SZ)|(?:IF|IH|IC|IM)[0-9]{2}(?:0[1-9]|1[0-2])\.CFE)')


@dataclass
class QuoteUpdate:
    live: dict
    reference: dict
    closes: list
    message: str


def _timestamp(value):
    try:
        value = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return value.astimezone(SHANGHAI) if value.tzinfo else None


def _payload(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def dashboard_profile(paths):
    local = paths.repo_root / 'dashboard' / 'localsetting'
    custom = os.environ.get('SWHY_DASHBOARD_LOCAL_ROOT')
    candidates = [Path(custom)] if custom else [local / 'app', local / 'numeric_excel', local]
    profile = next((candidate for candidate in candidates if (candidate / 'native.json').is_file()), candidates[0])
    saved = _payload(profile / 'native.json')
    config = saved if isinstance(saved, dict) else {}
    fallback = paths.root / 'market' / 'index_futures' / 'dashboard' / 'realtime'
    return profile, config, Path(config.get('realtime_root') or fallback)


def _mark(row, at, source, kind):
    when = _timestamp(row.get('source_event_time'))
    received = _timestamp(row.get('observed_at') or row.get('received_at'))
    from index_strategy.instant_dld.quotes import price_number
    price = price_number(row.get('close'))
    if not price or not when or not received or when > at + timedelta(seconds=3) or received > at:
        return None
    return dict(code=row['symbol'], price=price, time=when.isoformat(timespec='seconds'), source=source,
                kind=kind, observed_at=received.isoformat(), date_status=row.get('date_status'),
                date_basis=row.get('source_date_basis'))


def compatible_marks(first, second):
    """Track current pair quality while allowing explicit reference estimates."""
    if not (first and second):
        return False
    kinds = {first.get('kind'), second.get('kind')}
    if kinds == {'live'}:
        return all(abs((_timestamp(first[key]) - _timestamp(second[key])).total_seconds()) <= 3
                   for key in ('time', 'observed_at'))
    if 'manual' in kinds:
        return True
    if 'live' in kinds:
        return False
    days = [mark['time'][:10] for mark in (first, second) if mark.get('time') and len(mark['time']) >= 10]
    if len(days) == 2 and days[0] != days[1]:
        return False
    return True


class MarketQuotes:
    def __init__(self, paths, *, clock=now, client_factory=None, phase=None):
        self.paths, self.clock, self.client_factory, self.phase = paths, clock, client_factory, phase
        self.client = None
        self.direct = {}
        self.references = {}
        self.retry_at = 0

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def refresh(self, codes, *, force=False, on_cached=None):
        from dashboard.marketdata.quote_quality import quote_quality
        from dashboard.session_clock import market_phase
        from index_strategy.instant_dld.reader import RealtimeReader

        profile, config, root = dashboard_profile(self.paths)
        at = self.clock()
        continuous = (self.phase or market_phase)(at)['continuous']
        codes = sorted({c for c in codes if SUPPORTED.fullmatch(c)})
        if not codes:
            return QuoteUpdate({}, {}, [], '请填写带交易所后缀的实际标的代码')
        reader = RealtimeReader(root)
        try:
            rows = reader.latest_records(codes) if codes and reader.db_path.is_file() else {}
        except (OSError, sqlite3.Error):
            rows = {}
        snapshot = _payload(profile / 'overview_snapshots' / 'latest.json')
        cached = snapshot.get('quotes') if isinstance(snapshot, dict) and snapshot.get('schema') == 'overview-latest-snapshot-v1' else {}
        if not isinstance(cached, dict):
            cached = {}
        at = self.clock()
        for symbol in codes:
            for raw, source in ((cached.get(symbol), '网厅 · 看板快照'), (rows.get(symbol), '网厅 · 看板缓存'),
                                (self.direct.get(symbol), '网厅 · 上次报价')):
                if not isinstance(raw, dict) or raw.get('source_symbol', raw.get('symbol')) != symbol:
                    continue
                mark = _mark(dict(raw, symbol=symbol), at, source, 'reference')
                if mark and (not self.references.get(symbol) or mark['time'] >= self.references[symbol]['time']):
                    self.references[symbol] = mark

        def fresh(raw, source, timestamp):
            if raw and raw.get('source_symbol') == raw.get('symbol') and quote_quality(raw, timestamp)['usable']:
                return _mark(raw, timestamp, source, 'live')
            return None

        live = {}
        message = '休市参考' if not continuous else '网厅行情'
        if continuous:
            for symbol in codes:
                candidates = (fresh(rows.get(symbol), '网厅 · 看板实时', at),
                              fresh(self.direct.get(symbol), '网厅 · 实时直连', at))
                valid = [mark for mark in candidates if mark]
                if valid:
                    live[symbol] = max(valid, key=lambda mark: mark['time'])
            missing = [symbol for symbol in codes if symbol not in live]
            needed = [s for s in codes if s not in live or (live[s]['source'] == '网厅 · 实时直连' and
                      (force or (at - _timestamp(live[s]['observed_at'])).total_seconds() >= 2.8))]
            if needed and (force or monotonic() >= self.retry_at):
                if on_cached:
                    on_cached(QuoteUpdate(live.copy(), self._references(codes), [], '看板缓存 · 后台补查中'))
                # Fetch the pair in one batch when only one side is covered or refreshed.
                state = self._fetch(codes, config, live, fresh)
                message = state or message
            elif missing and self.retry_at > monotonic():
                message = '网厅连接等待重试，沿用参考价'
            live = {symbol: mark for symbol, mark in live.items() if mark and
                    (self.clock() - _timestamp(mark['time'])).total_seconds() <= 30}
        refs = self._references(codes)
        if on_cached and force and any(s not in live for s in codes):
            on_cached(QuoteUpdate(live, refs, [], message))
        closes, _ = local_closes(self.paths, [s for s in codes if s not in live]) if force and any(s not in live for s in codes) else ([], [])
        return QuoteUpdate(live, refs, closes, message)

    def _references(self, codes):
        return {s: self.references[s] for s in codes if s in self.references}

    def _fetch(self, codes, config, live, fresh):
        from dashboard.session_guard import network_lease
        from index_strategy.instant_dld.client import MarketDataClient
        from index_strategy.instant_dld.quotes import normalize_quote

        try:
            with network_lease(config):
                if self.client is None:
                    self.client = (self.client_factory or MarketDataClient)(connect_timeout=1, read_timeout=2)
                result = self.client.fetch(codes)
        except (OSError, ValueError) as exc:
            self.retry_at = monotonic() + 12
            return ('看板占用行情通道，优先使用共享报价' if getattr(exc, 'lock_operation', '') == 'acquire_byte_lock'
                    else '行情通道不可用，沿用参考价')
        good = result.get('status') in ('success', 'partial')
        self.retry_at = 0 if good else monotonic() + 15
        if not good:
            return '网厅暂不可用，沿用参考价'
        at = self.clock()
        data = result['response']['data']
        for symbol in codes:
            raw = data.get(symbol)
            if not isinstance(raw, dict) or raw.get('securityId') != symbol:
                continue
            try:
                row = normalize_quote(symbol, raw, result['received_at'])
                explicit = next((raw[key] for key in ('tradeDate', 'tradingDate', 'tradingDay') if raw.get(key)), None)
                if explicit:
                    day = datetime.fromisoformat(str(explicit)).date()
                    if day != at.date() or not row['quote_time']:
                        continue
                    row.update(source_event_time=f"{day}T{row['quote_time']}+08:00", date_status='source_reported')
                mark = fresh(row, '网厅 · 实时直连', at)
            except (TypeError, ValueError):
                continue
            if mark:
                self.direct[symbol] = row
                self.references[symbol] = dict(mark, source='网厅 · 上次报价', kind='reference')
                if symbol not in live or mark['time'] >= live[symbol]['time']:
                    live[symbol] = mark
        if any(s not in live for s in codes):
            self.retry_at = monotonic() + 12
            return '部分标的缺少有效实时价'
        return None


def local_closes(paths, codes):
    end = now().date()
    start = end - timedelta(days=35)
    found, problems = {}, []
    for mode, source in (('wind', 'Wind 本地收盘'), ('offline', '离线库收盘')):
        if not (paths.basis(mode) / 'market.sqlite').is_file():
            continue
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
