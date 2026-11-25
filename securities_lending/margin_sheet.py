from __future__ import annotations

import re
from collections import Counter
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from .inventory import ALIASES, MissingSheetError, clean, heading, normalize_code, read_rows


SHEET_NAME = "两融券单"
CODE_HEADERS = {
    heading(name) for name in (
        *ALIASES["code"], "证券编码", "股票编码", "标的证券代码", "标的证券编码",
    ) if name not in {"代码", "标的"}
}


def display_value(cell):
    if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
        pattern = re.fullmatch(r"(#,##0|0)(?:\.(0+))?\s*(%)?", cell.format.partition(";")[0])
        if pattern and (pattern[1] == "#,##0" or pattern[3]):
            grouping = "," if pattern[1] == "#,##0" else ""
            precision = len(pattern[2] or "")
            kind = "%" if pattern[3] else "f"
            return f"{Decimal(str(cell.value)):{grouping}.{precision}{kind}}"
    return clean(cell.value)


def read_margin_sheet(path: Path):
    columns = None
    records = []
    with closing(read_rows(path, SHEET_NAME)) as rows:
        for row_number, cells in enumerate(rows, 1):
            if columns is None:
                names = [heading(cell.value) for cell in cells]
                candidates = [index for index, name in enumerate(names) if name in CODE_HEADERS]
                if not candidates:
                    candidates = [index for index, name in enumerate(names) if name in {"代码", "标的"}]
                if len(candidates) > 1:
                    raise ValueError(f"第 {row_number} 行有多列可能是证券代码")
                if candidates:
                    code_index = candidates[0]
                    occurrences = Counter()
                    columns = {}
                    for index, cell in enumerate(cells):
                        name = clean(cell.value)
                        if index != code_index and name:
                            occurrences[name] += 1
                            columns[index] = (name, occurrences[name])
                elif row_number >= 50:
                    break
                continue
            code = normalize_code(cells[code_index].value) if code_index < len(cells) else ""
            if code:
                records.append((code, {
                    "columns": tuple(columns.values()),
                    "values": tuple(display_value(cells[index]) if index < len(cells) else "" for index in columns),
                    "row": row_number,
                }))
    if columns is None:
        raise ValueError("前 50 行未识别证券代码列")
    return records


def load_margin_sheets(files, progress=None):
    by_code, sources = {}, []
    for entry in files:
        name = entry["name"]
        if progress:
            progress(f"正在读取本地文件：{name} → {SHEET_NAME}")
        source = {"file": name, "state": "ready", "message": ""}
        try:
            rows = read_margin_sheet(Path(entry["path"]))
        except MissingSheetError:
            source.update(state="missing", message=f"缺少「{SHEET_NAME}」工作表")
        except Exception as exc:
            source.update(state="error", message=str(exc))
        else:
            for code, row in rows:
                by_code.setdefault(code, []).append({**row, "file": name})
        sources.append(source)
    return by_code, sources
