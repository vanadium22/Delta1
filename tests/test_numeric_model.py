from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import pandas as pd
import pyarrow as pa

from dashboard.marketdata import BAR_SCHEMA,BarDataset
from dashboard.marketdata.repository import MarketDataRepository,ReferenceBook
from dashboard.native.collection import ScopedResolver,CollectionJob
from dashboard.native.factors import TEMPLATES,definition,evaluate
from dashboard.native.factor_worker import zscore
from dashboard.native.metrics import summarize,executable_spread
from dashboard.native.model import NativeModel
from index_strategy.instant_dld.contract_aliases import DualIdentityStore


def fixture(root):
    instruments={"000905.SH":{"asset_type":"cn_index","market_region":"CN"},
        "IC2610.CFE":{"asset_type":"cn_index_future","market_region":"CN","underlying_id":"000905.SH"},
        "IC2611.CFE":{"asset_type":"cn_index_future","market_region":"CN","underlying_id":"000905.SH"}}
    store=BarDataset.create(root,{"dataset_id":"test_new_domestic","source_id":"test_fixture",
        "series_kind":"concrete","price_adjustment":"none","volume_unit":"test_contracts",
        "availability_policy":"source_reported","instruments":instruments})
    rows=[]
    for rank,symbol in enumerate(instruments):
        for frequency,events in (("1d",pd.bdate_range("2026-08-03","2026-09-30")),
            ("1m",pd.date_range("2026-09-30T01:31:00Z",periods=120,freq="min")),
            ("1s",pd.date_range("2026-09-30T03:29:01Z",periods=60,freq="s"))):
            for i,event in enumerate(events):
                if frequency=="1d": event=(event.tz_localize("Asia/Shanghai")+pd.Timedelta(hours=15)).tz_convert("UTC")
                close=7000-rank*15+i*.05+math.sin(i*.15+rank)
                rows.append({"instrument_id":symbol,"frequency":frequency,"event_time":event,
                    "bar_start":event-pd.Timedelta(seconds={"1d":19800,"1m":60,"1s":1}[frequency]),
                    "trade_date":event.tz_convert("Asia/Shanghai").date(),"session_id":"day_am",
                    "close":close,"prev_close":6990. if frequency=="1d" else None,
                    "is_final":True,"revision":0,"available_at":event+pd.Timedelta(seconds=1),
                    "recorded_at":"2026-10-01T00:00:00Z","quality_flags":0})
    store.commit(rows)
    return store


class NativeBackendTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.store=fixture(self.root/"new_history")
        self.model=NativeModel(self.root/"settings")
        self.model.config.update(history_roots=[str(self.store.root)],results_root=str(self.root/"results"))
        self.addCleanup(self.model.close)
        self.request={"product":"IC","frequency":"1m","as_of":"2026-09-30T03:30:02Z","save":False}

    def test_multifrequency_snapshot_uses_concrete_contracts_and_past_daily_data(self):
        state=self.model.snapshot(self.request)
        self.assertEqual(state["roles"]["$near"],"IC2610.CFE")
        self.assertEqual(len(state["spread"]),120)
        self.assertIsNotNone(state["values"]["basis_bp"])
        daily=self.model.repo.read_window("000905.SH","1d",count=20,unit="trading_days",as_of=self.request["as_of"])
        self.assertEqual(len(daily),20)
        self.assertLess(daily.iloc[-1].trade_date,pd.Timestamp("2026-09-30").date())

    def test_frozen_repository_does_not_see_new_revision(self):
        repo=MarketDataRepository([self.store.root]);frozen=repo.freeze()
        prior=repo.read_window("IC2610.CFE","1m",count=1,as_of=self.request["as_of"],frozen=frozen)
        row=pa.Table.from_pandas(self.store.read_bars("IC2610.CFE","1m"),schema=BAR_SCHEMA,preserve_index=False).to_pylist()[-1]
        row.update(revision=1,close=row["close"]+1.,quality_flags=int(row["quality_flags"]))
        self.store.commit([row])
        before=repo.read_window("IC2610.CFE","1m",count=1,as_of=self.request["as_of"],frozen=frozen)
        after=repo.read_window("IC2610.CFE","1m",count=1,as_of=self.request["as_of"])
        self.assertEqual(before.iloc[-1].close,prior.iloc[-1].close)
        self.assertEqual(after.iloc[-1].close,prior.iloc[-1].close+1.)

    def test_seconds_window_is_clock_range_not_poll_count(self):
        repo=MarketDataRepository([self.store.root])
        data=repo.read_window("IC2610.CFE","1s",count=10,unit="seconds",as_of="2026-09-30T03:30:01Z")
        self.assertEqual(len(data),9)  # one-second availability delay and exclusive left clock boundary
        self.assertTrue((data["event_time"]>pd.Timestamp("2026-09-30T03:29:51Z")).all())

    def test_duplicate_sources_require_selection(self):
        new=BarDataset.create(self.root/"second",{**self.store.descriptor,"dataset_id":"second_vendor"})
        row=pa.Table.from_pandas(self.store.read_bars("IC2610.CFE","1m"),schema=BAR_SCHEMA,preserve_index=False).to_pylist()[0]
        row.update(revision=int(row["revision"]),quality_flags=int(row["quality_flags"]))
        new.commit([row])
        repo=MarketDataRepository([self.store.root,new.root])
        with self.assertRaisesRegex(ValueError,"多个来源"):
            repo.read_window("IC2610.CFE","1m",count=1,as_of=self.request["as_of"])

    def test_dynamic_formula_publish_and_multifrequency_preview(self):
        spec={**TEMPLATES[1],"id":"new_multi","name":"新多频指标"}
        published=self.model.publish_formula(spec)
        answer=self.model.preview(published,self.request)
        self.assertEqual({item["frequency"] for item in answer["inputs"]},{"1d","1m"})
        self.assertIsNotNone(answer["values"]["分钟均值偏离"])
        restored=NativeModel(self.root/"settings");self.addCleanup(restored.close)
        self.assertIn("new_multi",[s["id"] for s in restored.formulas])

    def test_unchanged_data_does_not_create_results_for_each_clock_refresh(self):
        self.model.snapshot({**self.request,"save":True})
        count=self.model.results.stats()["rows"]
        self.model.snapshot({**self.request,"as_of":"2026-09-30T03:30:03Z","save":True})
        self.assertEqual(self.model.results.stats()["rows"],count)
        self.assertTrue(list((self.root/"results"/"factors").rglob("*.parquet")))

    def test_unwritable_results_do_not_prevent_market_view_from_rendering(self):
        with patch('dashboard.native.model.ResultStore',side_effect=OSError('mock output path locked')):
            state=self.model.snapshot({**self.request,"save":True})
        self.assertEqual(len(state["spread"]),120)
        self.assertIn('mock output path locked',state['archive_error'])

    def test_replay_timeline_does_not_shrink_at_an_earlier_cursor(self):
        all_data=self.model.snapshot(self.request)
        earlier=self.model.snapshot({**self.request,"as_of":"2026-09-30T02:20:01Z"})
        self.assertEqual(earlier["timeline"],all_data["timeline"])
        self.assertLess(len(earlier["near"]),len(all_data["near"]))

    def test_missing_second_frequency_reports_reason(self):
        spec={**TEMPLATES[2],"inputs":[{**TEMPLATES[2]["inputs"][0],"instrument_id":"IF2610.CFE"}]}
        with self.assertRaisesRegex(ValueError,"缺少"):
            self.model.preview(spec,self.request)

    def test_no_default_external_history_source(self):
        model=NativeModel(self.root/"blank");self.addCleanup(model.close)
        self.assertEqual(model.config["history_roots"],[])
        self.assertEqual(model.config["realtime_root"],"")
        self.assertEqual(model.config["reference_file"],"")

    def test_auto_refresh_skips_unchanged_sources_but_not_a_commit_during_calculation(self):
        request={"product":"IC","frequency":"1m","save":False}
        self.model.snapshot(request)
        self.assertIsNone(self.model.auto_snapshot(request))
        row=pa.Table.from_pandas(self.store.read_bars("IC2610.CFE","1m"),schema=BAR_SCHEMA,preserve_index=False).to_pylist()[-1]
        row.update(revision=1,close=row["close"]+1.)
        original=self.model.repo.freeze
        def during_freeze():
            self.store.commit([row])
            return original()
        with patch.object(self.model.repo,"freeze",side_effect=during_freeze):
            self.model.snapshot(request)
        self.assertIsNotNone(self.model.auto_snapshot(request))
        self.assertIsNone(self.model.auto_snapshot(request))

    def test_new_realtime_store_can_feed_formulas_without_history_and_cannot_leak_into_replay(self):
        live_root=self.root/"new_live"
        symbols=["IC2610.CFE","IC2611.CFE","000905.SH"]
        with DualIdentityStore(live_root) as writer:
            quotes={symbol:{"securityId":symbol,"latestPrice":7000.-i*10,
                "quoteTimestamp":113000,"tradedQuantities":100.,
                "b1Price":7000.-i*10,"s1Price":7001.-i*10,"b1Stocks":3.,"s1Stocks":5.} for i,symbol in enumerate(symbols)}
            writer.batch({"symbols":symbols,"status":"success","received_at":"2026-09-30T11:30:00.123456+08:00",
                "response":{"data":quotes},"poll":1,"batch":1,"batch_count":1,
                "symbol_mapping":{s:{"source_symbol":s,"mapping_date":None,"trading_date":None} for s in symbols}})
        self.model.config.update(history_roots=[],realtime_root=str(live_root),realtime_id="new_fixture_only",collection_symbols=symbols)
        self.model.root_key=None
        request={**self.request,"as_of":"2026-09-30T03:30:01Z"}
        state=self.model.snapshot(request)
        self.assertEqual(state["book"]["buy"],11.)
        factor=next(f for f in state["factors"] if f["spec"]["id"]=="live_calendar_book")
        self.assertEqual(factor["values"]["买入价差"],11.)
        self.assertEqual(factor["quality"],"unverified_observation")
        index=next(x for x in state["indices"] if x["symbol"]=="000905.SH")
        self.assertTrue(index["observation"]);self.assertIsNone(index["change"])
        earlier=self.model.snapshot({**request,"as_of":"2026-09-30T03:29:59Z"})
        self.assertEqual(earlier["live_quotes"],0);self.assertIsNone(earlier["book"])
        expired=self.model.snapshot({**request,"as_of":"2026-09-30T03:31:00Z"})
        self.assertIsNone(expired["book"])
        self.assertIn("过期",next(f for f in expired["factors"] if f["spec"]["id"]=="live_calendar_book")["error"])

    def test_formula_zscore_does_not_mix_morning_with_afternoon(self):
        rows=[{"frequency":"1m","trade_date":"2026-09-30","session_id":"am","close":i*1.} for i in range(40)]
        rows.append({**rows[-1],"session_id":"pm","close":100.})
        self.assertIsNone(zscore(rows,"close",30))

    def test_reference_time_and_expiry_filter_out_unknown_and_expired_contracts(self):
        path=self.root/"new_reference.json"
        path.write_text(json.dumps({"schema_version":"cn_index_reference_v1","contracts":[
            {"instrument_id":"IC2610.CFE","listing_date":"2026-08-01","expiry_date":"2026-09-29","known_at":"2026-08-01T00:00:00Z"},
            {"instrument_id":"IC2611.CFE","listing_date":"2026-08-01","expiry_date":"2026-11-20","known_at":"2026-08-01T00:00:00Z"}],
            "aliases":[{"alias":"IC00.CFE","concrete_instrument_id":"IC2611.CFE","trade_date":"2026-09-30",
                "valid_from":"2026-09-30T01:00:00Z","valid_to":"2026-09-30T16:00:00Z","known_at":"2026-09-30T02:00:00Z"}]}))
        reference=ReferenceBook(path)
        with self.assertRaisesRegex(ValueError,"当时已知"):
            reference.resolve_alias("IC00.CFE","2026-09-30T01:30:00Z")
        self.model.config["reference_file"]=str(path)
        state=self.model.snapshot(self.request)
        self.assertEqual(state["roles"]["$near"],"IC2611.CFE")
        self.assertIsNone(state["roles"]["$far"])
        self.assertTrue(state["contracts_verified"])

    def test_results_are_visible_after_restart_without_loading_market_data(self):
        self.model.save_config(self.model.config)
        self.model.snapshot({**self.request,"save":True})
        expected=len(self.model.result_history());self.assertGreater(expected,0)
        self.model.close()
        restored=NativeModel(self.root/"settings");self.addCleanup(restored.close)
        self.assertIsNone(restored.repo)
        self.assertEqual(len(restored.result_history()),expected)

    def test_archive_page_uses_current_output_path_and_never_reuses_demo_rows(self):
        self.model.snapshot({**self.request,"save":True})
        self.assertGreater(len(self.model.result_history()),0)
        self.model.config["results_root"]=str(self.root/"other_new_results")
        self.assertEqual(self.model.result_history(),[])
        self.model.demo=True
        self.assertEqual(self.model.result_history(),[])
        self.assertEqual(self.model.result_directory(),self.model.local_root/"demo_results")

    def test_collection_reports_client_initialization_failure_and_rejects_bad_months(self):
        resolver=ScopedResolver(["000905.SH"])
        _,errors=resolver.resolve_many(["IC2613.CFE"])
        self.assertIn("月份",errors["IC2613.CFE"])
        job=CollectionJob(self.root/"settings")
        def fail(**kwargs): raise RuntimeError("mock initialization failure")
        from unittest.mock import patch
        with patch('dashboard.session_clock.session_policy',return_value=dict(allowed=True,reason='test session')):
            job.start(self.root/"new_live",["IC2610.CFE"],["000905.SH"],once=True,client_factory=fail)
        job.worker.join(timeout=5)
        self.assertEqual(job.state()["status"],"failed")
        self.assertIn("mock initialization failure",job.state()["error"])

    def test_gapped_or_cross_session_prices_do_not_produce_realized_volatility(self):
        state=self.model.snapshot(self.request)
        near=state["near"].copy();near.loc[near.index[-5],"session_id"]="different"
        values,reasons,_,_=summarize(near,state["near"],state["spot"],"1m")
        self.assertIsNone(values["realized_bp"])
        self.assertIn("跨会话",reasons["realized_bp"])

    def test_quote_receipt_skew_and_staleness_block_executable_spread(self):
        near={"observed_at":"2026-09-30T03:30:00Z","bid_price_1":100.,"ask_price_1":101.}
        far={**near,"bid_price_1":98.,"ask_price_1":99.}
        values,_=executable_spread(near,far,"2026-09-30T03:30:01Z")
        self.assertEqual(values["buy"],3.)
        self.assertIsNone(executable_spread(near,far,"2026-09-30T03:31:00Z")[0])
        self.assertIsNone(executable_spread(near,far,"2026-09-30T03:29:59Z")[0])
        self.assertIsNone(executable_spread(near,{**far,"observed_at":"2026-09-30T03:30:10Z"},"2026-09-30T03:30:10Z")[0])

    def test_scoped_collector_does_not_resolve_with_existing_calendar(self):
        resolver=ScopedResolver(["000905.SH"])
        accepted,errors=resolver.resolve_many(["IC2610.CFE","000905.SH","IC00.CFE","AU2612.SHF","00700.HK"])
        self.assertEqual(set(accepted),{"IC2610.CFE","000905.SH"})
        self.assertEqual(accepted["IC2610.CFE"]["trading_date"],None)
        self.assertEqual(len(errors),3)

    def test_formula_v2_keeps_process_isolation_and_resource_limits(self):
        for code in ("def compute(inputs, params):\n    import os\n    return {'x':1}",
                     "def compute(inputs, params):\n    return {'x': inputs.__class__}",
                     "def compute(inputs, params):\n    while True:\n        pass"):
            with self.subTest(code=code),self.assertRaises(ValueError): definition({**TEMPLATES[0],"code":code})
        spec=definition({**TEMPLATES[0],"code":"def compute(inputs, params):\n    x = [1] * 1000000000000\n    return {'x':len(x)}"})
        with self.assertRaisesRegex(ValueError,"列表扩增"): evaluate(spec,{"near":[],"far":[]})
