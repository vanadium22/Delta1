"""Verify observation-volume continuity and safe repair of published v2 data."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from index_strategy.instant_dld.quotes import DEPTH_COLUMNS, QUOTE_COLUMNS, VOLUME_COLUMNS
from index_strategy.instant_dld.reader import RealtimeReader
from index_strategy.instant_dld.realtime_store import DB_RELATIVE, SCHEMA, RealtimeStore, publish_parquet


START = datetime.fromisoformat("2026-09-18T09:30:00.125+08:00")
SYMBOLS = ["AU.SHF", "AG.SHF"]


def live_batch(seconds, totals, *, poll=1, failed=()):
    at = START + timedelta(seconds=seconds)
    data, mappings = {}, {}
    for symbol, total in zip(SYMBOLS, totals):
        actual = symbol.replace(".", "2610.")
        mappings[symbol] = {"source_symbol": actual, "mapping_date": "2026-09-17", "trading_date": "2026-09-18"}
        if symbol not in failed:
            data[symbol] = {"securityId": actual, "latestPrice": 940.32,
                            "tradedQuantities": total, "quoteTimestamp": int(at.strftime("%H%M%S"))}
    return {"received_at": at.isoformat(), "symbols": SYMBOLS[:len(totals)],
            "status": "partial" if failed else "success", "poll": poll, "batch": 1, "batch_count": 1,
            "symbol_mapping": mappings, "response": {"data": data}}


def begin_run(store, interval=2):
    store.manifest({"started_at": START.isoformat(), "status": "running", "interval_seconds": interval,
                    "polls_started": 0, "initial_symbols": SYMBOLS})


def build_v2(root):
    """An actual old schema, including the erroneous 2991 cross-run difference."""
    database = root / DB_RELATIVE
    database.parent.mkdir(parents=True)
    numeric = ",".join(f"{name} REAL" for name in ["close", "volume", "volume_total", *DEPTH_COLUMNS])
    old_columns = [name for name in QUOTE_COLUMNS if name not in VOLUME_COLUMNS]
    records = []
    for sequence, elapsed, total, delta, run, poll in (
        (1, 0, 1000, None, "before_restart", 1),
        (2, 2, 1006, 6, "before_restart", 2),
        (3, 583, 3997, 2991, "after_restart", 1),
        (4, 585, 4003, 6, "after_restart", 2),
    ):
        at = START + timedelta(seconds=elapsed)
        row = {name: None for name in old_columns}
        row.update(sequence=sequence, timestamp=int(at.timestamp()), symbol="AU.SHF", source_symbol="AU2610.SHF",
                   mapping_date="2026-09-17", trading_date="2026-09-18", quote_time=at.strftime("%H:%M:%S"),
                   close=940.32, volume=delta, volume_total=total, quality_flags=2 | (16 if delta is None else 0),
                   capture_date="2026-09-18", run_id=run, poll=poll, batch=1, batch_received_at=at.isoformat())
        records.append(row)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(f"""
            CREATE TABLE quotes (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,timestamp INTEGER NOT NULL,capture_date TEXT NOT NULL,
                symbol TEXT NOT NULL,source_symbol TEXT NOT NULL,mapping_date TEXT,trading_date TEXT,quote_time TEXT,
                {numeric},quality_flags INTEGER NOT NULL,run_id TEXT NOT NULL,poll INTEGER,batch INTEGER
            );
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,started_at TEXT,finished_at TEXT,status TEXT,interval_seconds REAL,
                polls_started INTEGER,requests_saved INTEGER,symbols TEXT
            );
            CREATE TABLE batches (
                id INTEGER PRIMARY KEY,run_id TEXT,timestamp TEXT,poll INTEGER,batch INTEGER,status TEXT,
                requested INTEGER,saved INTEGER,failed_symbols TEXT,description TEXT
            );
            CREATE TABLE parquet_parts (
                path TEXT PRIMARY KEY,symbol TEXT NOT NULL,capture_date TEXT NOT NULL,
                first_sequence INTEGER NOT NULL,last_sequence INTEGER NOT NULL,rows INTEGER NOT NULL
            );
            PRAGMA user_version=2;
        """)
        for run in ("before_restart", "after_restart"):
            connection.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                               (run, START.isoformat(), None, "completed", 2, 2, 2, "AU.SHF"))
        columns = [*old_columns, "capture_date", "run_id", "poll", "batch"]
        for row in records:
            connection.execute(f"INSERT INTO quotes ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                               [row[name] for name in columns])
            connection.execute("INSERT INTO batches(run_id,timestamp,poll,batch,status,requested,saved) "
                               "VALUES (?,?,?,?,?,?,?)", (row["run_id"], row["batch_received_at"], row["poll"], 1, "success", 1, 1))
        old_schema = pa.schema([field for field in SCHEMA if field.name not in VOLUME_COLUMNS],
                               metadata={b"schema_version": b"swhy_realtime_v2"})
        archived = [{**row, "timestamp": datetime.fromtimestamp(row["timestamp"], timezone.utc)} for row in records]
        part = publish_parquet(pa.Table.from_pylist(archived, schema=old_schema), root / "data/AU.SHF/2026/09", "2026-09-18")
        connection.execute("INSERT INTO parquet_parts VALUES (?,?,?,?,?,?)",
                           (part.relative_to(root).as_posix(), "AU.SHF", "2026-09-18", 1, 4, 4))
    return part


class VolumeStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_v2_reader_hides_unbounded_deltas_without_modifying_old_data(self):
        part = build_v2(self.root)
        old_bytes = part.read_bytes()
        reader = RealtimeReader(self.root)
        for frame in (reader.read_since(), reader.history("AU.SHF", "2026-09-18"),
                      reader.read_parquet_day("AU.SHF", "2026-09-18")):
            self.assertTrue(frame["volume"].isna().all())
            self.assertTrue(frame["volume_start"].isna().all())
            self.assertTrue(frame["volume_interval_seconds"].isna().all())
            self.assertEqual(list(frame["volume_total"]), [1000, 1006, 3997, 4003])
        self.assertEqual(part.read_bytes(), old_bytes)
        with reader.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT volume FROM quotes WHERE sequence=3").fetchone()[0], 2991)
            self.assertNotIn("volume_interval_seconds", [row[1] for row in connection.execute("PRAGMA table_info(quotes)")])

    def test_v2_repair_preserves_cumulative_volume_and_retires_immutable_parts(self):
        part = build_v2(self.root)
        old_bytes = part.read_bytes()
        with RealtimeStore(self.root) as store:
            self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 3)
            retired = store.connection.execute("SELECT path,reason FROM retired_parquet_parts").fetchall()
            self.assertEqual([(row[0], row[1]) for row in retired],
                             [(part.relative_to(self.root).as_posix(), "volume_interval_v3")])
        reader = RealtimeReader(self.root)
        for frame in (reader.read_since(), reader.read_parquet_day("AU.SHF", "2026-09-18")):
            self.assertEqual(list(frame["volume_total"]), [1000, 1006, 3997, 4003])
            self.assertTrue(pd.isna(frame.iloc[0]["volume"]))
            self.assertEqual(frame.iloc[1]["volume"], 6)
            self.assertTrue(pd.isna(frame.iloc[2]["volume"]))
            self.assertTrue(int(frame.iloc[2]["quality_flags"]) & 16)
            self.assertEqual(frame.iloc[3]["volume"], 6)
            self.assertEqual(frame.iloc[3]["volume_interval_seconds"], 2)
            self.assertEqual(frame.iloc[3]["volume_start"], pd.Timestamp("2026-09-18T01:39:43Z"))
        active = reader.parquet_files("AU.SHF", "2026-09-18")
        self.assertEqual(len(active), 1)
        self.assertNotIn(part, active)
        self.assertEqual(pq.ParquetFile(active[0]).schema_arrow.metadata[b"schema_version"], b"swhy_realtime_v3")
        self.assertEqual(part.read_bytes(), old_bytes)
        backups = list((self.root / "live/backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT volume FROM quotes WHERE sequence=3").fetchone()[0], 2991)

    def test_failed_parquet_publication_rolls_back_entire_v2_repair(self):
        part = build_v2(self.root)
        old_bytes = part.read_bytes()
        with patch("index_strategy.instant_dld.realtime_store.publish_parquet", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                RealtimeStore(self.root)
        reader = RealtimeReader(self.root)
        with reader.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT volume FROM quotes WHERE sequence=3").fetchone()[0], 2991)
            self.assertNotIn("volume_start", [row[1] for row in connection.execute("PRAGMA table_info(quotes)")])
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='retired_parquet_parts'").fetchone())
        self.assertEqual(reader.parquet_files("AU.SHF", "2026-09-18"), [part])
        self.assertEqual(part.read_bytes(), old_bytes)
        with RealtimeStore(self.root):
            pass
        self.assertTrue(pd.isna(reader.read_since().iloc[2]["volume"]))

    def test_live_restart_resets_first_delta_then_resumes_precise_interval(self):
        with RealtimeStore(self.root) as store:
            begin_run(store)
            store.batch(live_batch(0, [1000]))
            store.batch(live_batch(2, [1006], poll=2))
        with RealtimeStore(self.root) as store:
            begin_run(store)
            store.batch(live_batch(583, [3997]))
            store.batch(live_batch(585.375, [4003], poll=2))
        frame = RealtimeReader(self.root).read_since()
        self.assertTrue(pd.isna(frame.iloc[2]["volume"]))
        self.assertEqual(frame.iloc[2]["volume_total"], 3997)
        self.assertEqual(frame.iloc[3]["volume"], 6)
        self.assertEqual(frame.iloc[3]["volume_interval_seconds"], 2.375)
        self.assertEqual(frame.iloc[3]["volume_start"], pd.Timestamp("2026-09-18T01:39:43Z"))
        self.assertEqual(str(frame["volume_start"].dt.tz), "UTC")
        archived = RealtimeReader(self.root).read_parquet_day("AU.SHF", "2026-09-18")
        self.assertEqual(archived.iloc[3]["volume_start"], frame.iloc[3]["volume_start"])
        self.assertEqual(archived.iloc[3]["volume_interval_seconds"], 2.375)

    def test_partial_failure_resets_only_the_failed_symbol_baseline(self):
        with RealtimeStore(self.root) as store:
            begin_run(store)
            store.batch(live_batch(0, [1000, 2000]))
            store.batch(live_batch(2, [1006, 2006], poll=2, failed=["AU.SHF"]))
            store.batch(live_batch(4, [1012, 2012], poll=3))
            recovered = {row["symbol"]: row for row in store.last_rows}
            self.assertIsNone(recovered["AU.SHF"]["volume"])
            self.assertTrue(recovered["AU.SHF"]["quality_flags"] & 16)
            self.assertEqual(recovered["AG.SHF"]["volume"], 6)
            self.assertEqual(recovered["AG.SHF"]["volume_interval_seconds"], 2)
            store.batch(live_batch(6, [1018, 2018], poll=4))
            self.assertTrue(all(row["volume"] == 6 for row in store.last_rows))

    def test_long_observation_gap_is_null_and_next_contiguous_sample_recovers(self):
        with RealtimeStore(self.root) as store:
            begin_run(store)
            store.batch(live_batch(0, [1000]))
            store.batch(live_batch(4.001, [1100], poll=2))
            gap = store.last_rows[0]
            self.assertIsNone(gap["volume"])
            self.assertIsNone(gap["volume_start"])
            self.assertIsNone(gap["volume_interval_seconds"])
            self.assertTrue(gap["quality_flags"] & 128)
            self.assertEqual(gap["volume_total"], 1100)
            store.batch(live_batch(6.001, [1106], poll=3))
            self.assertEqual(store.last_rows[0]["volume"], 6)
            self.assertEqual(store.last_rows[0]["volume_interval_seconds"], 2)


if __name__ == "__main__":
    unittest.main()
