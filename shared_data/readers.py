"""Read-only adapters; consumers keep their own business parsing and calculations."""
from __future__ import annotations

from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3

from .io import resolved_manifest, sha256
from .paths import DataPaths


class LocalData:
    def __init__(self, paths: DataPaths):
        self.paths = paths

    def daily_quotes(self, start, end, *, codes=(), fields=(), mode="wind"):
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("Reversed date range")
        database = self.paths.basis(mode) / "market.sqlite"
        sql, values = "SELECT code,day,field,value FROM quotes WHERE day BETWEEN ? AND ?", [start, end]
        for column, selected in (("code", codes), ("field", fields)):
            if selected:
                sql += f" AND {column} IN ({','.join('?' for _ in selected)})"
                values.extend(selected)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute(sql + " ORDER BY day,code,field", values)]
        return {"api_version": 1, "frequency": "1d", "timezone": "Asia/Shanghai", "mode": mode,
                "database": str(database), "start": start, "end": end, "records": rows}

    def dividend_files(self):
        return sorted(p for p in self.paths.dividend_inputs.glob("*基差情况_*.xlsx") if not p.name.startswith("~$"))

    def report_file(self, kind, day):
        names = {"swap": "收益互换日报", "review": "日报复核表"}
        if kind not in names or date.fromisoformat(day).isoformat() != day:
            raise ValueError("Invalid report kind/date")
        path = self.paths.reports / day / f"{names[kind]}({day})-D1.xlsx"
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def lending_files(self, day, *, demo=False):
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Invalid inventory date")
        root = self.paths.lending(demo)
        manifest = resolved_manifest(json.loads((root / day / "latest.json").read_text(encoding="utf-8")), root)
        if manifest["date"] != day:
            raise ValueError("Inventory date mismatch")
        for entry in manifest["files"]:
            path = Path(entry["path"]).resolve()
            if not path.is_relative_to((root / day).resolve()) or sha256(path) != entry["sha256"]:
                raise ValueError("Inventory file failed validation")
        return manifest
