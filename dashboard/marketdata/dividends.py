"""Read Excel caches only; immutable, explicit scenario mappings and daily inputs."""
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re

import openpyxl
import pandas as pd


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def read_snapshot(directory):
    snapshots = []
    for path in sorted(Path(directory).glob("*.xlsx")):
        if path.name.startswith(("~$", ".")): continue
        book = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            if "Sheet1" not in book: continue
            sheet = book["Sheet1"]
            stamp = sheet["B1"].value
            if not isinstance(stamp, (date, datetime)): raise ValueError(f"{path.name}: Sheet1!B1 缺少缓存快照日期")
            points, raw_rows = {}, []
            for row in sheet.iter_rows(values_only=True):
                if len(row) < 7 or not isinstance(row[1], str) or not re.fullmatch(r"(?:IF|IH|IC|IM)0[0-3]\.CFE", row[1]): continue
                alias, value = row[1], row[6]
                if alias in points: raise ValueError(f"重复分红档位 {alias}")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{alias}: G列没有有效缓存分红点数")
                points[alias] = float(value)
                raw_rows.append(dict(alias=alias, source_contract=row[2], source_expiry=str(row[4]), points=float(value)))
            if len(points) != 16: raise ValueError(f"{path.name}: 分红档位不足16个")
            content = {"date":str(pd.Timestamp(stamp).date()), "rows":raw_rows}
            snapshots.append(dict(**content, points=points, content_hash=digest(content), path=str(path.resolve()), file_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        finally: book.close()
    if not snapshots: raise ValueError("分红目录没有有效Excel缓存快照")
    latest = max(s["date"] for s in snapshots)
    candidates = [s for s in snapshots if s["date"] == latest]
    if len({s["content_hash"] for s in candidates}) != 1:
        raise ValueError(f"{latest} 分红快照同日冲突；请指定/核验源文件，未任意选取")
    return {**candidates[0], "equivalent_files":[s["path"] for s in candidates],
            "note":"读取Sheet1缓存值；具体合约模式使用C列代码/G列分红，E列日期不覆盖独立合约参考；Sheet2未来零值不作未来分红。"}


def make_contract_scenario(snapshot, metadata, as_of):
    """Concrete C/G values first; missing active maturities inherit their predecessor.

    Inheritance is an explicit user-selected estimate, not a new observation.
    Rebuild from source every time so a later real value (including zero) wins.
    """
    day=str(pd.Timestamp(as_of).date())
    mapping={}
    for row in snapshot['rows']:
        symbol=row['source_contract']
        if not isinstance(symbol,str) or not re.fullmatch(r'(?:IF|IH|IC|IM)\d{4}\.CFE',symbol) or symbol[:2]!=row['alias'][:2]:
            raise ValueError('分红表C列缺少有效的同品种具体合约：'+str(symbol))
        ref=metadata.get(symbol)
        if not ref:continue
        value=dict(alias=row['alias'],points=row['points'],expiry=ref['expiry_date'],
                   value_source_contract=symbol,source_kind='spreadsheet_concrete',source_snapshot=snapshot['date'])
        if symbol in mapping and mapping[symbol]['points']!=value['points']:
            raise ValueError('分红表同一具体合约数值冲突：'+symbol)
        mapping[symbol]=value
    inherited={}
    for product in ('IF','IH','IC','IM'):
        active=sorted((s for s,r in metadata.items() if s.startswith(product) and r['listing_date']<=day<=r['expiry_date']),
                      key=lambda s:metadata[s]['expiry_date'])
        for i,symbol in enumerate(active):
            if symbol not in mapping:
                previous=[s for s,r in mapping.items() if s.startswith(product) and r['expiry']<metadata[symbol]['expiry_date']]
                if not previous:continue
                predecessor=max(previous,key=lambda s:mapping[s]['expiry'])
                origin=mapping[predecessor]
                mapping[symbol]=dict(points=origin['points'],expiry=metadata[symbol]['expiry_date'],
                    inherited_from=predecessor,value_source_contract=origin['value_source_contract'],
                    source_kind='previous_contract_estimate',source_snapshot=snapshot['date'])
                inherited[symbol]=predecessor
            mapping[symbol]['alias']=f'{product}0{i}.CFE' if len(active)==4 else symbol
    result=dict(mode='fixed_snapshot',snapshot_date=snapshot['date'],snapshot_hash=snapshot['content_hash'],
        mapping_anchor=day,mapping=mapping,inherited=inherited,
        mapping_policy='Sheet1!C具体合约对应G分红；缺失的在市合约沿用同品种前一到期合约，正式值优先（包括零）',
        historical_policy='固定分红情景；继承值为估计，非真实逐日剩余分红')
    result['version']=digest(result)
    return result


def make_scenario(snapshot, reference, anchor):
    """Explicit scenario anchor, persisted by the caller; never called on a roll."""
    anchor = str(pd.Timestamp(anchor).date())
    mapping = {}
    for product in ("IF", "IH", "IC", "IM"):
        latest = {}
        for row in reference.data["contracts"]:
            symbol = row["instrument_id"]
            if not symbol.startswith(product): continue
            if symbol in latest and row["known_at"] == latest[symbol]["known_at"] and (row["listing_date"],row["expiry_date"]) != (latest[symbol]["listing_date"],latest[symbol]["expiry_date"]):
                raise ValueError(f"{symbol} 同版本合约参考冲突")
            if symbol not in latest or row["known_at"] > latest[symbol]["known_at"]: latest[symbol] = row
        active = sorted([r for r in latest.values() if r["listing_date"] <= anchor <= r["expiry_date"]], key=lambda r:r["expiry_date"])
        if len(active) != 4 or len({r["expiry_date"] for r in active}) != 4:
            raise ValueError(f"{product} 在 {anchor} 无法形成可信的4档具体合约映射")
        for i, row in enumerate(active):
            alias = f"{product}0{i}.CFE"
            mapping[row["instrument_id"]] = dict(alias=alias, points=snapshot["points"][alias], expiry=row["expiry_date"])
    result = dict(mode="fixed_snapshot", snapshot_date=snapshot["date"], snapshot_hash=snapshot["content_hash"],
        mapping_anchor=anchor, mapping=mapping, reference_version=reference.version,
        mapping_policy="按映射锚定日独立DDB合约参考的挂牌/到期排序；源表C/E均不参与；映射固定，不随换月滚动",
        historical_policy="同一具体合约全部历史使用同一固定分红情景；不是当时真实剩余分红")
    result["version"] = digest(result)
    return result


@dataclass
class DividendBook:
    mode: str = "fixed_snapshot"
    version: str = "unavailable"
    info: dict = field(default_factory=dict)
    reason: str = "缺少分红输入"

    @classmethod
    def load(cls, directory, scenario_file=None, daily_file=None, mode="fixed_snapshot", *, contracts=None, as_of=None, missing_policy=None):
        try:
            if mode == "daily_remaining":
                data = json.loads(Path(daily_file).read_text(encoding="utf-8"))
                if data.get("schema") != "contract_daily_dividends_v1": raise ValueError("逐日分红格式无效")
                seen = {}
                for row in data["rows"]:
                    key = (row["date"], row["instrument_id"])
                    date.fromisoformat(row["date"])
                    if not re.fullmatch(r"(?:IF|IH|IC|IM)\d{4}\.CFE", key[1]): raise ValueError("逐日分红须使用具体合约")
                    if not math.isfinite(row["points"]) or row["points"] < 0: raise ValueError("分红点数无效")
                    if key in seen and seen[key] != row: raise ValueError("同日同合约分红冲突")
                    seen[key] = row
                return cls(mode, digest(data), data, "")
            snapshot = read_snapshot(directory)
            if missing_policy=='previous_contract':
                if contracts is None or as_of is None:raise ValueError('具体合约分红需要合约参考与计算日期')
                scenario=make_contract_scenario(snapshot,contracts,as_of)
                return cls(mode,scenario['version'],{**scenario,'source':snapshot},'')
            if not scenario_file: raise ValueError("固定快照尚未建立明确情景映射")
            scenario = json.loads(Path(scenario_file).read_text(encoding="utf-8"))
            if scenario["snapshot_hash"] != snapshot["content_hash"]: raise ValueError("分红快照版本已变化，需建立新的明确情景映射")
            if scenario["version"] != digest({k:v for k,v in scenario.items() if k != "version"}): raise ValueError("情景映射版本哈希不符")
            return cls(mode, scenario["version"], {**scenario, "source":snapshot}, "")
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return cls(mode=mode, reason=str(exc))

    def points(self, symbol, day):
        if self.reason: return None
        if self.mode == "fixed_snapshot":
            row = self.info.get("mapping", {}).get(symbol)
            if not row or str(pd.Timestamp(day).date()) > row["expiry"]: return None
            return row["points"]
        rows = [r for r in self.info["rows"] if r["instrument_id"] == symbol and r["date"] == str(pd.Timestamp(day).date())]
        return rows[0]["points"] if rows else None


def adjusted_basis(future, spot, dividend, days):
    if any(v is None or not math.isfinite(v) for v in (future, spot, dividend)) or spot <= 0:
        return dict(adjusted_future=None, points=None, bp=None, annual_pct=None, convergence_bp_day=None)
    points = future - spot + dividend
    bp = 10000 * points / spot
    return dict(adjusted_future=future+dividend, points=points, bp=bp,
        annual_pct=bp*365/(100*days) if days is not None and days >= 5 else None,
        convergence_bp_day=-bp/days if days is not None and days > 0 else None)
