"""Inspect accessible Wind tables and download bounded market-data samples."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__:
    from .wind_connection import connect, safe_error, select
else:
    from wind_connection import connect, safe_error, select


DAILY_GROUPS = {
    "etf_daily": ("CHINACLOSEDFUNDEODPRICE", ["510050.SH", "510300.SH", "510500.SH", "512100.SH", "518880.SH", "511010.SH"]),
    "index_daily": ("AINDEXEODPRICES", ["000016.SH", "000300.SH", "000905.SH", "000852.SH"]),
    "index_futures_daily": ("CINDEXFUTURESEODPRICES", ["IH.CFE", "IF.CFE", "IC.CFE", "IM.CFE"]),
    "index_futures_contract_daily": ("CINDEXFUTURESEODPRICES", ["IH{month}.CFE", "IF{month}.CFE", "IC{month}.CFE", "IM{month}.CFE"]),
    "commodity_futures_daily": ("CCOMMODITYFUTURESEODPRICES", ["AU.SHF"]),
    "bond_futures_daily": ("CBONDFUTURESEODPRICES", ["T.CFE"]),
}
MARKET_FIELDS = ["S_INFO_WINDCODE", "TRADE_DT", "CRNCY_CODE", "S_DQ_PRECLOSE", "S_DQ_PRESETTLE",
                 "S_DQ_OPEN", "S_DQ_HIGH", "S_DQ_LOW", "S_DQ_CLOSE", "S_DQ_SETTLE",
                 "S_DQ_VOLUME", "S_DQ_AMOUNT", "S_DQ_OI", "S_DQ_ADJFACTOR", "S_DQ_ADJCLOSE", "FS_INFO_TYPE"]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def catalog(db, output):
    queries = {
        "tables": "SELECT OWNER, TABLE_NAME FROM ALL_TABLES ORDER BY OWNER, TABLE_NAME",
        "views": "SELECT OWNER, VIEW_NAME FROM ALL_VIEWS WHERE OWNER NOT IN ('SYS','SYSTEM') ORDER BY OWNER, VIEW_NAME",
        "synonyms": "SELECT OWNER, SYNONYM_NAME, TABLE_OWNER, TABLE_NAME, DB_LINK FROM ALL_SYNONYMS WHERE TABLE_OWNER NOT IN ('SYS','SYSTEM') ORDER BY OWNER, SYNONYM_NAME",
        "comments": "SELECT OWNER, TABLE_NAME, COMMENTS FROM ALL_TAB_COMMENTS WHERE OWNER NOT IN ('SYS','SYSTEM') AND COMMENTS IS NOT NULL ORDER BY OWNER, TABLE_NAME",
    }
    result = {}
    for name, sql in queries.items():
        print(f"Catalog: {name}", flush=True)
        try:
            result[name] = select(db, sql, limit=30000)
            print(f"  {len(result[name])} entries", flush=True)
        except Exception as exc:
            result[name] = {"error": safe_error(exc)}
        write_json(output / "catalog.json", result)
    return result


def save_frame(output, name, rows):
    import pandas as pd

    frame = pd.DataFrame(rows)
    path = output / (name + ".parquet")
    frame.to_parquet(path, index=False)
    pd.testing.assert_frame_equal(frame, pd.read_parquet(path))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"file": str(path.resolve()), "rows": len(frame), "bytes": path.stat().st_size,
            "sha256": digest, "roundtrip_verified": True}


def daily_samples(db, output, end_date, days):
    start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=days - 1)).strftime("%Y%m%d")
    all_columns = select(db, "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_ID FROM ALL_TAB_COLUMNS "
                         "WHERE OWNER='WIND' AND TABLE_NAME IN (" + ",".join(":" + f"t{i}" for i in range(len(DAILY_GROUPS))) + ") "
                         "ORDER BY TABLE_NAME, COLUMN_ID", {f"t{i}": v[0] for i, v in enumerate(DAILY_GROUPS.values())})
    write_json(output / "market_columns.json", all_columns)
    results = {}
    for name, (table, codes) in DAILY_GROUPS.items():
        codes = [code.format(month=end_date[2:6]) for code in codes]
        print(f"Daily sample: {table}", flush=True)
        item = {"table": "WIND." + table, "requested_start": start_date, "requested_end": end_date, "per_code": [], "queries": []}
        results[name] = item
        try:
            columns = {r["COLUMN_NAME"] for r in all_columns if r["TABLE_NAME"] == table}
            required = {"S_INFO_WINDCODE", "TRADE_DT", "S_DQ_OPEN", "S_DQ_HIGH", "S_DQ_LOW", "S_DQ_CLOSE"}
            if not required.issubset(columns):
                raise ValueError("Required daily price columns not visible.")
            fields = ", ".join(c for c in MARKET_FIELDS if c in columns)
            rows = []
            for code in codes:
                sql = f"SELECT {fields} FROM WIND.{table} WHERE S_INFO_WINDCODE=:code AND TRADE_DT BETWEEN :start_dt AND :end_dt AND ROWNUM <= :cap ORDER BY TRADE_DT"
                binds = {"code": code, "start_dt": start_date, "end_dt": end_date, "cap": 1001}
                found = select(db, sql, binds, limit=1000)
                item["queries"].append({"sql": sql, "binds": binds, "rows": len(found)})
                fallback = False
                if not found:
                    fallback = True
                    sql = f"SELECT {fields} FROM (SELECT {fields} FROM WIND.{table} WHERE S_INFO_WINDCODE=:code AND TRADE_DT<=:end_dt ORDER BY TRADE_DT DESC) WHERE ROWNUM<=:cap"
                    binds = {"code": code, "end_dt": end_date, "cap": 5}
                    found = select(db, sql, binds, limit=5)
                    item["queries"].append({"sql": sql, "binds": binds, "rows": len(found)})
                rows.extend(found)
                dates = [r["TRADE_DT"] for r in found]
                item["per_code"].append({"code": code, "rows": len(found), "start": min(dates) if dates else None,
                                         "end": max(dates) if dates else None, "fallback_to_latest": fallback})
            rows.sort(key=lambda row: (row["S_INFO_WINDCODE"], row["TRADE_DT"]))
            if not rows:
                item["status"] = "no_data"
                continue
            item.update(save_frame(output, name, rows))
            keys = [(r["S_INFO_WINDCODE"], r["TRADE_DT"]) for r in rows]
            item["duplicate_code_dates"] = len(keys) - len(set(keys))
            prices = ["S_DQ_OPEN", "S_DQ_HIGH", "S_DQ_LOW", "S_DQ_CLOSE"]
            item["null_ohlc_rows"] = sum(any(r.get(k) is None for k in prices) for r in rows)
            item["invalid_ohlc_rows"] = sum(
                all(r.get(k) is not None for k in prices) and
                (r["S_DQ_LOW"] > min(r["S_DQ_OPEN"], r["S_DQ_CLOSE"]) + 1e-8 or
                 r["S_DQ_HIGH"] < max(r["S_DQ_OPEN"], r["S_DQ_CLOSE"]) - 1e-8)
                for r in rows)
            item["preview"] = rows[:2]
            item["status"] = "success" if (all(p["rows"] for p in item["per_code"]) and
                         not any(item[k] for k in ["duplicate_code_dates", "null_ohlc_rows", "invalid_ohlc_rows"])) else "partial"
            print(f"  {item['status']}: {len(rows)} rows, read-back verified", flush=True)
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = safe_error(exc)
            print(f"  {item['error']}", flush=True)
        finally:
            write_json(output / "daily_results.json", results)
    return results


def reference_samples(db, output):
    codes = DAILY_GROUPS["etf_daily"][1]
    binds = {f"c{i}": code for i, code in enumerate(codes)}
    code_list = ",".join(":" + name for name in binds)
    specifications = {
        "etf_tracking_index": ("SELECT S_INFO_WINDCODE, S_INFO_INDEXWINDCODE, ENTRY_DT, REMOVE_DT "
                               f"FROM WIND.CHINAMUTUALFUNDTRACKINGINDEX WHERE S_INFO_WINDCODE IN ({code_list}) AND ROWNUM<=501", binds),
        "etf_classification": ("SELECT S_INFO_WINDCODE, S_INFO_NAME, S_INFO_SECTOR "
                               f"FROM WIND.CHINAETFINVESTCLASS WHERE S_INFO_WINDCODE IN ({code_list}) AND ROWNUM<=501", binds),
        "index_descriptions": ("SELECT S_INFO_WINDCODE, S_INFO_NAME, S_INFO_EXCHMARKET, S_INFO_LISTDATE "
                               "FROM WIND.AINDEXDESCRIPTION WHERE S_INFO_WINDCODE IN ('000016.SH','000300.SH','000905.SH','000852.SH') AND ROWNUM<=501", {}),
    }
    results = {}
    for name, (sql, values) in specifications.items():
        try:
            rows = select(db, sql, values, limit=500)
            item = {"status": "success" if rows else "no_data", "sql": sql, "binds": values}
            if rows:
                item.update(save_frame(output, name, rows))
                item["preview"] = rows[:10]
            results[name] = item
        except Exception as exc:
            results[name] = {"status": "failed", "error": safe_error(exc)}
    write_json(output / "reference_results.json", results)
    return results


def minute_discovery(db, output, inventory):
    pattern = re.compile(r"MINUTE|INTRADAY|TICK|[0-9]MIN|MIN[0-9]|分钟|分时", re.I)
    candidates = []
    for kind in ["tables", "views", "synonyms", "comments"]:
        entries = inventory.get(kind, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if entry.get("OWNER") in {"SYS", "SYSTEM", "APEX_030200", "ORDSYS", "MDSYS", "XDB"}:
                continue
            if entry.get("TABLE_OWNER") in {"SYS", "SYSTEM", "ORDSYS"}:
                continue
            text = " ".join(str(entry.get(key, "")) for key in ["TABLE_NAME", "VIEW_NAME", "SYNONYM_NAME", "COMMENTS"])
            if pattern.search(text):
                candidates.append({"kind": kind, **entry})
    time_columns = select(db, "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS "
                          "WHERE OWNER='WIND' AND TABLE_NAME NOT LIKE 'LOG\\_%' ESCAPE '\\' "
                          "AND (COLUMN_NAME LIKE '%TIME%' OR COLUMN_NAME LIKE '%MINUTE%' OR COLUMN_NAME LIKE '%HOUR%') "
                          "ORDER BY TABLE_NAME,COLUMN_NAME")
    catalog_complete = all(isinstance(v, list) for v in inventory.values())
    result = {"status": ("metadata_incomplete" if not catalog_complete else
                         "candidate_requires_schema_review" if candidates else "no_name_match_in_accessible_catalog"),
              "catalog_complete": catalog_complete,
              "name_candidates": candidates, "time_columns": time_columns,
              "minute_rows_downloaded": 0,
              "limitation": "Metadata discovery only. Does not prove minute data are absent from other databases/products or unavailable to other accounts."}
    write_json(output / "minute_discovery.json", result)
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(r"Z:\Project\_data\index\_etf") / ("smoke_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument("--end-date", help="YYYYMMDD; default is the database's yesterday")
    parser.add_argument("--days", type=int, default=14, help="Calendar-day sample window, 1-90")
    args = parser.parse_args()
    if not 1 <= args.days <= 90:
        parser.error("--days must be between 1 and 90")
    if args.end_date:
        datetime.strptime(args.end_date, "%Y%m%d")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"started_at": datetime.now().isoformat(), "output": str(args.output.resolve())}
    try:
        with connect() as db:
            report["database_version"] = db.version
            report["server_date"] = select(db, "SELECT CURRENT_DATE AS SERVER_DATE FROM DUAL")[0]["SERVER_DATE"]
            print(f"Connected to Oracle {db.version}; server date: {report['server_date']}", flush=True)
            inventory = catalog(db, args.output)
            report["catalog_errors"] = {k: v for k, v in inventory.items() if not isinstance(v, list)}
            report["wind_table_count"] = sum(r["OWNER"] == "WIND" for r in inventory.get("tables", []) if isinstance(r, dict))
            report["status"] = "partial" if report["catalog_errors"] else "catalog_complete"
            if not args.catalog_only:
                end_date = args.end_date or (report["server_date"] - timedelta(days=1)).strftime("%Y%m%d")
                report["daily"] = daily_samples(db, args.output, end_date, args.days)
                report["references"] = reference_samples(db, args.output)
                report["minute"] = minute_discovery(db, args.output, inventory)
                report["status"] = "partial"  # Minute downloads require a verified minute source.
                report["daily_success_groups"] = sum(x["status"] == "success" for x in report["daily"].values())
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = safe_error(exc)
        print(report["error"], flush=True)
    finally:
        report["finished_at"] = datetime.now().isoformat()
        write_json(args.output / "report.json", report)
        print(f"Report: {args.output / 'report.json'}", flush=True)
    return {"failed": 1, "partial": 2}.get(report["status"], 0)


if __name__ == "__main__":
    raise SystemExit(main())
