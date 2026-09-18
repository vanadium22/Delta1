"""Contract identity must survive rollovers, schema upgrades and immutable archives."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
import pyarrow as pa

from index_strategy.instant_dld.quotes import DEPTH_COLUMNS, IDENTITY_COLUMNS, QUOTE_COLUMNS, VOLUME_COLUMNS, normalize_quote
from index_strategy.instant_dld.reader import RealtimeReader
from index_strategy.instant_dld.realtime_store import DB_RELATIVE, SCHEMA, RealtimeStore, publish_parquet


def quote(contract="AU2610.SHF", total=1000, clock=93001):
    return {"securityId": contract, "latestPrice": 940.32,
            "tradedQuantities": total, "quoteTimestamp": clock}


def identity(contract="AU2610.SHF", trading_date="2026-09-18", mapping_date="2026-09-17"):
    return {"source_symbol": contract, "trading_date": trading_date, "mapping_date": mapping_date}


def batch(contract="AU2610.SHF", total=1000):
    return {"received_at": "2026-09-18T09:30:02+08:00", "symbols": ["AU.SHF"],
            "status": "success", "poll": 1, "batch": 1, "batch_count": 1,
            "symbol_mapping": {"AU.SHF": identity(contract)},
            "response": {"data": {"AU.SHF": quote(contract, total)}}}


def legacy_database(root):
    """Build the previously published v1 format without running new writer code."""
    path = root / DB_RELATIVE
    path.parent.mkdir(parents=True)
    old_columns = [name for name in QUOTE_COLUMNS if name not in IDENTITY_COLUMNS + VOLUME_COLUMNS]
    row = normalize_quote("AU.SHF", {**quote(), "securityId": None}, "2026-09-18T09:30:01+08:00")
    row.update(sequence=1, run_id="old", poll=1, batch=1)
    numeric = ",".join(f"{name} REAL" for name in ["close", "volume", "volume_total", *DEPTH_COLUMNS])
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(f"""
            CREATE TABLE quotes (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,timestamp INTEGER NOT NULL,
                capture_date TEXT NOT NULL,symbol TEXT NOT NULL,quote_time TEXT,{numeric},
                quality_flags INTEGER NOT NULL,run_id TEXT NOT NULL,poll INTEGER,batch INTEGER
            );
            CREATE TABLE parquet_parts (
                path TEXT PRIMARY KEY,symbol TEXT NOT NULL,capture_date TEXT NOT NULL,
                first_sequence INTEGER NOT NULL,last_sequence INTEGER NOT NULL,rows INTEGER NOT NULL
            );
            PRAGMA user_version=1;
        """)
        columns = [*old_columns, "capture_date", "run_id", "poll", "batch"]
        connection.execute(f"INSERT INTO quotes ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                           [row[name] for name in columns])
        old_schema = pa.schema([field for field in SCHEMA if field.name not in IDENTITY_COLUMNS + VOLUME_COLUMNS],
                               metadata={b"schema_version": b"swhy_realtime_v1"})
        archived = {name: row[name] for name in old_columns}
        archived["timestamp"] = datetime.fromtimestamp(row["timestamp"], timezone.utc)
        part = publish_parquet(pa.Table.from_pylist([archived], schema=old_schema),
                               root / "data/AU.SHF/2026/09", "2026-09-18")
        connection.execute("INSERT INTO parquet_parts VALUES (?,?,?,?,?,?)",
                           (part.relative_to(root).as_posix(), "AU.SHF", "2026-09-18", 1, 1, 1))
    return part


class ContractNormalizationTests(unittest.TestCase):
    def test_alias_validates_actual_contract_and_records_mapping_identity(self):
        row = normalize_quote("AU.SHF", quote(), "2026-09-18T09:30:01+08:00", **identity())
        self.assertEqual(row["symbol"], "AU.SHF")
        for name, value in identity().items():
            self.assertEqual(row[name], value)
        with self.assertRaises(ValueError):
            normalize_quote("AU.SHF", quote("AU2612.SHF"), "2026-09-18T09:30:01+08:00", **identity())

    def test_rollover_resets_delta_even_when_new_contract_volume_is_higher(self):
        previous = normalize_quote("AU.SHF", quote(), "2026-09-18T09:30:01+08:00", **identity())
        rolled = normalize_quote("AU.SHF", quote("AU2612.SHF", 2000),
                                 "2026-09-18T09:30:02+08:00", previous, **identity("AU2612.SHF"))
        self.assertIsNone(rolled["volume"])
        self.assertTrue(rolled["quality_flags"] & 64)
        next_row = normalize_quote("AU.SHF", quote("AU2612.SHF", 2050),
                                   "2026-09-18T09:30:03+08:00", rolled, **identity("AU2612.SHF"))
        self.assertEqual(next_row["volume"], 50)
        self.assertFalse(next_row["quality_flags"] & 64)

    def test_trading_day_baseline_survives_midnight_but_resets_next_session(self):
        mapping = identity(trading_date="2026-09-21", mapping_date="2026-09-18")
        previous = normalize_quote("AU.SHF", quote(clock=235959), "2026-09-18T23:59:59+08:00", **mapping)
        midnight = normalize_quote("AU.SHF", quote(total=1050, clock=1),
                                    "2026-09-19T00:00:01+08:00", previous, **mapping)
        self.assertEqual(midnight["volume"], 50)
        self.assertFalse(midnight["quality_flags"] & (8 | 16))
        daytime = normalize_quote("AU.SHF", quote(total=1075), "2026-09-21T09:30:01+08:00", midnight, **mapping)
        self.assertEqual(daytime["volume"], 25)
        next_day = normalize_quote("AU.SHF", quote(total=2000, clock=210000),
                                   "2026-09-21T21:00:00+08:00", daytime,
                                   **identity(trading_date="2026-09-22", mapping_date="2026-09-21"))
        self.assertIsNone(next_day["volume"])
        self.assertTrue(next_day["quality_flags"] & 16)

    def test_legacy_explicit_contract_identity_falls_back_to_symbol(self):
        previous = {"symbol": "AU2610.SHF", "capture_date": "2026-09-18",
                    "volume_total": 1000, "quote_time": "09:30:01"}
        current = normalize_quote("AU2610.SHF", quote(total=1025), "2026-09-18T09:30:02+08:00", previous)
        self.assertEqual(current["source_symbol"], "AU2610.SHF")
        self.assertEqual(current["volume"], 25)
        self.assertFalse(current["quality_flags"] & 64)


class ContractStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_alias_partition_contains_actual_contract_and_resets_rollover_delta(self):
        with RealtimeStore(self.root) as store:
            store.batch(batch())
            store.batch(batch("AU2612.SHF", 2000))
            rows = RealtimeReader(self.root).history("AU.SHF", "2026-09-18")
            self.assertEqual(list(rows["source_symbol"]), ["AU2610.SHF", "AU2612.SHF"])
            self.assertTrue(rows["volume"].isna().all())
            self.assertTrue(int(rows.iloc[-1]["quality_flags"]) & 64)
        reader = RealtimeReader(self.root)
        self.assertTrue(all(path.parent == self.root / "data/AU.SHF/2026/09"
                            for path in reader.parquet_files("AU.SHF", "2026-09-18")))
        archived = reader.read_parquet_day("AU.SHF", "2026-09-18")
        self.assertEqual(list(archived["source_symbol"]), ["AU2610.SHF", "AU2612.SHF"])

    def test_v1_reader_fills_missing_identity_without_mutating_database(self):
        legacy_database(self.root)
        reader = RealtimeReader(self.root)
        for frame in (reader.read_since(), reader.latest(), reader.history("AU.SHF", "2026-09-18"),
                      reader.read_parquet_day("AU.SHF", "2026-09-18")):
            self.assertEqual(frame.iloc[0]["source_symbol"], "AU.SHF")
            self.assertTrue(pd.isna(frame.iloc[0]["mapping_date"]))
            self.assertTrue(pd.isna(frame.iloc[0]["trading_date"]))
        with reader.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertNotIn("source_symbol", [row[1] for row in connection.execute("PRAGMA table_info(quotes)")])

    def test_v1_upgrade_and_mixed_parquet_preserve_existing_rows_and_files(self):
        part = legacy_database(self.root)
        original_bytes = part.read_bytes()
        with RealtimeStore(self.root) as store:
            self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 3)
            old = store.connection.execute("SELECT * FROM quotes WHERE sequence=1").fetchone()
            self.assertEqual(old["source_symbol"], old["symbol"])
            self.assertIsNone(old["mapping_date"])
            store.batch(batch(total=1050))
        self.assertEqual(part.read_bytes(), original_bytes)
        reader = RealtimeReader(self.root)
        for frame in (reader.read_since(), reader.read_parquet_day("AU.SHF", "2026-09-18")):
            self.assertEqual(list(frame["sequence"]), [1, 2])
            self.assertEqual(list(frame["source_symbol"]), ["AU.SHF", "AU2610.SHF"])
            self.assertTrue(pd.isna(frame.iloc[0]["mapping_date"]))
            self.assertEqual(frame.iloc[1]["mapping_date"], "2026-09-17")

    def test_failed_identity_backfill_rolls_back_schema_upgrade(self):
        legacy_database(self.root)
        with closing(sqlite3.connect(self.root / DB_RELATIVE)) as connection, connection:
            connection.execute("CREATE TRIGGER block_upgrade BEFORE UPDATE ON quotes "
                               "BEGIN SELECT RAISE(ABORT,'upgrade interrupted'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            RealtimeStore(self.root)
        with closing(sqlite3.connect(self.root / DB_RELATIVE)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertNotIn("source_symbol", [row[1] for row in connection.execute("PRAGMA table_info(quotes)")])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 1)
            connection.execute("DROP TRIGGER block_upgrade")
        with RealtimeStore(self.root):
            pass

    def test_daily_mapping_pin_survives_restart_and_ignores_same_day_revisions(self):
        with RealtimeStore(self.root) as store:
            self.assertIsNone(store.pinned_contract("AU.SHF", "2026-09-18"))
            self.assertEqual(store.pin_contract("AU.SHF", identity()), identity())
            self.assertEqual(store.pin_contract("AU.SHF", identity("AU2612.SHF")), identity())
        with RealtimeStore(self.root) as store:
            self.assertEqual(store.pinned_contract("AU.SHF", "2026-09-18"), identity())
            next_day = identity("AU2612.SHF", "2026-09-21", "2026-09-18")
            self.assertEqual(store.pin_contract("AU.SHF", next_day), next_day)
            self.assertEqual(store.pinned_contract("AU.SHF", "2026-09-18"), identity())


if __name__ == "__main__":
    unittest.main()
