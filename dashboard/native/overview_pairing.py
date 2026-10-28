"""Saved-pair references for non-trading views; never certify realtime freshness."""
from bisect import bisect_left, bisect_right
import pandas as pd

from dashboard.marketdata.quote_quality import finite
from dashboard.indicator_v6.sources import dates_between


def clock(value):
    try:
        value = pd.Timestamp(value)
        return value if not pd.isna(value) and value.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def valid(row, now):
    source = clock(row.get('source_event_time'))
    received = clock(row.get('observed_at', row.get('received_at')))
    if (source is None or received is None or received > now or source > now + pd.Timedelta(seconds=3)
            or (received-source).total_seconds() < -3 or not finite(row.get('close')) or row['close'] <= 0):
        return None
    day = str(source.tz_convert('Asia/Shanghai').date())
    try:
        if not dates_between(day, day):
            return None
    except ValueError:
        return None
    return source, received


def reference_pair(symbol, spot, live, observations, daily, now):
    candidates = {symbol:[], spot:[]}
    for code in candidates:
        row = live.get(code)
        if row and (times:=valid(row, now)):
            candidates[code].append((*times, row))
    if observations is not None and not observations.empty:
        frame = observations[observations.instrument_id.isin(candidates)]
        for row in frame.tail(40000).to_dict('records'):
            if times:=valid(row, now):
                candidates[row['instrument_id']].append((*times, row))
    funds = sorted(candidates[symbol], key=lambda item:(item[0],item[1]), reverse=True)
    spots = sorted(candidates[spot], key=lambda item:(item[0],item[1]))
    times = [item[0].value for item in spots]
    best = None
    skew = 3_000_000_000
    for fs, fr, f in funds:
        if best and fs < best['at']-pd.Timedelta(seconds=3):
            break
        for ss, sr, s in spots[bisect_left(times,fs.value-skew):bisect_right(times,fs.value+skew)]:
            if abs((fr-sr).total_seconds()) > 3 or fs.tz_convert('Asia/Shanghai').date() != ss.tz_convert('Asia/Shanghai').date():
                continue
            at = max(fs,ss)
            if best is None or (at,max(fr,sr)) > (best['at'],best['received']):
                best = dict(future=f,spot=s,at=at,received=max(fr,sr),mode='cached_pair',
                    day=str(at.tz_convert('Asia/Shanghai').date()))
    tables = {}
    for code in (symbol,spot):
        frame = daily.get(code)
        tables[code] = {} if frame is None or frame.empty else {
            str(r['trade_date'])[:10]:r for r in frame.to_dict('records')
            if r.get('is_final') == True and finite(r.get('close')) and r['close'] > 0
            and (at:=clock(r.get('event_time'))) is not None and at <= now}
    common = tables[symbol].keys() & tables[spot].keys()
    if common:
        day = max(common)
        f, s = tables[symbol][day], tables[spot][day]
        at = max(clock(f['event_time']),clock(s['event_time']))
        if best is None or at >= best['at']:
            best = dict(future=f,spot=s,at=at,received=None,mode='completed_daily',day=day)
    return best
