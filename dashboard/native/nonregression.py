"""A/B research on fixed contracts. No regression, C indicators or trading logic.

Missing dates are reindexed to the observed index calendar before differences;
intraday rolling windows are calculated separately in each continuous session.
"""
from itertools import combinations
from copy import deepcopy
import math
import numpy as np
import pandas as pd

from dashboard.marketdata.dividends import DividendBook, adjusted_basis
from dashboard.marketdata.quote_quality import aligned_quotes, quote_quality, finite
from dashboard.marketdata.repository import ReferenceBook
from .instruments import UNDERLYINGS

MULTIPLIERS = {"IF":300, "IH":300, "IC":200, "IM":200}
FIELDS = ("open", "high", "low", "close", "volume", "open_interest", "turnover", "prev_close")
from .metric_inputs import INPUTS, input_value, theoretical_cost_band, etf_premium
from .metric_components import minute_events, add_original_and_components
from .pair_metrics import (PAIR_FORMULA_VERSION, pair_definition, pair_value, pair_series,
                           pair_quantities, pair_minute_frame, pair_ohlc_statistics, ratio_for_day,
                           pair_daily, required_symbols)


def prior(s, n=20):
    return s.shift().rolling(n, min_periods=n)


def statistics(s, n=20):
    sigma = prior(s,n).std(ddof=1)
    z = (s-prior(s,n).mean())/sigma.where(sigma > 1e-12)
    pct = s.rolling(n+1,min_periods=n+1).apply(lambda x:100*((x[:-1]<x[-1]).sum()+.5*(x[:-1]==x[-1]).sum())/n,raw=True)
    return z, pct, s.diff(5)


def legacy_percentile(s,n=30):
    """Original overview tie rule; separate from the 20-value half-weight rank."""
    return s.rolling(n+1,min_periods=n+1).apply(lambda values:100*(values[:-1]<=values[-1]).sum()/n,raw=True)


def weighted(delta, weight, n=5):
    valid = delta.notna() & weight.notna() & (weight >= 0)
    den = weight.where(valid).rolling(n,min_periods=n).sum()
    return (delta*weight).where(valid).rolling(n,min_periods=n).sum()/den.where(den>0)


def efficiency(s, n=5):
    den = s.diff().abs().rolling(n,min_periods=n).sum()
    return s.diff(n)/den.where(den>1e-12)


def positive(s):
    values=pd.to_numeric(s,errors='coerce').astype(float)
    return values.where(values>0)


def frame_index(frame):
    if frame.empty: return pd.DataFrame(columns=FIELDS, index=pd.DatetimeIndex([],tz="UTC"))
    # Provenance remains on repository results. Research arithmetic uses the
    # frozen manifest separately; copying a full instrument registry on every
    # pandas slice/rolling operation is unnecessary and very expensive.
    frame = frame.copy(deep=False)
    frame.attrs = {}
    return frame.set_index("event_time").sort_index()


def complete_history_calendar(dates):
    """Expose whole-session holes using the bundled exchange calendar only.

    Unknown years remain explicit and cannot acquire fabricated weekday rows.
    The original timestamps remain present; all inserted daily labels are 15:00
    Asia/Shanghai, matching the repository's daily close convention.
    """
    from dashboard.marketdata.trading_calendar import HOLIDAYS
    index=pd.DatetimeIndex(sorted(set(dates)))
    if not len(index):return pd.DatetimeIndex([],tz='UTC'), ''
    if index.tz is None:raise ValueError('历史日线时刻必须带时区')
    local=index.tz_convert('Asia/Shanghai')
    unknown=sorted(set(local.year)-set(HOLIDAYS))
    added=[]
    for day in pd.date_range(local.min().normalize(),local.max().normalize(),freq='D'):
        if day.year not in HOLIDAYS:continue
        key=day.strftime('%m-%d')
        if day.weekday()<5 and not any(a<=key<=b for a,b in HOLIDAYS[day.year]):
            added.append((day+pd.Timedelta(hours=15)).tz_convert('UTC'))
    expanded=index.union(pd.DatetimeIndex(added)).sort_values() if added else index
    return expanded, '交易日历年份未认证：'+','.join(map(str,unknown)) if unknown else ''


def single(f, spot, symbol, expiry, dividends, calendar):
    f = f.reindex(calendar).copy()
    for c in FIELDS:
        if c not in f: f[c] = np.nan
        else: f[c] = pd.to_numeric(f[c],errors='coerce')
    for c in ('open','high','low','close','prev_close'):
        f[c]=positive(f[c])
    f['volume']=f.volume.where(f.volume>=0)
    f['open_interest']=f.open_interest.where(f.open_interest>=0)
    spot = spot.reindex(calendar)
    f["S"] = positive(spot.get("close", pd.Series(np.nan,index=calendar)))
    sh=spot.get('high',pd.Series(np.nan,index=calendar));sl=spot.get('low',pd.Series(np.nan,index=calendar))
    f['spot_clv']=(2*f.S-sh-sl)/(sh-sl).where(sh>sl)
    f['spot_volume']=spot.get('volume',pd.Series(np.nan,index=calendar))
    days = pd.Series([(pd.Timestamp(expiry).date()-t.tz_convert("Asia/Shanghai").date()).days for t in calendar], index=calendar) if expiry else pd.Series(np.nan,index=calendar)
    f["T"] = days
    f["D"] = [dividends.points(symbol,t.tz_convert("Asia/Shanghai").date()) for t in calendar]
    f["D"] = pd.to_numeric(f.D,errors="coerce")
    f["points"] = f.close-f.S+f.D
    f["basis"] = 10000*f.points/positive(f.S)
    f["annual"] = f.basis*365/(100*days.where(days>=5))
    f["raw_points"] = f.close-f.S
    f["raw_basis"] = 10000*f.raw_points/positive(f.S)
    f["log_basis"] = 10000*np.log(positive(f.close)/positive(f.S))
    f["raw_annual"] = f.raw_basis*365/(100*days.where(days>=5))
    f["log_annual"] = f.log_basis*365/(100*days.where(days>=5))
    f["log_convergence"] = -f.log_basis/days.where(days>0)
    f["future"] = f.close
    f["convergence"] = -f.basis/days.where(days>0)
    # Legitimate expiry OI=0 is retained in raw data, but no expiry liquidation signal.
    f["oi_valid"] = f.open_interest.where(days>0) if expiry else f.open_interest*np.nan
    f["doi"] = f.oi_valid.diff()
    f.loc[f.doi.abs()>f.volume, "doi"] = np.nan
    f["Q"] = f.volume/positive(f.oi_valid.shift())
    f["K"] = f.doi/positive(f.volume)
    f["rvol"] = f.volume/positive(prior(f.volume).median())
    f["clv"] = (2*f.close-f.high-f.low)/(f.high-f.low).where(f.high>f.low)
    # All three TR legs are required: a missing prior close is not silently skipped.
    tr = pd.concat([f.high-f.low,(f.high-f.close.shift()).abs(),(f.low-f.close.shift()).abs()],axis=1).max(axis=1,skipna=False)
    f["trbp"] = 10000*tr/positive(f.close.shift())
    f["stress"] = f.trbp/positive(prior(f.trbp).median())
    return f


def minute_series(raw, spot, symbol, expiry, dividends, price_input):
    f = frame_index(raw)
    if f.empty: return pd.DataFrame(columns=["x", "volume", "session_id", "trade_date"])
    if not {'close','volume','session_id','trade_date'}<=set(f):
        return pd.DataFrame(columns=["x", "volume", "session_id", "trade_date"])
    f['close']=positive(f.close)
    f['volume']=pd.to_numeric(f.volume,errors='coerce')
    if price_input == "future": x = f.close
    else:
        s = frame_index(spot).reindex(f.index)
        values=[]
        spot_values=positive(s.get('close',pd.Series(float('nan'),index=f.index)))
        for stamp, price, spot_price in zip(f.index, f.close, spot_values):
            day=stamp.tz_convert('Asia/Shanghai').date()
            days=(pd.Timestamp(expiry).date()-day).days if expiry else None
            values.append(input_value(price_input,float(price),float(spot_price),dividends.points(symbol,day),days))
        x=pd.Series(values,index=f.index,dtype=float)
    return f.assign(x=x)


def minute_daily(frame):
    """Sample OHLC only from synchronized minute closes. No high-minus-high shortcut."""
    rows = []
    if frame.empty: return pd.DataFrame()
    for day,g in frame.groupby("trade_date"):
        day = pd.Timestamp(day).tz_localize("Asia/Shanghai")
        expected = pd.date_range(day+pd.Timedelta(hours=9,minutes=31),periods=120,freq="min").append(pd.date_range(day+pd.Timedelta(hours=13,minutes=1),periods=120,freq="min")).tz_convert("UTC")
        g = g.reindex(expected)
        complete = g.x.notna().all() and g.volume.notna().all() and (g.volume>=0).all()
        if not complete: continue
        den = g.volume.sum()
        center = (g.x*g.volume).sum()/den if den>0 else np.nan
        rows.append(dict(event_time=expected[-1], open=g.x.iloc[0], high=g.x.max(), low=g.x.min(), close=g.x.iloc[-1], center=center, center_gap=g.x.iloc[-1]-center, n=int(g.x.notna().sum()), weight_sum=den, weighted_sum=(g.x*g.volume).sum()))
    return pd.DataFrame(rows).set_index("event_time") if rows else pd.DataFrame()


def minute_diagnostics(frame, price_input):
    vol, confirmations = [], []
    if frame.empty: return pd.Series(dtype=float),pd.Series(dtype=float)
    for _,g in frame.groupby(["trade_date","session_id"]):
        g = g.sort_index()
        # A missing minute starts a new contiguous block, it cannot be bridged.
        block = (g.index.to_series().diff()!=pd.Timedelta(minutes=1)).cumsum()
        for _,chunk in g.groupby(block):
            x = chunk.x
            changes = np.log(positive(x)).diff()*10000 if price_input=="future" else x.diff()
            vol.append(np.sqrt((changes**2).rolling(30,min_periods=30).sum()))
            zs,_,_ = statistics(x,30)
            streak=0;sign=0;episode=0;counts=[]
            for value in zs:
                direction = np.sign(value) if pd.notna(value) and abs(value)>=2 else 0
                streak = streak+1 if direction != 0 and direction==sign else 1 if direction else 0
                if streak==3: episode+=1
                sign=direction
                counts.append(episode if pd.notna(value) else np.nan)
            confirmations.append(pd.Series(counts,index=x.index))
    return pd.concat(vol).sort_index() if vol else pd.Series(dtype=float),pd.concat(confirmations).sort_index() if confirmations else pd.Series(dtype=float)


def metric(code, title, series, unit, formula, meaning, *, reason="样本不足、数据缺失或分母无效", scope="完整历史日线", current=None, current_time=None, current_reason=None):
    if not isinstance(series,pd.Series): series=pd.Series(dtype=float)
    clean=pd.to_numeric(series,errors='coerce').astype(float).replace([np.inf,-np.inf],np.nan)
    valid=clean.dropna()
    value=float(valid.iloc[-1]) if len(valid) else None
    stamp=valid.index[-1].isoformat() if len(valid) else None
    last_missing=bool(len(clean) and pd.isna(clean.iloc[-1]))
    plotted=clean.loc[valid.index[0]:] if len(valid) else clean.iloc[:0]
    return dict(id=code,title=title,value=value,unit=unit,time=stamp,scope=scope,formula=formula,meaning=meaning,
        reason=reason if value is None or last_missing else "",last_valid=last_missing,
        current=current if finite(current) else None,current_time=current_time,current_reason=current_reason,
        current_supported=current_reason is not None or current_time is not None,
        history=[dict(time=t.isoformat(),value=float(v) if pd.notna(v) else None) for t,v in plotted.tail(400).items()])


def collection_center(samples,left,right,category,price_input,dividends,metadata,live,now,*,pair_ratio=None):
    """Receipt observations remain observations; no fabricated exchange minute bars."""
    legs=[left]
    if category!="basis":legs.append(right)
    if price_input!="future":legs.extend(UNDERLYINGS[s[:2]][0] for s in list(legs))
    if category!='basis':legs=required_symbols(category,price_input,left,right)
    legs=list(dict.fromkeys(legs))
    ok,reason=aligned_quotes([live.get(s) for s in legs],now)
    if not ok:return None,None,None,reason
    if samples.empty or "run_id" not in samples:return None,None,None,"尚无连续采集区间"
    if category=='calendar' and pair_ratio is None:pair_ratio=1.
    if category!='basis' and not (finite(pair_ratio) and pair_ratio>0):
        return None,None,None,'缺合约对前一完整交易日匹配比例；不使用当前价格代替'
    tail=live[left];day=pd.Timestamp(tail['observed_at']).tz_convert('Asia/Shanghai').date()
    selected=samples[(samples.run_id==tail['run_id']) & samples.instrument_id.isin(legs)]
    numerator=denominator=0.;first=None;last_x=None;session=None
    for _,g in selected.groupby(['poll','batch'],sort=True):
        group={r.instrument_id:r.to_dict() for _,r in g.iterrows()}
        if not all(s in group for s in legs):numerator=denominator=0.;first=None;continue
        a=group[left];stamp=pd.Timestamp(a['observed_at'])
        source=pd.Timestamp(a.get('source_event_time'))
        if pd.isna(source) or stamp.tz_convert('Asia/Shanghai').date()!=day:continue
        sid=(str(day),source.tz_convert('Asia/Shanghai').hour>=12)
        ok,_=aligned_quotes([group[s] for s in legs],max(pd.Timestamp(group[s]['observed_at']) for s in legs))
        weight=a.get('volume');flags=int(a.get('quality_flags',0))
        if category!='basis':
            other=group[right];other_weight=other.get('volume')
            flags|=int(other.get('quality_flags',0))
            weight=min(weight,other_weight/pair_ratio) if finite(weight) and finite(other_weight) and weight>=0 and other_weight>=0 else None
        if sid!=session or not ok or flags & (8|16|64|128):
            numerator=denominator=0.;first=None;session=sid
        if not ok or not finite(weight) or weight<=0 or flags & (8|16|64|128):continue
        def value(symbol):
            f=group[symbol]['close']
            if price_input=='future':return f
            d=dividends.points(symbol,day);expiry=metadata.get(symbol,{}).get('expiry_date')
            days=(pd.Timestamp(expiry).date()-day).days if expiry else None
            return input_value(price_input,f,group[UNDERLYINGS[symbol[:2]][0]]['close'],d,days)
        if category=='basis':x=value(left)
        else:
            def pair_leg(symbol):
                expiry=metadata.get(symbol,{}).get('expiry_date')
                return (group[symbol]['close'],group.get(UNDERLYINGS[symbol[:2]][0],{}).get('close'),
                        dividends.points(symbol,day),(pd.Timestamp(expiry).date()-day).days if expiry else None)
            fa,sa,da,ta=pair_leg(left);fb,sb,db,tb=pair_leg(right)
            x=pair_value(category,price_input,future_a=fa,future_b=fb,spot_a=sa,spot_b=sb,
                         dividend_a=da,dividend_b=db,days_a=ta,days_b=tb)
        if not finite(x):numerator=denominator=0.;first=None;continue
        first=first or stamp;last_x=x
        numerator+=x*weight;denominator+=weight
    if not denominator:return None,None,None,"有效增量量权重不足；首次/重连/跨会话从新基准开始"
    center=numerator/denominator
    note='；合约对匹配容量代理 min(增量V_A,增量V_B/h)，非实际配对成交' if category!='basis' else ''
    return center,last_x-center,str(tail['source_event_time']),f"采集区间 {first.tz_convert('Asia/Shanghai').strftime('%H:%M:%S')} 起；HTTP接收区间增量量加权，非开盘以来VWAP/交易所分钟线"+note


def calculate(left, right, category, price_input, data, minute_data, metadata, dividends, calendar, live, as_of, *, carry_inputs=None, etf_mapping=None, participation=None):
    """One fixed contract/pair per calculation; UI may select another afterwards."""
    rows=[]; unit=INPUTS[price_input][1]
    empty=pd.DataFrame(columns=FIELDS,index=calendar)
    def get(symbol):
        if not symbol or symbol[:2] not in UNDERLYINGS: return empty.copy()
        spot=UNDERLYINGS[symbol[:2]][0]
        return single(data.get(symbol,empty),data.get(spot,empty),symbol,metadata.get(symbol,{}).get("expiry_date"),dividends,calendar)
    a=get(left); b=get(right) if right and right.endswith(".CFE") else None
    spot_a=UNDERLYINGS[left[:2]][0]
    ma=minute_series(minute_data.get(left,pd.DataFrame()),minute_data.get(spot_a,pd.DataFrame()),left,metadata.get(left,{}).get("expiry_date"),dividends,price_input)
    mb=None
    if b is not None:
        mb=minute_series(minute_data.get(right,pd.DataFrame()),minute_data.get(UNDERLYINGS[right[:2]][0],pd.DataFrame()),right,metadata.get(right,{}).get("expiry_date"),dividends,price_input)
    legacy_x=a[price_input] if b is None else a[price_input]-b[price_input]
    x=legacy_x if b is None else pair_series(a,b,category,price_input)
    pair_meta=pair_definition(category,price_input) if b is not None else None
    if pair_meta:unit=pair_meta['unit']
    quantities=pair_quantities(a,b,category,left,right) if b is not None else None
    minute=ma.copy()
    if b is not None:
        minute=pair_minute_frame(ma,mb,frame_index(minute_data.get(spot_a,pd.DataFrame())),
            frame_index(minute_data.get(UNDERLYINGS[right[:2]][0],pd.DataFrame())),
            left,right,metadata,dividends,category,price_input,quantities)
    def add(code,title,s,u,formula,meaning,**kwargs):
        if ((code.startswith("B01") and (price_input!="future" or category!="basis")) or
            (code.startswith("B07") and b is not None and price_input!="future") or
            (code.startswith("B11") and price_input!="future")):
            kwargs.setdefault("scope","完整历史日内·同步分钟收盘观测")
        if code.startswith(("B03","B04","B05","B06")):
            kwargs.setdefault("reason","对应历史OI缺失、到期归零、净变化异常或增仓权重为零；不使用HTTP零OI")
        elif code.startswith("A03"):
            kwargs.setdefault("reason","需固定合约/合约对的连续窗口：Z/分位20个先前值，五期变化6个值；方差须有效")
        elif code.startswith(("B01","B02","B07","B11","A11","A12")):
            kwargs.setdefault("reason","对应频率字段缺失、同步/连续窗口不足或分母无效；不从两腿日线反推基差OHLC")
        row=metric(code,title,s,u,formula,meaning,**kwargs)
        version=PAIR_FORMULA_VERSION if b is not None else 'nonregression-v2'
        row.update(input_id=price_input, formula_version=version,
                   variant_id=f'{code}:{price_input}:{category}:{version}')
        if pair_meta:
            row.update(pair_construction=pair_meta['construction'],pair_metadata=dict(pair_meta))
            if code!='A03.legacy_percentile30' and ('.legacy_' in code or code.startswith('pair.legacy_')):row['role']='auxiliary'
        required=(6 if code.endswith('change5') or code.startswith('B10') or code.startswith('A07') or code=='B08' else
                  20 if code.startswith('A03.') or code.startswith(('A04.raw_','A05.log_','A06.raw_','A06.log_')) and code.rsplit('_',1)[-1] in ('mean','std','z','percentile') else
                  31 if code=='A11' else 30 if code.startswith('A12') else
                  240 if code.startswith('B02.') and 'collection' not in code else
                  5 if code.startswith('B03') else 20 if code in ('B09','B09.pair.baseline','B11','B11.max','B11.pair.baseline','B09.legacy_log_ratio','B11.legacy_log_ratio') or code.startswith(('B09.A.','B09.B.','B11.A.','B11.B.')) else None)
        if code.startswith('B11.') and code.endswith('.tr'):required=2
        if code.startswith('B03.') and code.endswith('.doi'):required=2
        if code=='A03.legacy_percentile30':required=30
        row['n']=required if row['value'] is not None else None
        row['history_cutoff']=row['time']
        row['source_times']={'observation':row['time']} if row['time'] else {}
        row['input_versions']={'dividend':dividends.version,'dividend_mode':dividends.mode}
        prior_reference=(code.startswith('A03.') and not code.endswith('change5') or
            code.startswith(('A04.raw_','A05.log_','A06.raw_','A06.log_')) and code.rsplit('_',1)[-1] in ('mean','std','z','percentile') or
            code.startswith(('B09','B11')) and not code.endswith('.tr'))
        if row['time'] and prior_reference:
            before=x.index[x.index<pd.Timestamp(row['time'])]
            row['reference_end']=before[-1].isoformat() if len(before) else None
            row['history_cutoff']=row['reference_end']
        rows.append(row)
    live_a=live.get(left); live_s=live.get(spot_a)
    ok,why=aligned_quotes([live_a,live_s],as_of)
    day=pd.Timestamp(as_of).tz_convert("Asia/Shanghai").date()
    expiry=metadata.get(left,{}).get("expiry_date")
    days=(pd.Timestamp(expiry).date()-day).days if expiry else None
    current=adjusted_basis(live_a["close"],live_s["close"],dividends.points(left,day),days) if ok else {}
    current_time=live_a.get("source_event_time") if ok else None
    if hasattr(current_time,"isoformat"): current_time=current_time.isoformat()
    if category=="basis":
        for suffix,title,col,u,formula in (("points","调整基差点数","points","点","F − S + D"),("bp","调整基差","basis","bp","10000 × (F − S + D) / S")):
            add("A01."+suffix,title,a[col],u,formula,"正为升水，负为贴水；D为固定合约的分红情景。",current=current.get(suffix),current_time=current_time,current_reason=why if not ok else dividends.reason or "分红情景缺失时留空")
        add("A02.annual","简单年化基差",a.annual,"年化百分点", "100 × (F−S+D) / S × 365/T","T为实际到期自然日；T<5隐藏当前值。",current=current.get("annual_pct"),current_time=current_time,current_reason="临到期T<5，当前年化隐藏" if days is not None and days<5 else why)
        add("A02.convergence","假设每日收敛量级",a.convergence,"bp/日","−调整基差bp / T (T>0)","假设线性归零的量级，不是已锁定收益。",current=current.get("convergence_bp_day"),current_time=current_time,current_reason=why)
    elif b is not None:
        if category=="calendar":
            points=a.close+a.D-b.close-b.D
            add("A04.points","分红调整跨期点差",points,"点","(F近+D近) − (F远+D远)","近减远；实际盘口与名义金额仍用真实期货。")
            add("A04.bp","分红调整标准化跨期价差",10000*points/positive(a.S),"bp","10000 × 调整点差 / S","两腿同指数、固定具体合约。")
            delta=(pd.Timestamp(metadata[right]["expiry_date"])-pd.Timestamp(metadata[left]["expiry_date"])).days if metadata.get(right,{}).get("expiry_date") and expiry else 0
            carry=100*(positive(b.close+b.D)/positive(a.close+a.D)-1)*365/delta if delta>0 else x*np.nan
            add('A05.legacy_carry','原简单期限持有率（未设近到期门槛，辅助）',carry,'年化百分点','100 × [(F远+D远)/(F近+D近)−1] × 365/到期日间隔','旧口径辅助保留；主值要求两腿T≥5。')
            carry=carry.where(a['T'].ge(5)&b['T'].ge(5))
            add("A05","简单期限持有率",carry,"年化百分点","100 × [(F远+D远)/(F近+D近)−1] × 365/到期日间隔；两腿T≥5","简单口径；不与对数年化混用。")
        else:
            add("A06","同月跨指数调整基差差",a.basis-b.basis,"bp","调整基差bp_A − 调整基差bp_B","先按各自指数标准化，再比较同到期月份。")
        multip_a=MULTIPLIERS[left[:2]];multip_b=MULTIPLIERS[right[:2]]
        h=a.close*multip_a/(b.close*multip_b)
        add("A09.h","等名义 B/A 手数",h,"手/手","F_A × 乘数A / (F_B × 乘数B)","小数手仅为理论金额匹配。")
        add("A09.amountA","A每手名义金额",a.close*multip_a,"元","真实F_A × 乘数A","不使用F+D；名义金额不是保证金。")
        add("A09.amountB","B每手名义金额",b.close*multip_b,"元","真实F_B × 乘数B","不使用基差或分红调整价格。")
        add("A09.rounding","1手A与就近整数B金额差",a.close*multip_a-h.round()*b.close*multip_b,"元","A名义 − round(h) × B名义","取整为0时提示小规模无法匹配，不是下单建议。")
        actual=10000*(np.log(positive(a.close)).diff(5)-np.log(positive(b.close)).diff(5))
        spot_return=10000*(np.log(positive(a.S)).diff(5)-np.log(positive(b.S)).diff(5))
        raw_basis=10000*(np.log(positive(a.close)/positive(a.S))-np.log(positive(b.close)/positive(b.S))).diff(5)
        scenario_move=10000*(np.log(positive(a.close+a.D)/positive(a.close))-np.log(positive(b.close+b.D)/positive(b.close))).diff(5)
        # Ensure every intervening trading observation exists for attribution.
        continuous=a.close.notna().rolling(6).sum().eq(6)&b.close.notna().rolling(6).sum().eq(6)
        for code,title,s,formula in (("actual","实际期货5日对数收益差",actual,"10000 × [Δ5 ln F_A − Δ5 ln F_B]"),("spot","指数收益差贡献",spot_return,"10000 × [Δ5 ln S_A − Δ5 ln S_B]"),("basis","未调基差贡献",raw_basis,"10000 × Δ5 [ln(F_A/S_A)−ln(F_B/S_B)]"),("scenario","分红情景变换差",scenario_move,"10000 × Δ5 [ln((F_A+D_A)/F_A) − ln((F_B+D_B)/F_B)]")):
            valid=continuous
            if code in ('spot','basis'):valid=valid&a.S.notna().rolling(6).sum().eq(6)&b.S.notna().rolling(6).sum().eq(6)
            if code=='scenario':valid=valid&positive(a.close+a.D).notna().rolling(6).sum().eq(6)&positive(b.close+b.D).notna().rolling(6).sum().eq(6)
            add("A07."+code,title,s.where(valid),"bp",formula,"实际期货收益差=指数贡献+未调基差贡献；分红情景变换单列，不计作期货收益。")
    add("X","输入值" if b is None else "合约对输入",x,unit,"x_A" if b is None else pair_meta['construction'],"固定合约对联合输入；先构造序列，再计算历史统计。" if b is not None else "所选输入序列。")
    if b is not None:
        add('pair.legacy_input','原各腿输入之差（辅助）',legacy_x,INPUTS[price_input][1],'x_A−x_B','原不同指数期货点位差，仅作原始点位辅助；不能与新对数bp主值比较。' if category=='cross' and price_input=='future' else '旧单腿变换差，仅作辅助对照。')
        lz,lp,lc=statistics(legacy_x)
        for suffix,series,u in (('mean',prior(legacy_x).mean(),INPUTS[price_input][1]),('std',prior(legacy_x).std(ddof=1),INPUTS[price_input][1]),('z',lz,'倍'),('percentile',lp,'%'),('change5',lc.where(legacy_x.notna().rolling(6).sum().eq(6)),INPUTS[price_input][1])):
            add('pair.legacy_'+suffix,'原输入差统计 '+suffix,series,u,'旧 x_A−x_B 序列的自身统计','辅助保留；不是新合约对主指标。')
    z,pct,change=statistics(x)
    for code,title,s,u,formula in (("mean","此前20期均值",prior(x).mean(),unit,"mean(x[t−20:t−1])"),("std","此前20期样本标准差",prior(x).std(ddof=1),unit,"sample_std(x[t−20:t−1]), ddof=1"),("z","历史Z",z,"倍","(x_t − mean(x[t−20:t−1])) / sample_std"),("percentile","历史半权分位",pct,"%","100 × (历史<x + 0.5×历史=x) / 20"),("change5","五期变化",change,unit,"x_t − x_(t−5)，需连续6个观测")):
        s=s.where(x.notna().rolling(6).sum().eq(6)) if code=="change5" else s
        add("A03."+code,title,s,u,formula,"按固定合约/固定合约对计算；参照窗口不含当前观测。")
    add('A03.legacy_percentile30','固定合约30期≤分位',legacy_percentile(x),'%','100 × N(此前30期x≤当前x)/30','原概览并列处理公式的固定合约扩展；连续到期档位分布由概览独立提供，不替代20期半权分位。')
    rv,events=minute_diagnostics(minute,price_input if b is None else "basis")
    add("A11","短窗实现波动",rv,"bp" if price_input=="future" and b is None else unit,"sqrt(sum(最近30个连续分钟变化²))；真实单腿价格用10000ΔlnF","有符号基差用差分；缺分钟、午休、跨日重置。",scope="完整历史分钟·尾端30分钟")
    add("A12","连续偏离确认",events,"次/会话","此前30分钟Z，同方向|Z|≥2连续3根，每个episode只计一次","每个X独立计算；不使用回归残差。",scope="完整历史分钟·会话累计")
    event_state=minute_events(minute)
    for key,title,event_unit in (('first','事件首次偏离时刻','Unix秒'),('last','事件末次偏离时刻','Unix秒'),('peak','事件峰值绝对Z','倍'),('duration','事件持续分钟根数','根'),('confirmed','事件确认状态','0/1'),('recovered','事件恢复状态','0/1'),('confirmed_at','事件确认时刻','Unix秒'),('recovered_at','事件恢复时刻','Unix秒')):
        add('A12.'+key,title,event_state.get(key,pd.Series(dtype=float)),event_unit,'同会话连续同方向偏离；第3根确认，退出阈值恢复','时刻为源分钟时刻；保留最近已确认或正在持续的事件，缺口重置。',scope='完整历史分钟·事件状态')
    model_values,model_reason=theoretical_cost_band(live_a.get('close') if ok else None,live_s.get('close') if ok else None,days,carry_inputs,as_of,expiry=expiry) if category=='basis' else ({k:None for k in ('fair','deviation','upper','lower','long_space','short_space')},'理论成本带仅适用于可执行期现关系')
    add('A13','理论价偏离',pd.Series(dtype=float),'bp','10000 × (F−Ffair)/S','真实输入的简单融资股息模型；方向性成本另列。',reason=model_reason or '没有已认证历史成本输入',current=model_values['deviation'],current_time=current_time,current_reason=model_reason)
    rows[-1]['input_versions']['carry']={k:carry_inputs.get(k) for k in ('version','known_at','effective_from','effective_to','spot_leg_id','expiry_date')} if isinstance(carry_inputs,dict) else None
    for key,title,model_unit,formula in (('fair','理论期货价格','点','S × [1+(r−q)T/365]'),('deviation','理论价偏离','bp','10000 × (F−Ffair)/S'),('upper','卖期货方向成本上界','点','Ffair + S×short_cost_bp/10000'),('lower','买期货方向成本下界','点','Ffair − S×long_cost_bp/10000'),('long_space','买期货方向带外空间','bp','−deviation − long_cost_bp'),('short_space','卖期货方向带外空间','bp','deviation − short_cost_bp')):
        add('A13.'+key,title,pd.Series(dtype=float),model_unit,formula,'只接受显式真实条款；负空间保留，不构成交易承诺。',reason=model_reason or '没有已认证历史成本输入',current=model_values[key],current_time=current_time,current_reason=model_reason)
        rows[-1]['input_versions']={'carry':{k:carry_inputs.get(k) for k in ('version','known_at','effective_from','effective_to','spot_leg_id','expiry_date')}} if isinstance(carry_inputs,dict) else {}
    if category=="calendar" and b is not None:
        book_ok,book_reason=aligned_quotes([live.get(left),live.get(right)],as_of)
        qa,qb=live.get(left,{}),live.get(right,{})
        for side,title,la,lb in (("buy","买近卖远一档报价","ask_price_1","bid_price_1"),("sell","卖近买远一档报价","bid_price_1","ask_price_1")):
            valid=book_ok and all(finite(q.get(k)) and q[k]>0 for q in (qa,qb) for k in ("bid_price_1","ask_price_1","bid_volume_1","ask_volume_1")) and all(q["bid_price_1"]<=q["ask_price_1"] for q in (qa,qb))
            add("A14."+side,title,pd.Series(dtype=float),"点",f"真实{la}_近 − 真实{lb}_远","源行情日期仍待认证；这是观测报价，不保证成交。",current=qa[la]-qb[lb] if valid else None,current_time=str(qa.get("source_event_time")) if valid else None,current_reason=book_reason,reason="没有历史盘口")
    premium,premium_time,premium_reason=etf_premium(etf_mapping,live,as_of,underlying=spot_a) if category=='basis' else (None,None,'ETF指标仅适用于对应指数的期现关系')
    add("A14.etf","ETF折溢价",pd.Series(dtype=float),"bp","10000 × (ETF/IOPV−1)","显式ETF/IOPV/对应指数映射；同一源时刻校验。",reason="未提供历史ETF/IOPV",current=premium,current_time=premium_time,current_reason=premium_reason)
    if isinstance(etf_mapping,dict):
        rows[-1]['input_versions']['etf_iopv_mapping']={k:etf_mapping.get(k) for k in ('etf_id','iopv_id','underlying_id','version','known_at')}
        rows[-1]['current_source_times']={etf_mapping[k]:live.get(etf_mapping[k],{}).get('source_event_time') for k in ('etf_id','iopv_id') if etf_mapping.get(k)}
        rows[-1]['source_times']=dict(rows[-1]['current_source_times'])
    # B01/B07/B11: actual price OHLC or synchronized minute-close sample OHLC.
    oa=a if price_input=="future" else minute_daily(ma)
    ob=b if price_input=="future" else minute_daily(mb) if mb is not None else None
    if category in ("basis","calendar","cross"):
        opening_frame=oa if category=="basis" else pair_daily(minute)
        opening=opening_frame.get("open",x*np.nan).reindex(calendar)
        closing=opening_frame.get("close",x*np.nan).reindex(calendar)
        gap=opening-x.shift(); intra=closing-opening
        threshold=.0002*a.close.shift() if price_input=="future" and category!='cross' else .02 if price_input.endswith('annual') or price_input=='annual' else 2
        for code,title,s,u,formula in (("gap","开盘偏离",gap,unit,"开盘x − 前收x"),("repair","开盘偏离修复比",-intra/gap.where(gap.abs()>=threshold),"倍","−(收盘x−开盘x)/(开盘x−前收x)")):
            detail="以9:31首个同步分钟收盘观测替代开盘，非两腿日线开盘拼接。" if price_input!="future" or category!="basis" else "真实期货开盘。"
            add("B01."+code,title,s,u,formula,detail+"修复比分母门槛：基差2bp、年化0.02个百分点、真实价格为前收的2bp。")
    md=minute_daily(minute) if b is None else pair_daily(minute)
    add("B02.center","分钟成交量加权中枢",md.get("center",pd.Series(dtype=float)),unit,"Σ(x_m × 匹配量_m)/Σ匹配量_m；匹配量=min(V_A,m,V_B,m/h_t)，完整240分钟" if b is not None else "Σ(x_m × V_A,m) / ΣV_A,m；完整240分钟","匹配容量代理，非实际配对成交；分钟不完整时不称开盘以来中枢。" if b is not None else "权重来自实际合约。分钟不完整时不称开盘以来中枢。",scope="完整历史日内·同步分钟收盘观测")
    add("B02.gap","收盘偏离加权中枢",md.get("center_gap",pd.Series(dtype=float)),unit,"收盘x − 成交量加权中枢","不是逐笔可成交VWAP。",scope="完整历史日内·同步分钟收盘观测")
    drift=weighted(a[price_input].diff(),a.doi.clip(lower=0))
    if b is not None: drift=drift-weighted(b[price_input].diff(),b.doi.clip(lower=0))
    if b is not None:
        add('B03.legacy_difference','原各腿增仓漂移差（辅助）',drift,INPUTS[price_input][1],'weighted(Δx_A,W_A)−weighted(Δx_B,W_B)','保留旧定义；不是合约对漂移。')
        drift=weighted(x.diff(),quantities.positive_weight)
    add("B03","合约对增仓加权漂移" if b is not None else "增仓加权漂移",drift,unit,"Σ5(ΔX × W+)/Σ5W+；W+=min(max(ΔOI_A,0),max(ΔOI_B,0)/h_t)" if b is not None else "Σ5(Δx × max(ΔOI,0)) / Σ5 max(ΔOI,0)，两腿各算后相减","零权重留空；匹配容量代理，非账户配对持仓。" if b is not None else "零权重留空。OI来自具体合约有效历史；不使用实时零OI。")
    for code,title,col,u,formula in (("Q","A换手率","Q","倍","V_t / OI_(t−1)"),("K","A净持仓变化比","K","%","100 × ΔOI_t / V_t"),("doi","A净持仓变化","doi","手","OI_t − OI_(t−1)")):
        series=a[col]*(100 if code=="K" else 1)
        if b is not None:
            series={'Q':quantities.volume/positive(quantities.previous_oi),'K':100*quantities.doi/positive(quantities.volume),'doi':quantities.doi}[code]
            title={'Q':'合约对匹配换手代理','K':'合约对匹配持仓变化比','doi':'合约对匹配持仓变化'}[code]
            formula={'Q':'min(V_A,V_B/h_t) / min(OI_A前,OI_B前/h_t)','K':'100 × 同h匹配OI变化 / 匹配量','doi':'min(OI_A,OI_B/h_t)−min(OI_A前,OI_B前/h_t)'}[code]
        add("B04."+code,title,series,u,formula,"匹配容量代理，非实际账户仓位；到期归零不作减仓信号。" if b is not None else "完整日量与前一交易日有效OI；到期归零不作减仓信号。")
    if b is not None:
        den=a.oi_valid.shift()+b.oi_valid.shift();m=pd.concat([(-a.doi).clip(lower=0),b.doi.clip(lower=0)],axis=1).min(axis=1,skipna=False)
        if category=="calendar":
            for code,title,s,u,formula in (("M","近减远增迁移代理",m,"手","min(max(−ΔOI近,0), max(ΔOI远,0))"),("R","迁移匹配占比",100*m/positive(den),"%","100 × M / (OI近前值+OI远前值)"),("N","两月合计净增率",100*(a.doi+b.doi)/positive(den),"%","100 × (ΔOI近+ΔOI远) / 前期合计OI")):
                add("B05."+code,title,s,u,formula,"仅为净变化形态，不代表账户实际移仓。")
            add("B06","成交与持仓份额偏移",100*(b.volume/positive(a.volume+b.volume)-b.oi_valid.shift()/positive(den)),"百分点","100 × [V远/(V近+V远) − OI远前值/(OI近前值+OI远前值)]","当日流量与前期存量分开。")
        def clv(o):
            if o is None or o.empty: return x*np.nan
            return ((2*o.close-o.high-o.low)/(o.high-o.low).where(o.high>o.low)).reindex(calendar)
        cv=(clv(oa)-clv(ob))/2
        add('B07.legacy_difference','原各腿收盘位置差（辅助）',cv,'倍','(CLV_A−CLV_B)/2','旧单腿收盘位置对比。')
        pair_ohlc=pair_ohlc_statistics(md,calendar)
        add("B07","合约对收盘位置",pair_ohlc['clv'],"倍","(2C_X−H_X−L_X)/(H_X−L_X)","从240个同步合约对分钟观测聚合；绝不以单腿高低价相减。")
        add("B07.volume","双腿量能条件",pd.Series(np.where((a.rvol>=1)&(b.rvol>=1),1.,0.),index=calendar).where(a.rvol.notna()&b.rvol.notna()),"0/1","RVOL_A≥1 且 RVOL_B≥1","保留位置差，不将量能条件当作资金方向。")
        add('B09.legacy_log_ratio','原各腿相对活跃对数比（辅助）',np.log(positive(a.rvol)/positive(b.rvol)),'对数倍数','ln(RVOL_A/RVOL_B)','旧各腿成交活跃比较。')
        add('B09','合约对匹配量活跃度',quantities.volume/positive(prior(quantities.volume).median()),'倍','匹配量_t / median(此前20期匹配量)','完整全日匹配容量代理，非实际配对成交。')
        add('B08','合约对匹配持仓扩张',quantities.growth,'对数增长百分点','100 ln[min(OI_A,t,OI_B,t/h_t)/min(OI_A,t−5,OI_B,t−5/h_t)]','两端冻结同一前收h_t，6点完整；匹配容量代理，非账户持仓。')
        ratio=quantities.h
        cap=pd.concat([a.volume,b.volume/positive(ratio)],axis=1).min(axis=1,skipna=False)
        add("B12.A","双腿成交容量·A侧",cap,"手","min(V_A, V_B/h_t)；跨期h=1，跨品种h来自上一完整交易日","匹配容量代理，非实际配对成交。用户参与比例p时乘p；不是可成交承诺。")
        add("B12.B","双腿成交容量·B侧",cap*ratio,"手","A侧容量 × h","不依赖回归；名义折算使用真实价格。")
        legacy_h=pd.Series(1.,index=calendar) if category=='calendar' else a.close*MULTIPLIERS[left[:2]]/(b.close*MULTIPLIERS[right[:2]])
        legacy_cap=pd.concat([a.volume,b.volume/positive(legacy_h)],axis=1).min(axis=1,skipna=False)
        for suffix,series,u,formula in (('A',legacy_cap,'手','min(V_A,V_B/h_当前)'),('B',legacy_cap*legacy_h,'手','旧A容量×h_当前'),('h',legacy_h,'手/手','F_A,当前M_A/(F_B,当前M_B)，跨期1')):
            add('B12.legacy_'+suffix,'原当前名义折算 '+suffix,series,u,formula,'辅助保留；新匹配容量主值使用前收h。')
        na=a.volume*a.close*MULTIPLIERS[left[:2]];nb=b.volume*b.close*MULTIPLIERS[right[:2]]
        add("B12.balance","名义成交量平衡度",pd.concat([na,nb],axis=1).min(axis=1,skipna=False)/positive(pd.concat([na,nb],axis=1).max(axis=1,skipna=False)),"倍","min(V_A F_A M_A,V_B F_B M_B)/max(...) ","收盘价折算名义规模，不是逐笔成交金额。")
    else:
        add("B09","A相对成交活跃度",a.rvol,"倍","V_t / median(V[t−20:t−1])","仅完整历史日线；不与盘中累计量比较。")
        spot=data.get(spot_a,pd.DataFrame()).reindex(calendar)
        if {"close","high","low"}<=set(spot):
            spot_clv=(2*spot.close-spot.high-spot.low)/(spot.high-spot.low).where(spot.high>spot.low)
            add("B07","期货与指数收盘位置差",(a.clv-spot_clv)/2,"倍","(真实期货CLV − 真实指数CLV)/2","此项固定使用两腿各自真实OHLC，不将日线高低价相减生成基差OHLC。")
    add("B10","五期路径效率",efficiency(x),"倍","(x_t−x_(t−5)) / Σ5|Δx|","允许负基差及过零；零路径长度留空。")
    # Signed inputs use absolute amplitude, normalized by their prior median,
    # never divided by a negative/near-zero prior basis.
    def stress(o, f):
        if price_input=="future": return f.stress
        if o is None or o.empty: return x*np.nan
        o=o.reindex(calendar)
        amp=pd.concat([o.high-o.low,(o.high-o.close.shift()).abs(),(o.low-o.close.shift()).abs()],axis=1).max(axis=1,skipna=False)
        return amp/positive(prior(amp).median())
    sa=stress(oa,a);sb=stress(ob,b) if b is not None else None
    if b is not None:add('B11.legacy_log_ratio','原各腿振幅压力对数比（辅助）',np.log(positive(sa)/positive(sb)),'对数倍数','ln(压力_A/压力_B)','旧各腿压力对比。')
    add("B11","合约对振幅压力" if b is not None else "振幅压力",pair_ohlc['pressure'] if b is not None else sa,"倍","TR_X / median(此前20期TR_X)，TR_X=max(H_X−L_X,|H_X−C_X前|,|L_X−C_X前|)" if b is not None else "真实价TR/前收→自身前20日中位归一；有符号输入用绝对振幅/前20期振幅中位", "合约对OHLC来自同步分钟；绝对振幅不除以有符号价格水平。" if b is not None else "基差OHLC须同步观测聚合；不从两腿日线高低价反推。")
    if b is not None: add("B11.max","双腿最大振幅压力",pd.concat([sa,sb],axis=1).max(axis=1,skipna=False),"倍","max(压力A,压力B)","相对压力差为0时，两腿也可能共同高波动。")
    if b is not None:
        qa,qb=live.get(left),live.get(right)
        pair_ok,pair_reason=aligned_quotes([qa,qb],as_of)
        pair_time=str(qa.get("source_event_time")) if pair_ok else None
        current_values={}
        if pair_ok:
            fa,fb=qa["close"],qb["close"]
            na,nb=fa*MULTIPLIERS[left[:2]],fb*MULTIPLIERS[right[:2]]
            h=na/nb
            current_values.update({"A09.h":h,"A09.amountA":na,"A09.amountB":nb,"A09.rounding":na-round(h)*nb})
            da,db=dividends.points(left,day),dividends.points(right,day)
            if category=="calendar" and da is not None and db is not None:
                current_values["A04.points"]=fa+da-fb-db
                if delta>0 and fa+da>0 and fb+db>0:
                    legacy_carry=100*((fb+db)/(fa+da)-1)*365/delta
                    current_values['A05.legacy_carry']=legacy_carry
                    right_days=(pd.Timestamp(metadata[right]['expiry_date']).date()-day).days
                    current_values['A05']=legacy_carry if days is not None and days>=5 and right_days>=5 else None
                all_ok,_=aligned_quotes([qa,qb,live.get(spot_a)],as_of)
                if all_ok:current_values["A04.bp"]=10000*(fa+da-fb-db)/live[spot_a]["close"]
            if category=="cross":
                spot_b=UNDERLYINGS[right[:2]][0]
                all_ok,_=aligned_quotes([qa,qb,live.get(spot_a),live.get(spot_b)],as_of)
                if all_ok and da is not None and db is not None:
                    current_values["A06"]=10000*((fa-live[spot_a]["close"]+da)/live[spot_a]["close"]-(fb-live[spot_b]["close"]+db)/live[spot_b]["close"])
            va,vb=qa.get("volume_total"),qb.get("volume_total")
            if finite(va) and finite(vb) and va>=0 and vb>=0:
                legacy_ratio=1 if category=="calendar" else h
                legacy_cap=min(va,vb/legacy_ratio)
                current_values.update({'B12.legacy_A':legacy_cap,'B12.legacy_B':legacy_cap*legacy_ratio,'B12.legacy_h':legacy_ratio})
                ratio=ratio_for_day(a,b,category,left,right,pd.Timestamp(as_of))
                cap=min(va,vb/ratio) if ratio is not None else None
                current_values.update({"B12.A":cap,"B12.B":cap*ratio if cap is not None else None,"B12.balance":min(va*na,vb*nb)/max(va*na,vb*nb) if max(va*na,vb*nb)>0 else None})
        for r in rows:
            if r["id"].startswith(("A04","A05","A06","A09","B12")):
                why=pair_reason if not pair_ok else "盘中截至当前累计成交容量，不能与全日量同比" if r["id"].startswith("B12") else "盘中同步观测；分红或指数腿缺失时留空，源日期推定"
                if r['id']=='A05' and pair_ok and current_values.get('A05') is None:
                    why='缺分红/到期信息或任一腿T<5；合约对年化留空'
                if r['id'] in ('B12.A','B12.B') and pair_ok and current_values.get(r['id']) is None:
                    why='缺有效双腿累计量或上一完整交易日h；不以当前价格代替'
                r.update(current=current_values.get(r["id"]),current_time=pair_time,current_supported=True,current_reason=why)
    add_original_and_components(add,a,b,x,ma,mb,oa,ob,minute,calendar,category,price_input,metadata,left,right,participation,quantities=quantities)
    from .intraday import apply
    rows=apply(rows,left=left,right=right,category=category,price=price_input,a=a,b=b,x=x,
               minute_data=minute_data,metadata=metadata,dividends=dividends,live=live,now=as_of)
    if b is not None:
        from .intraday import previous_day
        h_now=ratio_for_day(a,b,category,left,right,pd.Timestamp(as_of))
        ratio_day=previous_day(pd.Timestamp(as_of)) if category=='cross' else None
        weight5=quantities.positive_weight.rolling(5,min_periods=5).sum()
        for row in rows:
            info=dict(row.get('pair_metadata') or pair_meta)
            nominal_ratio=row['id'].startswith('A09.') or row['id'].startswith('B12.legacy_')
            stamp=pd.Timestamp(row['time']) if row.get('time') else quantities.index[-1] if len(quantities) else None
            daily_stamp=next((t for t in reversed(quantities.index) if stamp is not None and t.tz_convert('Asia/Shanghai').date()==stamp.tz_convert('Asia/Shanghai').date()),None)
            historical={}
            if daily_stamp is not None:
                position=quantities.index.get_loc(daily_stamp)
                q=quantities.loc[daily_stamp]
                historical={'time':daily_stamp.isoformat(),'metric_value_time':row.get('time'),
                            'context':'当日匹配容量代理参数；价格构造按construction，不将h加入未含h的价格公式',
                            'ratio_source_time':quantities.index[position-1].isoformat() if category=='cross' and position>0 and finite(q.h) else None}
                values={'effective_h':q.h,'matched_volume':q.volume,'matched_oi':q.oi,'previous_matched_oi':q.previous_oi}
                if row['id'].startswith('B03'):values['weight_sum']=weight5.loc[daily_stamp]
                if row['id'].startswith('B02') and daily_stamp in md.index:values['weight_sum']=md.at[daily_stamp,'weight_sum']
                historical.update({key:float(value) if finite(value) else None for key,value in values.items()})
                if nominal_ratio:
                    ha=a.at[daily_stamp,'close'];hb=b.at[daily_stamp,'close']
                    hn=1. if category=='calendar' and row['id'].startswith('B12.legacy_') else ha*MULTIPLIERS[left[:2]]/(hb*MULTIPLIERS[right[:2]]) if finite(ha) and finite(hb) and hb>0 else None
                    historical={'time':daily_stamp.isoformat(),'metric_value_time':row.get('time'),
                                'effective_h':hn,'ratio_source_time':daily_stamp.isoformat(),
                                'context':'当期名义金额说明；不使用匹配容量主指标的前收h'}
            info['historical']=historical
            info['current']={'time':row.get('current_time'),'effective_h':h_now,
                             'ratio_source_date':str(ratio_day) if ratio_day is not None else None,
                             'context':'当日匹配容量代理的前收h；不替代价格构造'} if row.get('current') is not None else {}
            if nominal_ratio:
                info['ratio']='当期真实价格等名义比例；原跨期容量辅助为1'
                if row.get('current') is not None:
                    ha=live.get(left,{}).get('close');hb=live.get(right,{}).get('close')
                    hn=1. if category=='calendar' and row['id'].startswith('B12.legacy_') else ha*MULTIPLIERS[left[:2]]/(hb*MULTIPLIERS[right[:2]]) if finite(ha) and finite(hb) and hb>0 else None
                    info['current']={'time':row.get('current_time'),'effective_h':hn,
                                     'ratio_source_time':row.get('current_time'),'context':'当前名义金额说明；不是匹配容量主指标的前收h'}
            row.update(pair_metadata=info,pair_construction=row.get('pair_construction') or pair_meta['construction'])
    return rows


class ResearchEngine:
    def __init__(self, model):
        self.model=model; self.cache={}; self.minute_cache={}; self.history_key=None; self.daily={}; self.calendar=None
        self.card_metric_cache={}
        self.observation_cache={}

    def snapshot(self, request):
        model=self.model
        repo=model.configure_repository(False)
        frozen=getattr(model,'_app_capture_frozen',None)
        if frozen is None:frozen=repo.freeze()
        ref=ReferenceBook(model.config.get("reference_file") or None)
        now=pd.Timestamp(request.get("as_of") or pd.Timestamp.now(tz="UTC"))
        symbols=repo.symbols(frozen)
        index_ids={v[0] for v in UNDERLYINGS.values()}
        for symbol in model.config.get("collection_symbols",[]):
            symbols.setdefault(symbol,dict(asset_type="cn_index" if symbol in index_ids else "cn_index_future",market_region="CN"))
        # Read configured ETF/IOPV observations already in the local store only.
        # This does not enable collection, acquire a feed or change native config.
        for mapping in model.config.get('research_etf_iopv_mapping',{}).values():
            if isinstance(mapping,dict):
                for field in ('etf_id','iopv_id'):
                    if mapping.get(field):symbols.setdefault(mapping[field],dict(asset_type='cn_etf_reference',market_region='CN'))
        from dashboard.marketdata.contract_reference import latest_contracts
        metadata=latest_contracts(ref.data)
        # Historical reference is revised research, explicitly not PIT. No price
        # data is filled from reference or from another contract.
        for s in metadata:
            symbols.setdefault(s,dict(asset_type="cn_index_future",market_region="CN"))
        live=model._live(symbols,now)
        all_contracts=sorted(s for s in symbols if s.endswith(".CFE"))
        today=str(now.tz_convert("Asia/Shanghai").date())
        active=[s for s in all_contracts if s in metadata and metadata[s]["listing_date"]<=today<=metadata[s]["expiry_date"]]
        default=next((s for s in active if s.startswith(model.config.get("product","IC")) and metadata[s]["expiry_date"]>today),None)
        selection=None
        if request.get("cards"):
            from .card_data import selections
            selection=selections(request,all_contracts,active,model.config.get("research_contract") or default,metadata,now)
            request=dict(request)
            if selection["pairs"]:
                _,request["left"],request["right"]=selection["pairs"][0]
        left=request.get("left") or model.config.get("research_contract") or default or (active or all_contracts or [None])[0]
        category=request.get("category","basis"); price_input=request.get("price_input","basis")
        if category not in {"basis","calendar","cross"} or price_input not in INPUTS:raise ValueError("未知指标范围或价格输入")
        right=request.get("right")
        if category=="basis": right=UNDERLYINGS[left[:2]][0] if left else None
        elif not right:
            options=[s for s in active if s!=left and (s[:2]==left[:2] and s>left if category=="calendar" else s[2:]==left[2:])]
            right=options[0] if options else None
        dividends=DividendBook.load(model.config.get("dividend_root",""),model.config.get("dividend_scenario_file"),model.config.get("daily_dividend_file"),model.config.get("dividend_mode","fixed_snapshot"),
            contracts=metadata,as_of=now.tz_convert('Asia/Shanghai'),missing_policy=model.config.get('dividend_missing_policy'))
        key=tuple((k,v["version"]) for k,v in frozen.items())
        end_times=[pd.Timestamp(p["max_time"]) for m in frozen.values() for p in m["parts"]]
        history_cutoff=min(now,max(end_times)) if end_times else now
        errors=[]
        history_key=(key,history_cutoff.isoformat())
        if history_key!=self.history_key:
            self.daily={}; self.cache={}; self.minute_cache={}
            self.card_metric_cache={}
            self.observation_cache={}
            self.continuous_cache={}
        required=set(active)|index_ids|{left,right}
        if selection:
            # Continuous distributions need every historical mapped contract;
            # the research indicators below still operate on fixed pairs.
            start_day=str((history_cutoff-pd.DateOffset(months=13)).date())
            required.update(s for s,r in metadata.items() if r['expiry_date']>=start_day and r['listing_date']<=str(history_cutoff.date()))
            required.update(selection["overview_symbols"])
            required.update(s for _,a,b in selection["pairs"] for s in (a,b) if s)
            # B08 needs every fixed member at the historical endpoint, including
            # a contract that has expired between that endpoint and today.
            end_day=str(history_cutoff.tz_convert("Asia/Shanghai").date())
            required.update(s for s,r in metadata.items() if r["listing_date"]<=end_day<r["expiry_date"])
        for symbol in required-{None}:
            if symbol in self.daily:continue
            # A newly listed live contract has no bars at the prior-session
            # history endpoint. Its continuous-slot history uses older contracts.
            listing=metadata.get(symbol,{}).get('listing_date')
            if listing and listing>str(history_cutoff.tz_convert('Asia/Shanghai').date()):continue
            try:
                self.daily[symbol]=frame_index(repo.read_window(symbol,"1d",count=400,as_of=history_cutoff,fields=FIELDS,frozen=frozen))
            except ValueError as exc: errors.append(str(exc))
        if history_key!=self.history_key:
            # Include futures sessions too: a whole missing index day must remain
            # visible after futures-only backfill, not silently vanish from windows.
            dates=sorted({t for frame in self.daily.values() for t in frame.index})
            self.calendar,self.history_calendar_reason=complete_history_calendar(dates)
            self.history_key=history_key
        daily=self.daily; calendar=self.calendar
        minute_data={}
        selected={left,right}
        selected.update(UNDERLYINGS[s[:2]][0] for s in (left,right) if s and s.endswith(".CFE"))
        def load_minutes(symbol):
            if symbol not in self.minute_cache:
                try:
                    identifier,ds=repo.locate(symbol,"1m",frozen)
                    start=calendar[max(0,len(calendar)-35)]-pd.Timedelta(hours=8) if len(calendar) else None
                    self.minute_cache[symbol]=ds.read_bars(symbol,"1m",start=start,end=history_cutoff,as_of=history_cutoff,
                        fields=[*FIELDS,"session_id"],version=frozen[identifier]["version"],allow_unverified_availability=repo.allow_unverified)
                except ValueError:self.minute_cache[symbol]=pd.DataFrame()
            return self.minute_cache[symbol]
        if not selection and request.get('metrics',True):
            for symbol in selected-{None}: minute_data[symbol]=load_minutes(symbol)
        metric_rows=[]
        pair_error=None
        if category=="calendar" and (not right or right[:2]!=left[:2] or right<=left): pair_error="跨期需要同品种近月/远月，且近月在前"
        if category=="cross" and (not right or right[:2]==left[:2] or (
            not request.get('allow_mixed_expiry') and (right[2:]!=left[2:] or metadata.get(left,{}).get("expiry_date")!=metadata.get(right,{}).get("expiry_date")))): pair_error="跨指数需要不同品种；普通同月视图要求相同到期日"
        if left and len(calendar) and not pair_error and not selection and request.get('metrics',True):
            carry=model.config.get('research_carry_inputs',{}).get(left)
            mappings=model.config.get('research_etf_iopv_mapping',{})
            mapping=mappings.get(left,mappings.get(left[:2]))
            reference_key=tuple((s,repr(r)) for s,r in sorted(metadata.items()))
            live_key=tuple((s,repr(q),quote_quality(q,now)['status']) for s,q in sorted(live.items()))
            # Timestamp-sensitive input validity participates even when quotes do
            # not change. Full-source identity prevents stale results reappearing.
            known_valid=None
            if isinstance(carry,dict):
                try:known_valid=pd.Timestamp(carry.get('known_at'))<=now
                except (ValueError,TypeError):known_valid=False
            cache_key=(PAIR_FORMULA_VERSION if category!='basis' else 'nonregression-v2',history_key,reference_key,dividends.version,dividends.mode,dividends.reason,
                       category,price_input,left,right,str(now.tz_convert('Asia/Shanghai').date()),
                       live_key,repr(carry),repr(mapping),repr(request.get('participation')),known_valid)
            if cache_key not in self.cache:
                if len(self.cache)>=48:self.cache.clear()
                self.cache[cache_key]=calculate(left,right,category,price_input,daily,minute_data,metadata,dividends,calendar,live,now,
                    carry_inputs=carry,etf_mapping=mapping,participation=request.get('participation'))
            metric_rows=deepcopy(self.cache[cache_key])
            pair_ratio=ratio_for_day(daily.get(left,pd.DataFrame()),daily.get(right,pd.DataFrame()),category,left,right,now) if category!='basis' else None
            center,gap,stamp,note=collection_center(model.live_rows,left,right,category,price_input,dividends,metadata,live,now,pair_ratio=pair_ratio)
            for suffix,title,value in (("collection_center","采集区间成交量加权中枢",center),("collection_gap","采集区间中枢偏离",gap)):
                metric_rows.append(metric("B02."+suffix,title,pd.Series(dtype=float),INPUTS[price_input][1],"Σ(同步观测x × 有效增量V_A) / Σ有效增量V_A",note,
                    scope="采集以来·HTTP观测",reason="此项不是完整历史分钟指标",current=value,current_time=stamp,current_reason=note))
                metric_rows[-1]['current_scope']='采集区间'
            if category=="cross":
                end=str(calendar[-1].tz_convert("Asia/Shanghai").date())
                months={s[2:] for s,r in metadata.items() if s.startswith(left[:2]) and r["listing_date"]<=end<r["expiry_date"]}&{s[2:] for s,r in metadata.items() if s.startswith(right[:2]) and r["listing_date"]<=end<r["expiry_date"]}
                growth=[]
                for product in (left[:2],right[:2]):
                    ids=sorted(product+m for m in months)
                    frames=[]
                    for s in ids:
                        f=daily.get(s,pd.DataFrame()).reindex(calendar)
                        oi=f.get("open_interest",pd.Series(np.nan,index=calendar))
                        oi=oi.where(calendar.tz_convert("Asia/Shanghai").strftime("%Y-%m-%d")<metadata[s]["expiry_date"])
                        frames.append(oi.rename(s))
                    total=pd.concat(frames,axis=1).sum(axis=1,min_count=len(frames)) if frames else pd.Series(np.nan,index=calendar)
                    g=100*np.log(positive(total)/positive(total.shift(5)))
                    growth.append(g.where(total.notna().rolling(6).sum().eq(6)))
                metric_rows.append(metric("B08.legacy_collection","原同组月份持仓扩张差（辅助）",growth[0]-growth[1],"对数增长百分点","100 × [ln(OI_A合计/OI_A合计前5日) − ln(OI_B合计/OI_B合计前5日)]", "固定月份集合 "+", ".join(sorted(months))+"；全组齐备、到期前才更新，不拼接换月。"))
                metric_rows[-1]['role']='auxiliary'
        if not selection and metric_rows:
            from .intraday import observations
            observations(metric_rows,model.live_rows,left,right,category,price_input,daily,minute_data,metadata,dividends,now,self.observation_cache)
        quote_rows=[]
        visible=list(dict.fromkeys([*(active or model.config.get("collection_symbols",[])),*sorted(index_ids)]))
        for symbol in visible:
            q=live.get(symbol,{})
            quality=quote_quality(q,now)
            history=daily.get(symbol,pd.DataFrame())
            oi=history.get("open_interest",pd.Series(dtype=float)).dropna()
            change=(q["close"]/q["prev_close"]-1)*100 if finite(q.get("close")) and finite(q.get("prev_close")) and q["prev_close"]>0 else None
            quote_rows.append(dict(symbol=symbol,**{k:q.get(k) for k in ("close","prev_close","open","high","low","volume_total","volume","bid_price_1","bid_volume_1","ask_price_1","ask_volume_1","open_interest","open_interest_raw","oi_status","oi_reason","quote_time","source_event_time","received_at","date_status","is_final","snapshot_status")},
                change_pct=change,quality=quality,expiry=metadata.get(symbol,{}).get("expiry_date"),
                history_oi=float(oi.iloc[-1]) if len(oi) else None,history_oi_date=str(oi.index[-1].tz_convert("Asia/Shanghai").date()) if len(oi) else None))
        coverage=[]
        for dataset in repo.catalog(frozen):
            groups={}
            for p in dataset["parts"]:
                group=(p["instrument_id"][:2] if p["instrument_id"].endswith(".CFE") else p["instrument_id"],p["frequency"])
                row=groups.setdefault(group,dict(product=group[0],frequency=group[1],first=p["min_time"],last=p["max_time"],symbols=set()))
                row["first"]=min(row["first"],p["min_time"]);row["last"]=max(row["last"],p["max_time"]);row["symbols"].add(p["instrument_id"])
            coverage.extend([{**r,"symbols":len(r["symbols"]),"dataset_id":dataset["dataset_id"]} for r in groups.values()])
        state=dict(as_of=now.isoformat(),product=left[:2] if left else "IC",frequency="1d",demo=False,versions=dict(key),spread=pd.DataFrame(),
            quotes=quote_rows,metrics=metric_rows,coverage=coverage,contracts=all_contracts,active_contracts=active,
            left=left,right=right,category=category,price_input=price_input,pair_error=pair_error,errors=errors,
            dividend_info=dividends.info,dividend_reason=dividends.reason,dividend_mode=dividends.mode,dividend_version=dividends.version,
            history_calendar_reason=getattr(self,'history_calendar_reason',''))
        if selection:
            from .card_data import dashboard_cards
            state.update(dashboard_cards(self,state,request,selection,daily,calendar,metadata,dividends,live,now,load_minutes))
        return state
