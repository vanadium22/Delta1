from __future__ import annotations

from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from dashboard.marketdata import BarDataset, normalize_bars
from dashboard.marketdata.adapters import read_realtime_observations
from index_strategy.instant_dld.contract_aliases import DualIdentityStore

DESCRIPTOR = {"dataset_id": "test_cfe", "source_id": "test_only", "series_kind": "concrete",
              "price_adjustment": "none", "volume_unit": "contracts",
              "availability_policy": "source_reported",
              "instruments": {"IC2610.CFE":{"asset_type":"cn_index_future","market_region":"CN"},
                              "000300.SH":{"asset_type":"cn_index","market_region":"CN"}}}


def bar(event="2026-09-30T01:31:00Z", frequency="1m", **changes):
    stamp = pd.Timestamp(event)
    row = {"instrument_id": "IC2610.CFE", "frequency": frequency,
           "event_time": event, "trade_date": "2026-09-30", "session_id": "day_am",
           "source_symbol": "IC2610.CFE", "bar_start": stamp-pd.Timedelta(seconds={"1m":60,"1s":1,"1d":19800}.get(frequency,60)),
           "open": 7000., "high": 7002., "low": 6999., "close": 7001., "volume": 10.,
           "is_final": True, "revision": 0, "recorded_at": "2026-09-30T09:00:00Z",
           "available_at": stamp+pd.Timedelta(seconds=1), "quality_flags": 0}
    return {**row, **changes}


class DatasetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)/"a custom folder"/"data"
        self.store = BarDataset.create(self.root, DESCRIPTOR)

    def test_overlapping_download_is_idempotent_even_when_download_time_changes(self):
        a = self.store.commit([bar()], checkpoint={"through":"2026-09-30"})
        b = self.store.commit([bar(recorded_at="2026-10-01T09:00:00Z")])
        self.assertEqual(b, {"version":a["version"],"inserted":0})
        self.assertEqual(len(self.store.read_bars("IC2610.CFE","1m")),1)
        self.assertEqual(len(self.store.snapshot()["parts"]),1)

    def test_incremental_backfill_and_revision_keep_frozen_old_version(self):
        original = self.store.commit([bar()])
        self.store.commit([bar("2026-09-30T01:32:00Z"), bar(revision=1,close=7002.)])
        now=self.store.read_bars("IC2610.CFE","1m",fields=["close"])
        before=self.store.read_bars("IC2610.CFE","1m",version=original["version"])
        self.assertEqual(list(now["close"]),[7002.,7001.])
        self.assertEqual(list(before["close"]),[7001.])

    def test_conflicting_revision_does_not_publish_or_advance_checkpoint(self):
        self.store.commit([bar()],checkpoint={"cursor":1})
        before=self.store.snapshot()
        with self.assertRaisesRegex(ValueError,"revision"):
            self.store.commit([bar("2026-09-30T01:32:00Z"),bar(close=7002.)],checkpoint={"cursor":2})
        self.assertEqual(self.store.snapshot(),before)

    def test_market_availability_and_ingestion_knowledge_are_distinct(self):
        self.store.commit([bar(), bar(revision=1,close=7002.,available_at="2026-09-30T10:00:00Z",
                                      recorded_at="2026-09-30T11:00:00Z")])
        self.assertEqual(self.store.read_bars("IC2610.CFE","1m",as_of="2026-09-30T09:30:00Z").iloc[0].close,7001.)
        self.assertEqual(self.store.read_bars("IC2610.CFE","1m",as_of="2026-09-30T12:00:00Z",knowledge_at="2026-09-30T09:30:00Z").iloc[0].close,7001.)
        self.assertEqual(self.store.read_bars("IC2610.CFE","1m",as_of="2026-09-30T12:00:00Z").iloc[0].close,7002.)

    def test_day_bar_not_visible_before_publication(self):
        self.store.commit([bar("2026-09-30T07:00:00Z",frequency="1d",available_at="2026-09-30T08:00:00Z")])
        self.assertTrue(self.store.read_bars("IC2610.CFE","1d",as_of="2026-09-30T07:30:00Z").empty)
        self.assertEqual(len(self.store.read_bars("IC2610.CFE","1d",as_of="2026-09-30T08:00:00Z")),1)

    def test_unverified_availability_requires_explicit_opt_in(self):
        self.store.commit([bar(available_at=None,quality_flags=1)])
        self.assertTrue(self.store.read_bars("IC2610.CFE","1m").empty)
        frame=self.store.read_bars("IC2610.CFE","1m",allow_unverified_availability=True)
        self.assertEqual(len(frame),1)
        self.assertTrue(frame.attrs["availability_unverified"])

    def test_provisional_row_requires_explicit_opt_in(self):
        self.store.commit([bar(is_final=False)])
        self.assertTrue(self.store.read_bars("IC2610.CFE","1m").empty)
        self.assertEqual(len(self.store.read_bars("IC2610.CFE","1m",include_partial=True)),1)

    def test_exchange_trade_date_and_utc_time_are_preserved(self):
        self.store.commit([bar("2026-09-30T01:31:00Z",instrument_id="000300.SH",trade_date="2026-09-30")])
        part=self.store.snapshot()["parts"][0]
        self.assertIn("2026-09-30.",part["path"])
        self.assertEqual(len(self.store.read_bars("000300.SH","1m",start="2026-09-30T01:30:00Z",end="2026-09-30T01:32:00Z")),1)

    def test_daily_timestamp_correction_stays_one_logical_row(self):
        self.store.commit([bar("2026-09-30T07:00:00Z",frequency="1d")])
        self.store.commit([bar("2026-09-30T07:00:01Z",frequency="1d",revision=1)])
        self.assertEqual(len(self.store.read_bars("IC2610.CFE","1d")),1)
        # The current corrected label is outside this window; an obsolete
        # revision must not reappear just because the query ends at the old label.
        self.assertTrue(self.store.read_bars("IC2610.CFE","1d",end="2026-09-30T07:00:00Z").empty)

    def test_intraday_conflict_detected_even_if_incoming_trade_date_is_wrong(self):
        self.store.commit([bar()])
        with self.assertRaisesRegex(ValueError,"revision"):
            self.store.commit([bar(trade_date="2026-10-08")])

    def test_orphan_file_not_in_manifest_is_never_read(self):
        self.store.commit([bar()])
        path=self.root/self.store.snapshot()["parts"][0]["path"]
        path.with_name("orphan.parquet").write_bytes(path.read_bytes())
        self.assertEqual(len(self.store.read_bars("IC2610.CFE","1m")),1)

    def test_source_units_or_adjustment_cannot_change_in_place(self):
        with self.assertRaisesRegex(ValueError,"单位"):
            BarDataset.create(self.root,{**DESCRIPTOR,"volume_unit":"shares"})

    def test_zero_volume_is_distinct_from_missing_volume(self):
        self.store.commit([bar(volume=0),bar("2026-09-30T01:32:00Z",volume=None)])
        df=self.store.read_bars("IC2610.CFE","1m")
        self.assertEqual(df.iloc[0].volume,0.)
        self.assertTrue(pd.isna(df.iloc[1].volume))

    def test_rows_must_keep_timezone_and_real_bar_duration(self):
        for change in ({"event_time":"2026-09-30T09:31:00"}, {"volume":-1},
                       {"close":float("nan")},{"frequency":"poll_1s"},
                       {"bar_start":"2026-09-30T01:30:59Z"}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                normalize_bars([bar(**change)])

    def test_manifest_tamper_rejected(self):
        self.store.commit([bar()])
        ref=json.loads((self.root/"current.json").read_text())
        (self.root/ref["manifest"]).write_text("{}")
        with self.assertRaisesRegex(ValueError,"哈希"):
            self.store.read_bars("IC2610.CFE","1m")

    def test_unregistered_or_non_domestic_instruments_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"未注册"):
            self.store.commit([bar(instrument_id="OTHER.CFE")])
        for kind,region in (("commodity_future","CN"),("cn_index","HK")):
            descriptor={**DESCRIPTOR,"instruments":{"X":{"asset_type":kind,"market_region":region}}}
            with self.assertRaises(ValueError):
                BarDataset.create(self.root/"other",descriptor)

    def test_future_new_contract_registration_keeps_existing_version_metadata(self):
        old=self.store.commit([bar()])["version"]
        info={"asset_type":"cn_index_future","market_region":"CN"}
        self.store.register_instruments({"IC2611.CFE":info})
        self.store.commit([bar(instrument_id="IC2611.CFE")])
        self.assertEqual(len(self.store.read_bars("IC2611.CFE","1m")),1)
        oldframe=self.store.read_bars("IC2610.CFE","1m",version=old)
        self.assertNotIn("IC2611.CFE",oldframe.attrs["dataset"]["instruments"])
        with self.assertRaisesRegex(ValueError,"口径"):
            self.store.register_instruments({"IC2610.CFE":{**info,"price_unit":"other"}})

    def test_failure_before_pointer_publication_is_recoverable(self):
        from dashboard.marketdata import bars
        self.store.commit([bar()],checkpoint={"cursor":1})
        original=bars._atomic_bytes
        def fail_pointer(path,data):
            if path.name=="current.json":
                raise OSError("simulated crash before publication")
            original(path,data)
        with patch.object(bars,"_atomic_bytes",side_effect=fail_pointer),self.assertRaises(OSError):
            self.store.commit([bar("2026-09-30T01:32:00Z")],checkpoint={"cursor":2})
        self.assertEqual(self.store.snapshot()["checkpoint"],{"cursor":1})
        self.assertEqual(len(self.store.read_bars("IC2610.CFE","1m")),1)
        self.store.commit([bar("2026-09-30T01:32:00Z")],checkpoint={"cursor":2})
        self.assertEqual(len(self.store.read_bars("IC2610.CFE","1m")),2)
        self.assertEqual(self.store.snapshot()["checkpoint"],{"cursor":2})


class ObservationTests(unittest.TestCase):
    def test_alias_duplicates_and_poll_interval_do_not_become_second_bars(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"live").mkdir()
            with closing(sqlite3.connect(root/"live"/"quotes.sqlite3")) as con:
                con.execute("CREATE TABLE quotes(sequence INTEGER,symbol TEXT,source_symbol TEXT,run_id TEXT,poll INTEGER,batch INTEGER,received_at TEXT,volume REAL,volume_interval_seconds REAL,quote_time TEXT)")
                con.executemany("INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?,?,?)",[
                    (1,"IC00.CFE","IC2610.CFE","run1",1,1,"2026-09-30T09:31:00.123456+08:00",10,2.5,"093100"),
                    (2,"IC2610.CFE","IC2610.CFE","run1",1,1,"2026-09-30T09:31:00.123456+08:00",10,2.5,"093100")])
                con.commit()
            frame,cursor=read_realtime_observations(root,dataset_id="a",instruments=DESCRIPTOR["instruments"])
            self.assertEqual(len(frame),1)
            self.assertEqual(cursor["sequence"],2)
            self.assertEqual(frame.iloc[0].volume_interval_seconds,2.5)
            self.assertEqual(frame.iloc[0].source_event_time,pd.Timestamp("2026-09-30T09:31:00+08:00"))
            self.assertFalse(frame.attrs["source_time_verified"])
            self.assertEqual(frame.iloc[0].observed_at.microsecond,123456)
            page1,_=read_realtime_observations(root,dataset_id="a",instruments=DESCRIPTOR["instruments"],limit=1)
            page2,_=read_realtime_observations(root,dataset_id="a",instruments=DESCRIPTOR["instruments"],after_sequence=1,limit=1)
            self.assertEqual(page1.iloc[0].observation_id,page2.iloc[0].observation_id)
            other,_=read_realtime_observations(root,dataset_id="b",instruments=DESCRIPTOR["instruments"],limit=1)
            self.assertNotEqual(page1.iloc[0].observation_id,other.iloc[0].observation_id)

    def test_actual_collector_v3_round_trip_without_network_or_existing_data(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with DualIdentityStore(root) as store:
                for poll,total in ((1,100),(2,110)):
                    quote={"securityId":"IC2610.CFE","latestPrice":7000.+poll,
                           "tradedQuantities":total,"quoteTimestamp":93100+poll,
                           "b1Price":7000.,"s1Price":7002.,"b1Stocks":3.,"s1Stocks":5.}
                    store.batch({"symbols":["IC00.CFE"],"status":"success",
                        "received_at":f"2026-09-30T09:31:0{poll}.123456+08:00",
                        "response":{"data":{"IC00.CFE":quote}},
                        "symbol_mapping":{"IC00.CFE":{"source_symbol":"IC2610.CFE",
                            "mapping_date":None,"trading_date":"2026-09-30"}},
                        "poll":poll,"batch":1,"batch_count":1})
            frame,cursor=read_realtime_observations(root,dataset_id="new_test_only",instruments=DESCRIPTOR["instruments"])
            self.assertEqual(cursor["sequence"],4)
            self.assertEqual(len(frame),2)
            self.assertTrue(pd.isna(frame.iloc[0].volume))
            self.assertEqual(frame.iloc[1].volume,10.)
            self.assertEqual(frame.iloc[1].volume_interval_seconds,1.)
            self.assertEqual(frame.iloc[1].observed_at.microsecond,123456)
            self.assertIn("IC00.CFE",frame.iloc[0].aliases)
            self.assertTrue(frame["source_event_time"].notna().all())
            self.assertFalse(frame.attrs["source_time_verified"])
            self.assertTrue(frame["trade_date_status"].eq("receipt_date_inferred_unverified").all())


if __name__ == "__main__":
    unittest.main()
