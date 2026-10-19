"""Plan every requested trading day, fetch/derive it, and report coverage honestly."""
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import time
import uuid

import numpy as np
import pandas as pd

from .catalog import FREQUENCIES, identify, route, order_book_source
from .contracts import HistoricalResolver, source_query_identity
from .transforms import (aggregate_minutes, aggregate_snapshots, combine_frames,
                         required_fields, units)
from ..instant_dld.contracts import DEFAULT_MAPPING_FILE, DEFAULT_CALENDAR_FILE
from ..instant_dld.quotes import CHINA


def source_candidates(symbol, request):
    info = identify(symbol, request["asset"])
    frequency = request["frequency"]
    if frequency not in FREQUENCIES.values():
        raise ValueError("不支持的下载频率")
    def optional(freq):
        try:
            source = route(symbol, freq, request["asset"])[1]
        except ValueError as exc:
            if "没有" not in str(exc):
                raise
            return None
        if source["frequency"] == "tick" and request["depth"] > 1:
            source = order_book_source(source) or source
        return source
    native = optional(frequency) if not frequency.endswith("s") else None
    alt = []
    if request["mode"] != "native" and frequency != "tick":
        choices = (["1m", "tick"] if frequency == "1d" or frequency.endswith("m") and frequency != "1m" else ["tick"])
        if request["derive_source"] != "auto":
            if request["derive_source"] not in choices:
                raise ValueError("生成来源必须比目标频率更细；秒线/1分钟只能由快照生成")
            choices = [request["derive_source"]]
        alt = [source for f in choices if (source := optional(f)) is not None]
    if request["mode"] == "native" and native is None:
        raise ValueError(f"{symbol} 没有原始 {frequency} 表，请选择允许生成的模式")
    if request["mode"] == "derived" and not alt or native is None and not alt:
        raise ValueError(f"{symbol} 没有可用于 {frequency} 的来源")
    return info, native, alt


def _public(item):
    return {key: value for key, value in item.items() if not key.startswith("_")}


def make_plan(request, client, check_cancel):
    resolver = HistoricalResolver(request.get("mapping_file") or DEFAULT_MAPPING_FILE,
        request.get("calendar_file") or DEFAULT_CALENDAR_FILE, request.get("next_mapping_dir"),
        request["main_rule"], request["next_source"])
    start, end = (date.fromisoformat(request[key]) for key in ("start", "end"))
    days = resolver.trading_days(start, end)
    cache, plan = {}, []
    now = datetime.now(CHINA)
    def available(source, actual, day):
        if source is None:
            return False
        query = source_query_identity(source, actual, day)
        code = query["source_query_code"]
        key = source["db"], source["table"], code
        if key not in cache:
            cache[key] = set(client.available_dates(source, code, start, end))
        return day in cache[key]
    for symbol in request["symbols"]:
        info, native, alternatives = source_candidates(symbol, request)
        for day in days:
            check_cancel()
            item = {"symbol": symbol, "date": str(day), "source_symbol": "", "status": "unavailable",
                    "reason": "所选来源无记录；未自动判定为停牌、未上市或源端缺失", "_info": info,
                    "_native": native, "_alternatives": [], "native_available": False}
            if request["frequency"] == "1d" and day == now.date() and now.hour < 16:
                item.update(status="pending", reason="当日尚未完成日线；16:00后可重新检查")
            else:
                try:
                    identity = resolver.resolve(symbol, day, client)
                except (ValueError, OSError) as exc:
                    item.update(status="mapping_missing", reason=str(exc))
                else:
                    actual = identity["source_symbol"]
                    item.update(source_symbol=actual, identity=identity)
                    item["source_queries"] = [{"source": f"{s['db']}/{s['table']}",
                        **source_query_identity(s, actual, day)} for s in [native, *alternatives] if s is not None]
                    item["native_available"] = available(native, actual, day) if request["mode"] != "derived" else False
                    for source in alternatives:
                        if available(source, actual, day):
                            item["_alternatives"].append(source)
                    if item["native_available"]:
                        item.update(status="native", reason="原始频率有记录，字段与完整性在读取时核验")
                    elif item["_alternatives"]:
                        item.update(status="derivable", reason="可从 " + ", ".join(s["frequency"] for s in item["_alternatives"]) + " 生成；待校验")
                    item["candidate_sources"] = [f"{s['db']}/{s['table']}" for s in item["_alternatives"]]
            plan.append(item)
    return plan, {"reference_days": len(days), "nontrading_days": (end - start).days + 1 - len(days),
                  "requested_items": len(plan)}


def fetch_item(client, item, request):
    actual, day, info = item["source_symbol"], date.fromisoformat(item["date"]), item["_info"]
    fields = required_fields(request, info)
    native = pd.DataFrame(columns=["trading_date", "timestamp"])
    meta, sources, warnings, derivations = {}, [], [], []
    contributors = {f: [] for f in fields}
    def add_sources(field, detail, frame, method, frequency):
        book_source = (detail.get("order_book") or {}).get("source")
        column = field
        if frequency == "tick":
            if request["frequency"] == "1d":
                column = {"open":"session_open", "high":"session_high", "low":"session_low", "close":"session_close",
                          "volume":"volume_total", "amount":"amount_total"}.get(field, field)
            elif field in {"open", "high", "low", "close"}:
                column = "last"
        source_name = detail.get("source", "")
        actual_sources = [source_name] if source_name else []
        if book_source and field.startswith(("bid_", "ask_")) and "filled_fields" in frame:
            filled = frame.filled_fields.fillna("").str.split(", ").map(lambda x:field in x)
            if filled.any():
                actual_sources = ([source_name] if field in frame and (frame[field].notna() & ~filled).any() else []) + [book_source]
        for source_name in actual_sources:
            mapping = (detail.get("order_book") or {}).get("field_mapping", {}) if source_name == book_source else detail.get("field_mapping", {})
            item = {"source": source_name, "input_column": mapping.get(column, column),
                    "frequency": "tick" if source_name == book_source else frequency, "method": method,
                    "unit_factor": detail.get("unit_factors", {}).get(column, 1),
                    **{key: value for key, value in detail.items() if key.startswith("source_query_")}}
            if item not in contributors[field]:
                contributors[field].append(item)
    queries = transforms = 0.
    if item["native_available"]:
        native, meta = client.fetch(item["_native"], actual, day, {**request, "frequency": item["_native"]["frequency"]})
        queries += meta.get("query_seconds", 0)
        transforms += meta.get("transform_seconds", 0)
        sources.append(meta.get("source", f"{item['_native']['db']}/{item['_native']['table']}"))
        if not native.empty:
            if "data_origin" not in native:
                native["data_origin"] = "native"
            if "filled_fields" not in native:
                native["filled_fields"] = ""
            for field in fields:
                if field in native and native[field].notna().any():
                    add_sources(field, meta, native, "原始或同日盘口匹配", item["_native"]["frequency"])
    data = native
    needs = (data.empty or any(f not in data or data[f].isna().any() for f in fields))
    # Inspect a finer source for missing intraday buckets, not just missing whole days.
    inspect_buckets = request["frequency"].endswith("m") and request["mode"] == "fill"
    if needs or inspect_buckets or request["mode"] == "derived":
        for source in item["_alternatives"]:
            aux, detail = client.fetch(source, actual, day, {**request, "frequency": source["frequency"]})
            queries += detail.get("query_seconds", 0)
            transforms += detail.get("transform_seconds", 0)
            if aux.empty:
                continue
            started = time.perf_counter()
            if source["frequency"] == "1m":
                generated, derivation = aggregate_minutes(aux, request["frequency"], info)
            else:
                generated, derivation = aggregate_snapshots(aux, request["frequency"], info)
            transforms += time.perf_counter() - started
            source_name = detail.get("source", f"{source['db']}/{source['table']}")
            derivation.update(source=source_name, source_frequency=source["frequency"],
                              source_rows=len(aux), first_observation=str(aux.timestamp.min()),
                              last_observation=str(aux.timestamp.max()))
            derivations.append(derivation)
            warnings.extend(derivation.get("warnings", []))
            sources.append(source_name)
            if generated.empty:
                continue
            before = data.set_index(["trading_date", "timestamp"])
            generated["data_origin"] = "derived"
            available_fields = [f for f in fields if f in generated]
            generated["filled_fields"] = [", ".join(f for f,valid in zip(available_fields,row) if valid)
                                           for row in generated[available_fields].notna().to_numpy()]
            if data.empty:
                data = generated
                meta = detail
            else:
                data = combine_frames(data, generated, fields)
            candidate = generated.set_index(["trading_date", "timestamp"])
            accepted = data.set_index(["trading_date", "timestamp"]).reindex(candidate.index)
            used_fields = []
            for field in fields:
                if field not in candidate or field not in accepted:
                    continue
                existing = before[field].reindex(candidate.index) if field in before else pd.Series(np.nan, index=candidate.index)
                if (candidate[field].notna() & existing.isna() & accepted[field].notna()).any():
                    used_fields.append(field)
                    add_sources(field, detail, aux, derivation["aggregation_rule"], source["frequency"])
            derivation["used_fields"] = used_fields
            needs = any(f not in data or data[f].isna().any() for f in fields)
            if not needs or request["derive_source"] != "auto":
                break
    if data.empty:
        return data, {}
    data = data.copy()
    for field in fields:
        if field not in data:
            data[field] = np.nan
    null_counts = {f: int(data[f].isna().sum()) for f in fields}
    quality = "partial" if any(null_counts.values()) else "complete"
    data["quality"] = np.where(data[fields].isna().any(axis=1), "partial", "complete")
    extras = [f for f in ["data_origin", "filled_fields", "quality", "source_observations", "book_timestamp",
                          "volume_total", "amount_total", "session_close"] if f in data]
    if request["frequency"] == "1d":
        extras = [f for f in extras if f not in {"book_timestamp", "volume_total", "amount_total", "session_close"}]
    data = data[["trading_date", "timestamp", *fields, *extras]].sort_values("timestamp", kind="stable").reset_index(drop=True)
    if "volume" in fields:
        data["volume_unit"] = units(info)["volume"]
    if "amount" in fields:
        data["amount_unit"] = "元"
    origins = set(data.data_origin) if "data_origin" in data else {"native"}
    origin = next(iter(origins)) if len(origins) == 1 else "mixed"
    # Strip large repeated source schema from UI protocol; it remains in the on-disk catalog.
    meta.pop("source_columns", None)
    if meta.get("order_book"):
        meta["order_book"].pop("columns", None)
    actual_sources = list(dict.fromkeys(x["source"] for inputs in contributors.values() for x in inputs))
    filled_sets = data.get("filled_fields", pd.Series("", index=data.index)).str.split(", ").map(set)
    meta.update(query_seconds=queries, transform_seconds=transforms, source=" + ".join(actual_sources or dict.fromkeys(sources)),
        units=units(info), quality=quality, origin=origin, missing_fields=[f for f,n in null_counts.items() if n],
        null_counts=null_counts, warnings=list(dict.fromkeys(warnings)), derivations=derivations,
        field_sources={f: {"sources": list(dict.fromkeys(x["source"] for x in contributors[f])),
                          "inputs": contributors[f], "native_column": ", ".join(dict.fromkeys(x["input_column"] for x in contributors[f])),
                          "generated_rows": int(filled_sets.map(lambda x:f in x).sum())}
                      for f in fields},
        bar_semantics="；".join(d.get("aggregation_rule", "") for d in derivations if d.get("used_fields")) or meta.get("bar_semantics", "原始频率"))
    return data, meta


def run_download(request, *, emit=lambda event: None, cancelled=lambda: False, client_factory=None):
    from .downloader import Client, Cancelled, DEFAULT_CONFIG, validate, register, write_json
    request = validate(request)
    action = request.get("action", "download")
    output = Path(request["output_dir"])
    batch = output / "historical" / (datetime.now(CHINA).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    report = {"request": {k:v for k,v in request.items() if k != "config_path"}, "state": "running", "version": 2,
              "files": [], "errors": [], "skipped": [], "coverage": [], "sampled": 0,
              "counts": {"native": 0, "derived": 0, "mixed": 0, "partial": 0, "pending": 0, "unavailable": 0}}
    client = None
    started = time.perf_counter()
    def check_cancel():
        if cancelled():
            raise Cancelled("已停止；已完成文件保留")
    try:
        check_cancel()
        client = (client_factory or Client)(request.get("config_path") or DEFAULT_CONFIG)
        report["connect_seconds"] = client.connect_seconds
        plan, coverage_summary = make_plan(request, client, check_cancel)
        report.update(coverage_summary)
        report["coverage"] = [_public(item) for item in plan]
        emit({"type": "coverage", "items": report["coverage"], **coverage_summary})
        if action == "download":
            batch.mkdir(parents=True, exist_ok=False)
        sampled_by_symbol = {}
        for index, item in enumerate(plan):
            check_cancel()
            public = report["coverage"][index]
            if item["status"] not in {"native", "derivable"}:
                if item["status"] == "mapping_missing":
                    error = {"symbol": item["symbol"], "date": item["date"], "error": item["reason"]}
                    report["errors"].append(error)
                    emit({"type": "error", **error})
                else:
                    report["skipped"].append(public)
                    report["counts"]["pending" if item["status"] == "pending" else "unavailable"] += 1
                continue
            limit = 60 if request["frequency"] == "1d" else 3
            if action == "preview" and sampled_by_symbol.get(item["symbol"], 0) >= limit:
                public["sampled"] = False
                continue
            try:
                emit({"type": "progress", "current": index + 1, "total": len(plan),
                      "message": f"{item['symbol']} → {item['source_symbol']} · {item['date']} · {index+1}/{len(plan)}"})
                data, details = fetch_item(client, item, request)
                if data.empty:
                    public.update(status="unavailable", reason="读取时无可用记录")
                    report["skipped"].append(public)
                    report["counts"]["unavailable"] += 1
                    emit({"type": "item_status", "item": public})
                    continue
                for column in ("trading_date", "timestamp", "book_timestamp"):
                    if column in data:
                        data[column] = data[column].astype("datetime64[ns]")
                data.insert(0, "source_symbol", item["source_symbol"])
                data.insert(0, "symbol", item["symbol"])
                metadata = {"symbol": item["symbol"], "source_symbol": item["source_symbol"],
                    "trading_date": item["date"], "frequency": request["frequency"], "identity": item["identity"],
                    "rows": len(data), "schema_version": 2, "first_timestamp": str(data.timestamp.min()), "last_timestamp": str(data.timestamp.max()),
                    "downloaded_at": datetime.now(CHINA).isoformat(), **details}
                report["counts"][metadata["origin"]] += 1
                report["counts"]["partial"] += int(metadata["quality"] == "partial")
                public.update(status=metadata["origin"], quality=metadata["quality"], rows=len(data), sampled=True,
                              reason="；".join(metadata.get("warnings", [])) or ("所选字段有空值" if metadata["quality"] == "partial" else "所选字段有值，来源已记录"))
                if action == "download":
                    folder = batch / item["symbol"] / request["frequency"]
                    folder.mkdir(parents=True, exist_ok=True)
                    parquet = folder / (item["date"] + ".parquet")
                    saved = time.perf_counter()
                    partial = parquet.with_suffix(".parquet.partial")
                    data.to_parquet(partial, index=False)
                    pd.testing.assert_frame_equal(data, pd.read_parquet(partial))
                    partial.rename(parquet)
                    metadata.update(write_verify_seconds=time.perf_counter() - saved, bytes=parquet.stat().st_size,
                                    sha256=hashlib.sha256(parquet.read_bytes()).hexdigest(), file=str(parquet))
                    metadata["total_seconds"] = sum(metadata.get(k, 0) for k in ("query_seconds", "transform_seconds", "write_verify_seconds"))
                    manifest = parquet.with_suffix(".json")
                    write_json(manifest, metadata)
                    register([parquet, manifest], metadata["source"],
                             f"{item['symbol']} {item['date']} {request['frequency']} {metadata['origin']} {len(data)}行", output)
                    report["files"].append(metadata)
                report["sampled"] += 1
                sampled_by_symbol[item["symbol"]] = sampled_by_symbol.get(item["symbol"], 0) + 1
                emit({"type": "saved" if action == "download" else "preview", "metadata": metadata,
                      "columns": list(data.columns), "rows": json.loads(data.head(100).to_json(orient="records", date_format="iso"))})
                emit({"type": "item_status", "item": public})
            except Cancelled:
                raise
            except Exception as exc:
                error = {"symbol": item["symbol"], "date": item["date"], "error": str(exc)}
                report["errors"].append(error)
                public.update(status="failed", reason=str(exc))
                emit({"type": "error", **error})
                emit({"type": "item_status", "item": public})
        incomplete = bool(report["errors"] or report["skipped"] or report["counts"]["partial"])
        report["state"] = ("partial" if incomplete and report["sampled"] else "failed" if report["errors"] else "empty") if incomplete else (
            "preview" if action == "preview" and report["sampled"] else "complete" if report["files"] else "empty")
    except Cancelled:
        report["state"] = "cancelled"
    except Exception as exc:
        report["state"] = "failed"
        report["errors"].append({"error": str(exc)})
        emit({"type": "error", "error": str(exc)})
    finally:
        cleanup_interrupt = None
        try:
            if client is not None:
                client.close()
        except BaseException as exc:
            # Native VPN/session cleanup can fail after verified Parquet files
            # exist. Keep both the download outcome and the cleanup failure in
            # the unique run manifest, so callers can still locate the batch.
            report["state_before_cleanup"] = report["state"]
            report["cleanup_error"] = {"stage": "cleanup", "error_type": type(exc).__name__, "error": str(exc)}
            report["errors"].append(report["cleanup_error"])
            report["state"] = "partial" if report["files"] else "failed"
            if not isinstance(exc, Exception):
                cleanup_interrupt = exc
        finally:
            report["elapsed_seconds"] = time.perf_counter() - started
            if action == "download" and batch.is_dir():
                report_path = batch / "run.json"
                write_json(report_path, report)
                report["report_file"] = str(report_path)
                register([report_path], "DolphinDB", "历史下载批次结果（含覆盖与生成来源）", output)
        if cleanup_interrupt is not None:
            raise cleanup_interrupt
        if report.get("cleanup_error"):
            emit({"type": "error", **report["cleanup_error"]})
    return report
