"""Explicit one-shot, read-only DDB daily acquisition into a new Delta1/data snapshot.

This command never connects a VPN. The route must already be available.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .calendar import verified_days
from .io import write_json
from .models import BacktestError, SPOT_SYMBOLS, check_source_paths
from .strategy.mapping import slot_mapping


DAILY_SOURCES = {
    "futures": ("dfs://ods_tsdb_y_wind", "cindexfutureseodprices"),
    "indices": ("dfs://ods_tsdb_m_wind", "aindexeodprices"),
}
REFERENCE_SOURCE = ("dfs://ods_tsdb_wind", "cfuturesdescription")
ROOTS = ("IF", "IH", "IC", "IM")


def clean_prices(frame, symbols):
    required = {"symbol", "trade_date", "close"}
    if not required <= set(frame):
        raise BacktestError("Daily source lacks symbol/trade_date/close fields")
    frame = frame[["symbol", "trade_date", "close"]].drop_duplicates().copy()
    if not set(frame.symbol) <= set(symbols):
        raise BacktestError("Daily source returned an unrequested symbol")
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.strftime("%Y-%m-%d")
    frame["close"] = pd.to_numeric(frame.close, errors="raise")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise BacktestError("Conflicting daily source values; no arbitrary revision selection")
    if (~np.isfinite(frame.close) | frame.close.le(0)).any():
        raise BacktestError("Source contains missing/nonpositive close values")
    return frame.sort_values(["trade_date", "symbol"])


def reference_rows(frame, retrieved):
    required = {"S_INFO_WINDCODE", "S_INFO_LISTDATE", "S_INFO_DELISTDATE", "OPDATE"}
    if not required <= set(frame):
        raise BacktestError("Contract reference source schema changed")
    records = []
    for symbol, group in frame.groupby("S_INFO_WINDCODE"):
        if not re.fullmatch(r"(?:IF|IH|IC|IM)\d{4}\.CFE", symbol):
            continue
        group = group.sort_values("OPDATE", na_position="first")
        latest = group.iloc[-1]
        tied = group.loc[group.OPDATE.eq(latest.OPDATE)] if pd.notna(latest.OPDATE) else group
        if len(tied[["S_INFO_LISTDATE", "S_INFO_DELISTDATE"]].drop_duplicates()) > 1:
            raise BacktestError("Same-version contract listing/expiry conflict")
        if pd.isna(latest.S_INFO_LISTDATE) or pd.isna(latest.S_INFO_DELISTDATE):
            raise BacktestError(f"Missing source listing/expiry for {symbol}")
        first, last = str(pd.Timestamp(latest.S_INFO_LISTDATE).date()), str(pd.Timestamp(latest.S_INFO_DELISTDATE).date())
        if first > last:
            raise BacktestError(f"Invalid source listing interval for {symbol}")
        records.append(dict(instrument_id=symbol, listing_date=first, expiry_date=last, known_at=retrieved,
                            source="ddb_wind_cfuturesdescription", source_updated_at=str(latest.OPDATE)))
    return records


def audit_daily(close, contracts, start, requested_end):
    days = verified_days(start, requested_end)
    index = pd.DatetimeIndex(days, tz="Asia/Shanghai") + pd.Timedelta(hours=15)
    mapping, mapping_gaps = slot_mapping(index, contracts, ROOTS)
    aligned = close.reindex(index=index)
    complete, gaps = [], []
    for stamp in index:
        needed = [root + "_spot" for root in ROOTS]
        symbols = mapping.loc[stamp].dropna().tolist()
        missing_mapping = len(symbols) != 16
        needed += symbols
        absent = [s for s in needed if s not in aligned or not np.isfinite(aligned.at[stamp, s]) or aligned.at[stamp, s] <= 0]
        if absent or missing_mapping:
            gaps.append(dict(date=str(stamp.date()), missing=absent, mapping_missing=missing_mapping))
        else:
            complete.append(str(stamp.date()))
    effective_end = complete[-1] if complete else None
    interior = [g for g in gaps if effective_end is None or g["date"] <= effective_end]
    tail = [d for d in days if effective_end is None or d > effective_end]
    return dict(requested_start=start, requested_end=requested_end, effective_end=effective_end,
                expected_sessions=len(days), complete_sessions=len(complete), interior_gaps=interior,
                unavailable_tail=tail, mapping_gap_count=len(mapping_gaps),
                status="complete" if not gaps else "tail_pending" if not interior and effective_end else "incomplete")


def acquire_daily(connection_path, output_dir, *, start="2023-07-01", end="2026-11-02", client_factory=None):
    check_source_paths([connection_path, output_dir])
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    raw_root = root / "raw"
    raw_root.mkdir()
    retrieved = datetime.now(timezone.utc).isoformat()
    client = None
    stage = "connect"
    try:
        if client_factory is None:
            from dashboard.marketdata.history_maintenance import open_direct
            client_factory = open_direct
        client = client_factory(connection_path)
        possible = [f"{r}{year % 100:02}{month:02}.CFE" for r in ROOTS
                    for year in range(int(start[:4]) - 1, int(end[:4]) + 3) for month in range(1, 13)]
        client.session.upload(dict(btCandidates=possible, btStart=np.datetime64(start, "D"), btEnd=np.datetime64(end, "D")))
        stage = "contract_reference"
        database, table = REFERENCE_SOURCE
        source = f'loadTable("{database}","{table}")'
        where = "S_INFO_WINDCODE in btCandidates,S_INFO_LISTDATE<=btEnd,S_INFO_DELISTDATE>=btStart"
        count = int(client.session.run(f"exec count(*) from {source} where {where}"))
        if count > 20_000:
            raise BacktestError("Contract reference row bound exceeded")
        frame = client.session.run(f"select S_INFO_WINDCODE,S_INFO_LISTDATE,S_INFO_DELISTDATE,OPDATE from {source} where {where}")
        if len(frame) != count:
            raise BacktestError("Contract source changed during query")
        frame.to_parquet(raw_root / "contract_reference.parquet", index=False)
        references = reference_rows(frame, retrieved)
        contracts = {r["instrument_id"]: r for r in references}
        if not contracts:
            raise BacktestError("No dated concrete futures returned")
        write_json(root / "reference.json", dict(schema_version="cn_index_reference_v1", contracts=references, aliases=[],
                   retrieved_at=retrieved, source="/".join(REFERENCE_SOURCE), historical_availability="revised_source_not_PIT"))
        output = []
        for kind, (database, table) in DAILY_SOURCES.items():
            symbols = sorted(contracts) if kind == "futures" else list(SPOT_SYMBOLS)
            client.session.upload(dict(btSymbols=symbols))
            source = f'loadTable("{database}","{table}")'
            for year in range(int(start[:4]), int(end[:4]) + 1):
                stage = f"{kind}_{year}"
                left, right = max(start, f"{year}-01-01"), min(end, f"{year}-12-31")
                client.session.upload(dict(btLeft=np.datetime64(left, "D"), btRight=np.datetime64(right, "D")))
                where = "TRADE_DT between btLeft:btRight,S_INFO_WINDCODE in btSymbols"
                count = int(client.session.run(f"exec count(*) from {source} where {where}"))
                if count > 200_000:
                    raise BacktestError("Daily query row bound exceeded")
                frame = client.session.run(f"select S_INFO_WINDCODE as symbol,TRADE_DT as trade_date,S_DQ_CLOSE as close from {source} where {where}")
                if len(frame) != count:
                    raise BacktestError("Daily source changed during query")
                frame.to_parquet(raw_root / f"{kind}_{year}.parquet", index=False)
                if len(frame):
                    output.append(clean_prices(frame, symbols))
                print(f"{stage}: {len(frame)} daily rows", flush=True)
        if not output:
            raise BacktestError("No daily prices returned")
        long = pd.concat(output, ignore_index=True)
        long["symbol"] = long.symbol.replace(SPOT_SYMBOLS)
        if long.duplicated(["symbol", "trade_date"]).any():
            raise BacktestError("Overlapping downloaded daily rows")
        close = long.pivot(index="trade_date", columns="symbol", values="close").sort_index()
        close.index = (pd.DatetimeIndex(close.index).tz_localize("Asia/Shanghai") + pd.Timedelta(hours=15)).rename("timestamp")
        close.to_parquet(root / "daily_close.parquet")
        write_json(root / "data_config.local.json", dict(data=dict(daily_close_path=str(root / "daily_close.parquet"),
                   reference_path=str(root / "reference.json"), allow_unverified_availability=True, dividend_policy="none")))
        audit = audit_daily(close, contracts, start, end)
        write_json(root / "coverage.json", audit)
        files = []
        for file in sorted(root.rglob("*")):
            if file.is_file():
                files.append(dict(path=str(file.relative_to(root)), size=file.stat().st_size,
                                  sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
        report = dict(state="downloaded", retrieved_at=retrieved, start=start, end=end,
                      data_source="DDB unadjusted actual-contract and index daily close", references=len(contracts),
                      price_rows=len(long), source_tables=DAILY_SOURCES, reference_table=REFERENCE_SOURCE,
                      historical_availability="current revised research history; no original publication clock",
                      vpn_operation=False, z_drive_used=False, files=files, coverage=audit)
        write_json(root / "acquisition.json", report)
        with (root.parent / "下载索引.md").open("a", encoding="utf-8") as handle:
            handle.write(f"\n- {retrieved} | {root.name} | {root} | DDB daily/reference | requested {start}..{end} | "
                         f"{sum(f['size'] for f in files)} bytes | SHA manifest acquisition.json\n")
        return report
    except Exception as exc:
        write_json(root / "failure.json", dict(stage=stage, error_type=type(exc).__name__, credentials_exported=False, vpn_operation=False))
        if isinstance(exc, BacktestError):
            raise
        raise BacktestError(f"Daily acquisition failed at {stage}: {type(exc).__name__}; credentials and SDK text withheld") from None
    finally:
        if client is not None:
            client.close()
            if hasattr(client, "config"):
                client.config.clear()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2023-07-01")
    parser.add_argument("--end", default="2026-11-02")
    args = parser.parse_args(argv)
    try:
        report = acquire_daily(args.connection, args.output, start=args.start, end=args.end)
        print(json.dumps(dict(output=str(args.output.resolve()), price_rows=report["price_rows"], coverage=report["coverage"]["status"]), ensure_ascii=False))
        return 0
    except BacktestError as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
