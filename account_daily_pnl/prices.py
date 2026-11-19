"""Resolve daily marks from BCT first and cache exact-date Wind fallbacks."""

from collections import defaultdict
from pathlib import Path
import shutil

from openpyxl import load_workbook

from index_futures_basis.wind import WindProvider
from dashboard.marketdata.overview_windpy import executable as wind_executable

from .ledger import money
from .sources import read_source, write_book


CACHE_COLUMNS = ("tradingDate", "instrumentId", "price", "field", "source")


def cache_read(path, day):
    if not path.is_file():
        return {}
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        iterator = workbook.active.values
        if next(iterator) != CACHE_COLUMNS:
            raise ValueError(f"{path} 的 Wind 缓存表头不一致。")
        result = {}
        for stamp, code, value, field, source in iterator:
            if stamp != day or not code or code in result or source != "Wind" or money(value) <= 0:
                raise ValueError(f"{path} 中的 Wind 缓存记录无效。")
            result[code] = (money(value), field)
        return result
    finally:
        workbook.close()


def field_for(code, config):
    return config.get("wind_futures_field", "settle") if code.endswith(".CFE") else "close"


def resolve(exposure, root, config, *, no_wind=False, provider_class=WindProvider):
    required = defaultdict(set)
    for day, code in exposure:
        required[day].add(code)
    marks = {}
    source_errors = []
    caches = {}
    missing = defaultdict(set)
    for day, codes in sorted(required.items()):
        snapshot_file = root / "snapshots" / f"{day}.xlsx"
        if snapshot_file.is_file():
            for row in read_source(snapshot_file, "snapshot", day):
                code = row["instrumentId"].upper()
                if code not in codes or row["currencyCode"] != "CNY":
                    continue
                try:
                    price = money(row["instrumentQuote"])
                except ValueError:
                    continue
                if price > 0:
                    marks[day, code] = price, "BCT:instrumentQuote"
        cache = cache_read(root / "wind" / f"{day}.xlsx", day)
        caches[day] = cache
        for code in codes:
            if (day, code) in marks:
                continue
            field = field_for(code, config)
            if code in cache and cache[code][1] == field:
                marks[day, code] = cache[code][0], f"Wind:{field}"
            else:
                missing[code].add(day)
    if not missing:
        return marks, source_errors
    if no_wind:
        return marks, ["本次使用 --no-wind，缺价保留待补。"]

    executable = wind_executable(config, root)
    resolved = shutil.which(executable)
    if not resolved and Path(executable).is_file():
        resolved = str(Path(executable).resolve())
    if not resolved:
        return marks, ["Wind Python 路径不存在，缺价保留待补。"]

    print(f"Wind 待补 {len(missing)} 个标的、{sum(map(len, missing.values()))} 个标的交易日。", flush=True)
    provider = provider_class({"wind_python": resolved, "wind_timeout_seconds": float(config.get("wind_timeout_seconds", 30))})
    changed = set()
    try:
        for code, days in sorted(missing.items()):
            field = field_for(code, config)
            try:
                history = provider.series(code, [field], min(days), max(days))
            except (ConnectionError, TimeoutError) as exc:
                source_errors.append(f"Wind 连接失败：{exc}")
                break
            except (RuntimeError, ValueError) as exc:
                source_errors.append(f"Wind {code} {min(days)} 至 {max(days)}：{exc}")
                continue
            for day in sorted(days):
                value = history.get(day, {}).get(field)
                try:
                    price = money(value)
                except ValueError:
                    continue
                if price > 0:
                    marks[day, code] = (price, f"Wind:{field}")
                    caches[day][code] = price, field
                    changed.add(day)
    finally:
        provider.close()
        for day in sorted(changed):
            rows = ((day, code, price, field, "Wind") for code, (price, field) in sorted(caches[day].items()))
            write_book(root / "wind" / f"{day}.xlsx", [("Wind日线", CACHE_COLUMNS, rows)])
    return marks, source_errors
