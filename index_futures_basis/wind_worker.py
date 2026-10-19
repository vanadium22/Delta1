"""Standard-library-only JSON-lines worker; Wind stdout never enters the protocol."""
from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta
import json
import math
import re
import sys


def check(result, label):
    if result.ErrorCode:
        raise RuntimeError(f"{label}: Wind ErrorCode={result.ErrorCode}，请核对终端及字段权限")
    return result


def iso(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    value = str(value).strip()
    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    return datetime.fromisoformat(value[:10]).date().isoformat()


def series(w, code, fields, start, end, options="Period=D;Days=Trading;Fill=Blank"):
    result = check(w.wsd(code, ",".join(fields), start, end, options), f"WSD {code}")
    actual = [str(f).lower() for f in result.Fields]
    if set(actual) != set(fields) or len(result.Data) != len(fields):
        raise ValueError("Wind 返回字段不匹配")
    days = [iso(t) for t in result.Times]
    if len(set(days)) != len(days) or any(len(values) != len(days) for values in result.Data):
        raise ValueError("Wind 日期重复或返回长度不匹配")
    return {day: {field: result.Data[actual.index(field)][i] for field in fields} for i, day in enumerate(days)}


CALENDAR_OPTIONS = "TradingCalendar=CFFE;Days=Trading"
CALENDAR_VALIDATION = 2
CALENDAR_PROFILES = (
    (CALENDAR_OPTIONS, "iso"),
    (CALENDAR_OPTIONS, "compact"),
    ("TradingCalendar=CFFE", "compact"),
    ("TradingCalendar=CFFEX;Days=Trading", "compact"),
    ("TradingCalendar=CFFEX", "compact"),
)


def calendar_dates(result, context, start, end):
    data = getattr(result, "Data", None)
    times = getattr(result, "Times", [])
    columns = len(data) if isinstance(data, (list, tuple)) else None
    lengths = [len(c) if isinstance(c, (list, tuple)) else type(c).__name__
               for c in data[:4]] if columns is not None else []

    def reject(reason):
        raise ValueError(f"{context}；{reason}；DataColumns={columns}；DataLengths={lengths!r}；"
                         "本批交易日历未写入，请确认Wind终端在线及CFFE日历权限后重试。")

    # WindData.set can keep Data=[] when its dimensions are zero. TDAYS also
    # exposes the returned calendar dates in Times; preserve those when present.
    if columns not in (0, 1) or (columns == 1 and not isinstance(data[0], (list, tuple))):
        reject("交易日历返回为空或结构不完整")
    if not isinstance(times, (list, tuple)):
        reject("交易日历Times结构无效")
    try:
        days = [iso(day) for day in data[0]] if columns else []
        time_days = [iso(day) for day in times]
    except (ValueError, TypeError, OverflowError):
        reject("交易日历包含无效日期")
    for values in (days, time_days):
        if len(set(values)) != len(values) or any(not start <= day <= end for day in values):
            reject("交易日历日期重复或超出请求范围")
    if days and time_days and sorted(days) != sorted(time_days):
        reject("交易日历Data与Times不一致")
    return sorted(days or time_days)


def calendar_query(w, start, end, options, style, trace, role="requested"):
    first_arg, last_arg = (start.replace("-", ""), end.replace("-", "")) if style == "compact" else (start, end)
    context = f"Wind TDAYS({start!r}, {end!r}, {options!r}, date_format={style})"
    evidence = {"start": start, "end": end, "options": options, "date_format": style,
                "sent_start": first_arg, "sent_end": last_arg, "role": role}
    if trace is not None:
        trace.append(evidence)
    result = w.tdays(first_arg, last_arg, options)
    evidence["tdays"] = result
    result = check(result, context)
    days = calendar_dates(result, context, start, end)

    count_context = f"Wind TDAYSCOUNT({start!r}, {end!r}, {options!r}, date_format={style})"
    counted = w.tdayscount(first_arg, last_arg, options)
    evidence["tdayscount"] = counted
    counted = check(counted, count_context)
    data = getattr(counted, "Data", None)
    count = (data[0][0] if isinstance(data, (list, tuple)) and len(data) == 1
             and isinstance(data[0], (list, tuple)) and len(data[0]) == 1 else None)
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if (isinstance(count, bool) or not isinstance(count, (int, float)) or not math.isfinite(count)
            or count < 0 or not float(count).is_integer() or count > span):
        raise ValueError(f"{count_context}；交易日数量无效，不能确认空结果是否休市；本批交易日历未写入。")
    evidence["count"] = int(count)
    if days:
        if len(days) != int(count):
            raise ValueError(f"{context}；日期数量{len(days)}与TDAYSCOUNT={int(count)}不一致；本批交易日历未写入。")
        return days, evidence
    if count == 0:
        return [], evidence

    # Count says the interval is open: retry once with surrounding dates, then
    # filter back to the original request. Never cache an unconfirmed closure.
    first = (date.fromisoformat(start) - timedelta(days=14)).isoformat()
    last = (date.fromisoformat(end) + timedelta(days=14)).isoformat()
    retry_context = f"Wind TDAYS({first!r}, {last!r}, {options!r}, date_format={style})"
    retry_first, retry_last = (first.replace("-", ""), last.replace("-", "")) if style == "compact" else (first, last)
    retry = w.tdays(retry_first, retry_last, options)
    if trace is not None:
        trace.append({"start": first, "end": last, "options": options, "date_format": style,
                      "sent_start": retry_first, "sent_end": retry_last, "role": "expanded", "tdays": retry})
    retry = check(retry, retry_context)
    surrounding = calendar_dates(retry, retry_context, first, last)
    days = [day for day in surrounding if start <= day <= end]
    if len(days) != int(count):
        raise ValueError(f"{context}；TDAYSCOUNT确认{int(count)}个交易日，扩窗重试仅返回{len(days)}个；"
                         "日历返回不一致，本批交易日历未写入，请稍后重试。")
    return days, evidence


def calendar(w, start, end, trace=None):
    """A zero count is a closure only after the same calendar proves healthy."""
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    for index, (options, style) in enumerate(CALENDAR_PROFILES):
        try:
            days, evidence = calendar_query(w, start, end, options, style, trace)
            if days:
                evidence["selected"] = True
                return days
            if span < 60:
                first = (date.fromisoformat(end) - timedelta(days=89)).isoformat()
                control, _ = calendar_query(w, first, end, options, style, trace, role="health_control")
                if control:
                    if any(start <= day <= end for day in control):
                        raise ValueError("Wind 请求区间返回零，但同日历扩窗包含该区间交易日；"
                                         "日历返回不一致，本批交易日历未写入。")
                    evidence["selected"] = True
                    return []
        except (RuntimeError, ValueError, TypeError) as exc:
            if trace:
                trace[-1]["error"] = f"{type(exc).__name__}: {exc}"[:2000]
            if index == 0:
                raise
        # Both APIs can silently return zero for an unusable calendar/options.
        # Only try explicit CFFE/CFFEX profiles; never substitute an equity calendar.
    raise ValueError(f"Wind TDAYS/TDAYSCOUNT 在 {start} 至 {end} 及健康检查窗口均未提供可靠交易日；"
                     "已核对ISO/紧凑日期及CFFE/CFFEX参数，不能据此认定周末或节假日。"
                     "交易日历服务或参数异常，本批交易日历未写入；请运行Wind诊断并复制完整结果。")


def perform(w, request):
    op = request["operation"]
    if op == "calendar":
        return calendar(w, request["start"], request["end"])
    if op == "series":
        return series(w, request["code"], request["fields"], request["start"], request["end"])
    if op == "expiries":
        field = request["field"].lower()
        result = check(w.wss(",".join(request["codes"]), field, ""), "到期日")
        if [str(f).lower() for f in result.Fields] != [field] or len(result.Data) != 1 or len(result.Data[0]) != len(result.Codes):
            raise ValueError("到期日字段或长度不匹配")
        if len(set(result.Codes)) != len(result.Codes):
            raise ValueError("到期日返回重复合约")
        return {str(code).upper(): iso(value) for code, value in zip(result.Codes, result.Data[0]) if value is not None}
    raise ValueError("未知 Wind 操作")


def json_safe(value):
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (date, datetime)):
        return iso(value)
    return value


def main(performer=perform):
    w = None
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                with contextlib.redirect_stdout(sys.stderr):
                    if w is None:
                        from WindPy import w as wind
                        check(wind.start(waitTime=15, showmenu=False), "连接 Wind")
                        w = wind
                    data = performer(w, request)
                response = {"data": json_safe(data)}
            except Exception as exc:
                response = {"error": f"{type(exc).__name__}: {exc}", "fatal": w is None}
            print(json.dumps(response, ensure_ascii=True, allow_nan=False), flush=True)
    finally:
        if w is not None:
            with contextlib.redirect_stdout(sys.stderr):
                w.stop()


if __name__ == "__main__":
    main()
