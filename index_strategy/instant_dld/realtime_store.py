"""Transactional live quotes and immutable, catalogued Parquet fragments."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from .quotes import DEPTH_COLUMNS, IDENTITY_COLUMNS, QUOTE_COLUMNS, normalize_quote

DEFAULT_OUTPUT = Path("Z:/Project_data/realtime_market")
DB_RELATIVE = Path("live/quotes.sqlite3")
SCHEMA = pa.schema([
    pa.field("sequence", pa.int64()), pa.field("timestamp", pa.timestamp("ms", tz="UTC")),
    pa.field("symbol", pa.string()),
    *[pa.field(name, pa.string()) for name in IDENTITY_COLUMNS], pa.field("quote_time", pa.string()),
    *[pa.field(name, pa.float64()) for name in ["close", "volume", "volume_total", *DEPTH_COLUMNS]],
    pa.field("quality_flags", pa.uint16()),
], metadata={b"schema_version": b"swhy_realtime_v2", b"timestamp_semantics": b"capture_time_floor_second_UTC",
             b"quote_time_semantics": b"source_HHMMSS_exchange_date_unavailable",
             b"source_symbol": b"actual_requested_contract;symbol_is_maintained_alias",
             b"mapping_date": b"completed_session_date_used_for_main_contract_mapping",
             b"trading_date": b"resolved_session_date_when_available;not_exchange_reported",
             b"volume": b"difference_between_successful_cumulative_observations;first_or_reset=null",
             b"volume_total": b"tradedQuantities;source_native_units_unverified",
             b"depth_volume": b"bNStocks/sNStocks;source_native_units_unverified",
             b"invalid_price": b"zero_or_INT64_MAX_div_1e6_to_null"})


class WriterBusyError(ValueError):
    pass


class WriterLock:
    """OS lock: a crashed writer releases ownership without stale-lock deletion."""
    def __init__(self, root: Path):
        self.stream = (root / ".writer.lock").open("a+b")
        if self.stream.seek(0, os.SEEK_END) == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise WriterBusyError("此数据目录已有采集程序在写入，请先停止另一个任务") from exc

    def close(self):
        if not self.stream.closed:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_UN)
            self.stream.close()


def publish_parquet(table: pa.Table, directory: Path, prefix: str) -> Path:
    """Readers can discover only a closed, fsynced file; existing files stay intact."""
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer, compression="zstd")
    contents = buffer.getvalue().to_pybytes()
    digest = hashlib.sha256(contents).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{prefix}.{digest}.parquet"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise OSError(f"已发布文件校验失败：{target}")
        return target
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".publishing-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.rename(target)
        if os.name != "nt":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class RealtimeStore:
    def __init__(self, root: Path, *, archive_interval: float = 60):
        self.root = Path(root).expanduser().resolve()
        if os.name == "nt":
            import ctypes
            if ctypes.windll.kernel32.GetDriveTypeW(str(self.root.anchor)) == 4:
                raise ValueError("实时库需要本机磁盘；网络共享盘不支持 SQLite WAL 并发读取")
        self.root.mkdir(parents=True, exist_ok=True)
        self.writer_lock = WriterLock(self.root)
        self.connection = None
        self.archive_interval = archive_interval
        self.next_archive = 0.0
        self.run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
        self.run_dir = self.root / "live"
        self.db_path = self.root / DB_RELATIVE
        self.last_rows = []
        self.last_report = None
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.db_path, timeout=5)
            self.connection.row_factory = sqlite3.Row
            mode = self.connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise OSError("数据目录无法启用 WAL 并发读写模式")
            self.connection.execute("PRAGMA synchronous=FULL")
            self._create_schema()
        except BaseException:
            if self.connection is not None:
                self.connection.close()
            self.writer_lock.close()
            raise

    def _create_schema(self):
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            raise ValueError(f"不支持的实时库版本：{version}")
        floats = ", ".join(f'"{name}" REAL' for name in ["close", "volume", "volume_total", *DEPTH_COLUMNS])
        # Keep ALTERs, historical identity backfill and version upgrade atomic.
        # An interrupted upgrade remains a readable v1 database.
        try:
            self.connection.executescript(f"""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS quotes (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL,
                capture_date TEXT NOT NULL, symbol TEXT NOT NULL,
                source_symbol TEXT NOT NULL, mapping_date TEXT, trading_date TEXT, quote_time TEXT,
                {floats}, quality_flags INTEGER NOT NULL, run_id TEXT NOT NULL, poll INTEGER, batch INTEGER
            );
            CREATE INDEX IF NOT EXISTS quotes_symbol_sequence ON quotes(symbol, sequence);
            CREATE INDEX IF NOT EXISTS quotes_date_symbol ON quotes(capture_date, symbol, sequence);
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY, run_id TEXT, timestamp TEXT, poll INTEGER, batch INTEGER,
                status TEXT, requested INTEGER, saved INTEGER, failed_symbols TEXT, description TEXT
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT,
                interval_seconds REAL, polls_started INTEGER, requests_saved INTEGER, symbols TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, run_id TEXT, timestamp TEXT, kind TEXT, description TEXT
            );
            CREATE TABLE IF NOT EXISTS parquet_parts (
                path TEXT PRIMARY KEY, symbol TEXT NOT NULL, capture_date TEXT NOT NULL,
                first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL, rows INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS parts_symbol_date ON parquet_parts(symbol, capture_date);
            CREATE TABLE IF NOT EXISTS main_contract_resolutions (
                symbol TEXT NOT NULL, trading_date TEXT NOT NULL, source_symbol TEXT NOT NULL,
                mapping_date TEXT, PRIMARY KEY(symbol,trading_date)
            );
            """)
            existing = {row[1] for row in self.connection.execute("PRAGMA table_info(quotes)")}
            for name in IDENTITY_COLUMNS:
                if name not in existing:
                    definition = "TEXT NOT NULL DEFAULT ''" if name == "source_symbol" else "TEXT"
                    self.connection.execute(f"ALTER TABLE quotes ADD COLUMN {name} {definition}")
            if version < 2 or not set(IDENTITY_COLUMNS).issubset(existing):
                self.connection.execute("UPDATE quotes SET source_symbol=symbol WHERE source_symbol IS NULL OR source_symbol=''")
            self.connection.execute("PRAGMA user_version=2")
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def pinned_contract(self, symbol: str, trading_date: str) -> dict | None:
        row = self.connection.execute("SELECT source_symbol,mapping_date,trading_date "
                                      "FROM main_contract_resolutions WHERE symbol=? AND trading_date=?",
                                      (symbol, trading_date)).fetchone()
        return dict(row) if row is not None else None

    def pin_contract(self, symbol: str, mapping: dict) -> dict:
        if not mapping.get("trading_date") or not mapping.get("source_symbol"):
            raise ValueError("固定主力合约需要实际合约和交易日")
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO main_contract_resolutions "
                                    "(symbol,trading_date,source_symbol,mapping_date) VALUES (?,?,?,?)",
                                    (symbol, mapping["trading_date"], mapping["source_symbol"], mapping.get("mapping_date")))
        return self.pinned_contract(symbol, mapping["trading_date"])

    def manifest(self, value: dict):
        with self.connection:
            self.connection.execute("""INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET finished_at=excluded.finished_at,
                status=excluded.status, polls_started=excluded.polls_started, requests_saved=excluded.requests_saved""",
                (self.run_id, value["started_at"], value.get("finished_at"), value["status"],
                 value["interval_seconds"], value["polls_started"], value.get("requests_saved", 0),
                 ",".join(value["initial_symbols"])))

    def event(self, kind: str, **details):
        with self.connection:
            self.connection.execute("INSERT INTO events(run_id,timestamp,kind,description) VALUES (?,?,?,?)",
                (self.run_id, datetime.now().astimezone().isoformat(), kind,
                 "; ".join(f"{key}={value}" for key, value in details.items())))

    def batch(self, record: dict):
        rows, failures = [], {}
        payload = record.get("response")
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}
        acceptable = record["status"] in {"success", "partial"}
        mappings = record.get("symbol_mapping", {})
        for symbol in record["symbols"]:
            quote = data.get(symbol) if acceptable else None
            if not isinstance(quote, dict) or not quote:
                failures[symbol] = record.get("error") or record["status"]
                continue
            previous = self.connection.execute(
                "SELECT capture_date,symbol,source_symbol,trading_date,quote_time,volume_total "
                "FROM quotes WHERE symbol=? ORDER BY sequence DESC LIMIT 1",
                (symbol,)).fetchone()
            try:
                identity = mappings.get(symbol, {})
                rows.append(normalize_quote(symbol, quote, record["received_at"], dict(previous) if previous else None,
                                            **{name: identity.get(name) for name in IDENTITY_COLUMNS}))
            except ValueError as exc:
                failures[symbol] = str(exc)
        status = "success" if len(rows) == len(record["symbols"]) else "partial" if rows else "failed"
        description = f"第 {record['poll']} 轮 / 批次 {record['batch']}/{record['batch_count']}：保存 {len(rows)}/{len(record['symbols'])} 个标的"
        if failures:
            description += "；" + "；".join(dict.fromkeys(failures.values()))
        incomplete = sum(bool(row["quality_flags"] & 7) for row in rows)
        if incomplete:
            description += f"；{incomplete} 个标的有缺失字段，已留空并标记"
        columns = ["timestamp", "capture_date", "symbol", *IDENTITY_COLUMNS, "quote_time", "close", "volume", "volume_total",
                   *DEPTH_COLUMNS, "quality_flags"]
        sql = f"INSERT INTO quotes ({','.join(columns)},run_id,poll,batch) VALUES ({','.join('?' for _ in range(len(columns)+3))})"
        with self.connection:
            for row in rows:
                inserted = self.connection.execute(sql, [row[name] for name in columns] +
                                                   [self.run_id, record["poll"], record["batch"]])
                row["sequence"] = inserted.lastrowid
            self.connection.execute("""INSERT INTO batches
                (run_id,timestamp,poll,batch,status,requested,saved,failed_symbols,description) VALUES (?,?,?,?,?,?,?,?,?)""",
                (self.run_id, record["received_at"], record["poll"], record["batch"], status,
                 len(record["symbols"]), len(rows), ",".join(failures), description))
        # Expose only committed data. A UI observer must never see partial batches.
        self.last_rows = rows
        self.last_report = {"timestamp": record["received_at"], "status": status,
                            "description": description, "failed_symbols": list(failures)}
        record["storage_status"] = status
        record["failed_symbols"] = list(failures)
        if acceptable and status != "success":
            record["status"] = "partial" if rows else "invalid_quote"
        if time.monotonic() >= self.next_archive:
            self.flush_parquet()
            self.next_archive = time.monotonic() + self.archive_interval

    def flush_parquet(self):
        groups = self.connection.execute("""SELECT q.symbol,q.capture_date,COALESCE(p.archived,0) AS archived
            FROM (SELECT symbol,capture_date,MAX(sequence) AS newest FROM quotes GROUP BY symbol,capture_date) q
            LEFT JOIN (SELECT symbol,capture_date,MAX(last_sequence) AS archived FROM parquet_parts
                       GROUP BY symbol,capture_date) p
            ON q.symbol=p.symbol AND q.capture_date=p.capture_date
            WHERE q.newest>COALESCE(p.archived,0)""").fetchall()
        for group in groups:
            after = group["archived"]
            while True:
                records = self.connection.execute("""SELECT * FROM quotes WHERE symbol=? AND capture_date=?
                    AND sequence>? ORDER BY sequence LIMIT 50000""", (group["symbol"], group["capture_date"], after)).fetchall()
                if not records:
                    break
                normalized = []
                for record in records:
                    row = {name: record[name] for name in QUOTE_COLUMNS}
                    row["timestamp"] = datetime.fromtimestamp(row["timestamp"], timezone.utc)
                    normalized.append(row)
                day = group["capture_date"]
                directory = self.root / "data" / group["symbol"] / day[:4] / day[5:7]
                target = publish_parquet(pa.Table.from_pylist(normalized, schema=SCHEMA), directory, day)
                # The catalogue is advanced only after the immutable file is complete.
                with self.connection:
                    self.connection.execute("INSERT INTO parquet_parts VALUES (?,?,?,?,?,?)",
                        (target.relative_to(self.root).as_posix(), group["symbol"], day,
                         records[0]["sequence"], records[-1]["sequence"], len(records)))
                after = records[-1]["sequence"]

    def close(self):
        if self.connection is not None:
            try:
                self.flush_parquet()
            except BaseException:
                with self.connection:
                    self.connection.execute("UPDATE runs SET status='failed' WHERE run_id=?", (self.run_id,))
                raise
            finally:
                try:
                    self.connection.close()
                finally:
                    self.connection = None
                    self.writer_lock.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
