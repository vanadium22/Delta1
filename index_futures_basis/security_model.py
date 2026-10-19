"""Single-security query contract and calculations; no network or filesystem access."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re

import numpy as np
import pandas as pd

TZ = "Asia/Shanghai"
FIELDS = {"close": "收盘价", "open": "开盘价", "high": "最高价", "low": "最低价",
          "volume": "成交量", "amt": "成交额", "oi": "持仓量（手）"}
REALTIME = {"close": "rt_last", "open": "rt_open", "high": "rt_high", "low": "rt_low",
            "volume": "rt_vol", "amt": "rt_amt"}
VOLUME_UNITS = {"unknown": ("未确认", None), "share": ("股 / 份", 1), "lot100": ("手（100股/份）", 100)}
AMOUNT_UNITS = {"unknown": ("未确认", None), "yuan": ("元", 1), "thousand": ("千元", 1000), "wan": ("万元", 10000)}


def local_time(value):
    value = pd.Timestamp(value)
    if pd.isna(value):
        raise ValueError("时间不能为空")
    return value.tz_localize(TZ) if value.tzinfo is None else value.tz_convert(TZ)


def field_label(field, frequency):
    if frequency == "snapshot":
        return {"close": "最新成交价", "volume": "当日累计成交量", "amt": "当日累计成交额"}.get(field, FIELDS[field])
    return FIELDS[field]


@dataclass(frozen=True)
class SecurityQuery:
    code: str
    frequency: str = "1d"
    fields: tuple = ("close",)
    start: str = ""
    end: str = ""
    twap: bool = False
    vwap: bool = False
    volume_unit: str = "unknown"
    amount_unit: str = "unknown"
    adjustment: str = "none"

    def __post_init__(self):
        code = self.code.strip().upper()
        if re.fullmatch(r"(?:IF|IH|IC|IM)(?:0[0-3]|\d{4})", code):
            code += ".CFE"
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "fields", tuple(sorted(set(self.fields))))
        if not re.fullmatch(r"\d{6}\.(SH|SZ)", self.code) and not self.is_future:
            raise ValueError("请输入完整沪深 Wind 代码或股指期货代码，例如 600519.SH、IF02、IF2612.CFE")
        if self.frequency not in {"1d", "1m", "5m", "15m", "30m", "60m", "snapshot"}:
            raise ValueError("不支持的频率")
        if not self.fields or set(self.fields) - FIELDS.keys():
            raise ValueError("至少选择一个支持的行情字段")
        if "oi" in self.fields and not self.is_future:
            raise ValueError("持仓量字段仅用于本地股指期货日线")
        object.__setattr__(self, "fields", tuple(f for f in FIELDS if f in self.fields))
        if self.adjustment != "none":
            raise ValueError("本版使用不复权原始行情")
        if self.volume_unit not in VOLUME_UNITS or self.amount_unit not in AMOUNT_UNITS:
            raise ValueError("无效单位")
        if self.frequency == "snapshot":
            object.__setattr__(self, "start", "")
            object.__setattr__(self, "end", "")
            if self.twap or self.vwap:
                raise ValueError("最新快照不计算区间 TWAP / VWAP")
        else:
            start, end = local_time(self.start), local_time(self.end)
            if self.frequency == "1d":
                start, end = start.normalize(), end.normalize()
                object.__setattr__(self, "start", start.date().isoformat())
                object.__setattr__(self, "end", end.date().isoformat())
            else:
                for value in (start, end):
                    if value.second or value.microsecond:
                        raise ValueError("分钟窗口须精确到整分钟")
                    minute = value.hour * 60 + value.minute
                    for first, last in ((570, 690), (780, 900)):
                        if first < minute < last and (minute - first) % self.bar_minutes:
                            raise ValueError("窗口端点须对齐所选分钟周期（以09:30、13:00起算）")
                object.__setattr__(self, "start", start.isoformat())
                object.__setattr__(self, "end", end.isoformat())
            if start > end or (self.frequency != "1d" and start == end):
                raise ValueError("开始时间必须早于结束时间（日频可选同一天）")
            limit = 3660 if self.frequency == "1d" else 62
            if (end - start).days > limit:
                raise ValueError(f"单次窗口最多 {limit} 天，请分段查询")
        if self.twap and not self.frequency.endswith("m"):
            raise ValueError("TWAP 使用分钟采样；日频可查看日收盘价均值")
        if self.vwap and not self.is_equity:
            raise ValueError("VWAP 当前仅支持沪深股票 / ETF；指数成交额除成交量不等于指数点位")

    @property
    def is_future(self):
        return bool(re.fullmatch(r"(?:IF|IH|IC|IM)(?:0[0-3]|\d{4})\.CFE", self.code))

    @property
    def is_equity(self):
        return bool(re.fullmatch(r"(?:[56]\d{5}\.SH|(?:00|30|15|16|18)\d{4}\.SZ)", self.code))

    @property
    def bar_minutes(self):
        return int(self.frequency[:-1]) if self.frequency.endswith("m") else 0

    @property
    def required_fields(self):
        fields = set(self.fields)
        if self.twap:
            fields.add("close")
        if self.vwap:
            fields.update(("volume", "amt"))
        return [f for f in FIELDS if f in fields]

    def metadata(self):
        return asdict(self)


def expected_times(query, days):
    """Mainland continuous-session bars, labelled by right endpoint; (start, end]."""
    if query.frequency == "1d":
        return [str(day) for day in days if query.start <= str(day) <= query.end]
    start, end = local_time(query.start), local_time(query.end)
    result = []
    for day in days:
        for first, last in (("09:30", "11:30"), ("13:00", "15:00")):
            begin, finish = local_time(f"{day} {first}"), local_time(f"{day} {last}")
            for value in pd.date_range(begin, finish, freq=f"{query.bar_minutes}min")[1:]:
                if value - pd.Timedelta(minutes=query.bar_minutes) >= start and value <= end:
                    result.append(value.isoformat())
    return result


def calculate(query, frame):
    # Apply the same validity rules to calculations and downloaded/cache values.
    # VWAP uses paired observations, never two independently filtered sums.
    clean = pd.DataFrame({f: [numeric(v, f) for v in frame[f]] for f in query.required_fields},
                         index=frame.index, dtype=float)
    stats = []
    for field in query.required_fields:
        values = clean[field]
        valid = values.dropna()
        stats.append({"field": field, "label": field_label(field, query.frequency), "n": int(valid.size),
                      "missing": int(values.isna().sum()), "mean": float(valid.mean()) if len(valid) else None,
                      "median": float(valid.median()) if len(valid) else None,
                      "min": float(valid.min()) if len(valid) else None, "max": float(valid.max()) if len(valid) else None,
                      "sum": float(valid.sum()) if len(valid) and field in {"volume", "amt"} else None})
    metrics, notes, details = {}, [], {}
    if query.twap:
        valid = clean.close.dropna()
        details["twap"] = {"n": len(valid), "excluded": len(frame) - len(valid), "total": len(frame)}
        if len(valid):
            metrics["twap"] = float(valid.mean())
            if len(valid) != len(frame):
                notes.append(f"TWAP 已剔除 {len(frame) - len(valid)} 个无效收盘价，仅代表 {len(valid)} 个有效分钟样本。")
        else:
            details["twap"]["reason"] = "没有有效收盘价"
            notes.append("TWAP 无有效分钟收盘价；不补零或沿用前值。")
    if query.vwap:
        volume_factor = VOLUME_UNITS[query.volume_unit][1]
        amount_factor = AMOUNT_UNITS[query.amount_unit][1]
        paired = clean.volume.notna() & clean.amt.notna() & (clean.volume > 0)
        valid = clean.loc[paired, ["volume", "amt"]]
        details["vwap"] = {"n": len(valid), "excluded": len(frame) - len(valid), "total": len(frame)}
        inconsistent = int(((clean.volume == 0) & (clean.amt > 0)).sum())
        if inconsistent:
            notes.append(f"VWAP 已剔除 {inconsistent} 行零成交量但非零成交额的异常样本。")
        if volume_factor is None or amount_factor is None:
            details["vwap"]["reason"] = "请先选择成交量、成交额单位"
            notes.append("VWAP 待确认原始成交量 / 成交额单位；可按 Wind 代码生成器字段说明选择后重新计算。")
        elif valid.empty:
            details["vwap"]["reason"] = "没有量额均有效且成交量大于零的样本"
            notes.append("VWAP 无有效成交样本，不提供数值。")
        else:
            metrics["vwap"] = float(valid.amt.sum() * amount_factor / (valid.volume.sum() * volume_factor))
            if len(valid) != len(frame):
                notes.append(f"VWAP 量额成对剔除无效或零成交量行：有效 {len(valid)}/{len(frame)}，仅代表有效成交样本。")
    return {"statistics": stats, "metrics": metrics, "metric_details": details, "notes": notes}


def numeric(value, field):
    if value is None or isinstance(value, (bool, str)):
        return None
    try:
        number = float(value)
        if not np.isfinite(number) or number < 0 or (field not in {"volume", "amt", "oi"} and number == 0):
            return None
        return number
    except (ValueError, TypeError, OverflowError):
        return None
