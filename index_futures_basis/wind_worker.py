"""Standard-library-only JSON-lines worker; Wind stdout never enters the protocol."""
from __future__ import annotations

import contextlib
from datetime import date, datetime
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


def calendar(w, start, end):
    options = "TradingCalendar=CFFEX"
    context = f"Wind TDAYS({start!r}, {end!r}, {options!r})"
    result = check(w.tdays(start, end, options), context)
    data = getattr(result, "Data", None)
    columns = len(data) if isinstance(data, (list, tuple)) else None
    lengths = [len(c) if isinstance(c, (list, tuple)) else type(c).__name__
               for c in data[:4]] if columns is not None else []

    def reject(reason):
        raise ValueError(f"{context}；{reason}；DataColumns={columns}；DataLengths={lengths!r}；"
                         "本批交易日历未写入，请确认Wind终端在线及CFFEX日历权限后重试。")

    # A missing column is an incomplete response, not proof that the entire
    # requested interval was closed. An explicit [[]] is a valid empty calendar.
    if columns != 1 or not isinstance(data[0], (list, tuple)):
        reject("交易日历返回为空或结构不完整")
    try:
        days = [iso(day) for day in data[0]]
    except (ValueError, TypeError, OverflowError):
        reject("交易日历包含无效日期")
    if len(set(days)) != len(days) or any(not start <= day <= end for day in days):
        reject("交易日历日期重复或超出请求范围")
    return days


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
