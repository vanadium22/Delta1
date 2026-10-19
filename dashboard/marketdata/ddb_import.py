"""Offline import of shared-worker v2 / bulk_v1; never connects to DDB."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from .bars import BarDataset
from dashboard.native.instruments import UNDERLYINGS


def convert_file(item, *, bulk=False):
    path = Path(item["file"])
    if (not bulk and item.get("schema_version") != 2) or path.suffix != ".parquet":
        raise ValueError(f"Unsupported DDB file: {path}")
    if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError(f"DDB file checksum mismatch: {path}")
    frame = pd.read_parquet(path)
    if len(frame) != item["rows"]:
        raise ValueError(f"DDB row count mismatch: {path}")
    frequency = item["frequency"]
    if frequency not in {"1d", "1m"}:
        raise ValueError("Only daily and minute source bars have been audited")
    required = {"source_symbol", "trading_date", "timestamp", "open", "high", "low", "close", "volume", "amount"}
    if not required <= set(frame): raise ValueError(f"缺少标准字段: {required-set(frame)}")
    if item.get("units", {}).get("amount") != "元" or item.get("units", {}).get("volume") != "手":
        raise ValueError("未经确认的量额单位；仅接受已换算为手/元的已知下载格式")
    if item.get("unit_factors", {}).get("amount", 1) not in (1, 1000, 10000):
        raise ValueError("未知成交额单位换算")
    rows, excluded = [], Counter()
    for raw in frame.to_dict("records"):
        symbol = raw["source_symbol"]
        if not bulk and (symbol != item["source_symbol"] or raw["symbol"] != symbol):
            raise ValueError("This importer requires concrete contracts, not stitched aliases")
        from .bars import validate_instruments
        validate_instruments({symbol: {"asset_type": "cn_index_future" if symbol.endswith(".CFE") else "cn_index", "market_region": "CN"}})
        if not symbol.endswith(".CFE") and symbol not in {v[0] for v in UNDERLYINGS.values()}:
            raise ValueError("不支持的指数身份")
        if bulk and str(raw.get("source_code")) not in (symbol, symbol.split(".")[0]):
            raise ValueError("具体代码与源代码不符")
        day = pd.Timestamp(raw["trading_date"]).date()
        lo = item.get("start", item.get("trading_date")); hi = item.get("end", item.get("trading_date"))
        if (lo and str(day) < lo) or (hi and str(day) > hi): raise ValueError("行日期超出清单覆盖")
        event = pd.Timestamp(raw["timestamp"])
        event = event.tz_localize("Asia/Shanghai") if event.tzinfo is None else event.tz_convert("Asia/Shanghai")
        if event.date() != day: raise ValueError("时间与交易日不一致")
        if frequency == "1d":
            event = pd.Timestamp(day).tz_localize("Asia/Shanghai") + pd.Timedelta(hours=15)
            session = "day"
        else:
            minutes = event.hour * 60 + event.minute
            # Source 09:30 is an opening observation, not a full one-minute bar.
            if not (570 < minutes <= 690 or 780 < minutes <= 900) or event.second != 0 or event.microsecond != 0:
                excluded["opening_or_outside_regular_session"] += 1
                continue
            if event.date() != day:
                raise ValueError("Equity index minute timestamp and trading date disagree")
            session = "am" if minutes <= 690 else "pm"
        if pd.isna(raw.get("close")) or float(raw["close"]) <= 0:
            excluded["invalid_close"] += 1
            continue
        if raw.get("quality") == "pending":
            excluded["unfinished"] += 1
            continue
        # The server does not give historical release timestamps or exact minute
        # interval boundaries. Preserve the source close label, never invent PIT.
        row = dict(instrument_id=symbol, source_symbol=symbol, frequency=frequency,
                   event_time=event.tz_convert("UTC"), trade_date=day, session_id=session,
                   bar_start=None, available_at=None, recorded_at=item["downloaded_at"],
                   is_final=True, revision=0, quality_flags=8 | (128 if raw.get("quality", "complete" if bulk else None) != "complete" else 0))
        for target, source in {"open":"open", "high":"high", "low":"low", "close":"close",
                               "volume":"volume", "turnover":"amount", "open_interest":"oi"}.items():
            value = raw.get(source)
            row[target] = None if pd.isna(value) or value is None else float(value)
        rows.append(row)
    return rows, dict(excluded)


def manifest_file(run_file, item):
    """Resolve relocated batches using only their own relative tree, never a basename search."""
    old = Path(item["file"])
    if not old.is_absolute(): candidate = run_file.parent / old
    else:
        parts = old.parts
        matches = [i for i, part in enumerate(parts) if part == run_file.parent.name]
        candidate = run_file.parent.joinpath(*parts[matches[-1]+1:]) if matches else old
    candidate = candidate.resolve()
    if not candidate.is_relative_to(run_file.parent):
        raise ValueError("清单文件不在选定批次内")
    if not candidate.is_file() or candidate.stat().st_size != item["bytes"] or hashlib.sha256(candidate.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError(f"文件哈希或大小不符: {candidate}")
    return candidate


def merge_checked(store, rows, checkpoint, *, dry_run=False):
    """Coalesce identical economics; reject conflicts before publishing this batch.

    Download clocks are provenance, not market revisions. Every contributing
    manifest remains in checkpoint.imports even when all its rows are duplicates.
    """
    from .bars import normalize_bars, _row_key
    rows = normalize_bars(rows).to_pylist()
    pairs = {(r["instrument_id"], r["frequency"]) for r in rows}
    snap = store.snapshot()
    subset = {**snap, "parts": [p for p in snap["parts"] if (p["instrument_id"], p["frequency"]) in pairs]}
    fields = ("open", "high", "low", "close", "volume", "turnover", "open_interest", "settlement", "prev_close", "is_final", "event_time",
              "quality_flags", "source_quality_flags", "bar_start", "available_at", "session_id", "source_symbol")
    existing = {_row_key(r): r for r in store._rows(subset)}
    chosen, duplicates = [], 0
    for row in rows:
        key = _row_key(row)
        old = existing.get(key)
        if old is not None:
            changed = [f for f in fields if old.get(f) != row.get(f)]
            if changed:
                raise ValueError(f"来源冲突，未发布本批次: {key}; 字段 {changed}。请核验后提供明确修订版本，禁止自动覆盖。")
            duplicates += 1
        else:
            chosen.append(row); existing[key] = row
    if dry_run: return chosen, duplicates
    result = store.commit(chosen, checkpoint=checkpoint)
    return {**result, "duplicates": duplicates}


def import_runs(run_files, output, reference_file=None):
    from .bars import _atomic_bytes, _json_bytes
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    reference = json.loads(Path(reference_file).read_text(encoding="utf-8")) if reference_file else {"schema_version":"cn_index_reference_v1", "contracts":[], "aliases":[]}
    reports, excluded, pending = [], Counter(), []
    for run_file in run_files:
        run_file = Path(run_file).resolve()
        if run_file.is_dir(): run_file = run_file / "run.json"
        raw = run_file.read_bytes(); report = json.loads(raw)
        bulk = report.get("schema") == "basis_research_bulk_v1"
        if not (bulk or report.get("version") == 2) or report.get("state") not in {"complete", "partial"} or report.get("errors"):
            raise ValueError(f"未知格式或批次下载失败: {run_file}")
        files = []
        for item in report["files"]:
            path = manifest_file(run_file, item)
            item = {**item, "file":str(path)}
            if bulk and path.stem == "contract_reference":
                frame = pd.read_parquet(path)
                if len(frame) != item["rows"]: raise ValueError("参考资料行数不符")
                for r in frame.to_dict("records"):
                    reference["contracts"].append(dict(instrument_id=r["S_INFO_WINDCODE"],
                        listing_date=str(pd.Timestamp(r["S_INFO_LISTDATE"]).date()), expiry_date=str(pd.Timestamp(r["S_INFO_DELISTDATE"]).date()),
                        known_at=report["created_at"], source_updated_at=str(r["OPDATE"]), source="ddb_wind_cfuturesdescription", source_sha256=item["sha256"]))
            if not bulk or item.get("kind") == "normalized":
                files.append({**item, "downloaded_at":item.get("downloaded_at", report.get("created_at"))})
        reports.append(dict(path=str(run_file), sha256=hashlib.sha256(raw).hexdigest(), format="bulk_v1" if bulk else "shared_worker_v2", files=len(files), skipped=report.get("skipped", [])))
        pending.append((report, bulk, files))
    versions={}
    for row in reference.get("contracts",[]):
        key=(row["instrument_id"],row["known_at"])
        if key in versions and (row["listing_date"],row["expiry_date"])!=(versions[key]["listing_date"],versions[key]["expiry_date"]):
            raise ValueError(f"同版本合约参考冲突: {key}")
        versions.setdefault(key,row)
    reference["contracts"]=[versions[k] for k in sorted(versions)]
    contracts = {r["instrument_id"]:r for r in reference.get("contracts", [])}
    rows = []
    for report, bulk, files in pending:
        for skipped in report.get("skipped", []):
            contract = contracts.get(skipped.get("source_symbol"), {}); day = skipped.get("date", "")
            if skipped.get("status") == "unavailable" and contract and (day < contract["listing_date"] or day > contract["expiry_date"]):
                excluded["outside_contract_listing_interval"] += 1
            else:
                # Explicitly expose a gap; never fabricate a bar or hide the source.
                excluded["unexplained_source_gap"] += 1
        for item in files:
            converted, omissions = convert_file(item, bulk=bulk)
            for row in converted:
                meta = contracts.get(row["instrument_id"])
                if row["instrument_id"].endswith(".CFE") and (not meta or not meta["listing_date"] <= str(row["trade_date"]) <= meta["expiry_date"]):
                    raise ValueError(f"合约身份/挂牌区间无法认证: {row['instrument_id']} {row['trade_date']}")
            rows.extend(converted); excluded.update(omissions)
    if not rows: raise ValueError("没有可导入的有效数据")
    outputs = []
    # Preflight both asset kinds before either is committed.
    prepared = []
    for kind in ("cn_index", "cn_index_future"):
        chosen = [r for r in rows if r["instrument_id"].endswith(".CFE") == (kind == "cn_index_future")]
        if not chosen: continue
        instruments = {}
        for symbol in sorted({r["instrument_id"] for r in chosen}):
            instruments[symbol] = dict(asset_type=kind, market_region="CN", price_unit="index_points", currency="CNY")
            if kind == "cn_index_future": instruments[symbol]["underlying_id"] = UNDERLYINGS[symbol[:2]][0]
        descriptor = dict(dataset_id="ddb_basis_"+kind, source_id="shared_ddb_wind_csmar_v2", series_kind="concrete", price_adjustment="none",
            volume_unit="contracts" if kind == "cn_index_future" else "source_aggregate_not_futures_contracts", availability_policy="unknown",
            instruments=instruments, data_usage="historical_research", timestamp_note="1d: trade date 15:00 Asia/Shanghai; 1m: source close label, interval boundary unverified",
            limitation="修订后历史；未取得历史真实可用时间，允许标记后研究展示，不认证当时已知")
        root = output/kind
        if (root/"dataset.json").exists():
            store = BarDataset(root)
            for key in ("source_id", "series_kind", "price_adjustment", "volume_unit", "availability_policy"):
                if store.descriptor[key] != descriptor[key]: raise ValueError(f"数据集口径冲突: {key}")
        else: store = BarDataset.create(root, descriptor)
        old_imports = store.snapshot().get("checkpoint", {}).get("imports", [])
        imports = {r["sha256"]:r for r in [*old_imports, *reports]}
        prepared.append((store, instruments, chosen, {"imports":list(imports.values())}))
    validated=[]
    for store, instruments, chosen, checkpoint in prepared:
        accepted, duplicates=merge_checked(store,chosen,checkpoint,dry_run=True)
        validated.append((store,instruments,accepted,checkpoint,duplicates))
    for store, instruments, chosen, checkpoint, duplicates in validated:
        store.register_instruments(instruments)
        result = {**store.commit(chosen, checkpoint=checkpoint),"duplicates":duplicates}
        outputs.append(dict(root=str(store.root), **result))
    # Keep the manifest itself as immutable provenance, including repeat imports.
    batch_id = hashlib.sha256("".join(sorted(r["sha256"] for r in reports)).encode()).hexdigest()[:24]
    reference_bytes=_json_bytes(reference)
    ref_path = output/"references"/(hashlib.sha256(reference_bytes).hexdigest()+".json")
    if not ref_path.exists():_atomic_bytes(ref_path, reference_bytes)
    coverage = []
    from .repository import MarketDataRepository
    for d in outputs: coverage.extend(MarketDataRepository.inspect(d["root"])["coverage"])
    audit = dict(created_at=datetime.now(timezone.utc).isoformat(), batch_id=batch_id, rows=len(rows), datasets=outputs,
        excluded=dict(excluded), sources=reports, reference_file=str(ref_path), coverage=coverage,
        limitations=["修订后历史，真实可用时间未知", "分钟为源时间标签；不含09:30开盘观测", "OI为期末存量，不按时间求和", "缺数见来源清单和实际覆盖"])
    _atomic_bytes(output/"imports"/(batch_id+".json"), _json_bytes(audit))
    _atomic_bytes(output/"import_audit.json", _json_bytes(audit))
    return audit


def validate_standard(root):
    """Full registration audit: all hashes, rows, units, identity and conflicts."""
    from .bars import normalize_bars
    from .repository import MarketDataRepository
    report=MarketDataRepository.inspect(root);store=BarDataset(root);d=store.descriptor
    if report["synthetic"]: raise ValueError("合成数据不能注册为真实行情")
    if d.get("series_kind")!="concrete" or d.get("price_adjustment")!="none": raise ValueError("只接受未复权具体合约行情")
    if d.get("volume_unit") not in {"contracts","source_aggregate_not_futures_contracts"}: raise ValueError("成交量单位未认证")
    snap=store.snapshot()
    for part in snap["parts"]:
        rows=store._rows({**snap,"parts":[part]})
        if len(rows)!=part["rows"]:raise ValueError("分片行数不符")
        normalize_bars(rows)
        for row in rows:
            if row["instrument_id"]!=part["instrument_id"] or row["frequency"]!=part["frequency"] or row["source_symbol"] not in (None,row["instrument_id"]):raise ValueError("分片/具体合约身份冲突")
    # Each logical key/revision must carry exactly one economic payload.
    from .bars import _row_key, _payload
    seen={}
    for row in store._rows(snap):
        key=(_row_key(row),row["revision"]);payload=_payload(row)
        if key in seen and seen[key]!=payload:raise ValueError("标准数据集中存在同版本冲突记录")
        seen[key]=payload
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--register", action="store_true", help="Register imported roots for this dashboard")
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    audit = import_runs(args.run, args.output, args.reference)
    if args.register:
        from dashboard.native.model import NativeModel
        model = NativeModel()
        config = dict(model.config)
        config["history_roots"] = list(dict.fromkeys([d["root"] for d in audit["datasets"]]))
        config.update(allow_unverified=True, frequency="1d")
        config["reference_file"] = audit["reference_file"]
        if model.path.exists():
            backup = model.path.with_name("native.before_ddb_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
            backup.write_bytes(model.path.read_bytes())
        model.save_config(config)
        model.close()
    print(json.dumps({k:v for k,v in audit.items() if k != "sources"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
