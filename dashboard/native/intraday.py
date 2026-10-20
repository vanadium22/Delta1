"""Provisional observations alongside unchanged completed-day research results."""
import numpy as np
import pandas as pd
from numbers import Real

from dashboard.marketdata.quote_quality import aligned_quotes
from dashboard.session_clock import session_policy
from .instruments import UNDERLYINGS


def finite(value):
    return isinstance(value,Real) and not isinstance(value,(bool,np.bool_)) and np.isfinite(value)


def previous_day(now):
    from dashboard.marketdata.trading_calendar import HOLIDAYS
    day = pd.Timestamp(now).tz_convert('Asia/Shanghai').date()
    for _ in range(20):
        day -= pd.Timedelta(days=1)
        if day.year not in HOLIDAYS:
            return None
        if day.weekday() < 5 and not any(a <= day.strftime('%m-%d') <= b for a,b in HOLIDAYS[day.year]):
            return day
    return None


def expected_minutes(day, through=None):
    day = pd.Timestamp(day).tz_localize('Asia/Shanghai')
    index = pd.date_range(day+pd.Timedelta(hours=9, minutes=31), periods=120, freq='min').append(
        pd.date_range(day+pd.Timedelta(hours=13, minutes=1), periods=120, freq='min'))
    if through is not None:
        index = index[index <= through]
    return index.tz_convert('UTC')


def consecutive_days(days, now, count):
    """A dataset with an entirely absent session must not shorten the window."""
    if len(days) != count:
        return False
    expected = previous_day(now)
    for actual in reversed(days):
        if actual != expected:
            return False
        expected = previous_day(pd.Timestamp(str(expected), tz='Asia/Shanghai'))
    return True


def same_time_volume(raw, days, now):
    """Exactly the previous 20 sessions, all minute volumes through the last full minute."""
    if len(days) != 20 or raw.empty or 'volume' not in raw:
        return None
    frame = raw.set_index('event_time') if 'event_time' in raw else raw
    if frame.index.has_duplicates:
        return None
    local = pd.Timestamp(now).tz_convert('Asia/Shanghai').floor('min')
    totals = []
    for day in days:
        end = pd.Timestamp(day).tz_localize('Asia/Shanghai') + pd.Timedelta(
            hours=local.hour, minutes=local.minute)
        index = expected_minutes(day, end)
        values = pd.to_numeric(frame.reindex(index).volume, errors='coerce')
        if not len(index) or values.isna().any() or (values < 0).any():
            return None
        totals.append(float(values.sum()))
    median = float(np.median(totals))
    return median if median > 0 else None


def apply(rows, *, left, right, category, price, a, b, x, minute_data, metadata, dividends, live, now):
    """Never append provisional rows to the historical datasets or percentile pool."""
    from .nonregression import metric, efficiency
    now = pd.Timestamp(now)
    today = now.tz_convert('Asia/Shanghai').date()
    previous = previous_day(now)
    keep = x.index.tz_convert('Asia/Shanghai').date < today
    history = x.loc[keep]
    a = a.loc[keep]
    b = b.loc[keep] if b is not None else None
    daily_ok = bool(previous and len(history) and history.index[-1].tz_convert('Asia/Shanghai').date() == previous)
    active = session_policy(now.to_pydatetime())['allowed']
    row_map = {r['id']: r for r in rows}
    legs = [left] + ([right] if b is not None else [])

    def publish(code, value, stamp, reason, scope='盘中估算', n=None):
        row = row_map.get(code)
        if row is None:
            return
        row.update(current=float(value) if finite(value) else None,
                   current_time=stamp if finite(value) else None, current_reason=reason,
                   current_scope=scope, current_n=n, current_supported=True)

    def extra(code, title, value, unit, stamp, reason, formula, scope='盘中估算', n=None):
        row = metric(code, title, pd.Series(dtype=float), unit, formula, reason, scope=scope)
        rows.append(row); row_map[code] = row
        publish(code, value, stamp, reason, scope, n)

    def aligned(symbols):
        ok, reason = aligned_quotes([live.get(s) for s in dict.fromkeys(symbols)], now)
        ok = ok and active
        stamp = max((pd.Timestamp(live[s]['source_event_time']) for s in symbols)).isoformat() if ok else None
        return ok, stamp, reason if active else '非行情接入时段；查看日终或保存观测'

    def value(symbol):
        q = live[symbol]
        if price == 'future':
            return q['close']
        from dashboard.marketdata.dividends import adjusted_basis
        expiry = metadata.get(symbol, {}).get('expiry_date')
        days = (pd.Timestamp(expiry).date()-today).days if expiry else None
        result = adjusted_basis(q['close'], live[UNDERLYINGS[symbol[:2]][0]]['close'],
                                dividends.points(symbol, today), days)
        return result['bp' if price == 'basis' else 'annual_pct']

    required = legs + ([UNDERLYINGS[s[:2]][0] for s in legs] if price != 'future' else [])
    ok, stamp, reason = aligned(required)
    current = None
    if ok:
        values = [value(s) for s in legs]
        if all(finite(v) for v in values):
            current = values[0] - (values[1] if b is not None else 0)
    base_reason = reason if not ok else '缺分红/到期信息或临到期年化不可用' if current is None else (
        '历史未接续至上一交易日' if not daily_ok else '盘中观测加入日序列；参考窗口仅完整历史')
    usable = current is not None and daily_ok
    publish('X',current,stamp,base_reason)
    prior = history.tail(20)
    full20 = consecutive_days(list(prior.index.tz_convert('Asia/Shanghai').date),now,20) and prior.notna().all()
    sigma = float(prior.std(ddof=1)) if full20 else None
    z = (current-prior.mean())/sigma if usable and full20 and sigma > 1e-12 else None
    pct = 100*((prior < current).sum()+.5*(prior == current).sum())/20 if usable and full20 else None
    last5 = history.tail(5)
    full5 = consecutive_days(list(last5.index.tz_convert('Asia/Shanghai').date),now,5) and last5.notna().all()
    change = current-last5.iloc[0] if usable and full5 else None
    path = pd.Series([*last5.to_list(), current], dtype=float) if usable and full5 else pd.Series(dtype=float)
    eff = efficiency(path).iloc[-1] if len(path) else None
    for code, val, n in [('A03.z',z,20), ('A03.percentile',pct,20), ('A03.change5',change,5), ('B10',eff,5)]:
        publish(code, val, stamp, base_reason if not usable or finite(val) else '固定合约连续样本不足或分母无效',
                n=n if finite(val) else None)

    # Turnover needs previous valid OI, not unreliable intraday OI.
    ok, stamp, reason = aligned([left])
    qa = live.get(left, {})
    total, oi = qa.get('volume_total'), a.oi_valid.iloc[-1] if daily_ok else None
    valid = ok and daily_ok and finite(total) and total >= 0 and finite(oi) and oi > 0
    extra('B04.Q.intraday', '日内换手', total/oi if valid else None, '倍', stamp,
          'A腿累计成交量 / 昨日有效持仓' if valid else '缺有效累计量/昨日持仓或新鲜行情',
          'V_截至当前 / OI_上一交易日')
    # OI-based daily definitions have provisional counterparts only with valid reported OI.
    current_oi = qa.get('open_interest')
    doi = current_oi-oi if valid and finite(current_oi) and current_oi > 0 else None
    if doi is not None and abs(doi) > total:
        doi = None
    for code, val in [('B04.doi',doi), ('B04.K',100*doi/total if doi is not None and total > 0 else None)]:
        publish(code, val, stamp, '截至当前持仓变化；非日终' if finite(val) else '缺有效实时OI/昨日OI或净变化异常')

    # Cumulative current volume is compared only at its exact completed minute.
    ok, stamp, reason = aligned(legs)
    source = pd.Timestamp(stamp).tz_convert('Asia/Shanghai') if stamp else None
    boundary = bool(source is not None and source.second == 0 and source.microsecond == 0)
    volumes = []
    days = [t.tz_convert('Asia/Shanghai').date() for t in history.tail(20).index]
    for symbol in legs:
        denominator = same_time_volume(minute_data.get(symbol,pd.DataFrame()),days,source) if boundary and consecutive_days(days,now,20) else None
        v = live.get(symbol, {}).get('volume_total')
        volumes.append(v/denominator if denominator and finite(v) and v >= 0 else None)
    rvol = volumes[0] if ok and len(volumes) == 1 else (
        float(np.log(volumes[0]/volumes[1])) if ok and all(v is not None and v > 0 for v in volumes) else None)
    extra('B09.same_time', '同刻活跃度', rvol, '倍' if b is None else '对数倍数', stamp,
          '与此前20日同一分钟累计量比较' if finite(rvol) else '等待整分钟同步累计量或缺20日同刻分钟',
          'V_当前完整分钟 / median(此前20日截至同分钟累计量)；双腿取ln比', n=20 if finite(rvol) else None)

    if price == 'future':
        ok, stamp, reason = aligned(legs)
        stresses = []
        for symbol, frame in zip(legs, [a,b]):
            q = live.get(symbol,{})
            high, low = q.get('high'), q.get('low')
            prev = frame.close.iloc[-1] if daily_ok else None
            med = frame.trbp.tail(20)
            valid = ok and daily_ok and all(finite(v) for v in (high, low, prev)) and high >= q['close'] >= low and prev > 0
            den = med.median() if full20 and med.notna().all() else None
            stresses.append(10000*max(high-low,abs(high-prev),abs(low-prev))/prev/den if valid and finite(den) and den>0 else None)
        stress = stresses[0] if b is None else float(np.log(stresses[0]/stresses[1])) if all(v is not None and v>0 for v in stresses) else None
        publish('B11',stress,stamp,'当日已发生价格振幅 / 前20日完整振幅基准；非最终日振幅')
    return rows


def observations(rows, samples, left, right, category, price, data, minute_data, metadata, dividends, now, cache=None):
    """Bounded receipt samples are a separate intraday series, never exchange bars."""
    from .nonregression import minute_series, minute_daily, metric
    cache = {} if cache is None else cache
    now = pd.Timestamp(now)
    if samples.empty or not session_policy(now.to_pydatetime())['allowed']:
        return rows
    futures = [left] + ([right] if category != 'basis' else [])
    symbols = list(dict.fromkeys(futures + ([UNDERLYINGS[s[:2]][0] for s in futures] if price != 'future' else [])))
    selected = samples[samples.instrument_id.isin(symbols)].copy()
    if selected.empty:
        return rows
    selected = selected[selected.observed_at.le(now)]
    observations = []
    groups = {}
    for row in selected.to_dict('records'):
        groups.setdefault((row['run_id'],row['poll'],row['batch']),{})[row['instrument_id']]=row
    for quotes in groups.values():
        if any(s not in quotes for s in symbols):
            continue
        at = max(pd.Timestamp(q['observed_at']) for q in quotes.values())
        ok,_ = aligned_quotes([quotes[s] for s in symbols],at)
        if not ok or at.tz_convert('Asia/Shanghai').date()!=now.tz_convert('Asia/Shanghai').date():
            continue
        values = []
        for symbol in futures:
            q = quotes[symbol]
            if price=='future':
                values.append(q['close'])
            else:
                from dashboard.marketdata.dividends import adjusted_basis
                expiry=metadata.get(symbol,{}).get('expiry_date')
                days=(pd.Timestamp(expiry).date()-at.tz_convert('Asia/Shanghai').date()).days if expiry else None
                v=adjusted_basis(q['close'],quotes[UNDERLYINGS[symbol[:2]][0]]['close'],
                                 dividends.points(symbol,at.tz_convert('Asia/Shanghai').date()),days)
                values.append(v['bp' if price=='basis' else 'annual_pct'])
        if all(finite(v) for v in values):
            stamp=max(pd.Timestamp(quotes[s]['source_event_time']) for s in symbols)
            if stamp <= now:
                observations.append((stamp,values,quotes))
    observations.sort(key=lambda v:v[0])
    if not observations or (now-observations[-1][0]).total_seconds()>30:
        return rows
    # Use only the latest continuous source-time segment; reconnects and lunch reset.
    segment=[]
    for obs in observations:
        if segment and ((obs[0]-segment[-1][0]).total_seconds()>30 or
                        obs[2][left]['run_id']!=segment[-1][2][left]['run_id']):
            segment=[]
        if not segment or obs[0]>segment[-1][0]:
            segment.append(obs)
    stamp=segment[-1][0].isoformat()
    def append(code,title,value,unit,formula,reason):
        rows.append(metric(code,title,pd.Series(dtype=float),unit,formula,reason,scope='采集区间',
                           current=value,current_time=stamp if finite(value) else None,current_reason=reason))
        rows[-1].update(current_scope='采集区间',current_supported=True,current_n=len(segment))
    if price!='future':
        pressures=[]
        for i,symbol in enumerate(futures):
            key=('amplitude',symbol,price,metadata.get(symbol,{}).get('expiry_date'),
                 dividends.version,dividends.mode,dividends.reason,str(now.tz_convert('Asia/Shanghai').date()))
            if key not in cache:
                minute=minute_series(minute_data.get(symbol,pd.DataFrame()),minute_data.get(UNDERLYINGS[symbol[:2]][0],pd.DataFrame()),
                                     symbol,metadata.get(symbol,{}).get('expiry_date'),dividends,price)
                daily=minute_daily(minute)
                den=None
                if len(daily):
                    daily=daily[daily.index < now.normalize()]
                    tr=pd.concat([daily.high-daily.low,(daily.high-daily.close.shift()).abs(),
                                  (daily.low-daily.close.shift()).abs()],axis=1).max(axis=1,skipna=False).tail(20)
                    if consecutive_days(list(tr.index.tz_convert('Asia/Shanghai').date),now,20) and tr.notna().all():den=tr.median()
                cache[key]=den
            den=cache[key]
            values=[v[1][i] for v in segment]
            pressures.append((max(values)-min(values))/den if len(values)>1 and finite(den) and den>0 else None)
        val=pressures[0] if len(pressures)==1 else np.log(pressures[0]/pressures[1]) if all(v is not None and v>0 for v in pressures) else None
        append('B11.sample','采集段振幅',val,'倍' if len(pressures)==1 else '对数倍数',
               '采集段同步观测极差 / 前20日完整绝对振幅中位；双腿取ln比',
               '自 '+segment[0][0].tz_convert('Asia/Shanghai').strftime('%H:%M:%S')+' 起；非全天振幅，缺口后重置')
    # A current cumulative observation within 3 seconds BEFORE a completed minute
    # is an explicitly labelled approximation; no interpolation or fabricated volume.
    boundary=now.floor('min')
    choices=[v for v in observations if 0 <= (boundary-v[0]).total_seconds() <= 3]
    if choices:
        at,_,quotes=choices[-1]
        history=data.get(left,pd.DataFrame())
        days=[t.tz_convert('Asia/Shanghai').date() for t in history.index if t.tz_convert('Asia/Shanghai').date()<now.tz_convert('Asia/Shanghai').date()][-20:]
        if consecutive_days(days,now,20):
            values=[]
            for symbol in futures:
                den=same_time_volume(minute_data.get(symbol,pd.DataFrame()),days,boundary)
                v=quotes[symbol].get('volume_total')
                values.append(v/den if den and finite(v) and v>=0 else None)
            val=values[0] if len(values)==1 else np.log(values[0]/values[1]) if all(v is not None and v>0 for v in values) else None
            for row in rows:
                if row['id']=='B09.same_time' and finite(val):
                    row.update(current=float(val),current_time=at.isoformat(),current_scope='盘中分钟近似',
                               current_reason='历史同分钟累计量；当前观测在分钟末前0—3秒，未插值',current_n=20)
    return rows
