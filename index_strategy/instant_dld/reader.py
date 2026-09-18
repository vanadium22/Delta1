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
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .quotes import QUOTE_COLUMNS
from .realtime_store import DB_RELATIVE, DEFAULT_OUTPUT, SCHEMA, publish_parquet


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

    def _frame(self, clause: str, values=()) -> pd.DataFrame:
        with self.connect() as connection:
            existing = {row[1] for row in connection.execute("PRAGMA table_info(quotes)")}
            columns = []
            for name in QUOTE_COLUMNS:
                if name == "volume" and "volume_interval_seconds" not in existing:
                    columns.append("NULL AS volume")
                elif name == "quality_flags" and "volume_interval_seconds" not in existing:
                    columns.append("(quality_flags | 16) AS quality_flags")
                elif name == "source_symbol":
                    columns.append("COALESCE(NULLIF(source_symbol,''),symbol) AS source_symbol" if name in existing
                                   else "symbol AS source_symbol")
                else:
                    columns.append(name if name in existing else f"NULL AS {name}")
            rows = [dict(row) for row in connection.execute(f"SELECT {','.join(columns)} FROM quotes {clause}", values).fetchall()]
        frame = pd.DataFrame(rows, columns=QUOTE_COLUMNS)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
        frame["volume_start"] = pd.to_datetime(frame["volume_start"], unit="s", utc=True)
        return frame.set_index("timestamp")

    def pinned_contract(self, symbol: str, trading_date: str) -> dict | None:
        """Preview the same fixed mapping as a collector, without creating a database."""
        if not self.db_path.is_file():
            return None
        with self.connect() as connection:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                        "AND name='main_contract_resolutions'").fetchone()
            if not exists:
                return None
            row = connection.execute("SELECT source_symbol,mapping_date,trading_date "
                                     "FROM main_contract_resolutions WHERE symbol=? AND trading_date=?",
                                     (symbol, trading_date)).fetchone()
            return dict(row) if row is not None else None

    def read_since(self, sequence: int = 0, *, symbols: list[str] | None = None, limit: int = 10000) -> pd.DataFrame:
        if type(sequence) is not int or sequence < 0 or type(limit) is not int or not 1 <= limit <= 1000000:
            raise ValueError("sequence 必须是非负整数，limit 必须在 1 到 1000000 之间")
        where, args = "sequence>?", [sequence]
        if symbols is not None:
            where += " AND symbol IN (" + ",".join("?" for _ in symbols) + ")"
            args.extend(symbols)
        return self._frame(f"WHERE {where} ORDER BY sequence LIMIT ?", [*args, limit])

    def latest(self, symbols: list[str] | None = None) -> pd.DataFrame:
        where, args = "", []
        if symbols is not None:
            where = " WHERE symbol IN (" + ",".join("?" for _ in symbols) + ")"
            args = symbols
        return self._frame("WHERE sequence IN "
                           f"(SELECT MAX(sequence) FROM quotes{where} GROUP BY symbol) ORDER BY symbol", args)

    def history(self, symbol: str, day: str) -> pd.DataFrame:
        date.fromisoformat(day)
        return self._frame("WHERE symbol=? AND capture_date=? ORDER BY sequence", (symbol, day))

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
        tables = []
        for path in files:
            table = pq.ParquetFile(path).read()
            # Old immutable fragments predate identity columns. Normalize only
            # in memory; never replace a file that another reader may have open.
            arrays = []
            for field in SCHEMA:
                if field.name == "volume" and "volume_interval_seconds" not in table.column_names:
                    arrays.append(pa.nulls(len(table), type=field.type))
                elif field.name == "quality_flags" and "volume_interval_seconds" not in table.column_names:
                    arrays.append(pc.bit_wise_or(table[field.name], pa.scalar(16, type=field.type)))
                elif field.name == "source_symbol":
                    source = table[field.name] if field.name in table.column_names else table["symbol"]
                    arrays.append(pc.if_else(pc.or_(pc.is_null(source), pc.fill_null(pc.equal(source, ""), False)),
                                             table["symbol"], source))
                else:
                    arrays.append(table[field.name] if field.name in table.column_names
                                  else pa.nulls(len(table), type=field.type))
            tables.append(pa.Table.from_arrays(arrays, schema=SCHEMA))
        frame = pa.concat_tables(tables).to_pandas()
        return frame.sort_values("sequence").set_index("timestamp")


def write_strategy_frame(frame: pd.DataFrame, strategy: str, root: str | Path = DEFAULT_OUTPUT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", strategy):
        raise ValueError("策略目录名仅支持字母、数字、下划线和连字符")
    directory = Path(root).expanduser().resolve() / "strategy_results" / strategy
    return publish_parquet(pa.Table.from_pandas(frame), directory, uuid.uuid4().hex)
