"""Dated concrete-contract dividend records. No network or source mutation.

The overview owns this store; the frozen Excel/research scenario APIs retain
their original behavior. Date-only legacy observations retain that precision.
"""
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from contextlib import closing
from datetime import date, datetime
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from .dividends import digest, read_snapshot

TZ = ZoneInfo('Asia/Shanghai')
PARSER_VERSION = 'contract-dividends-v2'
HISTORICAL_CUTOFF = 'T15:05:00+08:00'
DEFAULT_SOURCE = r'\\192.168.91.230\FTPServer\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'
LEGACY_DEFAULT_SOURCE = r'\\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'
MAPPED_DEFAULT_SOURCE = r'Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'
HISTORICAL_POLICY = '按实际合约和定价时刻匹配，缺首份观测借用前序合约；历史在已知快照间插值，已到期尾段线性归零'
MISSING_DIVIDEND = '定价时点缺实际合约及可用前序合约的分红'
DIVIDEND_CONFLICT = '同一生效时刻的分红版本冲突，待明确生效顺序'


def source_directory(config):
    """Resolve only known old defaults to the confirmed share; preserve custom paths."""
    selected=config.get('overview_dividend_source_dir',DEFAULT_SOURCE)
    if str(selected).replace('/','\\').rstrip('\\').casefold() in {
            LEGACY_DEFAULT_SOURCE.casefold(),MAPPED_DEFAULT_SOURCE.casefold()}:return DEFAULT_SOURCE
    return selected


def stamp(value, *, daily_close=True):
    if isinstance(value, date) and not isinstance(value, datetime) or isinstance(value, str) and len(value) == 10:
        value = str(value) + ('T15:00:00' if daily_close else 'T00:00:00')
    value = datetime.fromisoformat(str(value)) if not isinstance(value, datetime) else value
    return (value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)).isoformat()


def remote(path):
    return str(path).startswith(('\\\\', '//'))


def directory(config, local_root):
    return Path(config.get('overview_dividend_cache') or Path(local_root)/'overview_dividends')


def local_sources(config, *, history=False):
    """Rendering may inspect local inputs, never the public-share directory."""
    result = []
    sources = [config.get('dividend_root'), config.get('overview_dividend_file')]
    recursive = set()
    if history:
        from .paths import PATHS
        sources.extend((PATHS.dividend_inputs, PATHS.dividend_archive))
        recursive.update(Path(source) for source in (config.get('dividend_root'), PATHS.dividend_inputs,
                                                     PATHS.dividend_archive) if source)
    for source in sources:
        if not source or remote(source):
            continue
        path = Path(source)
        try:
            files = path.rglob('*.xlsx') if path in recursive else path.glob('*.xlsx')
            result.extend([path] if path.is_file() else sorted(files))
        except OSError:
            pass
    return list(dict.fromkeys(p for p in result if not p.name.startswith(('~$', '.'))))


def records_from_file(path, *, first_seen=None, effective_from=None, metadata=None):
    if metadata is not None:
        from .dividend_curve import PENDING_CONTRACT

    snapshot = read_snapshot(path) if metadata is None else read_snapshot(path, allow_partial=True)
    day = snapshot['date']
    # A filename clock is accepted only when its date agrees with the cached
    # business date. Legacy misleading filenames cannot assign an earlier date.
    match = re.search(r'(\d{4}-\d{2}-\d{2})[_ -](\d{2})(\d{2})(?:\D|$)', Path(path).stem)
    workbook_clock = snapshot.get('business_at')
    filename_clock = day+'T'+match[2]+':'+match[3]+':00' if match and match[1] == day else None
    published_at = workbook_clock or (filename_clock if metadata is None else None)
    effective = effective_from or published_at or day+'T00:00:00'
    effective = stamp(effective)
    if effective[:10] != day:
        raise ValueError('分红生效日期与表内业务日不符')
    result = []
    for item in snapshot['rows']:
        symbol = item['source_contract']
        if metadata is not None and isinstance(symbol,str):
            symbol = symbol.strip().upper()
        source_kind = 'spreadsheet_concrete'
        if metadata is not None and (symbol is None or symbol in PENDING_CONTRACT or symbol == item['alias']):
            from dashboard.native.continuous import slot_map
            from dashboard.indicator_v6.sources import dates_between
            try:
                symbol = slot_map(metadata, item['alias'][:2], day)[0].get(item['alias']) if dates_between(day, day) else None
            except ValueError:
                symbol = None
            source_kind = 'spreadsheet_business_day_mapping'
        if (not isinstance(symbol, str) or not re.fullmatch(r'(IF|IH|IC|IM)\d{4}\.CFE', symbol)
                or symbol[:2] != item['alias'][:2]):
            if metadata is not None:
                continue
            raise ValueError('分红C列须为同品种实际合约')
        row = dict(contract_id=symbol, points=item['points'], effective_from=effective,
            effective_date=day, precision='observed_revision' if effective_from else 'minute' if published_at else 'day',
            source_business_date=day, source_published_at=stamp(published_at) if published_at else None,
            first_seen_at=stamp(first_seen or datetime.now(TZ)), file_sha256=snapshot['file_sha256'],
            parser_version=PARSER_VERSION, source_kind=source_kind)
        if metadata is not None:
            row['source_cell'] = item.get('source_cell')
        row['revision'] = digest({k:v for k,v in row.items() if k != 'first_seen_at'})
        result.append(row)
    if not result:
        raise ValueError('分红表没有可绑定到实际合约的有效记录')
    return result


class DividendStore:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root/'records.sqlite'

    def read(self):
        if not self.path.is_file():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as con:
            return [json.loads(r[0]) for r in con.execute('SELECT payload FROM records ORDER BY effective_from, revision')]

    def import_file(self, path, *, now=None, business_window=None):
        """Append valid input and archive bytes; never replace an older record."""
        import hashlib
        from .bars import _atomic_bytes
        path = Path(path)
        raw = path.read_bytes()
        if len(raw) > 16*1024*1024:
            raise ValueError('分红文件超过16MB限制')
        sha = hashlib.sha256(raw).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        now = now or datetime.now(TZ)
        with closing(sqlite3.connect(self.path, timeout=5)) as con, con:
            con.execute('CREATE TABLE IF NOT EXISTS files (sha TEXT PRIMARY KEY, imported_at TEXT)')
            con.execute('CREATE TABLE IF NOT EXISTS records (revision TEXT PRIMARY KEY, contract_id TEXT, effective_from TEXT, payload TEXT)')
            if con.execute('SELECT 1 FROM files WHERE sha=?', (sha,)).fetchone():
                return dict(status='unchanged', sha256=sha, inserted=0)
            records = records_from_file(path, first_seen=now)
            if any(r['file_sha256'] != sha for r in records):
                raise ValueError('分红源文件读取期间发生变化，等待下次重试')
            business_dates = sorted({r['source_business_date'] for r in records})
            if business_window and not all(business_window[0] <= day <= business_window[1] for day in business_dates):
                return dict(status='outside_range', sha256=sha, inserted=0, business_dates=business_dates)
            # Replacing a date-only file during that same business day is an
            # observation from now onward. Past ambiguous files retain the same
            # date key and are rejected at lookup, never arbitrarily ordered.
            day = records[0]['effective_date']
            if records[0]['precision'] == 'day' and day == now.astimezone(TZ).date().isoformat():
                prior = con.execute('SELECT 1 FROM records WHERE substr(effective_from,1,10)=? LIMIT 1', (day,)).fetchone()
                if prior:
                    records = records_from_file(path, first_seen=now, effective_from=now)
            target = self.root/'raw'/day/(sha+'.xlsx')
            if not target.is_file():
                _atomic_bytes(target, raw)
            for row in records:
                con.execute('INSERT OR IGNORE INTO records VALUES (?,?,?,?)',
                    (row['revision'], row['contract_id'], row['effective_from'], json.dumps(row, ensure_ascii=False)))
            con.execute('INSERT INTO files VALUES (?,?)', (sha, stamp(now)))
        return dict(status='imported', sha256=sha, inserted=len(records), business_dates=business_dates)


class DatedDividendBook:
    mode = 'dated_contract'

    def __init__(self, records, metadata, *, anchor=None, errors=(), inherit_predecessor=True):
        self.metadata = metadata
        self.inherit_predecessor = inherit_predecessor
        self.records = sorted({r['revision']:r for r in records}.values(), key=lambda r:(r['effective_from'], r['revision']))
        self.by_symbol = {}
        for row in self.records:
            self.by_symbol.setdefault(row['contract_id'], []).append(row)
        self.times = {s:[r['effective_from'] for r in rows] for s,rows in self.by_symbol.items()}
        self.version = digest([r['revision'] for r in self.records])
        self.reason = '' if self.records else '待按日期/实际合约保存的分红输入'
        self.info = dict(errors=list(errors), historical_policy='各历史定价时点当时有效的具体合约分红；新版本不回写过去',
            precision_policy='仅日期的旧表保留日精度，不声称当时分钟可得', mapping={})
        if anchor:
            self.info['mapping'] = {s:r for s in metadata if (r:=self.resolve(s, anchor)) and r.get('points') is not None}

    def _direct(self, symbol, at):
        rows = self.by_symbol.get(symbol, [])
        end = bisect_right(self.times.get(symbol, []), at)
        if not end:
            return None
        row = rows[end-1]
        start = bisect_left(self.times[symbol], row['effective_from'], 0, end)
        tied = rows[start:end]
        if len({r['points'] for r in tied}) > 1:
            return dict(points=None, reason=DIVIDEND_CONFLICT,
                        revision=digest([r['revision'] for r in tied]))
        return dict(row, value_source_contract=symbol, source_snapshot=row['source_business_date'],
            expiry=self.metadata.get(symbol, {}).get('expiry_date'))

    def resolve(self, symbol, when):
        return self._resolve(symbol, when, self.inherit_predecessor)

    def resolve_contract(self, symbol, when):
        return self._resolve(symbol, when, False)

    def _resolve(self, symbol, when, inherit_predecessor):
        if not symbol or when is None:
            return None
        at = stamp(when)
        ref = self.metadata.get(symbol)
        if ref and at[:10] > ref['expiry_date']:
            return None
        direct = self._direct(symbol, at)
        if direct is not None:
            return direct
        if not ref or not inherit_predecessor:
            return None
        earlier = sorted((s for s,r in self.metadata.items() if s[:2] == symbol[:2]
            and r['expiry_date'] < ref['expiry_date']), key=lambda s:self.metadata[s]['expiry_date'], reverse=True)
        for previous in earlier:
            row = self._direct(previous, at)
            if row is not None:
                return dict(row, inherited_from=previous, expiry=ref['expiry_date'], source_kind='previous_contract_estimate')
        return None

    def points(self, symbol, when):
        row = self.resolve(symbol, when)
        return row.get('points') if row else None

    def history_version(self, needed):
        return digest([(r['symbol'], r['day'], (self.resolve_contract(r['symbol'], r['day']+HISTORICAL_CUTOFF) or {}).get('revision'))
            for r in needed if r['symbol'] in self.metadata])


class OverviewDividendBook(DatedDividendBook):
    """Point-in-time live lookup plus a bounded cache of retrospective curves."""
    def __init__(self, records, metadata, *, day, errors=()):
        super().__init__(records, metadata, errors=errors, inherit_predecessor=False)
        self.day = day
        self.donor_months = {root: sorted(s for s in self.by_symbol if s[:2] == root)
                             for root in ('IF', 'IH', 'IC', 'IM')}
        self.effective_times = [r['effective_from'] for r in self.records]
        self.history = OrderedDict()
        self.info.update(historical_policy=HISTORICAL_POLICY,
                         mapping={s: row for s, ref in metadata.items()
                                  if ref['listing_date'] <= day <= ref['expiry_date']
                                  and (row := self.resolve(s, day+HISTORICAL_CUTOFF))
                                  and row.get('points') is not None})

    def resolve(self, symbol, when):
        if not symbol or when is None:
            return None
        at = stamp(when)
        ref = self.metadata.get(symbol)
        if ref and at[:10] > ref['expiry_date']:
            return None
        direct = self._direct(symbol, at)
        if direct is not None:
            return direct
        from .dividend_curve import PREVIOUS_CONTRACT, earlier_contracts

        for donor in earlier_contracts(self.donor_months.get(symbol[:2], ()), symbol):
            record = self._direct(donor, at)
            if record is not None and record.get('points') is not None:
                return dict(record, inherited_from=donor, expiry=ref['expiry_date'] if ref else None,
                            source_kind=PREVIOUS_CONTRACT, estimated=True)
        return None

    def historical_view(self, day, now=None):
        if not day:
            day = self.day
        cutoff = min(day+HISTORICAL_CUTOFF, stamp(now)) if now is not None else day+HISTORICAL_CUTOFF
        end = bisect_right(self.effective_times, cutoff)
        key = (day, cutoff[:10], end)
        if key not in self.history:
            available = self.records[:end]
            version = digest(['dividend_curve_v1', day, cutoff[:10], [r['revision'] for r in available]])
            self.history[key] = HistoricalDividendView(day, cutoff, available, self.metadata, version, self.info)
            if len(self.history) > 4:
                self.history.popitem(last=False)
        self.history.move_to_end(key)
        return self.history[key]


class HistoricalDividendView:
    def __init__(self, day, cutoff, records, metadata, version, info):
        self.version = version
        self.info = info
        self.reason = '' if records else MISSING_DIVIDEND
        self.rows = {}
        self.resolved = {}
        if not records:
            return
        import pandas as pd
        from dashboard.indicator_v6.sources import dates_between
        from .dividend_curve import match_curve
        from .trading_calendar import HOLIDAYS

        horizon = pd.Timestamp(day)
        start = max(horizon-pd.DateOffset(months=13, days=15), pd.Timestamp(f'{min(HOLIDAYS)}-01-01'))
        try:
            sessions = dates_between(start.date().isoformat(), day)
        except ValueError:
            self.reason = '缺已核验交易日历，历史分红不可用'
            self.info = {**info, 'historical_policy': self.reason}
            return
        if not sessions:
            return
        # Include every verified session even if there is a gap in the contract
        # reference. An observed value becomes an anchor on that session.
        entries = [(session, '', None) for session in sessions]
        for symbol, ref in metadata.items():
            first = bisect_left(sessions, ref['listing_date'])
            last = bisect_right(sessions, ref['expiry_date'])
            entries.extend((session, symbol, ref['expiry_date']) for session in sessions[first:last])
        panel = pd.DataFrame(entries, columns=['trade_date', 'instrument_id', 'expiry_date'])
        panel['trade_date'] = pd.to_datetime(panel.trade_date)
        panel['expiry_date'] = pd.to_datetime(panel.expiry_date)
        panel['calendar_known'] = True
        panel['order'] = range(len(panel))
        close = pd.Timedelta(hours=15, minutes=5)
        panel['pricing_at'] = (panel.trade_date+close).clip(upper=pd.Timestamp(cutoff).tz_localize(None))
        source = [dict(instrument_id=r['contract_id'], dividend_points=r['points'],
                       dividend_source_date=pd.Timestamp(r['source_business_date']),
                       dividend_effective_at=pd.Timestamp(r['effective_from']).tz_localize(None),
                       dividend_source_sha256=r.get('file_sha256'), dividend_source_cell=r.get('source_cell'),
                       dividend_match=r.get('source_kind', 'dated_concrete'), source_revision=r['revision'],
                       source_precision=r.get('precision')) for r in records]
        matched = match_curve(panel, source, close)
        self.rows = {(r.instrument_id, r.trade_date.date().isoformat()): r
                     for r in matched.itertuples(index=False) if r.instrument_id}

    def historical_record(self, symbol, day):
        key = (symbol, day)
        if key in self.resolved:
            return self.resolved[key]
        row = self.rows.get(key)
        if row is None:
            return {'reason': self.reason or MISSING_DIVIDEND}
        import pandas as pd

        if pd.isna(row.dividend_points):
            reason = DIVIDEND_CONFLICT if row.dividend_match == 'conflicting_same_effective_time' else MISSING_DIVIDEND
            record = {'reason': reason, 'revision': row.source_revision if pd.notna(row.source_revision) else None}
        else:
            def optional(value):
                return value if pd.notna(value) else None

            def day_label(value):
                return value.date().isoformat() if pd.notna(value) else None

            source = row.dividend_source_contract
            record = dict(points=float(row.dividend_points), value_source_contract=source,
                          source_business_date=day_label(row.dividend_source_date),
                          source_snapshot=day_label(row.dividend_source_date),
                          effective_from=stamp(row.dividend_effective_at),
                          file_sha256=optional(row.dividend_source_sha256),
                          source_cell=optional(row.dividend_source_cell), precision=optional(row.source_precision),
                          inherited_from=source if source != symbol else None, source_kind=row.dividend_match,
                          estimated=bool(row.dividend_is_estimated), interpolation=optional(row.dividend_interpolation),
                          anchor_date=day_label(row.dividend_anchor_date), anchor_points=optional(row.dividend_anchor_points),
                          end_date=day_label(row.dividend_end_date), end_points=optional(row.dividend_end_points),
                          end_source_date=day_label(row.dividend_end_source_date),
                          end_source_sha256=optional(row.dividend_end_source_sha256),
                          end_source_cell=optional(row.dividend_end_source_cell))
            record['revision'] = digest([row.source_revision, record]) if record['estimated'] else row.source_revision
        self.resolved[key] = record
        return record


def load(config, metadata, day, local_root=None):
    records = []
    errors = []
    if local_root:
        try:
            records = DividendStore(directory(config, local_root)).read()
        except (OSError, ValueError, sqlite3.Error) as exc:
            errors.append(dict(stage='local_dividend_store', error_type=type(exc).__name__))
    imported = {(r['file_sha256'], r['contract_id']) for r in records}
    hashes = {r['file_sha256'] for r in records}
    for path in local_sources(config, history=True):
        try:
            import hashlib
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if file_hash in hashes:
                continue
            # Store observations take precedence over rereading an older raw file
            # with unknown time; a persisted intraday revision keeps its clock.
            records.extend(r for r in records_from_file(path, metadata=metadata)
                           if (r['file_sha256'],r['contract_id']) not in imported)
            hashes.add(file_hash)
        except Exception as exc:
            errors.append(dict(stage='local_dividend_file', error_type=type(exc).__name__))
    return OverviewDividendBook(records, metadata, day=day, errors=errors)


class DerivedCache:
    """Versioned daily adjusted prices/basis, preloaded once and flushed in batches."""
    def __init__(self, root, *, writable=False):
        self.path = Path(root)/'derived.sqlite'
        self.writable = writable
        self.rows = {}
        self.pending = {}
        self.hits = self.misses = 0
        self.error_type = None
        if self.path.is_file():
            try:
                with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as con:
                    self.rows = {r[0]:json.loads(r[1]) for r in con.execute('SELECT key,payload FROM derived')}
            except (sqlite3.Error, ValueError) as exc:
                self.error_type = type(exc).__name__

    def calculate(self, symbol, day, future, spot, dividend, days, *, dividend_record=None, price_version=None, min_annual_days=1):
        from .overview_basis import calculate, FORMULA
        inputs = dict(symbol=symbol, day=day, future=future, spot=spot, dividend=dividend, days=days,
            dividend_revision=(dividend_record or {}).get('revision'), price_version=price_version, formula=FORMULA,
            min_annual_days=min_annual_days)
        key = digest(inputs)
        if key in self.rows:
            self.hits += 1
            return self.rows[key]['values']
        self.misses += 1
        values = calculate(future, spot, dividend, days, min_annual_days=min_annual_days)
        if values['annual_pct'] is not None:
            self.rows[key] = dict(inputs, values=values)
            if self.writable:
                self.pending[key] = self.rows[key]
        return values

    def flush(self):
        if not self.writable or not self.pending:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(sqlite3.connect(self.path, timeout=2)) as con, con:
                con.execute('CREATE TABLE IF NOT EXISTS derived (key TEXT PRIMARY KEY, payload TEXT)')
                con.executemany('INSERT OR IGNORE INTO derived VALUES (?,?)',
                    [(k,json.dumps(v, ensure_ascii=False, default=str)) for k,v in self.pending.items()])
        except (sqlite3.Error,OSError) as exc:
            self.error_type = type(exc).__name__
            self.writable = False
        self.pending.clear()
