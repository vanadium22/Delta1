"""Plan gaps by exchange date, concrete instrument and field, then persist batches."""
from __future__ import annotations

from collections import defaultdict
import math
import re
import threading

import pandas as pd

from .analytics import ROOTS
from .config import timestamp
from .wind_worker import CALENDAR_OPTIONS, CALENDAR_VALIDATION


class Cancelled(Exception):
    pass


def segments(missing, calendar, size=45):
    """Merge only consecutive missing trading dates, without re-requesting valid rows."""
    wanted = set(missing)
    group = []
    for day in calendar:
        if day in wanted:
            group.append(day)
            if len(group) == size:
                yield group
                group = []
        elif group:
            yield group
            group = []
    if group:
        yield group


def valid_value(value, field):
    try:
        number = float(value)
        return not isinstance(value, bool) and math.isfinite(number) and (
            number > 0 if field == "close" else number >= 0 and number.is_integer())
    except (TypeError, ValueError):
        return False


def synchronize(store, provider, start, end, progress=lambda message: None, cancel=None, repair=None):
    cancel = cancel or threading.Event()
    start, end = str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date())
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    repair = (str(pd.Timestamp(repair[0]).date()), str(pd.Timestamp(repair[1]).date())) if repair else None
    if repair and not start <= repair[0] <= repair[1] <= end:
        raise ValueError("重取范围必须在同步窗口内")
    forced = lambda day: bool(repair and repair[0] <= day <= repair[1])
    requests, errors = 0, []

    def call(method, *args):
        nonlocal requests
        if cancel.is_set():
            raise Cancelled("已取消；成功写入的批次保留，下次只补剩余缺口")
        requests += 1
        return getattr(provider, method)(*args)

    with store.writer_lock():
        run = store.start_run(end)
        try:
            all_dates = [str(d.date()) for d in pd.date_range(start, end)]
            cached = store.calendar(start, end)
            verification = store.meta("calendar_verification", {})
            verified = (set(verification.get("dates", []))
                        if verification.get("options") == CALENDAR_OPTIONS
                        and verification.get("validation_version") == CALENDAR_VALIDATION else set())
            # Recheck older parameter choices / unverified calendar rows once. Quotes are still
            # requested strictly by missing instrument/date/field after this step.
            for batch in segments([d for d in all_dates if d not in cached or d not in verified], all_dates, 400):
                progress(f"检查交易日历 {batch[0]} 至 {batch[-1]}")
                opened = call("calendar", batch[0], batch[-1])
                if len(opened) != len(set(opened)) or any(d not in batch for d in opened):
                    raise ValueError("Wind 交易日历日期重复或超出请求范围")
                if len(batch) >= 60 and not opened:
                    raise ValueError("Wind 连续两个月未返回任何交易日；本批次不写入，请检查日历权限后重试")
                store.save_calendar(batch[0], batch[-1], set(opened))
                verified.update(batch)
                store.set_meta("calendar_verification", {"options": CALENDAR_OPTIONS,
                               "validation_version": CALENDAR_VALIDATION, "dates": sorted(verified)})
            calendar = [d for d, opened in store.calendar(start, end).items() if opened]
            mapping = store.mappings(start, end)
            for root in ROOTS:
                for slot in range(1, 5):
                    alias = f"{root}0{slot-1}.CFE"
                    missing = [d for d in calendar if (d, root, slot) not in mapping or forced(d)]
                    for batch in segments(missing, calendar):
                        progress(f"补齐连续映射 {alias} · {batch[0]} 至 {batch[-1]}")
                        try:
                            response = call("mapping", alias, batch[0], batch[-1])
                            rows = []
                            for day in batch:
                                code = str(response.get(day, "")).strip().upper()
                                if re.fullmatch(root + r"\d{4}", code):
                                    code += ".CFE"
                                if re.fullmatch(root + r"\d{4}\.CFE", code):
                                    rows.append((day, root, slot, code))
                                else:
                                    errors.append(f"{day} {alias} 映射缺失")
                            store.save_rows("mapping", rows)
                        except (Cancelled, ConnectionError, TimeoutError):
                            raise
                        except Exception as exc:
                            errors.append(f"{alias}: {exc}")
            mapping = store.mappings(start, end)
            expiry = store.expiries()
            needed_codes = sorted({code for key, code in mapping.items()
                                   if code not in expiry or expiry[code] < key[0] or forced(key[0])})
            for offset in range(0, len(needed_codes), 50):
                codes = needed_codes[offset:offset+50]
                progress(f"补齐 {len(codes)} 个实际合约到期日")
                try:
                    result = call("expiries", codes)
                    rows = []
                    for code in codes:
                        try:
                            day = str(pd.Timestamp(result[code]).date())
                            if day == "NaT" or any(date > day for (date, _, _), c in mapping.items() if c == code):
                                raise ValueError("到期日早于实际交易日")
                            rows.append((code, day))
                        except (KeyError, ValueError, TypeError):
                            errors.append(f"{code} 到期日无效")
                    store.save_rows("contracts", rows)
                except (Cancelled, ConnectionError, TimeoutError):
                    raise
                except Exception as exc:
                    errors.append(f"到期日: {exc}")
            quotes = store.quotes(start, end)
            required = defaultdict(lambda: defaultdict(set))
            for (day, root, _slot), code in mapping.items():
                for field in ("close", "oi"):
                    if (code, day, field) not in quotes or forced(day):
                        required[code][day].add(field)
            for root in ROOTS:
                for day in calendar:
                    if (ROOTS[root], day, "close") not in quotes or forced(day):
                        required[ROOTS[root]][day].add("close")
            for code, dates in sorted(required.items()):
                by_fields = defaultdict(list)
                for day, fields in dates.items():
                    by_fields[tuple(sorted(fields))].append(day)
                for fields, missing in by_fields.items():
                    for batch in segments(missing, calendar):
                        progress(f"补齐行情 {code} {','.join(fields)} · {batch[0]} 至 {batch[-1]}")
                        try:
                            result = call("series", code, fields, batch[0], batch[-1])
                            rows = []
                            for day in batch:
                                for field in fields:
                                    value = result.get(day, {}).get(field)
                                    if valid_value(value, field):
                                        rows.append((code, day, field, float(value)))
                                    else:
                                        errors.append(f"{day} {code}.{field} 缺失或无效")
                            store.save_rows("quotes", rows)
                        except (Cancelled, ConnectionError, TimeoutError):
                            raise
                        except Exception as exc:
                            errors.append(f"{code}: {exc}")
            coverage = store.coverage(start, end)
            if calendar and not coverage["missing_fields"]:
                try:
                    store.panel(start, end)
                except ValueError as exc:
                    errors.append(f"行情结构校验失败，请按提示日期重取：{exc}")
            state = "complete" if not errors and not coverage["missing_fields"] else "partial"
            if not calendar:
                state = "empty"
            message = ("所选区间无交易日（周末或节假日），检查完成，无需补齐行情" if not calendar else
                       "数据齐全，未重复下载行情" if requests == 0 else
                       f"本次请求{requests}批，剩余{coverage['missing_fields']}个缺失字段")
            if errors:
                message += "；" + "；".join(errors[:8])
            store.set_meta("source", {"kind": "wind", "label": "Wind 日线", "checked_at": timestamp()})
            store.set_meta("requested_window", [start, end])
            store.finish_run(run, state, requests, message)
            return {"state": state, "requests": requests, "message": message, "errors": errors, **coverage}
        except Exception as exc:
            state = "cancelled" if isinstance(exc, Cancelled) else "failed"
            store.finish_run(run, state, requests, str(exc))
            raise
