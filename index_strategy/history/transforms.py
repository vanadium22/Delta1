"""Explicit aggregation, units and quality checks; never fill time gaps."""
from datetime import time
import numpy as np
import pandas as pd

PRICE_FIELDS = {"open", "high", "low", "close", "last", "session_open", "session_high", "session_low", "session_close"}
BASE_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
MODES = {"原始优先，缺失补齐": "fill", "仅原始数据": "native", "仅用其他频率生成": "derived"}
DERIVE_SOURCES = {"自动选择": "auto", "1分钟": "1m", "原始快照": "tick"}
MAIN_RULES = {"当日历史主力": "same_day", "前一交易日主力": "previous_day"}


def units(info):
    return {"price": "原始报价单位（未复权）", "volume":
            {"stock": "股", "etf": "份", "index": "手", "future": "手"}[info["asset"]],
            "amount": "元", "oi": "手"}


def normalize_units(frame, info, frequency):
    frame = frame.copy()
    factors = {}
    if frequency == "1d":
        if info["asset"] in {"stock", "etf"}:
            factors["volume"] = 100
        factors["amount"] = 10000 if info["asset"] == "future" else 1000
    for column in frame:
        if column in PRICE_FIELDS or column.startswith(("bid_", "ask_")) or column in {
                "volume", "amount", "oi", "volume_total", "amount_total"}:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
            valid = np.isfinite(frame[column]) & (frame[column].abs() < 1e100)
            valid &= frame[column] > 0 if column in PRICE_FIELDS or "_price_" in column else frame[column] >= 0
            frame[column] = frame[column].where(valid)
            if column in factors:
                frame[column] *= factors[column]
    for column in frame:
        if "_volume_" in column:
            price = column.replace("_volume_", "_price_")
            if price in frame:
                frame[column] = frame[column].where(frame[price].notna())
    return frame, factors


def close_time(info):
    return time(15, 15) if info["kind"] == "tf" else time(15)


def regular_rows(frame, info):
    """For derived bars only. Original intraday exports retain their source rows."""
    t = frame.timestamp.dt.time
    if info["asset"] != "future" or info["kind"] in {"ff", "tf"}:
        mask = ((t >= time(9, 30)) & (t <= time(11, 30))) | ((t >= time(13)) & (t <= close_time(info)))
    else:
        mask = (((t >= time(9)) & (t <= time(10, 15))) |
                ((t >= time(10, 30)) & (t <= time(11, 30))) |
                ((t >= time(13, 30)) & (t <= time(15))) |
                (t >= time(21)) | (t <= time(2, 30)))
    return frame.loc[mask].copy()


def required_fields(request, info):
    if request["frequency"] == "tick":
        fields = ["last", "session_open", "session_high", "session_low", "volume", "amount"]
    else:
        fields = list(request.get("fields", BASE_FIELDS))
    if request["oi"] and info["asset"] == "future":
        fields.append("oi")
    if request["frequency"] != "1d" and info["asset"] != "index":
        for level in range(1, request["depth"] + 1):
            fields += [f"{side}_{field}_{level}" for side in ("bid", "ask") for field in ("price", "volume")]
    return fields


def _strict_sum(s):
    return s.sum() if s.notna().all() else np.nan


def trading_buckets(frame, frequency, info):
    """CSMAR-style trading-minute buckets: skip breaks, reset between night and day."""
    size = int(frequency[:-1])
    output = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    minute_times = frame.timestamp.dt.ceil("min")
    for day, group in frame.groupby("trading_date", sort=True):
        day = pd.Timestamp(day).normalize()
        if info["asset"] != "future" or info["kind"] in {"ff", "tf"}:
            spans = [("09:30", "11:30"), ("13:00", close_time(info).strftime("%H:%M"))]
        else:
            spans = [("09:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00")]
        def assign(opening, labels, indices):
            mapping = {opening: opening}
            for number, stamp in enumerate(labels):
                mapping[stamp] = labels[min((number // size + 1) * size, len(labels)) - 1]
            mapped = minute_times.loc[indices].map(mapping)
            output.loc[indices] = output.loc[indices].where(mapped.isna(), mapped)
        labels = []
        for begin, finish in spans:
            labels.extend(pd.date_range(pd.Timestamp(str(day.date()) + " " + begin) + pd.Timedelta(minutes=1),
                                        pd.Timestamp(str(day.date()) + " " + finish), freq="min"))
        assign(pd.Timestamp(str(day.date()) + " " + spans[0][0]), labels, group.index)
        if info["asset"] == "future" and info["kind"] not in {"ff", "tf"}:
            night = group.loc[(minute_times.loc[group.index].dt.time >= time(21)) |
                              (minute_times.loc[group.index].dt.time <= time(2,30))]
            if not night.empty:
                first, last = minute_times.loc[night.index].min(), minute_times.loc[night.index].max()
                night_day = first.normalize() if first.hour >= 21 else first.normalize() - pd.Timedelta(days=1)
                opening = night_day + pd.Timedelta(hours=21)
                # Infer the observed session's conventional endpoint, never row-count across a data gap.
                ends = [night_day+pd.Timedelta(hours=23), night_day+pd.Timedelta(days=1,hours=1),
                        night_day+pd.Timedelta(days=1,hours=2,minutes=30)]
                ending = next((x for x in ends if x >= last), ends[-1])
                labels = list(pd.date_range(opening+pd.Timedelta(minutes=1), ending, freq="min"))
                assign(opening, labels, group.index)
    return output


def aggregate_minutes(frame, frequency, info):
    """Minute timestamps are interval ends; never shift a close into an earlier bar."""
    original_count = len(frame)
    ordered = regular_rows(frame.sort_values("timestamp", kind="stable"), info)
    if ordered.empty:
        return ordered, {"warnings": ["指定交易时段内没有分钟记录"]}
    daily = frequency == "1d"
    ordered["bucket"] = ordered.trading_date if daily else trading_buckets(ordered, frequency, info)
    rows, warnings = [], []
    previous_total = {}
    for (day, bucket), group in ordered.groupby(["trading_date", "bucket"], sort=True):
        row = {"trading_date": day, "timestamp": bucket, "source_observations": len(group)}
        for field in BASE_FIELDS:
            if field not in group:
                row[field] = np.nan
            elif field == "open":
                row[field] = group[field].iloc[0]
            elif field == "close":
                row[field] = group[field].iloc[-1]
            elif field in {"high", "low"}:
                row[field] = (group[field].max() if field == "high" else group[field].min()) if group[field].notna().all() else np.nan
            else:
                row[field] = _strict_sum(group[field])
        for field in group:
            if field == "oi" or (not daily and (field.startswith(("bid_", "ask_")) or field == "book_timestamp")):
                row[field] = group[field].iloc[-1]
        if daily:
            end_ok = group.timestamp.iloc[-1] >= pd.Timestamp(day).normalize() + pd.Timedelta(
                hours=close_time(info).hour, minutes=close_time(info).minute)
            start_time = group.timestamp.iloc[0].time()
            start_ok = start_time in ({time(9, 30)} if info["asset"] != "future" or info["kind"] in {"ff", "tf"}
                                    else {time(9), time(21)})
            volume_ok = ("volume_total" in group and pd.notna(group.volume_total.iloc[-1]) and
                         pd.notna(row["volume"]) and np.isclose(row["volume"], group.volume_total.iloc[-1], rtol=0, atol=1e-6))
            if not end_ok:
                warnings.append("分钟记录未到常规收盘时点，不能确认日收盘和日末OI")
                row.update(close=np.nan, oi=np.nan)
            if not start_ok or not volume_ok or not end_ok:
                warnings.append("分钟首尾或累计成交量校验不足；日内开高低及总量额保留为空")
                for field in ("open", "high", "low", "volume", "amount"):
                    row[field] = np.nan
        else:
            end_ok = group.timestamp.iloc[-1] == bucket
            total = group.volume_total.iloc[-1] if "volume_total" in group else np.nan
            expected = total - previous_total.get(day, 0)
            volume_ok = pd.notna(total) and pd.notna(row["volume"]) and np.isclose(expected, row["volume"], rtol=0, atol=1e-6)
            if not end_ok:
                row.update(close=np.nan, oi=np.nan)
            if not end_ok or not volume_ok:
                warnings.append("部分周期的末分钟或累计量校验不足，未假定底层分钟完整")
                for field in ("open", "high", "low", "volume", "amount"):
                    row[field] = np.nan
            previous_total[day] = total
        rows.append(row)
    return pd.DataFrame(rows), {"warnings": list(dict.fromkeys(warnings)),
            "filtered_rows": original_count - len(ordered),
            "aggregation_rule": "按交易归属日；OHLC首/最大/最小/末，期间量额求和，OI末值" if daily else
            "按交易分钟累计，跳过节间休市；夜盘/日盘分别分组，开盘点独立；结束标签，空桶不生成"}


def aggregate_snapshots(frame, frequency, info):
    ordered = frame.sort_values("timestamp", kind="stable").copy()
    if ordered.empty:
        return ordered, {"warnings": []}
    if frequency == "1d":
        # Daily cumulative fields retain trades between snapshots; sampled last prices do not.
        tail = ordered.iloc[-1]
        finished = tail.timestamp >= pd.Timestamp(tail.trading_date).normalize() + pd.Timedelta(
            hours=close_time(info).hour, minutes=close_time(info).minute)
        mapping = {"open": "session_open", "high": "session_high", "low": "session_low",
                   "close": "session_close", "volume": "volume_total", "amount": "amount_total", "oi": "oi"}
        row = {"trading_date": tail.trading_date, "timestamp": tail.trading_date,
               "source_observations": len(ordered)}
        row.update({field: tail.get(source, np.nan) if finished else np.nan for field, source in mapping.items()})
        return pd.DataFrame([row]), {"warnings": [] if finished else ["快照未到收盘时点，日线不能确认"],
                "aggregation_rule": "收盘后末条快照的当日累计OHLC/量额及OI；不从采样最新价推断全天极值",
                "observation_time": str(tail.timestamp)}
    seconds = frequency.endswith("s")
    ordered["bucket"] = ordered.timestamp.dt.floor(frequency) if seconds else trading_buckets(ordered, frequency, info)
    if not seconds:
        # Keep observations whose mapped minute label belongs to a regular session.
        labels = ordered.copy()
        labels["timestamp"] = labels.bucket
        ordered = ordered.loc[regular_rows(labels, info).index]
    keys = ["trading_date", "bucket"]
    grouped = ordered.groupby(keys, sort=True)
    sizes = grouped.size()
    # first/last aggregators skip nulls; select physical endpoint rows instead.
    first = ordered.drop_duplicates(keys, keep="first").set_index(keys).reindex(sizes.index)
    last = ordered.drop_duplicates(keys, keep="last").set_index(keys).reindex(sizes.index)
    result = pd.DataFrame(index=sizes.index)
    result["open"], result["close"] = first["last"], last["last"]
    valid_prices = grouped["last"].count().eq(sizes)
    result["high"] = grouped["last"].max().where(valid_prices)
    result["low"] = grouped["last"].min().where(valid_prices)
    result["source_observations"] = sizes
    for field in ("volume", "amount"):
        result[field] = grouped[field].sum(min_count=1).where(grouped[field].count().eq(sizes)) if field in ordered else np.nan
    for field in ordered:
        if field == "oi" or field.startswith(("bid_", "ask_")):
            result[field] = last[field]
    result["book_timestamp"] = last.timestamp
    return result.reset_index().rename(columns={"bucket": "timestamp"}), {"warnings": [], "aggregation_rule":
            "快照观测桶，非逐笔成交重建；秒桶左闭右开、起点标签，分钟桶结束标签；无观测的桶不生成；期间量归入观测桶"}


def combine_frames(native, derived, fields):
    """Fill missing cells only, with a per-row audit trail; keep explicit nulls when unavailable."""
    keys = ["trading_date", "timestamp"]
    a, b = native.set_index(keys), derived.set_index(keys)
    if a.index.has_duplicates or b.index.has_duplicates:
        raise ValueError("目标频率存在重复时间标签，不能安全补齐")
    merged = a.reindex(a.index.union(b.index)).sort_index()
    filled = {idx: [] for idx in merged.index}
    for field in fields:
        if field not in merged:
            merged[field] = np.nan
        if field in b:
            other = b[field].reindex(merged.index)
            mask = merged[field].isna() & other.notna()
            if "_volume_" in field:
                price = field.replace("_volume_", "_price_")
                mask &= np.isclose(merged[price], b[price].reindex(merged.index), rtol=0, atol=1e-9) if price in merged and price in b else False
            merged.loc[mask, field] = other.loc[mask]
            for idx in merged.index[mask]:
                filled[idx].append(field)
    # Do not create an internally contradictory OHLC group by mixing providers.
    if all(x in merged for x in ("open", "high", "low", "close")):
        invalid = ((merged.high < merged[["open", "close", "low"]].max(axis=1)) |
                   (merged.low > merged[["open", "close", "high"]].min(axis=1)))
        for idx in merged.index[invalid]:
            for field in tuple(filled[idx]):
                if field in PRICE_FIELDS:
                    merged.at[idx, field] = np.nan
                    filled[idx].remove(field)
    for column in ("book_timestamp", "source_observations"):
        if column in b:
            if column not in merged:
                merged[column] = b[column].reindex(merged.index)
            else:
                merged[column] = merged[column].combine_first(b[column].reindex(merged.index))
    prior = a.get("filled_fields", pd.Series("", index=a.index)).reindex(merged.index).fillna("")
    merged["filled_fields"] = [", ".join(dict.fromkeys([x for x in prior.loc[idx].split(", ") if x] + filled[idx])) for idx in merged.index]
    merged["data_origin"] = ["derived" if idx not in a.index or ("data_origin" in a and a.at[idx, "data_origin"] == "derived")
                             else ("mixed" if filled[idx] else a.at[idx, "data_origin"] if "data_origin" in a else "native")
                             for idx in merged.index]
    return merged.reset_index()
