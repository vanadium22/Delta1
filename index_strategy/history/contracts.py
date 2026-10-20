"""Historical identities use the local pipeline's dated main/next matrices."""
from bisect import bisect_left
from pathlib import Path
import re

from ..instant_dld.contracts import DEFAULT_CALENDAR_FILE, DEFAULT_MAPPING_FILE, dates, read_frame


def source_query_identity(source, actual, trading_day):
    """Separate the mapped contract label from the source's literal query code.

    CSMAR CZCE intraday tables use YYMM, while local/Wind contracts can use YMM.
    Infer the decade from the requested trading date, following the established
    observation-date nearest-year rule. An exact five-year tie is ambiguous and
    requires an explicit four-digit contract; never use the machine's year.
    Daily Wind labels and non-CZCE routes are preserved.
    """
    symbol = actual.strip().upper()
    code, exchange = symbol.rsplit(".", 1)
    rule = "source literal code; mapped contract identity preserved"
    match = re.fullmatch(r"([A-Z]+)(\d)(\d{2})", code)
    if (source["frequency"] != "1d" and source.get("market") == "czce"
            and source.get("db", "").endswith("_csmar") and exchange == "CZC" and match):
        root, year_digit, month = match.groups()
        if not 1 <= int(month) <= 12:
            raise ValueError(f"郑商所交割月份无效：{actual}")
        candidates = [year for year in range(trading_day.year - 5, trading_day.year + 6)
                      if year % 10 == int(year_digit)]
        distance = min(abs(year - trading_day.year) for year in candidates)
        nearest = [year for year in candidates if abs(year - trading_day.year) == distance]
        if len(nearest) != 1:
            raise ValueError(f"郑商所三位年份有十年歧义：{actual} at {trading_day}；请明确四位YYMM合约")
        code = f"{root}{nearest[0] % 100:02d}{month}"
        symbol = f"{code}.{exchange}"
        rule = "CSMAR CZCE YMM->YYMM; nearest year to requested trading date; reject decade ties"
    return {"source_query_symbol": symbol,
            "source_query_code": symbol if source["frequency"] == "1d" else code,
            "source_query_reference_date": str(trading_day), "source_query_rule": rule}


class HistoricalResolver:
    def __init__(self, mapping_file=DEFAULT_MAPPING_FILE, calendar_file=DEFAULT_CALENDAR_FILE,
                 next_dir=None, main_rule="same_day", next_source="local"):
        self.mapping_file = Path(mapping_file)
        self.calendar_file = Path(calendar_file)
        self.next_dir = Path(next_dir) if next_dir else self.mapping_file.parent.parent / "next"
        self.main_rule, self.next_source = main_rule, next_source
        self._frames = {}
        frame = read_frame(self.calendar_file)
        self.calendar = sorted(dates(frame["Date"] if "Date" in frame else frame.index, "交易日历"))

    def trading_days(self, start, end):
        if start < self.calendar[0] or end > self.calendar[-1]:
            raise ValueError(f"日期超出交易日历覆盖范围：{self.calendar[0]}～{self.calendar[-1]}")
        return [d for d in self.calendar if start <= d <= end]

    def _read(self, path):
        if path not in self._frames:
            frame = read_frame(path).copy()
            frame.index = dates(frame.index, "历史映射索引")
            frame.columns = [str(c).strip().upper() for c in frame.columns]
            if frame.columns.has_duplicates:
                raise ValueError(f"映射有重复品种列：{path}")
            self._frames[path] = frame
        return self._frames[path]

    def resolve(self, symbol, day, client=None):
        match = re.fullmatch(r"([A-Z]+)(\d{0,4})\.(SHF|DCE|CZC|INE|CFE|GFE)", symbol)
        if not match or len(match[2]) >= 3:
            return {"source_symbol": symbol, "mapping_date": None, "mapping_rule": "具体代码"}
        root, rank, exchange = match.groups()
        map_day = day
        if rank and self.next_source == "wind":
            return client.continuous(symbol, day)
        if rank:
            path = self.next_dir / f"+{int(rank)}" / "month_contract_code.pkl"
            rule = f"Z盘当日 next/+{int(rank)} 映射"
        else:
            path = self.mapping_file
            rule = "Z盘当日历史 main 映射"
            if self.main_rule == "previous_day":
                index = bisect_left(self.calendar, day)
                if index == 0:
                    raise ValueError(f"{day} 没有可用的前一交易日")
                map_day = self.calendar[index - 1]
                rule = "Z盘前一交易日 main 映射（交易口径）"
        frame = self._read(path)
        column = f"{root}.{exchange}"
        if map_day not in frame.index or column not in frame:
            raise ValueError(f"{symbol} 缺少 {map_day} 的映射：{path}")
        actual = frame.at[map_day, column]
        if not isinstance(actual, str) or not re.fullmatch(
                re.escape(root) + r"\d{3,4}\." + re.escape(exchange), actual.strip().upper()):
            raise ValueError(f"{symbol} 在 {map_day} 的映射为空或无效，未猜测合约")
        return {"source_symbol": actual.strip().upper(), "mapping_date": str(map_day),
                "mapping_rule": rule, "mapping_file": str(path), "trading_date": str(day)}
