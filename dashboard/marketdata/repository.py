"""Explicitly registered domestic datasets, frozen reads and bounded windows."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from .bars import BarDataset, VERSION, utc_timestamp, validate_instruments


class MarketDataRepository:
    def __init__(self, roots=(), *, allow_unverified=False, publication=None):
        self.datasets = {}
        self.publication = Path(publication) if publication else None
        self.allow_unverified = allow_unverified
        self.cache = OrderedDict()
        for root in roots:
            self.add(root)

    @staticmethod
    def inspect(root):
        if not str(root).strip():
            raise ValueError("请先选择新下载数据集目录")
        ds = BarDataset(root)
        descriptor = ds.descriptor
        if descriptor.get("schema_version") != VERSION:
            raise ValueError("该目录不符合 dashboard_bars_v1；请选择包含 dataset.json 的标准数据集目录")
        validate_instruments(descriptor["instruments"])
        manifest = ds.snapshot()
        coverage = {}
        for p in manifest["parts"]:
            key = (p["instrument_id"], p["frequency"])
            row = coverage.setdefault(key, {"instrument_id":key[0],"frequency":key[1],"rows":0,
                                           "first":p["min_time"],"last":p["max_time"]})
            row["rows"] += p["rows"]
            row["first"] = min(row["first"],p["min_time"])
            row["last"] = max(row["last"],p["max_time"])
        return {"root":str(ds.root),"descriptor":descriptor,"version":manifest["version"],
                "coverage":list(coverage.values()),"synthetic":descriptor.get("data_usage")=="synthetic_only"}

    def add(self, root):
        report = self.inspect(root)
        identifier = report["descriptor"]["dataset_id"]
        ds = BarDataset(root)
        if identifier in self.datasets and self.datasets[identifier].root != ds.root:
            raise ValueError("重复 dataset_id，不能将不同目录静默拼接")
        self.datasets[identifier] = ds
        self.cache.clear()
        return report

    def freeze(self):
        if self.publication and self.publication.exists():
            from .history_publication import read_publication
            return read_publication(self.publication, self.datasets)
        return {key: ds.snapshot() for key, ds in self.datasets.items()}

    def catalog(self, frozen=None):
        frozen = self.freeze() if frozen is None else frozen
        return [{"dataset_id":key,"root":str(ds.root),"descriptor":snapshot.get("descriptor",ds.descriptor),
                 "version":snapshot["version"],"parts":snapshot["parts"]}
                for key,ds in self.datasets.items() for snapshot in [frozen[key]]]

    def symbols(self, frozen=None):
        items = {}
        for entry in self.catalog(frozen):
            for symbol,info in entry["descriptor"]["instruments"].items():
                if symbol in items and items[symbol].get("asset_type") != info.get("asset_type"):
                    raise ValueError("标的注册信息冲突")
                items[symbol] = info
        return items

    def locate(self, symbol, frequency, frozen, dataset_id=None):
        options = [key for key,snapshot in frozen.items()
                   if (dataset_id is None or key==dataset_id)
                   and any(p["instrument_id"]==symbol and p["frequency"]==frequency for p in snapshot["parts"])]
        if not options:
            raise ValueError(f"缺少 {symbol} 的 {frequency} 数据，请下载或选择对应数据集")
        if len(options)>1:
            raise ValueError(f"{symbol} / {frequency} 有多个来源，请在公式声明 dataset_id 或移除重复来源")
        return options[0], self.datasets[options[0]]

    def read_window(self, symbol, frequency, *, count=120, unit="bars", as_of,
                    fields=("close",), frozen=None, dataset_id=None, knowledge_at=None):
        if type(count) is not int or not 1<=count<=2000:
            raise ValueError("窗口需要 1–2000；较长区间请分段处理")
        if unit not in {"bars","trading_days","seconds"}:
            raise ValueError("窗口单位只支持 bars / trading_days / seconds")
        if unit=="trading_days" and frequency!="1d" or unit=="seconds" and frequency!="1s":
            raise ValueError("trading_days 对应日频，seconds 对应真实秒级 bar")
        frozen = self.freeze() if frozen is None else frozen
        key,ds = self.locate(symbol,frequency,frozen,dataset_id)
        as_of=utc_timestamp(as_of)
        columns=list(dict.fromkeys([*fields,"session_id","is_final","available_at","recorded_at","quality_flags"]))
        token=(key,frozen[key]["version"],symbol,frequency,count,unit,as_of.isoformat(),
               str(knowledge_at),tuple(columns),self.allow_unverified)
        if token in self.cache:
            self.cache.move_to_end(token)
            return self.cache[token].copy()
        parts=[p for p in frozen[key]["parts"] if p["instrument_id"]==symbol and p["frequency"]==frequency
               and utc_timestamp(p["min_time"])<=as_of]
        if unit=="seconds":
            start=as_of-pd.Timedelta(seconds=count)+pd.Timedelta(nanoseconds=1)
            frame=ds.read_bars(symbol,frequency,start=start,end=as_of,as_of=as_of,knowledge_at=knowledge_at,
                fields=columns,version=frozen[key]["version"],allow_unverified_availability=self.allow_unverified)
        elif not parts:
            frame=ds.read_bars(symbol,frequency,end=as_of,as_of=as_of,fields=columns,
                version=frozen[key]["version"],allow_unverified_availability=self.allow_unverified)
        else:
            groups={}
            for p in parts:
                groups.setdefault(p["trade_date"],[]).append(p)
            days=sorted(groups,reverse=True)
            chosen=[]
            estimate=0
            for day in days:
                chosen.append(day)
                estimate += 1 if frequency=="1d" else sum(p["rows"] for p in groups[day])
                if estimate>=count:
                    break
            lower=min(utc_timestamp(p["min_time"]) for day in chosen for p in groups[day])
            # First try a small time range, then expand if gaps/revisions reduce
            # the number of effective bars. Never interpret raw revision counts as warmup.
            start=max(lower,as_of-pd.Timedelta(seconds=count*{"1m":60,"1s":1}.get(frequency,86400)*4)) if frequency!="1d" else lower
            while True:
                frame=ds.read_bars(symbol,frequency,start=start,end=as_of,as_of=as_of,knowledge_at=knowledge_at,
                    fields=columns,version=frozen[key]["version"],allow_unverified_availability=self.allow_unverified)
                if len(frame)>=count:
                    break
                if start>lower:
                    start=lower
                    continue
                if len(chosen)==len(days):
                    break
                chosen.append(days[len(chosen)])
                lower=min(utc_timestamp(p["min_time"]) for p in groups[chosen[-1]])
                start=lower
            frame=frame.tail(count).copy()
        frame.attrs.update(dataset_id=key,window_count=count,window_unit=unit,as_of=as_of.isoformat(),
                           warmup=unit!="seconds" and len(frame)<count,
                           availability_policy=ds.descriptor["availability_policy"],
                           volume_unit=ds.descriptor["volume_unit"])
        self.cache[token]=frame.copy()
        while len(self.cache)>40:
            self.cache.popitem(last=False)
        return frame


class ReferenceBook:
    """Only a user-selected NEW reference.json; no fallback paths or pickle."""
    def __init__(self, path=None):
        self.data={"contracts":[],"aliases":[]}
        self.version=None
        if path:
            raw=Path(path).read_bytes()
            self.data=json.loads(raw)
            if self.data.get("schema_version")!="cn_index_reference_v1":
                raise ValueError("参考资料需为 cn_index_reference_v1 reference.json")
            if not isinstance(self.data.get("contracts",[]),list) or not isinstance(self.data.get("aliases",[]),list):
                raise ValueError("contracts / aliases 须为数组")
            self.version=hashlib.sha256(raw).hexdigest()[:16]
            for row in self.data.get("contracts",[]):
                validate_instruments({row["instrument_id"]:{"asset_type":"cn_index_future","market_region":"CN"}})
                if date.fromisoformat(row["listing_date"])>date.fromisoformat(row["expiry_date"]):
                    raise ValueError("挂牌日不能晚于到期日")
                utc_timestamp(row["known_at"])
            for row in self.data.get("aliases",[]):
                if not re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE",row["alias"]):
                    raise ValueError("仅支持 IF/IH/IC/IM 的 00–03 本地月份别名")
                concrete=row["concrete_instrument_id"]
                validate_instruments({concrete:{"asset_type":"cn_index_future","market_region":"CN"}})
                if concrete[:2]!=row["alias"][:2]:
                    raise ValueError("别名不能映射到其他股指品种")
                date.fromisoformat(row["trade_date"])
                utc_timestamp(row["known_at"])
                if utc_timestamp(row["valid_from"])>=utc_timestamp(row["valid_to"]):
                    raise ValueError("别名生效区间须为正时长")

    def resolve_alias(self, alias, as_of):
        stamp=utc_timestamp(as_of)
        day=stamp.tz_convert("Asia/Shanghai").date().isoformat()
        rows=[r for r in self.data.get("aliases",[]) if r["alias"]==alias and r["trade_date"]==day
              and utc_timestamp(r["known_at"])<=stamp
              and utc_timestamp(r["valid_from"])<=stamp<utc_timestamp(r["valid_to"])]
        if not rows:
            raise ValueError(f"{alias} 没有当日且当时已知的新映射，请用具体合约或补下载参考资料")
        concrete={r["concrete_instrument_id"] for r in rows}
        if len(concrete)!=1:
            raise ValueError("别名映射冲突")
        return next(iter(concrete))

    def contract(self, symbol, as_of):
        stamp=utc_timestamp(as_of)
        rows=[r for r in self.data.get("contracts",[]) if r["instrument_id"]==symbol
              and r.get("known_at") and utc_timestamp(r["known_at"])<=stamp]
        latest=max((utc_timestamp(r["known_at"]) for r in rows),default=None)
        tied=[r for r in rows if utc_timestamp(r["known_at"])==latest]
        if len({(r["listing_date"],r["expiry_date"]) for r in tied})>1:
            raise ValueError(f"{symbol} 同版本合约参考冲突")
        return deepcopy(max(rows,key=lambda r:utc_timestamp(r["known_at"]))) if rows else None
