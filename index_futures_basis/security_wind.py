"""Standard-library Wind adapter. All intraday timestamps retain their time zone."""
from datetime import datetime, timedelta, timezone
import math

SHANGHAI = timezone(timedelta(hours=8))
FIELDS = {"close": "rt_last", "open": "rt_open", "high": "rt_high", "low": "rt_low", "volume": "rt_vol", "amt": "rt_amt"}


def checked(result):
    if result.ErrorCode:
        raise RuntimeError(f"Wind ErrorCode={result.ErrorCode}；请核对终端登录、字段及分钟历史权限")
    return result


def stamp(value, daily=False):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    value = value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value.astimezone(SHANGHAI)
    return value.date().isoformat() if daily else value.isoformat(timespec="seconds")


def perform(w, request):
    op, code = request["operation"], request["code"]
    if op == "calendar":
        calendar = "SSE" if code.endswith(".SH") else "SZSE"
        result = checked(w.tdays(request["start"], request["end"], "TradingCalendar=" + calendar))
        if len(result.Data) != 1:
            raise ValueError("Wind 交易日历结构不匹配")
        return [stamp(t, True) for t in result.Data[0]]
    if op == "info":
        result = checked(w.wss(code, "sec_name", ""))
        if [str(c).upper() for c in result.Codes] != [code] or len(result.Data) != 1 or len(result.Data[0]) != 1:
            raise ValueError("Wind 证券名称返回不匹配")
        value = result.Data[0][0]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Wind 未返回证券名称，请核对代码")
        return {"name": value}
    fields = request["fields"]
    if not fields or set(fields) - FIELDS.keys():
        raise ValueError("不支持的行情字段")
    if op == "snapshot":
        requested = [FIELDS[f] for f in fields]
        result = checked(w.wsq(code, ",".join(requested)))
    elif op == "history":
        requested = fields
        if request["frequency"] == "1d":
            result = checked(w.wsd(code, ",".join(fields), request["start"], request["end"],
                                   "Period=D;Days=Trading;Fill=Blank;PriceAdj=U"))
        else:
            result = checked(w.wsi(code, ",".join(fields), request["start"], request["end"],
                                   f"BarSize={int(request['frequency'][:-1])};PriceAdj=U;Fill=Blank"))
    else:
        raise ValueError("未知证券行情操作")
    actual = [str(f).lower() for f in result.Fields]
    if [str(c).upper() for c in result.Codes] != [code] or len(set(actual)) != len(actual) or set(actual) != set(requested):
        raise ValueError("Wind 返回证券代码或字段不匹配")
    count = 1 if op == "snapshot" else len(result.Times)
    if len(result.Data) != len(requested) or any(len(column) != count for column in result.Data):
        raise ValueError("Wind 返回数据长度不匹配")
    received = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    times = [stamp(t, op != "snapshot" and request["frequency"] == "1d") for t in result.Times]
    if len(set(times)) != len(times):
        raise ValueError("Wind 返回重复时间戳")
    if op == "snapshot":
        # WSQ Times is retained as provider-returned time, never claimed as last-trade time.
        times = [times[0] if len(times) == 1 else None]
    rows = []
    for i, time in enumerate(times):
        row = {"time": time}
        for field, raw in zip(fields, requested):
            value = result.Data[actual.index(raw)][i]
            row[field] = value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        rows.append(row)
    return {"rows": rows, "received_at": received, "wind_fields": dict(zip(fields, requested)),
            "source": "Wind " + ("WSQ" if op == "snapshot" else "WSD" if request["frequency"] == "1d" else "WSI")}
