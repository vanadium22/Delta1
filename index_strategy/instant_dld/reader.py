"""Short, read-only snapshots for strategies; calculations hold no database lock."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
import re
import sqlite3
import uuid

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .quotes import QUOTE_COLUMNS
from .realtime_store import DB_RELATIVE, DEFAULT_OUTPUT, publish_parquet


class RealtimeReader:
    def __init__(self, root: str | Path = DEFAULT_OUTPUT):
        self.root = Path(root).expanduser().resolve()
        self.db_path = self.root / DB_RELATIVE

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            connection.close()

    def _frame(self, sql: str, values=()) -> pd.DataFrame:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(sql, values).fetchall()]
        frame = pd.DataFrame(rows, columns=QUOTE_COLUMNS)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
        return frame.set_index("timestamp")

    def read_since(self, sequence: int = 0, *, symbols: list[str] | None = None, limit: int = 10000) -> pd.DataFrame:
        if type(sequence) is not int or sequence < 0 or type(limit) is not int or not 1 <= limit <= 1000000:
            raise ValueError("sequence 必须是非负整数，limit 必须在 1 到 1000000 之间")
        columns = ",".join(QUOTE_COLUMNS)
        where, args = "sequence>?", [sequence]
        if symbols is not None:
            where += " AND symbol IN (" + ",".join("?" for _ in symbols) + ")"
            args.extend(symbols)
        return self._frame(f"SELECT {columns} FROM quotes WHERE {where} ORDER BY sequence LIMIT ?", [*args, limit])

    def latest(self, symbols: list[str] | None = None) -> pd.DataFrame:
        where, args = "", []
        if symbols is not None:
            where = " WHERE symbol IN (" + ",".join("?" for _ in symbols) + ")"
            args = symbols
        return self._frame(f"SELECT {','.join(QUOTE_COLUMNS)} FROM quotes WHERE sequence IN "
                           f"(SELECT MAX(sequence) FROM quotes{where} GROUP BY symbol) ORDER BY symbol", args)

    def history(self, symbol: str, day: str) -> pd.DataFrame:
        date.fromisoformat(day)
        return self._frame(f"SELECT {','.join(QUOTE_COLUMNS)} FROM quotes WHERE symbol=? AND capture_date=? ORDER BY sequence", (symbol, day))

    def parquet_files(self, symbol: str, day: str) -> list[Path]:
        date.fromisoformat(day)
        with self.connect() as connection:
            paths = [row[0] for row in connection.execute(
                "SELECT path FROM parquet_parts WHERE symbol=? AND capture_date=? ORDER BY first_sequence", (symbol, day))]
        return [self.root / path for path in paths]

    def read_parquet_day(self, symbol: str, day: str) -> pd.DataFrame:
        # Freeze the file list in one transaction; published files are never replaced.
        files = self.parquet_files(symbol, day)
        if not files:
            return pd.DataFrame(columns=QUOTE_COLUMNS).set_index("timestamp")
        frame = pa.concat_tables([pq.ParquetFile(path).read() for path in files]).to_pandas()
        return frame.sort_values("sequence").set_index("timestamp")


def write_strategy_frame(frame: pd.DataFrame, strategy: str, root: str | Path = DEFAULT_OUTPUT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", strategy):
        raise ValueError("策略目录名仅支持字母、数字、下划线和连字符")
    directory = Path(root).expanduser().resolve() / "strategy_results" / strategy
    return publish_parquet(pa.Table.from_pandas(frame), directory, uuid.uuid4().hex)
