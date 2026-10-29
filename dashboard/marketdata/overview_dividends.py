"""Dated concrete-contract dividend records. No network or source mutation.

The overview owns this store; the frozen Excel/research scenario APIs retain
their original behavior. Date-only legacy observations retain that precision.
"""
from bisect import bisect_right
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
DEFAULT_SOURCE = r'Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'
LEGACY_DEFAULT_SOURCE = r'\\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'


def source_directory(config):
    """Use the user-confirmed mapped drive; retain unrelated custom/empty paths."""
    selected=config.get('overview_dividend_source_dir',DEFAULT_SOURCE)
    if str(selected).replace('/','\\').rstrip('\\').casefold()==LEGACY_DEFAULT_SOURCE.casefold():return DEFAULT_SOURCE
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


def local_sources(config):
    """Rendering may inspect local inputs, never the public-share directory."""
    result = []
    for source in (config.get('dividend_root'), config.get('overview_dividend_file')):
        if not source or remote(source):
            continue
        path = Path(source)
        try:
            result.extend([path] if path.is_file() else sorted(path.glob('*.xlsx')))
        except OSError:
            pass
    return list(dict.fromkeys(p for p in result if not p.name.startswith(('~$', '.'))))


def records_from_file(path, *, first_seen=None, effective_from=None):
    snapshot = read_snapshot(path)
    day = snapshot['date']
    # A filename clock is accepted only when its date agrees with the cached
    # business date. Legacy misleading filenames cannot assign an earlier date.
    match = re.search(r'(\d{4}-\d{2}-\d{2})[_ -](\d{2})(\d{2})(?:\D|$)', Path(path).stem)
    precise = bool(match and match[1] == day)
    effective = effective_from or (day+'T'+match[2]+':'+match[3]+':00' if precise else day+'T00:00:00')
    effective = stamp(effective)
    if effective[:10] != day:
        raise ValueError('分红生效日期与表内业务日不符')
    result = []
    for item in snapshot['rows']:
        symbol = item['source_contract']
        if (not isinstance(symbol, str) or not re.fullmatch(r'(IF|IH|IC|IM)\d{4}\.CFE', symbol)
                or symbol[:2] != item['alias'][:2]):
            raise ValueError('分红C列须为同品种实际合约')
        row = dict(contract_id=symbol, points=item['points'], effective_from=effective,
            effective_date=day, precision='minute' if precise else 'observed_revision' if effective_from else 'day',
            source_business_date=day, source_published_at=effective if precise else None,
            first_seen_at=stamp(first_seen or datetime.now(TZ)), file_sha256=snapshot['file_sha256'],
            parser_version=PARSER_VERSION, source_kind='spreadsheet_concrete')
        row['revision'] = digest({k:v for k,v in row.items() if k != 'first_seen_at'})
        result.append(row)
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

    def __init__(self, records, metadata, *, anchor=None, errors=()):
        self.metadata = metadata
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
        tied = [r for r in rows[:end] if r['effective_from'] == row['effective_from']]
        if len({r['points'] for r in tied}) > 1:
            return dict(points=None, reason='同日无时刻的分红版本冲突，待明确生效顺序')
        return dict(row, value_source_contract=symbol, source_snapshot=row['source_business_date'],
            expiry=self.metadata.get(symbol, {}).get('expiry_date'))

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
        if not ref:
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
        return digest([(r['symbol'], r['day'], (self.resolve(r['symbol'], r['day']) or {}).get('revision'))
            for r in needed if r['symbol'] in self.metadata])


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
    for path in local_sources(config):
        try:
            import hashlib
            if hashlib.sha256(path.read_bytes()).hexdigest() in hashes:
                continue
            # Store observations take precedence over rereading an older raw file
            # with unknown time; a persisted intraday revision keeps its clock.
            records.extend(r for r in records_from_file(path) if (r['file_sha256'],r['contract_id']) not in imported)
        except Exception as exc:
            errors.append(dict(stage='local_dividend_file', error_type=type(exc).__name__))
    return DatedDividendBook(records, metadata, anchor=day, errors=errors)


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

    def calculate(self, symbol, day, future, spot, dividend, days, *, dividend_record=None, price_version=None):
        from .overview_basis import calculate, FORMULA
        inputs = dict(symbol=symbol, day=day, future=future, spot=spot, dividend=dividend, days=days,
            dividend_revision=(dividend_record or {}).get('revision'), price_version=price_version, formula=FORMULA)
        key = digest(inputs)
        if key in self.rows:
            self.hits += 1
            return self.rows[key]['values']
        self.misses += 1
        values = calculate(future, spot, dividend, days)
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
