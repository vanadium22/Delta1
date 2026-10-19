"""Read the permanent daily basis store without contacting a market provider."""
from datetime import datetime
import hashlib
import re
import sqlite3

import pandas as pd

from .analytics import NAMES
from .config import SHANGHAI
from .security_model import calculate, numeric


def future_name(code):
    suffix = code.split(".")[0][2:]
    return NAMES[code[:2]] + (f" 连续档位{suffix}（逐日换月）" if len(suffix) == 2 else f" {suffix}合约")


def query_local_future(service, query, *, force=False):
    from .security_data import SecurityResult
    if query.frequency != "1d":
        raise ValueError("本地股指期货库为日线，请选择日频；不将日线冒充分钟或最新行情")
    if force:
        raise ValueError("股指期货分析只读本地日线；请在数据管理更新后重新查询")
    if service.basis is not None:
        base = service.basis.store.path.parent
    else:
        market = service.paths.root / "market" / "index_futures"
        root = service.paths.repo_root / "index_futures_basis"
        configured = service.paths.resolve_module_setting(root, service.config.get("data_directory", "@shared"), market, ("data",))
        base = service.paths.basis(service.mode) if configured == market else configured / service.mode
    candidates = [base / "market.sqlite"]
    if service.mode != "demo":
        candidates.append(base.parent / ("offline" if service.mode == "wind" else "wind") / "market.sqlite")
    selected = None
    for path in candidates:
        if not path.is_file():
            continue
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as con:
            # Same one-source fallback rule as the basis app; never mix stores or demo data.
            available = con.execute("SELECT 1 FROM quotes WHERE day<=? LIMIT 1", (query.end,)).fetchone()
            if not available:
                continue
            quotes = pd.read_sql_query("SELECT day,code,field,value FROM quotes WHERE day BETWEEN ? AND ?",
                                       con, params=(query.start, query.end))
            mappings = con.execute("SELECT day,code FROM mapping WHERE root=? AND slot=? AND day BETWEEN ? AND ?",
                                   (query.code[:2], int(query.code[3]) + 1 if len(query.code.split('.')[0]) == 4 else 0,
                                    query.start, query.end)).fetchall()
            calendar = dict(con.execute("SELECT day,is_open FROM calendar WHERE day BETWEEN ? AND ?", (query.start, query.end)))
            selected = path
            break
    if selected is None:
        raise ValueError("没有可用的本地股指日线，请先在数据管理更新或导入真实行情")
    continuous = len(query.code.split(".")[0]) == 4
    mapping = {day: code.upper() for day, code in mappings
               if re.fullmatch(query.code[:2] + r"\d{4}\.CFE", code.upper())}
    quotes["code"] = quotes.code.str.upper()
    values = {(r.day, r.code, r.field): r.value for r in quotes.itertuples()}
    observed = set(mapping) if continuous else set(quotes.loc[quotes.code == query.code, "day"])
    days = sorted({day for day, opened in calendar.items() if opened} | observed)
    if not days:
        raise ValueError("所选窗口没有本地交易日或该合约记录，请检查日期并更新本地数据")
    rows, identities = [], []
    for day in days:
        actual = mapping.get(day) if continuous else query.code
        identities.append({"date": day, "actual_code": actual})
        rows.append({"time": day, **{field: numeric(values.get((day, actual, field)), field)
                                     for field in query.required_fields}})
    frame = pd.DataFrame(rows)
    for field in query.required_fields:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    valid = frame.loc[frame[query.required_fields].notna().any(axis=1), "time"]
    notes = ["只读每日更新的本地股指日线，无分红调整；缺失字段/映射留空，不联网补取。",
             "连续档位按每日实际合约映射拼接，不做价格后复权，换月可能产生跳变。" if continuous else "实际合约按原代码读取。",
             "当前日线库通常仅含收盘价和持仓量；未保存的开高低、成交量、成交额留空。"]
    if not calendar or any(day not in calendar for day in observed):
        notes.append("本地交易日历覆盖不足，未确认的交易日不补造；统计仅代表已保存样本。")
    metadata = {"schema_version": 1, "query": query.metadata(), "name": future_name(query.code),
        "mode": service.mode, "source": "合成演示日线" if service.mode == "demo" else f"本地股指日线（{selected.parent.name}）",
        "source_database": str(selected), "query_time": datetime.now(SHANGHAI).isoformat(),
        "received_at": "本地库，原始采集时刻未记录", "requests": 0, "notes": notes,
        "actual_start": valid.iloc[0] if len(valid) else None, "actual_end": valid.iloc[-1] if len(valid) else None,
        "grid_start": days[0], "grid_end": days[-1], "expected_rows": len(frame),
        "complete_rows": int(frame[query.required_fields].notna().all(axis=1).sum()),
        "missing_cells": int(frame[query.required_fields].isna().sum().sum()), "contract_mapping": identities,
        "timezone": "Asia/Shanghai", "units": {"price": "点", "oi": "手"},
        "data_sha256": hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()}
    return SecurityResult(query, frame, calculate(query, frame), metadata)
