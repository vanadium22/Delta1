"""Explicit Wind queries and disposable, acquisition-date-partitioned local cache."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import uuid

import pandas as pd

from shared_data import Catalog, Dataset
from shared_data.io import atomic_json, file_lock
from .config import SHANGHAI
from .security_model import SecurityQuery, calculate, expected_times, local_time, numeric
from .sync import Cancelled
from .wind import WindProvider


class SecurityProvider(WindProvider):
    worker_filename = "security_worker.py"


class DemoSecurityProvider:
    """Deterministic synthetic bars, never used to fill a Wind cache."""
    def request(self, operation, **args):
        if operation == "info":
            return {"name": "合成演示证券"}
        if operation == "calendar":
            return [d.date().isoformat() for d in pd.bdate_range(args["start"], args["end"])]
        if operation == "snapshot":
            times = [datetime.now(SHANGHAI).isoformat(timespec="seconds")]
        else:
            q = SecurityQuery(args["code"], args["frequency"], tuple(args["fields"]), args["start"], args["end"])
            days = [d.date().isoformat() for d in pd.bdate_range(local_time(q.start).date(), local_time(q.end).date())]
            times = expected_times(q, days)
        rows = []
        for time in times:
            index = int(hashlib.sha256(time.encode()).hexdigest()[:8], 16)
            price, volume = 20 + (index % 500) / 1000, 1000 + index % 10000
            values = {"close": price, "open": price - .02, "high": price + .04, "low": price - .05,
                      "volume": volume, "amt": price * volume}
            rows.append({"time": time, **{f: values[f] for f in args["fields"]}})
        return {"rows": rows, "received_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
                "source": "合成演示 · 非真实行情", "wind_fields": {f: f for f in args["fields"]}}

    def close(self):
        pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_document(path):
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    if envelope.get("sha256") != digest(envelope.get("data")) or envelope["data"].get("schema_version") != 1:
        raise ValueError(f"缓存校验失败，请在缓存目录移走损坏文件后重新查询：{path}")
    return envelope["data"]


def write_document(path, data):
    atomic_json(path, {"sha256": digest(data), "data": data})


@dataclass
class SecurityResult:
    query: SecurityQuery
    frame: pd.DataFrame
    summary: dict
    metadata: dict


class SecurityService:
    def __init__(self, paths, config, mode="wind", cancel=None):
        if mode not in {"wind", "offline", "demo"}:
            raise ValueError("未知数据模式")
        self.paths, self.config, self.mode = paths, config, mode
        self.cancel = cancel if cancel is not None else threading.Event()
        self.catalog = Catalog(paths)

    def cache(self, frequency):
        # Offline is an explicitly labelled read-only view of previously acquired Wind queries.
        demo = self.mode == "demo"
        dataset = Dataset("security_query", "synthetic" if demo else "wind", frequency,
                          mode="demo" if demo else "live", storage="files", retention="daily_cache", keep_days=7)
        self.catalog.register(dataset)
        _, root = self.catalog.get(dataset.key)
        return dataset, root

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled("行情查询已取消，已完成批次保留在缓存")

    def query(self, query, progress=lambda text: None, *, force=False, provider=None, now=None):
        if not isinstance(query, SecurityQuery):
            raise TypeError("需要 SecurityQuery")
        now = local_time(now or datetime.now(SHANGHAI))
        if query.frequency != "snapshot" and local_time(query.end) > now:
            raise ValueError("结束时间不能晚于当前北京时间")
        if self.mode == "offline" and (force or query.frequency == "snapshot"):
            raise ValueError("离线模式只读历史查询缓存；最新值需要切回 Wind 正式数据")
        dataset, root = self.cache(query.frequency)
        self.cancel.clear()
        owned = provider is None
        provider = provider or (None if self.mode == "offline" else DemoSecurityProvider() if self.mode == "demo"
                                else SecurityProvider(self.config))
        request_count = 0

        def request(operation, **args):
            nonlocal request_count
            self.check_cancel()
            if provider is None:
                raise ValueError("离线缓存不完整，请在 Wind 模式查询相同标的、频率和窗口")
            progress(f"{query.code} · {operation} · {args.get('start', '')} {args.get('end', '')}")
            value = provider.request(operation, code=query.code, **args)
            request_count += 1
            self.check_cancel()
            return value

        try:
            with file_lock(root / ".writer.lock"):
                reference_file = root / "reference.json"
                reference = read_document(reference_file) if reference_file.exists() else {"schema_version": 1, "names": {}, "calendar": {}}
                if query.code not in reference["names"]:
                    reference["names"][query.code] = request("info")["name"]
                    write_document(reference_file, reference)
                name = reference["names"][query.code]
                if query.frequency == "snapshot":
                    payload = request("snapshot", fields=query.required_fields)
                    if len(payload["rows"]) != 1:
                        raise ValueError("最新查询须返回单个快照")
                    row = payload["rows"][0]
                    frame = pd.DataFrame([{ "time": row.get("time"),
                        **{f: numeric(row.get(f), f) for f in query.required_fields}}])
                    if frame[query.required_fields].isna().all().all():
                        raise ValueError("Wind未返回任何有效最新值，请核对代码、行情权限及市场状态")
                    metadata = self.metadata(query, name, root, now, request_count, payload["received_at"], [])
                    metadata.update(source=payload["source"], wind_fields=payload["wind_fields"],
                                    time_semantics="Wind返回时间，非逐笔成交时间；received_at 为本机采集时间")
                    target = root / now.date().isoformat() / f"{query.code}-{uuid.uuid4().hex}.json"
                    write_document(target, {"schema_version": 1, "metadata": metadata, "payload": payload})
                    return SecurityResult(query, frame, calculate(query, frame), metadata)

                first, last = local_time(query.start).date().isoformat(), local_time(query.end).date().isoformat()
                dates = [d.date().isoformat() for d in pd.date_range(first, last)]
                calendar = reference["calendar"].setdefault(query.code[-2:], {})
                unknown = [d for d in dates if d not in calendar]
                if unknown:
                    open_days = request("calendar", start=unknown[0], end=unknown[-1])
                    if len(set(open_days)) != len(open_days) or any(d < unknown[0] or d > unknown[-1] for d in open_days):
                        raise ValueError("Wind 交易日历范围或重复日期异常")
                    for day in pd.date_range(unknown[0], unknown[-1]):
                        key = day.date().isoformat()
                        calendar[key] = key in open_days
                    write_document(reference_file, reference)
                expected = expected_times(query, [d for d in dates if calendar[d]])
                if not expected:
                    raise ValueError("所选窗口没有完整交易周期；分钟窗口不包含午休和09:30集合竞价点")
                by_day = {}
                for value in expected:
                    by_day.setdefault(value[:10], []).append(value)
                docs, tasks, used_files, fresh_cells = {}, [], [], {}
                for day, times in by_day.items():
                    filename = f"{query.code}-{day}.json"
                    candidates = sorted(root.glob(f"????-??-??/{filename}"))
                    doc = read_document(candidates[-1]) if candidates else {"schema_version": 1, "code": query.code,
                        "frequency": query.frequency, "adjustment": "none", "rows": {}, "unverified": {},
                        "received_at": None, "batches": []}
                    if (doc.get("code"), doc.get("frequency"), doc.get("adjustment")) != (query.code, query.frequency, "none"):
                        raise ValueError("缓存标的、频率或复权口径不匹配")
                    docs[day] = doc
                    if candidates:
                        used_files.append(str(candidates[-1]))
                    missing = [f for f in query.required_fields if any(
                        numeric(doc["rows"].get(t, {}).get(f), f) is None or
                        (self.mode != "offline" and f in doc["unverified"].get(t, [])) for t in times)]
                    refresh = force or (self.mode != "offline" and day == now.date().isoformat())
                    if refresh:
                        missing = query.required_fields
                    if missing:
                        tasks.append((day, missing, refresh))
                if tasks and self.mode == "offline":
                    raise ValueError(f"离线缓存缺少 {len(tasks)} 个交易日的部分字段，请在 Wind 模式补齐")
                groups = []
                ordered_days = list(by_day)
                for day, fields, refresh in tasks:
                    if query.frequency == "1d":
                        if (groups and groups[-1][1] == fields
                                and ordered_days.index(day) == ordered_days.index(groups[-1][0][-1]) + 1
                                and (pd.Timestamp(day) - pd.Timestamp(groups[-1][0][0])).days < 31):
                            groups[-1][0].append(day)
                            groups[-1][2].extend(by_day[day])
                        else:
                            groups.append(([day], fields, list(by_day[day])))
                    else:
                        for time in by_day[day]:
                            needed = [f for f in fields if refresh or numeric(docs[day]["rows"].get(time, {}).get(f), f) is None
                                      or f in docs[day]["unverified"].get(time, [])]
                            if not needed:
                                continue
                            if (groups and groups[-1][0] == [day] and groups[-1][1] == needed
                                    and local_time(time) - local_time(groups[-1][2][-1]) == pd.Timedelta(minutes=query.bar_minutes)):
                                groups[-1][2].append(time)
                            else:
                                groups.append(([day], needed, [time]))
                notes = []
                for days, fields, selected_times in groups:
                    if query.frequency == "1d":
                        begin, finish = days[0], days[-1]
                    else:
                        # Request only missing coverage within this trading day; labels are right endpoints.
                        begin = (local_time(selected_times[0]) - pd.Timedelta(minutes=query.bar_minutes)).strftime("%Y-%m-%d %H:%M:%S")
                        finish = local_time(selected_times[-1]).strftime("%Y-%m-%d %H:%M:%S")
                    payload = request("history", fields=fields, frequency=query.frequency, start=begin, end=finish)
                    allowed = set(selected_times)
                    returned = {}
                    extras = 0
                    for row in payload["rows"]:
                        time = local_time(row["time"])
                        key = time.date().isoformat() if query.frequency == "1d" else time.isoformat()
                        if key in returned:
                            raise ValueError("Wind 返回重复时间戳")
                        if key not in allowed:
                            extras += 1
                            continue
                        returned[key] = {f: numeric(row.get(f), f) for f in fields}
                    if extras:
                        notes.append(f"接口另返回 {extras} 个窗口外或非标准连续交易时段时间点，未纳入计算。")
                    for day in days:
                        doc = docs[day]
                        for time in (t for t in selected_times if t[:10] == day):
                            values = returned.get(time, {f: None for f in fields})
                            # Failed/empty cells never destroy an earlier valid cache value. This query
                            # still shows the fresh null, rather than presenting stale data as a refresh.
                            fresh_cells.setdefault(time, {}).update(values)
                            doc["rows"].setdefault(time, {}).update({f: v for f, v in values.items() if v is not None})
                            unverified = set(doc["unverified"].get(time, []))
                            for field in fields:
                                if day >= now.date().isoformat() or values.get(field) is None:
                                    unverified.add(field)
                                else:
                                    unverified.discard(field)
                            doc["unverified"][time] = sorted(unverified)
                        doc["received_at"] = payload["received_at"]
                        doc["finalized"] = not any(doc["unverified"].values())
                        doc["batches"].append({"start": begin, "end": finish, "fields": fields, "received_at": payload["received_at"],
                                              "source": payload["source"], "wind_fields": payload["wind_fields"]})
                        target = root / now.date().isoformat() / f"{query.code}-{day}.json"
                        write_document(target, doc)
                        used_files.append(str(target))
                self.check_cancel()
                frame = pd.DataFrame([{"time": t, **{f: numeric(fresh_cells.get(t, {}).get(f, docs[t[:10]]["rows"].get(t, {}).get(f)), f)
                                                     for f in query.required_fields}} for t in expected])
                for f in query.required_fields:
                    frame[f] = pd.to_numeric(frame[f], errors="coerce")
                summary = calculate(query, frame)
                missing = int(frame[query.required_fields].isna().sum().sum())
                if missing:
                    notes.append(f"交易周期网格中有 {missing} 个字段值缺失；含停牌/上市前/权限或缺数可能，不填充。")
                if last == now.date().isoformat():
                    notes.append("包含当前交易日，数据可能尚未定稿；再次查询会刷新当天所选范围。")
                elif any(f in docs[t[:10]]["unverified"].get(t, []) for t in expected for f in query.required_fields):
                    notes.append("部分缓存采自未定稿时段或最新批次不完整；离线值仅作回看，联网查询会重新校验。")
                if query.bar_minutes:
                    notes.append("分钟按右端点标记，窗口为(开始,结束]；仅09:30—11:30、13:00—15:00完整周期，09:30竞价点不计入。")
                received = sorted({d["received_at"] for d in docs.values() if d["received_at"]})
                metadata = self.metadata(query, name, root, now, request_count, received[-1] if received else None, notes)
                valid_times = frame.loc[frame[query.required_fields].notna().any(axis=1), "time"]
                metadata.update(cache_files=sorted(set(used_files)), expected_rows=len(frame), missing_cells=missing,
                                complete_rows=int(frame[query.required_fields].notna().all(axis=1).sum()),
                                grid_start=frame.time.iloc[0], grid_end=frame.time.iloc[-1],
                                actual_start=valid_times.iloc[0] if len(valid_times) else None,
                                actual_end=valid_times.iloc[-1] if len(valid_times) else None,
                                acquisition_times=received, batches=[b for d in docs.values() for b in d["batches"]])
                return SecurityResult(query, frame, summary, metadata)
        finally:
            if owned and provider is not None:
                provider.close()

    def metadata(self, query, name, root, now, requests, received, notes):
        return {"schema_version": 1, "query": query.metadata(), "name": name, "mode": self.mode,
                "source": "合成演示 · 非真实行情" if self.mode == "demo" else "Wind 缓存（离线）" if self.mode == "offline" else "Wind",
                "query_time": now.isoformat(), "received_at": received, "requests": requests, "cache_root": str(root),
                "retention_basis": "acquisition_date", "timezone": "Asia/Shanghai", "notes": notes,
                "units": {"volume": query.volume_unit, "amount": query.amount_unit, "price": "原始报价单位，不复权"}}

    def inventory(self, frequency):
        _, root = self.cache(frequency)
        with file_lock(root / ".writer.lock"):
            return [{"date": p.parent.name, "file": p.name, "bytes": p.stat().st_size} for p in sorted(root.glob("????-??-??/*.json"))]

    def prune(self, frequency, apply=False):
        if self.mode == "offline" and apply:
            raise ValueError("离线模式不清理 Wind 缓存")
        dataset, _ = self.cache(frequency)
        return self.catalog.prune(dataset.key, apply=apply)


def export_result(result, folder):
    """Export an immutable bundle with raw rows, statistics, units and provenance."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    result.frame.to_csv(folder / "data.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(result.summary["statistics"]).to_csv(folder / "statistics.csv", index=False, encoding="utf-8-sig")
    atomic_json(folder / "manifest.json", {**result.metadata, "summary": result.summary,
                                           "data_fingerprint": digest(result.frame.fillna("<missing>").to_dict("records"))})
    return folder
