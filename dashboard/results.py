"""Dashboard-owned result database and immutable, daily Parquet fragments."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import time

import pyarrow as pa

from index_strategy.instant_dld.realtime_store import WriterLock, publish_parquet
from index_strategy.instant_dld.service import write_json


class ResultStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if __import__("os").name == "nt":
            import ctypes
            if ctypes.windll.kernel32.GetDriveTypeW(str(self.root.anchor)) == 4:
                raise ValueError("结果实时库需要本机磁盘，不能使用网络共享盘")
        self.root.mkdir(parents=True, exist_ok=True)
        # Independent lock and database: never open the collector's quote writer.
        live = self.root / "dashboard_live"
        live.mkdir(exist_ok=True)
        self.writer_lock = WriterLock(live)
        self.connection = None
        try:
            self.connection = sqlite3.connect(live / "results.sqlite3", check_same_thread=False, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS results (
                    id TEXT PRIMARY KEY, factor_id TEXT, version TEXT, name TEXT,
                    calculated_at TEXT, trade_date TEXT, quality TEXT, unit TEXT,
                    values_json TEXT, inputs_json TEXT, archived INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS results_date ON results(trade_date, calculated_at);
                CREATE TABLE IF NOT EXISTS parts (path TEXT PRIMARY KEY, rows INTEGER, created_at TEXT);
            ''')
            self.next_flush = 0.0
        except BaseException:
            self.close(flush=False)
            raise

    def register_formula(self, spec):
        path = self.root / "formulas" / spec["id"] / (spec["version"] + ".json")
        if not path.exists():
            write_json(path, spec)

    def append(self, item):
        with self.connection:
            cursor = self.connection.execute("INSERT OR IGNORE INTO results "
                "(id,factor_id,version,name,calculated_at,trade_date,quality,unit,values_json,inputs_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [item[k] for k in ("id", "factor_id", "version", "name", "calculated_at", "trade_date", "quality", "unit")]
                + [json.dumps(item[k], ensure_ascii=False, allow_nan=False) for k in ("values", "inputs")])
        if time.monotonic() >= self.next_flush:
            self.flush()
        return bool(cursor.rowcount)

    def flush(self):
        groups = self.connection.execute("SELECT DISTINCT factor_id,version,trade_date FROM results WHERE archived=0").fetchall()
        for group in groups:
            rows = [dict(r) for r in self.connection.execute(
                "SELECT * FROM results WHERE factor_id=? AND version=? AND trade_date=? AND archived=0 ORDER BY calculated_at",
                tuple(group))]
            if not rows:
                continue
            day = group["trade_date"]
            path = publish_parquet(pa.Table.from_pylist(rows),
                self.root / "factors" / group["factor_id"] / group["version"] / day[:4] / day[5:7], day)
            with self.connection:
                self.connection.executemany("UPDATE results SET archived=1 WHERE id=?", [(r["id"],) for r in rows])
                self.connection.execute("INSERT INTO parts VALUES (?,?,?)", (path.relative_to(self.root).as_posix(), len(rows), datetime.now().astimezone().isoformat()))
        self.next_flush = time.monotonic() + 60

    def history(self, day=None, factor_id=None, limit=250):
        where, args = [], []
        if day:
            where.append("trade_date=?")
            args.append(day)
        if factor_id:
            where.append("factor_id=?")
            args.append(factor_id)
        clause = " WHERE " + " AND ".join(where) if where else ""
        rows = [dict(r) for r in self.connection.execute(
            "SELECT * FROM results" + clause + " ORDER BY calculated_at DESC LIMIT ?", [*args, limit])]
        for row in rows:
            row["values"] = json.loads(row.pop("values_json"))
            row["inputs"] = json.loads(row.pop("inputs_json"))
        return rows

    def stats(self):
        row = dict(self.connection.execute("SELECT COUNT(*) AS rows, SUM(archived=0) AS pending, MAX(calculated_at) AS last_at FROM results").fetchone())
        row["parts"] = self.connection.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
        row["root"] = str(self.root)
        return row

    def close(self, flush=True):
        try:
            if self.connection is not None:
                if flush:
                    self.flush()
        finally:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
            self.writer_lock.close()
