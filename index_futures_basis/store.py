"""Durable raw daily data; each connection belongs to its calling thread."""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3

import pandas as pd

from .analytics import ROOTS, validate_panel
from .config import timestamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendar(day TEXT PRIMARY KEY, is_open INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS mapping(day TEXT, root TEXT, slot INTEGER, code TEXT NOT NULL,
 PRIMARY KEY(day,root,slot));
CREATE TABLE IF NOT EXISTS contracts(code TEXT PRIMARY KEY, expiry TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes(code TEXT, day TEXT, field TEXT, value REAL NOT NULL,
 PRIMARY KEY(code,day,field));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_runs(id INTEGER PRIMARY KEY, started TEXT, finished TEXT,
 requested_end TEXT, state TEXT, requests INTEGER DEFAULT 0, message TEXT);
CREATE INDEX IF NOT EXISTS quote_days ON quotes(day);
"""


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    @contextmanager
    def writer_lock(self):
        """OS releases this lock on process exit, including crashes."""
        path = self.path.with_suffix(".lock")
        with path.open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if __import__("os").name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("另一个窗口正在更新此行情库，请等待完成") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if __import__("os").name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def meta(self, key, default=None):
        with self.connection() as con:
            row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        with self.connection() as con:
            con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def calendar(self, start, end):
        with self.connection() as con:
            return dict(con.execute("SELECT day,is_open FROM calendar WHERE day BETWEEN ? AND ? ORDER BY day", (str(start), str(end))))

    def save_calendar(self, start, end, open_days):
        rows = [(str(d.date()), int(str(d.date()) in open_days)) for d in pd.date_range(start, end)]
        with self.connection() as con:
            con.executemany("INSERT OR REPLACE INTO calendar VALUES(?,?)", rows)

    def mappings(self, start, end):
        with self.connection() as con:
            rows = con.execute("SELECT * FROM mapping WHERE day BETWEEN ? AND ? ORDER BY day,root,slot", (str(start), str(end))).fetchall()
        import re
        return {(r["day"], r["root"], r["slot"]): r["code"] for r in rows
                if r["slot"] in range(1, 5) and re.fullmatch(r["root"] + r"\d{4}\.CFE", r["code"])}

    def expiries(self):
        with self.connection() as con:
            rows = con.execute("SELECT code,expiry FROM contracts").fetchall()
        valid = {}
        for code, day in rows:
            try:
                if str(pd.Timestamp(day).date()) == day:
                    valid[code] = day
            except (TypeError, ValueError):
                pass
        return valid

    def quotes(self, start, end):
        with self.connection() as con:
            rows = con.execute("SELECT * FROM quotes WHERE day BETWEEN ? AND ?", (str(start), str(end))).fetchall()
        return {(r["code"], r["day"], r["field"]): r["value"] for r in rows
                if math.isfinite(r["value"]) and (r["value"] > 0 if r["field"] == "close"
                    else r["value"] >= 0 and float(r["value"]).is_integer())}

    def save_rows(self, table, rows):
        if table not in {"mapping", "contracts", "quotes"}:
            raise ValueError("Unsupported table")
        if not rows:
            return
        width = {"mapping": 4, "contracts": 2, "quotes": 4}[table]
        with self.connection() as con:
            con.executemany(f"INSERT OR REPLACE INTO {table} VALUES({','.join('?' * width)})", rows)

    def start_run(self, end):
        with self.connection() as con:
            cur = con.execute("INSERT INTO sync_runs(started,requested_end,state) VALUES(?,?,?)", (timestamp(), str(end), "running"))
            return cur.lastrowid

    def finish_run(self, run, state, requests, message):
        with self.connection() as con:
            con.execute("UPDATE sync_runs SET finished=?,state=?,requests=?,message=? WHERE id=?",
                        (timestamp(), state, requests, message, run))

    def runs(self, limit=15):
        with self.connection() as con:
            return [dict(r) for r in con.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,))]

    def bounds(self):
        with self.connection() as con:
            row = con.execute("SELECT min(day),max(day) FROM calendar WHERE is_open=1").fetchone()
        return tuple(row)

    def latest_available(self, end):
        """Last cached observation at/before cutoff, without an all-roots requirement."""
        with self.connection() as con:
            row = con.execute("""SELECT max(day) FROM quotes WHERE day<=? AND value<1e308
                AND ((field='close' AND value>0) OR
                     (field='oi' AND value>=0 AND value=CAST(value AS INTEGER)))""", (str(end),)).fetchone()
        return row[0]

    def roots(self):
        with self.connection() as con:
            return tuple(r[0] for r in con.execute("SELECT DISTINCT root FROM mapping ORDER BY root"))

    def coverage(self, start, end, roots=tuple(ROOTS)):
        days = [d for d, opened in self.calendar(start, end).items() if opened]
        mappings, expiries, quotes = self.mappings(start, end), self.expiries(), self.quotes(start, end)
        rows = []
        complete_days = set(days)
        for root in roots:
            missing, complete = [], []
            for day in days:
                problems = []
                if (ROOTS[root], day, "close") not in quotes:
                    problems.append("指数收盘价")
                for slot in range(1, 5):
                    code = mappings.get((day, root, slot))
                    if not code:
                        problems.append(f"{root}0{slot-1}映射")
                        continue
                    if code not in expiries or expiries[code] < day:
                        problems.append(f"{code}到期日")
                    for field in ("close", "oi"):
                        if (code, day, field) not in quotes:
                            problems.append(f"{code}.{field}")
                if problems:
                    missing.append({"day": day, "fields": problems})
                    complete_days.discard(day)
                else:
                    complete.append(day)
            rows.append({"root": root, "expected_days": len(days), "complete_days": len(complete),
                         "first": complete[0] if complete else None, "last": complete[-1] if complete else None,
                         "missing_days": len(missing), "missing": missing})
        return {"rows": rows, "calendar_days": len(days), "latest_complete": max(complete_days) if complete_days else None,
                "missing_fields": sum(len(m["fields"]) for r in rows for m in r["missing"])}

    def panel(self, start, end, roots=tuple(ROOTS)):
        calendar = self.calendar(start, end)
        first = self.bounds()[0]
        if first:
            unknown = [str(d.date()) for d in pd.date_range(max(str(start), first), end)
                       if str(d.date()) not in calendar]
            if unknown:
                raise ValueError(f"交易日历尚未完整校验：{unknown[0]} 等 {len(unknown)} 个日期，请先补齐")
        days = [d for d, opened in calendar.items() if opened]
        mapping, expiry, quotes = self.mappings(start, end), self.expiries(), self.quotes(start, end)
        records = []
        for (day, root, slot), code in mapping.items():
            if root not in roots:
                continue
            records.append({"trade_date": day, "root": root, "slot": slot, "instrument_id": code,
                            "expiry_date": expiry.get(code), "futures_close": quotes.get((code, day, "close")),
                            "open_interest": quotes.get((code, day, "oi")),
                            "spot_close": quotes.get((ROOTS[root], day, "close"))})
        if not records:
            raise ValueError("本地还没有完整行情，请先增量同步或导入离线快照")
        return validate_panel(pd.DataFrame(records), list(roots), days)

    def import_raw(self, raw, source):
        panel = validate_panel(pd.DataFrame(raw["records"]), list(ROOTS), raw["calendar"])
        if panel.empty:
            raise ValueError("快照为空")
        if raw.get("actual_end") and pd.Timestamp(raw["actual_end"]) != panel.trade_date.max():
            raise ValueError("快照标注的截止日与实际行情不一致")
        with self.writer_lock():
            # One transaction: an invalid or interrupted import cannot replace a good snapshot.
            with self.connection() as con:
                for table in ("calendar", "mapping", "contracts", "quotes"):
                    con.execute(f"DELETE FROM {table}")
                open_days = set(panel.trade_date.dt.strftime("%Y-%m-%d"))
                con.executemany("INSERT INTO calendar VALUES(?,?)", [(str(d.date()), int(str(d.date()) in open_days))
                    for d in pd.date_range(panel.trade_date.min(), panel.trade_date.max())])
                for r in panel.itertuples():
                    day = str(r.trade_date.date())
                    con.execute("INSERT INTO mapping VALUES(?,?,?,?)", (day, r.root, r.slot, r.instrument_id))
                    con.execute("INSERT OR REPLACE INTO contracts VALUES(?,?)", (r.instrument_id, str(r.expiry_date.date())))
                    con.executemany("INSERT OR REPLACE INTO quotes VALUES(?,?,?,?)", [
                        (r.instrument_id, day, "close", r.futures_close), (r.instrument_id, day, "oi", r.open_interest),
                        (ROOTS[r.root], day, "close", r.spot_close)])
                con.execute("INSERT OR REPLACE INTO meta VALUES('source',?)", (json.dumps(source, ensure_ascii=False),))
        return len(panel)
