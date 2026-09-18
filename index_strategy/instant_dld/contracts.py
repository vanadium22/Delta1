"""Resolve continuous futures symbols using the previous trading day's main contract."""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from typing import Callable

import pandas as pd

from .quotes import CHINA

DEFAULT_MAPPING_FILE = Path("Z:/Project_data/future_investment/data/raw/day/main/month_contract_code.pkl")
DEFAULT_CALENDAR_FILE = Path("Z:/Project_data/future_investment/data/normalization/Date.pkl")
MAIN_SYMBOL = re.compile(r"([A-Z]+)\.(SHF|DCE|CZC|INE|CFE|GFE)\Z")


class ContractMappingError(ValueError):
    """No verified contract is available for the required trading day."""


def read_frame(path: Path) -> pd.DataFrame:
    # Pickle is supported for the user's trusted local daily-data pipeline only.
    try:
        if path.suffix.lower() in {".pkl", ".pickle"}:
            frame = pd.read_pickle(path)
        elif path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path)
        else:
            raise ValueError("仅支持本地可信的 .pkl / .pickle / .parquet 文件")
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("需要非空 pandas DataFrame")
        return frame
    except Exception as exc:
        raise ContractMappingError(f"无法读取 {path}：{exc}") from exc


def dates(values, label: str) -> list[date]:
    result = []
    for value in values:
        # Never interpret delivery months or a RangeIndex as nanosecond dates.
        if isinstance(value, datetime):
            value = value.date()
        elif isinstance(value, str):
            try:
                value = date.fromisoformat(value)
            except ValueError:
                raise ContractMappingError(f"{label} 必须使用 YYYY-MM-DD 日期") from None
        if not isinstance(value, date) or pd.isna(value):
            raise ContractMappingError(f"{label} 必须是逐日日期，不能是交割月份或整数索引")
        result.append(value)
    if len(result) != len(set(result)):
        raise ContractMappingError(f"{label} 含重复日期")
    return result


class MainContractResolver:
    def __init__(self, mapping_file: Path = DEFAULT_MAPPING_FILE, calendar_file: Path = DEFAULT_CALENDAR_FILE,
                 *, now: Callable[[], datetime] | None = None, store=None):
        self.mapping_file, self.calendar_file = Path(mapping_file), Path(calendar_file)
        self.now = now or (lambda: datetime.now(CHINA))
        self.store = store
        self._calendar_stamp = self._mapping_stamp = None
        self._calendar: list[date] = []
        self._mapping = None
        self._pinned: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _stamp(path):
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError as exc:
            raise ContractMappingError(f"文件不可用 {path}：{exc}") from exc

    def _load_calendar(self):
        stamp = self._stamp(self.calendar_file)
        if stamp != self._calendar_stamp:
            frame = read_frame(self.calendar_file)
            calendar = sorted(dates(frame["Date"] if "Date" in frame else frame.index, "交易日历"))
            if len(calendar) < 2 or any(day.weekday() >= 5 for day in calendar):
                raise ContractMappingError("交易日历至少需要两个交易日，且不能包含周末")
            self._calendar, self._calendar_stamp = calendar, stamp

    def _load_mapping(self):
        stamp = self._stamp(self.mapping_file)
        if stamp != self._mapping_stamp:
            frame = read_frame(self.mapping_file).copy()
            frame.index = dates(frame.index, "主力映射索引")
            frame.columns = [str(column).strip().upper() for column in frame.columns]
            if frame.columns.has_duplicates:
                raise ContractMappingError("主力映射包含重复标的列")
            self._mapping, self._mapping_stamp = frame, stamp

    def trading_dates(self, symbol: str, at: datetime) -> tuple[str, str]:
        self._load_calendar()
        if at.tzinfo is None:
            raise ContractMappingError("解析时间必须包含时区")
        local = at.astimezone(CHINA)
        target = local.date()
        # A mapping boundary for the coming commodity night session, not a market-open test.
        # CFFEX has no night session. On weekends, retain the next trading day's mapping.
        if symbol.rsplit(".", 1)[-1] != "CFE" and local.hour >= 20:
            target += timedelta(days=1)
        index = bisect_left(self._calendar, target)
        if index == 0 or index >= len(self._calendar):
            raise ContractMappingError(
                f"交易日历覆盖不足（{self._calendar[0]} 至 {self._calendar[-1]}），请更新交易日历")
        return self._calendar[index].isoformat(), self._calendar[index - 1].isoformat()

    def resolve(self, symbol: str, at: datetime | None = None) -> dict:
        matched = MAIN_SYMBOL.fullmatch(symbol)
        if matched is None:
            return {"source_symbol": symbol, "mapping_date": None, "trading_date": None}
        trade_day, map_day = self.trading_dates(symbol, at or self.now())
        key = symbol, trade_day
        if key in self._pinned:
            return dict(self._pinned[key])
        persisted = getattr(self.store, "pinned_contract", lambda *_: None)(symbol, trade_day)
        if persisted is not None:
            self._pinned[key] = persisted
            return dict(persisted)
        self._load_mapping()
        day = date.fromisoformat(map_day)
        if symbol not in self._mapping.columns or day not in self._mapping.index:
            raise ContractMappingError(f"{symbol} 缺少前一交易日 {map_day} 的主力映射（交易日 {trade_day}），等待日频更新")
        actual = self._mapping.at[day, symbol]
        if not isinstance(actual, str) or not re.fullmatch(
                re.escape(matched[1]) + r"\d{3,4}\." + re.escape(matched[2]), actual.strip().upper()):
            raise ContractMappingError(f"{symbol} 在 {map_day} 的主力合约为空或代码不匹配，等待日频更新")
        value = {"source_symbol": actual.strip().upper(), "mapping_date": map_day, "trading_date": trade_day}
        value = getattr(self.store, "pin_contract", lambda _, item: item)(symbol, value)
        # Keep only the current trading day's in-memory pins for each symbol.
        self._pinned = {old_key: item for old_key, item in self._pinned.items() if old_key[0] != symbol}
        self._pinned[key] = value
        return dict(value)

    def resolve_many(self, symbols: list[str], at: datetime | None = None) -> tuple[dict, dict]:
        at = at or self.now()
        resolved, errors = {}, {}
        for symbol in symbols:
            try:
                resolved[symbol] = self.resolve(symbol, at)
            except ContractMappingError as exc:
                errors[symbol] = str(exc)
        return resolved, errors
