from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
from time import monotonic

from index_strategy.instant_dld.consumer_quotes import MAX_CODES, QuoteSubscription, supported
from shared_data.readers import LocalData

from .model import LEGS, SHANGHAI, now, number
from .wind_close import WIND_CLOSE, WIND_LOCAL_CLOSE, download_closes


POLL_MS = 3000


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


def newer_closes(marks, existing):
    result = []
    for mark in marks:
        old = existing.get(mark['code'])
        if old:
            timestamp, previous = mark.get('time') or '', old.get('time') or ''
            if timestamp < previous:
                continue
            if timestamp == previous:
                if old['source'] == mark['source']:
                    if str(old['price']) == str(mark['price']):
                        continue
                elif old['source'] == WIND_CLOSE or (old['source'] == WIND_LOCAL_CLOSE and mark['source'] != WIND_CLOSE):
                    continue
        result.append(mark)
    return result


def effective_marks(config, base_marks, update, at):
    quotes = dict(base_marks)
    if not update:
        return quotes
    closes = {mark['code']: dict(mark, kind='local') for mark in update.closes}
    for leg in LEGS:
        base = quotes.get(leg)
        if base and base.get('kind') == 'manual':
            continue
        symbol = config[leg]
        live = update.live.get(symbol)
        old_live = base if base and base.get('kind') == 'live' else None
        candidates = [mark for mark in (live, old_live) if mark and _timestamp(mark.get('time')) and
                      at - _timestamp(mark['time']) <= timedelta(seconds=30)]
        if candidates:
            quotes[leg] = max(candidates, key=lambda mark: mark['time'])
            continue
        close = closes.get(symbol)
        if close and (not base or newer_closes([close], {symbol: base})):
            base = quotes[leg] = close
        reference = update.reference.get(symbol)
        if reference:
            day = reference['time'][:10]
            base_day = (base.get('time') or '')[:10] if base else ''
            if base and base.get('source') in (WIND_CLOSE, WIND_LOCAL_CLOSE) and day == base_day:
                continue
            if not base or day >= (base_day or (at.date() - timedelta(days=7)).isoformat()):
                if not base or day != base_day or reference['time'] > (base.get('time') or ''):
                    quotes[leg] = reference
    return quotes


class MarketQuotes:
    def __init__(self, paths, *, clock=now, client_factory=None, phase=None, wind_fetcher=download_closes):
        self.paths, self.clock, self.client_factory, self.phase = paths, clock, client_factory, phase
        self.wind_fetcher = wind_fetcher
        self.client = None
        self.direct = {}
        self.references = {}
        self.retry_at = 0
        self.retry_codes = ()
        self.retry_message = ''
        self.subscription = QuoteSubscription()
        self.wind_quotes = {}
        self.wind_pending = {}

    def close(self):
        self.subscription.close()
        if self.client:
            self.client.close()
            self.client = None

    def refresh(self, codes, *, force=False, on_cached=None, saved_closes=None, cache_only=False, allow_wind=True,
                subscribe=True):
        from dashboard.marketdata.quote_quality import quote_quality
        from dashboard.session_clock import market_phase
        from index_strategy.instant_dld.reader import RealtimeReader

        profile, config, root = dashboard_profile(self.paths)
        at = self.clock()
        phase = (self.phase or market_phase)(at)
        continuous = phase['continuous']
        codes = tuple(sorted({c for c in codes if supported(c)}))
        registered = self.subscription.publish(root, codes, at) if continuous and subscribe else False
        if not continuous or not subscribe:
            self.subscription.close()
        if not codes:
            return QuoteUpdate({}, {}, [], '请填写带交易所后缀的实际标的代码')
        reader = RealtimeReader(root)
        cache_message = ''
        try:
            rows = reader.latest_records(codes) if reader.db_path.is_file() else {}
        except (OSError, sqlite3.Error):
            rows = {}
            cache_message = '看板缓存读取失败'
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
            needed = [s for s in codes if s not in live or (live[s]['source'] == '网厅 · 实时直连' and
                      (force or (at - _timestamp(live[s]['observed_at'])).total_seconds() >= 2.8))]
            if self.retry_codes != codes:
                self.retry_at, self.retry_codes, self.retry_message = 0, codes, ''
            if needed and not cache_only and (force or monotonic() >= self.retry_at):
                if on_cached:
                    on_cached(QuoteUpdate(live.copy(), self._references(codes), [], '看板缓存 · 后台补查中'))
                # Fetch the pair in one batch when only one side is covered or refreshed.
                self.retry_message = self._fetch(list(codes[:MAX_CODES]), config, live, fresh)
            live = {symbol: mark for symbol, mark in live.items() if mark and
                    (self.clock() - _timestamp(mark['time'])).total_seconds() <= 30}
            missing = [s for s in codes if s not in live]
            if missing:
                reason = self.retry_message if not cache_only and self.retry_at > monotonic() else ''
                subscription_status = '已登记看板订阅' if registered else '订阅目录不可写' if subscribe else ''
                labels = []
                for symbol in missing[:4]:
                    raw = rows.get(symbol)
                    status = quote_quality(raw, at) if raw and raw.get('source_symbol') == symbol else None
                    detail = status['status'] if status and not status['usable'] else '缓存身份或价格校验失败' if raw else ''
                    labels.append(f'{symbol}（{detail}）' if detail else symbol)
                if len(missing) > len(labels):
                    labels.append(f'等 {len(missing)} 个标的')
                message = ' · '.join(filter(None, (reason, cache_message, subscription_status, '待实时价 ' + '、'.join(labels))))
        refs = self._references(codes)
        if allow_wind and phase.get('phase') in ('post_close', 'closed_day'):
            from dashboard.marketdata.overview_sessions import latest_completed_session
            try:
                day = latest_completed_session(at)
            except ValueError:
                day = None
            if day and (phase['phase'] == 'closed_day' or day == at.astimezone(SHANGHAI).date().isoformat()):
                return self._after_close(codes, day, profile, config, refs, saved_closes or {}, force, on_cached)
            if day and not force:
                return QuoteUpdate({}, refs, [], '等候当日 Wind 收盘数据')
        if on_cached and force and any(s not in live for s in codes):
            on_cached(QuoteUpdate(live, refs, [], message))
        closes, _ = local_closes(self.paths, [s for s in codes if s not in live]) if force and any(s not in live for s in codes) else ([], [])
        closes = newer_closes(closes, saved_closes or {})
        return QuoteUpdate(live, refs, closes, message)

    def _references(self, codes):
        return {s: self.references[s] for s in codes if s in self.references}

    def _after_close(self, codes, day, profile, config, refs, saved, force, on_cached):
        deadline = monotonic()
        confirmed = (WIND_CLOSE, WIND_LOCAL_CLOSE)

        def is_current(mark):
            return mark and mark.get('time') == day and mark.get('source') in confirmed

        for symbol in codes:
            if is_current(saved.get(symbol)):
                old = self.wind_quotes.get((day, symbol))
                if not old or newer_closes([saved[symbol]], {symbol: old}):
                    self.wind_quotes[(day, symbol)] = saved[symbol]
        need = [symbol for symbol in codes if (day, symbol) not in self.wind_quotes and
                (force or self.wind_pending.get((day, symbol), (0, ''))[0] <= deadline)]
        fallback = []
        if need:
            if on_cached:
                on_cached(QuoteUpdate({}, refs, [], '正在读取 Wind 盘后收盘价'))
            fallback, _ = local_closes(self.paths, need, end=day)
            for mark in fallback:
                if is_current(mark):
                    self.wind_quotes[(day, mark['code'])] = mark
            ask = [symbol for symbol in need if (day, symbol) not in self.wind_quotes]
            if ask:
                prices, error = self.wind_fetcher(ask, day, config, profile)
                for symbol in ask:
                    try:
                        price = number(prices.get(symbol), 'Wind 收盘价')
                    except ValueError:
                        price = None
                    if price and price < 10**10:
                        self.wind_quotes[(day, symbol)] = dict(code=symbol, price=price, time=day, source=WIND_CLOSE)
                        self.wind_pending.pop((day, symbol), None)
                    else:
                        self.wind_pending[(day, symbol)] = (monotonic() + 300, error or 'Wind 当日收盘价缺项')
        current = [self.wind_quotes[(day, s)] for s in codes if (day, s) in self.wind_quotes]
        ready = {mark['code'] for mark in current}
        message = f'Wind 收盘 {day} · {len(ready)}/{len(codes)}'
        missing = [self.wind_pending.get((day, s), (0, 'Wind 当日收盘价缺项'))[1] for s in codes if s not in ready]
        if missing:
            message += ' · ' + '、'.join(dict.fromkeys(missing))
        marks = current + [mark for mark in fallback if mark['code'] not in ready]
        return QuoteUpdate({}, refs, newer_closes(marks, saved), message)

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
            return ('行情通道正在使用' if getattr(exc, 'lock_operation', '') == 'acquire_byte_lock'
                    else '行情通道不可用')
        good = result.get('status') in ('success', 'partial')
        self.retry_at = 0 if good else monotonic() + 15
        if not good:
            return {'timeout': '网厅请求超时', 'connection_error': '网厅连接失败', 'tls_error': '网厅证书校验失败',
                    'proxy_error': '网厅代理连接失败'}.get(result.get('status'), '网厅暂不可用')
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
            return '网厅未返回有效报价'
        return None


def local_closes(paths, codes, *, end=None):
    from datetime import date

    end = date.fromisoformat(end) if end else now().date()
    start = end - timedelta(days=35)
    found, problems = {}, []
    for mode, source in (('wind', WIND_LOCAL_CLOSE), ('offline', '离线库收盘')):
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
