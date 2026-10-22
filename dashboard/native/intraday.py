"""Provisional observations alongside unchanged completed-day research results."""
import numpy as np
import pandas as pd
from numbers import Real

from dashboard.marketdata.quote_quality import aligned_quotes
from dashboard.session_clock import session_policy
from .instruments import UNDERLYINGS
from .pair_metrics import (PAIR_FORMULA_VERSION, pair_definition, quote_value,
                           required_symbols, ratio_for_day)


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
        if code.startswith(('A03.','B10')):
            row['current_reference_end']=history.index[-1].isoformat() if len(history) else None
            row['current_history_cutoff']=row['current_reference_end']

    def extra(code, title, value, unit, stamp, reason, formula, scope='盘中估算', n=None):
        row = metric(code, title, pd.Series(dtype=float), unit, formula, reason, scope=scope)
        if b is not None:
            definition=pair_definition(category,price)
            row.update(formula_version=PAIR_FORMULA_VERSION,pair_construction=definition['construction'],pair_metadata=definition)
            if '.legacy_' in code:row['role']='auxiliary'
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
        from .metric_inputs import input_value
        expiry = metadata.get(symbol, {}).get('expiry_date')
        days = (pd.Timestamp(expiry).date()-today).days if expiry else None
        return input_value(price,q['close'],live[UNDERLYINGS[symbol[:2]][0]]['close'],
                           dividends.points(symbol,today),days)

    required = legs + ([UNDERLYINGS[s[:2]][0] for s in legs] if price != 'future' else [])
    if b is not None:required=required_symbols(category,price,left,right)
    ok, stamp, reason = aligned(required)
    current = None
    if ok:
        if b is not None:
            current=quote_value(category,price,left,right,live,metadata,dividends,today)
        else:
            current=value(left)
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
    for code, val, n in [('A03.mean',float(prior.mean()) if usable and full20 else None,20), ('A03.std',sigma if usable else None,20), ('A03.z',z,20), ('A03.percentile',pct,20), ('A03.change5',change,6), ('B10',eff,6), ('B10.net',change,6), ('B10.path',float(path.diff().abs().sum()) if len(path) else None,6), ('B10.n',6 if len(path) else None,6)]:
        publish(code, val, stamp, base_reason if not usable or finite(val) else '固定合约连续样本不足或分母无效',
                n=n if finite(val) else None)
    prior30=history.tail(30)
    full30=consecutive_days(list(prior30.index.tz_convert('Asia/Shanghai').date),now,30) and prior30.notna().all()
    rank30=100*(prior30<=current).sum()/30 if usable and full30 else None
    publish('A03.legacy_percentile30',rank30,stamp,'此前30期≤分位；原并列规则，区别于20期半权分位',n=30 if finite(rank30) else None)

    # Turnover needs previous valid OI, not unreliable intraday OI.
    ok, stamp, reason = aligned(legs)
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
    if b is not None:
        qb=live.get(right,{})
        h=ratio_for_day(a,b,category,left,right,now)
        oi_b=b.oi_valid.iloc[-1] if daily_ok else None
        total_b=qb.get('volume_total');current_b=qb.get('open_interest')
        pair_valid=ok and daily_ok and all(finite(v) and v>=0 for v in (total,total_b,oi,oi_b)) and finite(h) and h>0
        pair_volume=min(total,total_b/h) if pair_valid else None
        pair_previous=min(oi,oi_b/h) if pair_valid else None
        expiries=[metadata.get(symbol,{}).get('expiry_date') for symbol in legs]
        oi_ok=pair_valid and all(finite(v) and v>0 for v in (current_oi,current_b)) and all(expiry and pd.Timestamp(expiry).date()>today for expiry in expiries)
        oi_ok=oi_ok and abs(current_oi-oi)<=total and abs(current_b-oi_b)<=total_b
        doi=min(current_oi,current_b/h)-pair_previous if oi_ok else None
        total=pair_volume
        row=row_map['B04.Q.intraday']
        row.update(title='合约对日内匹配换手代理',formula='min(累计V_A,累计V_B/h_t)/min(OI_A前,OI_B前/h_t)')
        publish('B04.Q.intraday',pair_volume/pair_previous if pair_valid and pair_previous>0 else None,stamp,
                '双腿同步累计匹配容量 / 同h昨日匹配OI；非实际配对成交' if pair_valid else '缺双腿有效累计量/昨日OI/前收h或新鲜行情')
    for code, val in [('B04.doi',doi), ('B04.K',100*doi/total if doi is not None and finite(total) and total > 0 else None)]:
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
    extra('B09.same_time' if b is None else 'B09.legacy_same_time', '同刻活跃度' if b is None else '原各腿同刻活跃对数比（辅助）', rvol, '倍' if b is None else '对数倍数', stamp,
          '与此前20日同一分钟累计量比较' if finite(rvol) else '等待整分钟同步累计量或缺20日同刻分钟',
          'V_当前完整分钟 / median(此前20日截至同分钟累计量)；双腿取ln比', n=20 if finite(rvol) else None)
    if b is not None:
        extra('B09.same_time','合约对同刻匹配量活跃度',None,'倍',None,'缺已认证的合约对前20日同刻匹配量基准；不以单腿比值代替',
              '同刻匹配量/median(此前20日同刻匹配量)',n=None)
        row_map['B09.same_time']['current_supported']=False

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
        publish('B11' if b is None else 'B11.legacy_log_ratio',stress,stamp,'当日已发生价格振幅 / 前20日完整振幅基准；非最终日振幅')
        if b is not None:publish('B11.max',max(stresses) if all(finite(v) for v in stresses) else None,stamp,'双腿截至当前振幅最大压力；非最终日振幅')
    if b is not None:
        for code in ('B03','B07','B08','B09','B11'):
            if code in row_map:
                row_map[code].update(current=None,current_time=None,current_supported=False,
                                     current_reason='合约对主指标需完整日终/同步分钟及匹配量基准；不以单腿比较代替')
        extra('B11.sample','合约对采集段振幅',None,'倍',None,'缺已认证的合约对同步采集段及同口径绝对TR基准；不以单腿压力比代替',
              '采集段X极差 / 前20日合约对绝对TR中位数')
        row_map['B11.sample']['current_supported']=False
    _publish_original_current(rows,publish,aligned,left,right,category,a,b,metadata,live,now)
    return rows


def _publish_original_current(rows,publish,aligned,left,right,category,a,b,metadata,live,now):
    """Current original definitions retain independent inputs and reference pools."""
    from .metric_inputs import input_value
    from .nonregression import MULTIPLIERS
    today=now.tz_convert('Asia/Shanghai').date()
    rows_by_id={r['id']:r for r in rows}
    def stats(prefix,value,series,stamp):
        series=series[series.index.tz_convert('Asia/Shanghai').date<today]
        previous=series.tail(20)
        enough=consecutive_days(list(previous.index.tz_convert('Asia/Shanghai').date),now,20) and previous.notna().all()
        sigma=previous.std(ddof=1) if enough else None
        five=series.tail(5)
        five_ok=consecutive_days(list(five.index.tz_convert('Asia/Shanghai').date),now,5) and five.notna().all()
        present=finite(value)
        values={'mean':previous.mean() if enough and present else None,
                'std':sigma if enough and present else None,
                'z':(value-previous.mean())/sigma if present and enough and sigma>1e-12 else None,
                'percentile':100*((previous<value).sum()+.5*(previous==value).sum())/20 if present and enough else None,
                'change5':value-five.iloc[0] if present and five_ok else None}
        for key,v in values.items():
            publish(prefix+key,v,stamp,'自身固定序列先前窗口；缺样本或零方差留空',n=(6 if key=='change5' else 20) if finite(v) else None)
            if prefix+key in rows_by_id:
                rows_by_id[prefix+key].update(current_reference_end=series.index[-1].isoformat() if len(series) else None,
                                            current_history_cutoff=series.index[-1].isoformat() if len(series) else None)
    spot_a=UNDERLYINGS[left[:2]][0]
    if category=='basis':
        ok,stamp,reason=aligned([left,spot_a])
        f=live.get(left,{}).get('close');s=live.get(spot_a,{}).get('close')
        expiry=metadata.get(left,{}).get('expiry_date')
        days=(pd.Timestamp(expiry).date()-today).days if expiry else None
        if ok:
            values={code:input_value(key,f,s,None,days) for code,key in (
                ('A01.raw_bp','raw_basis'),('A01.log_bp','log_basis'),('A02.raw_annual','raw_annual'),('A02.log_annual','log_annual'))}
            values['A01.raw_points']=f-s if finite(f) and finite(s) and f>0 and s>0 else None
            values['A02.log_convergence']=-values['A01.log_bp']/days if finite(values['A01.log_bp']) and days and days>0 else None
            for code,value in values.items():publish(code,value,stamp,'同刻真实期现未调整口径；年化要求T≥5')
        return
    if b is None:return
    ok,stamp,reason=aligned([left,right])
    fa=live.get(left,{}).get('close');fb=live.get(right,{}).get('close')
    valid=ok and all(finite(v) and v>0 for v in (fa,fb))
    if valid:
        h=ratio_for_day(a,b,category,left,right,now)
        publish('B12.h',h,stamp,'同品种1:1；跨品种使用上一完整交易日真实F等名义换算')
        va,vb=(live[s].get('volume_total') for s in (left,right))
        p=rows_by_id.get('B12.p',{}).get('value')
        if all(finite(v) and v>=0 for v in (va,vb)) and finite(h) and h>0 and finite(p) and 0<=p<=1:
            cap=min(va,vb/h)
            for code,value in (('B12.p',p),('B12.A_p',p*cap),('B12.B_p',p*cap*h)):
                publish(code,value,stamp,'显式p乘截至当前已发生成交基数；非可成交承诺')
    if category=='calendar':
        raw=fa-fb if valid else None
        publish('A04.raw_points',raw,stamp,reason)
        all_ok,all_stamp,_=aligned([left,right,spot_a])
        spot=live.get(spot_a,{}).get('close')
        raw_bp=10000*raw/spot if all_ok and finite(raw) and finite(spot) and spot>0 else None
        publish('A04.raw_bp',raw_bp,all_stamp,'真实期货近减远并以对应指数标准化')
        stats('A04.raw_',raw_bp,10000*(a.close-b.close)/a.S,all_stamp)
        ea,eb=(metadata.get(s,{}).get('expiry_date') for s in (left,right))
        delta=(pd.Timestamp(eb)-pd.Timestamp(ea)).days if ea and eb else 0
        legacy_carry=100*np.log(fb/fa)*365/delta if valid and delta>0 else None
        publish('A05.legacy_log_carry',legacy_carry,stamp,'原未设近到期门槛的对数期限持有率，仅作辅助')
        days_a=(pd.Timestamp(ea).date()-today).days if ea else None
        days_b=(pd.Timestamp(eb).date()-today).days if eb else None
        carry=legacy_carry if days_a is not None and days_b is not None and days_a>=5 and days_b>=5 else None
        publish('A05.log_carry',carry,stamp,'对数期限持有率；两腿T≥5' if finite(carry) else '缺同步价格/到期信息或任一腿T<5')
        series=100*np.log(b.close/a.close)*365/delta if delta>0 else a.close*np.nan
        series=series.where(a['T'].ge(5)&b['T'].ge(5))
        stats('A05.log_',carry,series,stamp)
    else:
        spot_b=UNDERLYINGS[right[:2]][0]
        all_ok,all_stamp,_=aligned([left,right,spot_a,spot_b])
        for prefix,key in (('raw','raw_basis'),('log','log_basis')):
            va=input_value(key,fa,live.get(spot_a,{}).get('close')) if all_ok else None
            vb=input_value(key,fb,live.get(spot_b,{}).get('close')) if all_ok else None
            value=va-vb if finite(va) and finite(vb) else None
            publish('A06.'+prefix+'_bp',value,all_stamp,'每腿按自身真实指数计算后相减；未加分红')
            stats('A06.'+prefix+'_',value,a[key]-b[key],all_stamp)


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
                from .metric_inputs import input_value
                expiry=metadata.get(symbol,{}).get('expiry_date')
                day=at.tz_convert('Asia/Shanghai').date()
                days=(pd.Timestamp(expiry).date()-day).days if expiry else None
                values.append(input_value(price,q['close'],quotes[UNDERLYINGS[symbol[:2]][0]]['close'],
                                          dividends.points(symbol,day),days))
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
        if category!='basis':
            definition=pair_definition(category,price)
            rows[-1].update(formula_version=PAIR_FORMULA_VERSION,pair_construction=definition['construction'],pair_metadata=definition)
            if '.legacy_' in code:rows[-1]['role']='auxiliary'
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
        append('B11.sample' if category=='basis' else 'B11.legacy_sample','采集段振幅' if category=='basis' else '原各腿采集段压力对数比（辅助）',val,'倍' if len(pressures)==1 else '对数倍数',
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
                if row['id']==('B09.same_time' if category=='basis' else 'B09.legacy_same_time') and finite(val):
                    row.update(current=float(val),current_time=at.isoformat(),current_scope='盘中分钟近似',
                               current_reason='历史同分钟累计量；当前观测在分钟末前0—3秒，未插值',current_n=20)
    return rows
