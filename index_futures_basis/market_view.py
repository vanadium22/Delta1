"""Read-only views of downloaded daily futures and index quotes."""
from datetime import date
import hashlib
from pathlib import Path
import uuid

import pandas as pd

from .analytics import ROOTS, NAMES
from .config import timestamp, atomic_json

COLUMNS = ["trade_date", "root", "name", "kind", "code", "continuous_code", "close", "open_interest", "expiry_date"]
HEADERS = ["日期", "品种", "名称", "类型", "实际代码", "连续档位", "收盘价（点）", "持仓量（手）", "到期日"]


def read_market_data(service, root=None, kind="all", code="", start=None, end=None):
    if root not in [None, *ROOTS] or kind not in {"all", "futures", "spot"}:
        raise ValueError("请选择有效品种和期货/现货类型")
    first = date.fromisoformat(str(start)).isoformat() if start else "1900-01-01"
    last = date.fromisoformat(str(end)).isoformat() if end else "9999-12-31"
    if first > last:
        raise ValueError("开始日期不能晚于结束日期")
    code = str(code).strip().upper()
    store, _ = service.local_source(last)
    with store.writer_lock(), store.connection() as con:
        quotes = pd.read_sql_query("""SELECT day AS trade_date, code,
            MAX(CASE WHEN field='close' THEN value END) AS close,
            MAX(CASE WHEN field='oi' THEN value END) AS open_interest
            FROM quotes WHERE day BETWEEN ? AND ? AND field IN ('close','oi')
            GROUP BY day,code ORDER BY day DESC,code""", con, params=(first, last))
        mappings = store.mappings(first, last)
        expiries = store.expiries()
        source = store.meta("source", {})
    aliases = {}
    for (day, r, slot), actual in mappings.items():
        aliases.setdefault((day, actual), []).append(f"{r}0{slot-1}.CFE")
    spots = {value: key for key, value in ROOTS.items()}
    rows = []
    for row in quotes.itertuples():
        r = spots.get(row.code) or (row.code[:2] if row.code[:2] in ROOTS else None)
        category = "spot" if row.code in spots else "futures"
        continuous = ",".join(sorted(aliases.get((row.trade_date, row.code), [])))
        if r is None or (root and r != root) or (kind != "all" and kind != category):
            continue
        if code and code not in row.code and code not in continuous:
            continue
        rows.append([row.trade_date, r, NAMES[r], "现货指数" if category == "spot" else "股指期货",
                     row.code, continuous, row.close, row.open_interest, expiries.get(row.code)])
    frame = pd.DataFrame(rows, columns=COLUMNS)
    source_mode = service.mode if store.path == service.store.path else ("offline" if service.mode == "wind" else "wind")
    provenance = {"kind": "local_index_quotes", "mode": service.mode, "source_mode": source_mode, "read_at": timestamp(),
        "source_database": str(store.path), "market_source": source,
        "filters": {"root": root, "kind": kind, "code": code, "start": start, "end": end},
        "rows": len(frame), "actual_start": frame.trade_date.min() if len(frame) else None,
        "actual_end": frame.trade_date.max() if len(frame) else None,
        "frequency": "1d", "valuation": "original_downloaded_values", "network_requests": 0,
        "data_sha256": hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest(),
        "note": "原始已下载记录；没有分红调整，不要求四品种完整；缺失字段留空。期货持仓单位手，现货指数没有期货持仓。"}
    return {"data": frame, "provenance": provenance}


def export_market_data(result, parent):
    output = Path(parent) / "local_market_data" / (timestamp().replace(":", "").replace("+", "_") + "_" + uuid.uuid4().hex[:6])
    output.mkdir(parents=True)
    path = output / "data.csv"
    result["data"].to_csv(path, index=False, encoding="utf-8-sig")
    manifest = {**result["provenance"], "generated_at": timestamp(),
                "fingerprint": result["provenance"]["data_sha256"],
                "columns": dict(zip(COLUMNS, HEADERS)), "files": [
                    {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    atomic_json(output / "run_manifest.json", manifest)
    return str(output)
