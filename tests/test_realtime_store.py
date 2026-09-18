from datetime import datetime
import hashlib
import multiprocessing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import pyarrow.parquet as pq

from index_strategy.instant_dld.quotes import DEPTH_COLUMNS, MISSING_PRICE_SENTINEL, normalize_quote
from index_strategy.instant_dld.reader import RealtimeReader, write_strategy_frame
from index_strategy.instant_dld.realtime_store import RealtimeStore, WriterBusyError


def quote(total=1000, price=10, source=93001):
    row = {"latestPrice": price, "tradedQuantities": total, "tradeVolume": 9999999, "quoteTimestamp": source}
    for side in ("b", "s"):
        for level in range(1, 6):
            row[f"{side}{level}Price"] = price + (-1 if side == "b" else 1) * level / 100
            row[f"{side}{level}Stocks"] = level * 100
    return row


def batch(total=1000, *, received="2026-09-18T09:30:01.987654+08:00", data=None, status="success"):
    symbols = ["000001.SZ", "603110.SH"]
    if data is None:
        data = {symbol: quote(total, 10 + index) for index, symbol in enumerate(symbols)}
    return {"received_at": received, "symbols": symbols, "status": status, "poll": 1, "batch": 1, "batch_count": 1,
            "response": {"respSuccess": True, "code": "0", "data": data}}


def concurrent_snapshot_reader(root, ready, release, results):
    reader = RealtimeReader(root)
    try:
        with reader.connect() as connection:
            connection.execute("BEGIN")
            before = connection.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
            ready.set()
            if not release.wait(10):
                raise TimeoutError("writer did not release reader")
            during = connection.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
            connection.execute("COMMIT")
        after = len(reader.read_since())
        results.put((before, during, after))
    except Exception as exc:
        results.put(repr(exc))
        ready.set()


class NormalizationTests(unittest.TestCase):
    def test_maps_all_five_levels_and_uses_cumulative_quantity_not_amount(self):
        row = normalize_quote("000001.SZ", quote(), "2026-09-18T09:30:01.999999+08:00")
        self.assertEqual(row["timestamp"], int(datetime.fromisoformat("2026-09-18T09:30:01+08:00").timestamp()))
        self.assertEqual(row["quote_time"], "09:30:01")
        self.assertEqual(row["volume_total"], 1000)
        self.assertIsNone(row["volume"])
        self.assertEqual(row["bid_price_5"], 9.95)
        self.assertEqual(row["ask_volume_5"], 500)
        self.assertEqual(row["capture_date"], "2026-09-18")
        self.assertNotIn("trade_date", row)
        self.assertEqual(row["quality_flags"], 16)

    def test_delta_reset_new_day_and_backwards_source_clock(self):
        old = normalize_quote("000001.SZ", quote(), "2026-09-18T09:30:01+08:00")
        same = normalize_quote("000001.SZ", quote(), "2026-09-18T09:30:02+08:00", old)
        self.assertEqual(same["volume"], 0)
        updated = normalize_quote("000001.SZ", quote(1050, source=93002), "2026-09-18T09:30:02+08:00", old)
        self.assertEqual(updated["volume"], 50)
        for total, source in ((900, 93002), (1050, 93000)):
            row = normalize_quote("000001.SZ", quote(total, source=source), "2026-09-18T09:30:02+08:00", old)
            self.assertIsNone(row["volume"])
            self.assertTrue(row["quality_flags"] & 8)
        next_day = normalize_quote("000001.SZ", quote(1100), "2026-09-19T09:30:01+08:00", old)
        self.assertIsNone(next_day["volume"])

    def test_missing_fields_stay_null_and_bad_price_or_symbol_is_rejected(self):
        row = normalize_quote("000001.SZ", {"latestPrice": 10}, "2026-09-18T09:30:01+08:00")
        self.assertIsNone(row["quote_time"])
        self.assertIsNone(row["volume_total"])
        self.assertTrue(all(row[key] is None for key in DEPTH_COLUMNS))
        for price in (None, True, 0, -1, float("nan"), float("inf")):
            with self.subTest(price=price), self.assertRaises(ValueError):
                normalize_quote("000001.SZ", {**quote(), "latestPrice": price}, "2026-09-18T09:30:01+08:00")
        with self.assertRaises(ValueError):
            normalize_quote("000001.SZ", {**quote(), "securityId": "603110.SH"}, "2026-09-18T09:30:01+08:00")

    def test_futures_missing_depth_sentinel_is_null_not_a_tradeable_price(self):
        source = quote(price=940.32)
        for side in ("b", "s"):
            for level in range(2, 6):
                source[f"{side}{level}Price"] = 9223372036854.775
                source[f"{side}{level}Stocks"] = 0
        row = normalize_quote("AU2610.SHF", source, "2026-09-18T21:53:58+08:00")
        self.assertEqual(row["close"], 940.32)
        self.assertIsNotNone(row["bid_price_1"])
        self.assertIsNone(row["bid_price_2"])
        self.assertIsNone(row["ask_price_5"])
        self.assertEqual(row["ask_volume_5"], 0)
        self.assertTrue(row["quality_flags"] & 32)
        with self.assertRaises(ValueError):
            normalize_quote("AU2610.SHF", {"latestPrice": MISSING_PRICE_SENTINEL}, "2026-09-18T21:53:58+08:00")


class RealtimeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = RealtimeStore(self.root)
        self.addCleanup(self.store.close)
        self.reader = RealtimeReader(self.root)

    def test_parquet_schema_partition_hash_and_round_trip(self):
        self.store.batch(batch())
        files = self.reader.parquet_files("000001.SZ", "2026-09-18")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, self.root / "data/000001.SZ/2026/09")
        self.assertEqual(files[0].name, "2026-09-18." + hashlib.sha256(files[0].read_bytes()).hexdigest() + ".parquet")
        frame = pd.read_parquet(files[0])
        self.assertEqual(len(frame), 1)
        self.assertTrue(set(DEPTH_COLUMNS).issubset(frame.columns))
        self.assertEqual(frame.loc[0, "volume_total"], 1000)
        self.assertTrue(pd.isna(frame.loc[0, "volume"]))
        self.assertEqual(str(frame["timestamp"].dt.tz), "UTC")
        self.assertEqual(frame.loc[0, "timestamp"].microsecond, 0)
        self.assertFalse(list(self.root.rglob("*.json*")))

    def test_live_data_is_immediate_archive_flushes_on_stop_and_files_stay_immutable(self):
        self.store.batch(batch())
        old_file = self.reader.parquet_files("000001.SZ", "2026-09-18")[0]
        old_bytes = old_file.read_bytes()
        with old_file.open("rb") as open_reader:
            self.store.batch(batch(1080, received="2026-09-18T09:30:02+08:00"))
            self.assertEqual(len(self.reader.read_since()), 4)
            self.assertEqual(len(self.reader.read_parquet_day("000001.SZ", "2026-09-18")), 1)
            self.store.close()
            self.assertEqual(open_reader.read(), old_bytes)
        archived = self.reader.read_parquet_day("000001.SZ", "2026-09-18")
        self.assertEqual(len(archived), 2)
        self.assertEqual(archived.iloc[-1]["volume"], 80)
        self.assertEqual(old_file.read_bytes(), old_bytes)

    def test_failed_and_missing_symbols_never_create_fabricated_rows(self):
        record = batch(data={"000001.SZ": quote(), "603110.SH": {"latestPrice": 0}})
        self.store.batch(record)
        self.assertEqual(record["status"], "partial")
        self.assertEqual(self.store.last_report["failed_symbols"], ["603110.SH"])
        self.assertEqual(list(self.reader.latest()["symbol"]), ["000001.SZ"])
        self.store.batch(batch(status="timeout"))
        self.assertEqual(self.store.last_report["status"], "failed")
        self.assertEqual(len(self.reader.read_since()), 1)

    def test_insertion_failure_rolls_back_every_symbol_in_the_batch(self):
        self.store.connection.execute("""CREATE TRIGGER reject_second BEFORE INSERT ON quotes
            WHEN NEW.symbol='603110.SH' BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.batch(batch())
        self.assertEqual(len(self.reader.read_since()), 0)
        with self.reader.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0], 0)

    def test_second_writer_is_rejected_and_lock_releases_on_close(self):
        with self.assertRaises(WriterBusyError):
            RealtimeStore(self.root)
        self.store.close()
        with RealtimeStore(self.root) as restarted:
            restarted.batch(batch())
        self.assertEqual(len(self.reader.latest()), 2)

    def test_separate_process_reader_keeps_snapshot_while_writer_commits(self):
        self.store.batch(batch())
        context = multiprocessing.get_context("spawn")
        ready, release, results = context.Event(), context.Event(), context.Queue()
        process = context.Process(target=concurrent_snapshot_reader, args=(str(self.root), ready, release, results))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
            self.store.batch(batch(1100, received="2026-09-18T09:30:02+08:00"))
            release.set()
            self.assertEqual(results.get(timeout=10), (2, 2, 4))
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
            results.close()
        self.assertEqual(process.exitcode, 0)

    def test_incremental_cursor_preserves_same_second_samples_and_reader_cannot_write(self):
        self.store.batch(batch())
        first = self.reader.read_since()
        cursor = int(first["sequence"].max())
        self.store.batch(batch(1010))
        second = self.reader.read_since(cursor)
        self.assertEqual(len(second), 2)
        self.assertTrue((second["sequence"] > cursor).all())
        self.assertEqual(first.index[0], second.index[0])
        self.assertEqual(len(self.reader.latest(["000001.SZ"])), 1)
        self.assertTrue(self.reader.latest([]).empty)
        with self.reader.connect() as connection, self.assertRaises(sqlite3.OperationalError):
            connection.execute("DELETE FROM quotes")

    def test_restart_publishes_pending_rows_without_duplicate_archive_rows(self):
        self.store.batch(batch())
        self.store.batch(batch(1020))
        # Emulate process loss after the committed live batch, before final archive.
        self.store.connection.close()
        self.store.connection = None
        self.store.writer_lock.close()
        with RealtimeStore(self.root):
            pass
        frame = self.reader.read_parquet_day("000001.SZ", "2026-09-18")
        self.assertEqual(len(frame), 2)
        self.assertFalse(frame["sequence"].duplicated().any())

    def test_publication_failure_keeps_live_commit_and_can_recover(self):
        with patch("index_strategy.instant_dld.realtime_store.publish_parquet", side_effect=OSError("archive full")):
            with self.assertRaises(OSError):
                self.store.batch(batch())
        self.assertEqual(len(self.reader.read_since()), 2)
        self.assertFalse(self.reader.parquet_files("000001.SZ", "2026-09-18"))
        self.store.close()
        self.assertEqual(len(self.reader.read_parquet_day("000001.SZ", "2026-09-18")), 1)

    def test_unregistered_file_after_interruption_is_excluded_from_reader_snapshot(self):
        self.store.connection.execute("""CREATE TRIGGER reject_catalog BEFORE INSERT ON parquet_parts
            BEGIN SELECT RAISE(ABORT, 'simulated interruption'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.batch(batch())
        self.assertTrue(list((self.root / "data").rglob("*.parquet")))
        self.assertFalse(self.reader.parquet_files("000001.SZ", "2026-09-18"))
        self.store.connection.execute("DROP TRIGGER reject_catalog")
        self.store.batch(batch(1030))
        archived = self.reader.read_parquet_day("000001.SZ", "2026-09-18")
        self.assertEqual(len(archived), 2)
        self.assertFalse(archived["sequence"].duplicated().any())

    def test_midnight_partition_and_independent_strategy_output(self):
        self.store.batch(batch(received="2026-09-18T23:59:59+08:00"))
        self.store.batch(batch(2000, received="2026-09-19T00:00:00+08:00"))
        self.store.close()
        self.assertEqual(len(self.reader.parquet_files("000001.SZ", "2026-09-18")), 1)
        self.assertEqual(len(self.reader.parquet_files("000001.SZ", "2026-09-19")), 1)
        frame = self.reader.latest()
        self.assertTrue(frame["volume"].isna().all())
        result = write_strategy_frame(frame, "example_signal", self.root)
        second = write_strategy_frame(frame, "example_signal", self.root)
        self.assertNotEqual(result, second)
        self.assertEqual(result.parent, self.root / "strategy_results/example_signal")
        self.assertEqual(len(pd.read_parquet(result)), 2)
        self.assertEqual(len(self.reader.read_since()), 4)
        with self.assertRaises(ValueError):
            write_strategy_frame(frame, "../data", self.root)


if __name__ == "__main__":
    unittest.main()
