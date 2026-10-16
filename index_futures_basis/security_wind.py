"""Standard-library Wind adapter. All intraday timestamps retain their time zone."""
from datetime import datetime, timedelta, timezone
import math

SHANGHAI = timezone(timedelta(hours=8))
FIELDS = {"close": "rt_last", "open": "rt_open", "high": "rt_high", "low": "rt_low", "volume": "rt_vol", "amt": "rt_amt"}


def checked(result, context="Wind"):
    if result.ErrorCode:
        # Wind puts its explanation in Data; don't discard it behind a generic hint.
        detail = repr(getattr(result, "Data", []))[:400]
        raise RuntimeError(f"{context}；Wind ErrorCode={result.ErrorCode}；返回说明={detail}；"
                           "请核对终端登录、字段及分钟历史权限")
    return result


def response_shape(result):
    """Bounded metadata only: enough to diagnose a schema failure without dumping quotes."""
    codes, fields = list(result.Codes), list(result.Fields)
    lengths = [len(c) if isinstance(c, (list, tuple)) else "非列数组" for c in result.Data[:12]]
    return (f"Codes={codes[:4]!r} (共{len(codes)}个)；Fields={fields[:12]!r}；"
            f"TimesCount={len(result.Times)}；DataLengths={lengths!r}")


def quote_rows(result, code, fields, requested, api, context):
    def reject(reason):
        raise ValueError(f"{context}；{reason}；{response_shape(result)}")

    raw_fields = list(result.Fields)
    actual = [str(f).strip().lower() for f in raw_fields]
    # WSI can return the amount column under its long name. This alias belongs
    # only to minute data; WSD/WSQ retain their own field contracts.
    if api == "WSI":
        actual = ["amt" if f == "amount" else f for f in actual]
    table = api == "WSI" and {"time", "windcode"}.issubset(actual)
    expected = set(requested) | ({"time", "windcode"} if table else set())
    if len(set(actual)) != len(actual) or set(actual) != expected:
        reject("Wind 返回字段不匹配（缺失、多余或重名字段）")
    if len(result.Data) != len(actual) or any(not isinstance(c, (list, tuple)) for c in result.Data):
        reject("Wind 返回数据列数或长度不匹配")
    columns = dict(zip(actual, result.Data))
    source_times = columns["time"] if table else result.Times
    count = 1 if api == "WSQ" else len(source_times)
    if any(len(column) != count for column in result.Data):
        reject("Wind 返回数据长度不匹配")
    if table:
        # Tabular WSI responses may use Codes as row numbers. Identity is in
        # the explicit windcode column: validate EVERY row, never silently filter.
        wrong = [str(c) for c in columns["windcode"] if str(c).strip().upper() != code]
        if wrong:
            reject(f"Wind 返回证券代码不匹配：windcode={wrong[:4]!r}，预期={code}")
    elif [str(c).strip().upper() for c in result.Codes] != [code]:
        reject(f"Wind 返回证券代码不匹配，预期={code}")
    try:
        times = [stamp(t, api == "WSD") for t in source_times]
    except (ValueError, TypeError, AttributeError):
        reject("Wind 返回时间戳格式不匹配")
    if len(set(times)) != len(times):
        reject("Wind 返回重复时间戳")
    if api == "WSQ":
        # Provider-returned time is never claimed to be last-trade time.
        times = [times[0] if len(times) == 1 else None]
    rows = []
    for i, time in enumerate(times):
        row = {"time": time}
        for field, raw in zip(fields, requested):
            value = columns[raw][i]
            row[field] = value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        rows.append(row)
    return rows, {field: raw_fields[actual.index(raw)] for field, raw in zip(fields, requested)}, "table" if table else "series"


def stamp(value, daily=False):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    value = value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value.astimezone(SHANGHAI)
    return value.date().isoformat() if daily else value.isoformat(timespec="seconds")


def perform(w, request):
    op, code = request["operation"], request["code"]

    def call(api, *args):
        context = f"Wind {api.upper()}({', '.join(repr(a) for a in args)})"
        return checked(getattr(w, api)(*args), context), context

    if op == "calendar":
        calendar = "SSE" if code.endswith(".SH") else "SZSE"
        result, context = call("tdays", request["start"], request["end"], "TradingCalendar=" + calendar)
        if len(result.Data) != 1:
            raise ValueError(f"{context}；Wind 交易日历结构不匹配；{response_shape(result)}")
        return [stamp(t, True) for t in result.Data[0]]
    if op == "info":
        result, context = call("wss", code, "sec_name", "")
        if [str(c).strip().upper() for c in result.Codes] != [code] or len(result.Data) != 1 or len(result.Data[0]) != 1:
            raise ValueError(f"{context}；Wind 证券名称返回不匹配；{response_shape(result)}")
        value = result.Data[0][0]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Wind 未返回证券名称，请核对代码")
        return {"name": value}
    fields = request["fields"]
    if not fields or set(fields) - FIELDS.keys():
        raise ValueError("不支持的行情字段")
    if op == "snapshot":
        requested = [FIELDS[f] for f in fields]
        api = "WSQ"
        result, context = call("wsq", code, ",".join(requested))
    elif op == "history":
        requested = fields
        if request["frequency"] == "1d":
            api = "WSD"
            result, context = call("wsd", code, ",".join(fields), request["start"], request["end"],
                                   "Period=D;Days=Trading;Fill=Blank;PriceAdj=U")
        else:
            api = "WSI"
            result, context = call("wsi", code, ",".join(fields), request["start"], request["end"],
                                   f"BarSize={int(request['frequency'][:-1])};PriceAdj=U;Fill=Blank")
    else:
        raise ValueError("未知证券行情操作")
    rows, returned_fields, layout = quote_rows(result, code, fields, requested, api, context)
    received = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    return {"rows": rows, "received_at": received, "wind_fields": dict(zip(fields, requested)),
            "returned_fields": returned_fields, "response_layout": layout, "source": "Wind " + api}
