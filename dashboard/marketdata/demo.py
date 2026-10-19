"""Generate SYNTHETIC fixtures only. Requires an explicit output root."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .bars import BAR_SCHEMA, REQUIRED, BarDataset


def create_examples(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "SYNTHETIC_ONLY.txt").write_text(
        "仅格式与读取测试用合成数据，不代表真实价格、交易日历、挂牌合约或行情。\n"
        "未接入任何已有市场数据。请不要将此目录启用为生产看板数据源。\n", encoding="utf-8")
    stores = {}
    for name, instruments, volume_unit in (
        ("synthetic_cn_index", {"000905.SH":{"asset_type":"cn_index","market_region":"CN"}}, "not_applicable"),
        ("synthetic_cfe", {s:{"asset_type":"cn_index_future","market_region":"CN"}
                           for s in ["IC2610.CFE","IC2611.CFE"]}, "synthetic_contracts"),
    ):
        descriptor = {"dataset_id":name,"source_id":"synthetic_fixture_no_provider",
                      "series_kind":"concrete","price_adjustment":"none","volume_unit":volume_unit,
                      "availability_policy":"assumed_bar_end_plus_delay",
                      "availability_delay_seconds":1,"instruments":instruments,
                      "data_usage":"synthetic_only","calendar_method":"weekday_fixture_not_exchange_calendar"}
        stores[name] = BarDataset.create(root/name,descriptor)
    daily = list(pd.bdate_range("2026-09-01","2026-09-30"))
    minute = list(pd.date_range("2026-09-30T01:31:00Z",periods=30,freq="min"))
    seconds = list(pd.date_range("2026-09-30T02:00:01Z",periods=30,freq="s"))
    summary={"data_usage":"synthetic_only","market_scope":["cn_index","cn_index_future"],"datasets":{}}
    for name,store in stores.items():
        rows=[]
        for symbol in store.descriptor["instruments"]:
            base={"000905.SH":7000.,"IC2610.CFE":6980.,"IC2611.CFE":6960.}[symbol]
            for frequency,events in (("1d",daily),("1m",minute),("1s",seconds)):
                for i,event in enumerate(events):
                    event=(event.tz_localize("Asia/Shanghai")+pd.Timedelta(hours=15)).tz_convert("UTC") if frequency=="1d" else event
                    close=base+i*.2
                    rows.append({"instrument_id":symbol,"frequency":frequency,"event_time":event,
                        "bar_start":event-pd.Timedelta(seconds={"1d":19800,"1m":60,"1s":1}[frequency]),
                        "trade_date":event.tz_convert("Asia/Shanghai").date(),"session_id":"synthetic_session",
                        "source_symbol":symbol,"open":close-.1,"high":close+.3,"low":close-.2,"close":close,
                        "volume":None if symbol.endswith(".SH") else float(10+i),
                        "is_final":True,"revision":0,"available_at":event+pd.Timedelta(seconds=1),
                        "recorded_at":"2026-10-01T00:00:00Z","quality_flags":1,"sample_count":None})
        first=store.commit(rows,checkpoint={"fixture_through":"2026-09-30"})
        repeated=store.commit(rows)
        counts={frequency:len(store.read_bars(list(store.descriptor["instruments"]),frequency))
                for frequency in ("1d","1m","1s")}
        summary["datasets"][name]={"root":str(store.root),"rows_by_frequency":counts,
                                    "first_commit":first,"repeat_commit":repeated}
    near=stores["synthetic_cfe"].read_bars("IC2610.CFE","1m",fields=["close"])
    far=stores["synthetic_cfe"].read_bars("IC2611.CFE","1m",fields=["close"])
    aligned=near.merge(far,on="event_time",suffixes=("_near","_far"))
    day_frame=stores["synthetic_cn_index"].read_bars("000905.SH","1d",fields=["close"])
    summary["read_examples"]={"matched_minute_rows":len(aligned),
         "last_calendar_spread_points":float(aligned.iloc[-1].close_near-aligned.iloc[-1].close_far),
         "daily_ma20":float(day_frame["close"].tail(20).mean()),
         "last_five_seconds_rows":len(stores["synthetic_cfe"].read_bars("IC2610.CFE","1s",
              start="2026-09-30T02:00:26Z",end="2026-09-30T02:00:30Z",fields=["close"]))}
    (root/"example_report.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    fields={"schema_version":"dashboard_bars_v1","timestamp_semantics":"bar_end",
            "required_presence":sorted(REQUIRED),
            "fields":[{"name":f.name,"arrow_type":str(f.type),
                       "required":f.name in REQUIRED,"nullable":f.name not in REQUIRED or f.name=="available_at"}
                      for f in BAR_SCHEMA]}
    (root/"bar_fields.json").write_text(json.dumps(fields,ensure_ascii=False,indent=2),encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser(description="只生成国内指数/股指期货格式的合成测试数据")
    parser.add_argument("--root",required=True,help="明确指定合成数据的测试输出目录")
    args=parser.parse_args()
    print(json.dumps(create_examples(args.root),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
