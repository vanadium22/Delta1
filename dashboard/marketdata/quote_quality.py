"""Receipt freshness cannot certify a source date or turn cache data into a tick."""
import math
import pandas as pd


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v,bool) and math.isfinite(v)


def quote_quality(quote, as_of, max_age=30):
    if not quote: return {"usable":False, "status":"缺少实时行情", "reason":"未收到该标的HTTP观测"}
    now = pd.Timestamp(as_of).tz_convert("Asia/Shanghai")
    result = dict(usable=False, status="源日期待认证", reason="只有源时分秒，日期按接收日推定")
    if not isinstance(quote,dict):return {**result,"status":"行情格式无效"}
    try:
        received = pd.Timestamp(quote.get("observed_at", quote.get("received_at")))
        source = pd.Timestamp(quote.get("source_event_time"))
    except (ValueError,TypeError,OverflowError):return {**result,"status":"源时间无效"}
    if pd.isna(received) or pd.isna(source): return {**result, "status":"源时间缺失"}
    if received.tzinfo is None or source.tzinfo is None:return {**result,"status":"源时间缺时区"}
    age, source_age = (now-received).total_seconds(), (now-source).total_seconds()
    result.update(receipt_age=age, source_age=source_age)
    if age < 0 or source_age < -3: return {**result, "status":"时间倒置"}
    if age > max_age or source_age > max_age: return {**result, "status":"陈旧/缓存行情"}
    minute = now.hour*3600+now.minute*60+now.second+now.microsecond/1e6
    local_source=source.tz_convert("Asia/Shanghai")
    source_minute = local_source.hour*3600+local_source.minute*60+local_source.second
    session = lambda m: "am" if 34200 <= m <= 41400 else "pm" if 46800 <= m <= 54000 else None
    if now.weekday() >= 5 or session(minute) is None or session(minute) != session(source_minute):
        return {**result, "status":"非连续交易会话/收盘缓存"}
    if not finite(quote.get("close")) or quote["close"] <= 0: return {**result, "status":"最新价无效"}
    return {**result, "usable":True, "status":"重复源快照·日期推定" if quote.get("snapshot_status")=="duplicate_source_snapshot" else "盘中观测·日期推定", "session":session(minute)}


def aligned_quotes(quotes, as_of, max_skew=3):
    if not quotes or any(not q for q in quotes): return False, "缺少实时腿；不使用历史价格补齐"
    qualities = [quote_quality(q, as_of) for q in quotes]
    if any(not q["usable"] for q in qualities): return False, "；".join(dict.fromkeys(q["status"] for q in qualities if not q["usable"]))
    for field in ("source_event_time", "observed_at"):
        times = [pd.Timestamp(q.get(field, q.get("received_at"))) for q in quotes]
        if (max(times)-min(times)).total_seconds() > max_skew: return False, "两腿源时间或接收时间偏差超过3秒"
    return True, "盘中截至当前·源日期推定，非已认证交易所时间"
