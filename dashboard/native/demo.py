"""Deterministic domestic-only synthetic fixtures for the native UI."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from dashboard.marketdata import BarDataset
from index_strategy.instant_dld.service import write_json

from .instruments import UNDERLYINGS


def generate(root):
    root=Path(root)
    marker=root/"demo_ready.json"
    if marker.is_file() and json.loads(marker.read_text()).get("version")==3:
        return [str(root/"index"),str(root/"futures")]
    root.mkdir(parents=True,exist_ok=True)
    (root/"SYNTHETIC_ONLY.txt").write_text("合成演示数据。价格、日期、盘口与挂牌信息均非真实行情。\n",encoding="utf-8")
    index_info={v[0]:{"asset_type":"cn_index","market_region":"CN","name":v[1],"price_unit":"index_points"}
                for v in UNDERLYINGS.values()}
    future_info={f"{product}{month}.CFE":{"asset_type":"cn_index_future","market_region":"CN",
                   "underlying_id":underlying[0],"price_unit":"index_points"}
                 for product,underlying in UNDERLYINGS.items() for month in ("2610","2611","2612","2703")}
    stores={}
    for name,instruments in (("index",index_info),("futures",future_info)):
        stores[name]=BarDataset.create(root/name,{"dataset_id":"native_synthetic_"+name,"source_id":"synthetic_only",
            "series_kind":"concrete","price_adjustment":"none","volume_unit":"not_applicable" if name=="index" else "synthetic_contracts",
            "availability_policy":"assumed_bar_end_plus_delay","availability_delay_seconds":1,
            "instruments":instruments,"data_usage":"synthetic_only","fixture_version":3})
    days=list(pd.bdate_range("2026-07-29","2026-09-30"))
    minutes=[*pd.date_range("2026-09-30T01:31:00Z",periods=120,freq="min"),
             *pd.date_range("2026-09-30T05:01:00Z",periods=120,freq="min")]
    seconds=list(pd.date_range("2026-09-30T06:50:01Z",periods=600,freq="s"))
    batches={"index":[],"futures":[]}
    for product_index,(product,(spot,name,base)) in enumerate(UNDERLYINGS.items()):
        for rank,symbol in enumerate([spot,*[f"{product}{m}.CFE" for m in ("2610","2611","2612","2703")]]):
            for frequency,events in (("1d",days),("1m",minutes),("1s",seconds)):
                for i,event in enumerate(events):
                    if frequency=="1d":
                        event=(event.tz_localize("Asia/Shanghai")+pd.Timedelta(hours=15)).tz_convert("UTC")
                    fraction=i/max(1,len(events)-1)
                    trend=(.003,.0015,-.002,.006)[product_index]
                    spot_value=base*(1+trend*fraction)+base*.0011*math.sin(fraction*math.pi*5+product_index*.45)
                    spot_value+=base*.00015*math.sin(i*.39+product_index*.7)
                    basis=0 if rank==0 else -base*(.0012+.00035*product_index)-(rank-1)*(10+product_index*4)+2.3*math.sin(fraction*11+rank*.35+product_index*.5)
                    if rank==1:
                        basis+=(8+product_index*5)*math.exp(-((fraction-(.6+product_index*.09))/.045)**2)
                        basis+=.3*math.sin(i*.73+product_index)
                        if product=="IM" and fraction>=.975: basis+=18
                        if product=="IF" and .69<=fraction<=.735: basis-=12
                    close=round(spot_value+basis,3)
                    previous=base*(1-.002) if frequency=="1d" else None
                    session="day_am" if event.tz_convert("Asia/Shanghai").hour<12 else "day_pm"
                    batches["index" if rank==0 else "futures"].append({"instrument_id":symbol,"frequency":frequency,
                        "event_time":event,"bar_start":event-pd.Timedelta(seconds={"1d":19800,"1m":60,"1s":1}[frequency]),
                        "trade_date":event.tz_convert("Asia/Shanghai").date(),"session_id":session,
                        "source_symbol":symbol,"open":close-.2,"high":close+.4,"low":close-.5,"close":close,
                        "volume":None if rank==0 else round(12+5*math.sin(i*.16)**2+rank*2,1),
                        "prev_close":previous,"is_final":True,"revision":0,
                        "available_at":event+pd.Timedelta(seconds=1),"recorded_at":"2026-10-01T00:00:00Z",
                        "quality_flags":1,"sample_count":None})
    for name,rows in batches.items():
        stores[name].commit(rows,checkpoint={"data_usage":"synthetic_only"})
    write_json(marker,{"version":3,"data_usage":"synthetic_only"})
    return [str(root/"index"),str(root/"futures")]
