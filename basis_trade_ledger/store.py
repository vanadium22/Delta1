from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3

from shared_data.paths import DataPaths

from .model import LEGS, group_config, now, number, plan_config, trade_data


def data_paths(root=None):
    return DataPaths.for_repo(Path(__file__).resolve().parents[1], data_root=root)


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as con:
            version = con.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('台账数据库版本较新，请更新应用')
            if version == 1:
                return
            con.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY, config TEXT NOT NULL, created TEXT NOT NULL,
                    import_key TEXT UNIQUE, audit TEXT
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
                    version INTEGER NOT NULL DEFAULT 1, data TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS trades_group ON trades(group_id, id);
                CREATE TABLE IF NOT EXISTS revisions (
                    trade_id INTEGER NOT NULL REFERENCES trades(id), version INTEGER NOT NULL,
                    data TEXT NOT NULL, updated TEXT NOT NULL, reason TEXT NOT NULL,
                    PRIMARY KEY (trade_id, version)
                );
                CREATE TABLE IF NOT EXISTS marks (
                    group_id INTEGER NOT NULL REFERENCES groups(id), code TEXT NOT NULL,
                    kind TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (group_id, code, kind)
                );
                CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version=1;
                COMMIT;
            ''')

    @contextmanager
    def connection(self, write=False):
        with closing(sqlite3.connect(self.path, timeout=3)) as con, con:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            if write:
                con.execute('BEGIN IMMEDIATE')
            yield con

    def groups(self):
        with self.connection() as con:
            return [dict(json.loads(row['config']), id=row['id'], imported=bool(row['import_key']))
                    for row in con.execute('SELECT id,config,import_key FROM groups ORDER BY id DESC')]

    def recent(self):
        with self.connection() as con:
            row = con.execute("SELECT value FROM preferences WHERE key='recent'").fetchone()
            return int(row[0]) if row else None

    @staticmethod
    def _set_recent(con, group_id):
        con.execute("INSERT OR REPLACE INTO preferences VALUES ('recent',?)", (str(group_id),))

    def open_group(self, group_id):
        with self.connection(write=True) as con:
            row = con.execute('SELECT config,audit FROM groups WHERE id=?', (group_id,)).fetchone()
            config = json.loads(row['config'])
            trades = [self._trade(row) for row in con.execute(
                'SELECT * FROM trades WHERE group_id=? ORDER BY id', (group_id,))]
            self._set_recent(con, group_id)
            return config, trades, self._quotes(con, group_id, config), json.loads(row['audit'] or 'null')

    @staticmethod
    def _trade(row):
        return dict(json.loads(row['data']), id=row['id'], version=row['version'], updated=row['updated'])

    @staticmethod
    def _quotes(con, group_id, config):
        marks = {(row['code'], row['kind']): json.loads(row['data']) for row in con.execute(
            'SELECT code,kind,data FROM marks WHERE group_id=?', (group_id,))}
        return {leg: next((marks[(config[leg], kind)] for kind in ('manual', 'local', 'excel')
                           if (config[leg], kind) in marks), None) for leg in LEGS}

    def group_quotes(self, group_id, config):
        with self.connection() as con:
            return self._quotes(con, group_id, config)

    def create(self, values):
        config = group_config(values)
        with self.connection(write=True) as con:
            group_id = self._insert_group(con, config)
            self._set_recent(con, group_id)
            return group_id

    @staticmethod
    def _insert_group(con, config, import_key=None, audit=None):
        return con.execute('INSERT INTO groups(config,created,import_key,audit) VALUES (?,?,?,?)',
                           (encode(config), now().isoformat(), import_key, encode(audit) if audit else None)).lastrowid

    def update_plan(self, group_id, values):
        plan = plan_config(values)
        with self.connection(write=True) as con:
            row = con.execute('SELECT config FROM groups WHERE id=?', (group_id,)).fetchone()
            con.execute('UPDATE groups SET config=? WHERE id=?', (encode(dict(json.loads(row[0]), **plan)), group_id))

    @staticmethod
    def _insert_trade(con, group_id, data, *, version=1, updated=None):
        return con.execute('INSERT INTO trades(group_id,data,updated,version) VALUES (?,?,?,?)',
                           (group_id, encode(data), updated or now().isoformat(), version)).lastrowid

    def save_trade(self, group_id, values, status, *, trade_id=None, version=None, reason=''):
        data = trade_data(values, status)
        with self.connection(write=True) as con:
            if trade_id is None:
                return self._insert_trade(con, group_id, data)
            row = con.execute('SELECT * FROM trades WHERE id=? AND group_id=?', (trade_id, group_id)).fetchone()
            if row is None or row['version'] != version:
                raise ValueError('这笔成交已由另一窗口修改，请重开该组后再更正')
            old = json.loads(row['data'])
            if old['status'] == 'posted':
                if status != 'posted' or not reason.strip():
                    raise ValueError('更正已入账成交时请填写原因')
                con.execute('INSERT INTO revisions VALUES (?,?,?,?,?)',
                            (trade_id, version, row['data'], row['updated'], reason.strip()))
            for key in ('origin', 'import_origin', 'pair', 'pair_lots', 'source_status', 'entry_type'):
                if key in old:
                    data[key] = old[key]
            con.execute('UPDATE trades SET data=?, version=version+1, updated=? WHERE id=?',
                        (encode(data), now().isoformat(), trade_id))
            return trade_id

    def revisions(self, group_id, trade_id):
        with self.connection() as con:
            return [dict(json.loads(row['data']), version=row['version'], reason=row['reason'], updated=row['updated'])
                    for row in con.execute('''SELECT r.* FROM revisions r JOIN trades t ON t.id=r.trade_id
                        WHERE t.group_id=? AND t.id=? ORDER BY r.version''', (group_id, trade_id))]

    @staticmethod
    def _save_marks(con, group_id, marks, kind):
        for mark in marks:
            con.execute('INSERT OR REPLACE INTO marks VALUES (?,?,?,?)',
                        (group_id, mark['code'], kind, encode(dict(mark, kind=kind))))

    def set_marks(self, group_id, marks, kind, *, clear=()):
        with self.connection(write=True) as con:
            allowed = json.loads(con.execute('SELECT config FROM groups WHERE id=?', (group_id,)).fetchone()[0])
            symbols = {allowed[leg] for leg in LEGS} - {''}
            if (set(clear) | {mark['code'] for mark in marks}) - symbols:
                raise ValueError('估值代码与当前组不符')
            for symbol in clear:
                con.execute('DELETE FROM marks WHERE group_id=? AND code=? AND kind=?', (group_id, symbol, kind))
            for mark in marks:
                if number(mark['price'], '估值价') is None:
                    raise ValueError('请填写估值价')
            self._save_marks(con, group_id, marks, kind)

    def exchange_groups(self, group_id=None):
        with self.connection() as con:
            con.execute('BEGIN')
            selected = con.execute('SELECT id,config FROM groups WHERE id=?', (group_id,)) if group_id else con.execute(
                'SELECT id,config FROM groups ORDER BY id')
            groups = []
            for row in selected:
                key = row['id']
                trades = [self._trade(trade) for trade in con.execute(
                    'SELECT * FROM trades WHERE group_id=? ORDER BY id', (key,))]
                marks = [json.loads(mark['data']) for mark in con.execute(
                    'SELECT data FROM marks WHERE group_id=? ORDER BY code,kind', (key,))]
                revisions = [dict(json.loads(r['data']), id=r['trade_id'], version=r['version'],
                                  updated=r['updated'], reason=r['reason']) for r in con.execute('''
                    SELECT r.* FROM revisions r JOIN trades t ON t.id=r.trade_id
                    WHERE t.group_id=? ORDER BY r.trade_id,r.version''', (key,))]
                groups.append(dict(id=key, config=json.loads(row['config']), trades=trades, marks=marks, revisions=revisions))
            return groups

    def import_groups(self, previews):
        added, skipped = [], 0
        with self.connection(write=True) as con:
            for group in previews:
                if con.execute('SELECT 1 FROM groups WHERE import_key=?', (group.key,)).fetchone():
                    skipped += 1
                    continue
                group_id = self._insert_group(con, group.config, group.key, group.audit)
                for order, trade in enumerate(group.trades, 1):
                    data = dict(trade)
                    trade_id = self._insert_trade(con, group_id, data, version=data.pop('version', 1),
                                                  updated=data.pop('updated', None))
                    for revision in (group.revisions or {}).get(order, ()):
                        data = dict(revision)
                        version, updated, reason = (data.pop(key) for key in ('version', 'updated', 'reason'))
                        con.execute('INSERT INTO revisions VALUES (?,?,?,?,?)', (
                            trade_id, version, encode(data), updated, reason))
                if group.marks is None:
                    self._save_marks(con, group_id, group.quotes.values(), 'excel')
                else:
                    for mark in group.marks:
                        self._save_marks(con, group_id, [mark], mark['kind'])
                added.append(group_id)
            if added:
                self._set_recent(con, added[0])
        return added, skipped
