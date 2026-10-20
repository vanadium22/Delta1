"""A/B research on fixed contracts. No regression, C indicators or trading logic.

Missing dates are reindexed to the observed index calendar before differences;
intraday rolling windows are calculated separately in each continuous session.
"""
from itertools import combinations
import math
import numpy as np
import pandas as pd

from dashboard.marketdata.dividends import DividendBook, adjusted_basis
from dashboard.marketdata.quote_quality import aligned_quotes, quote_quality, finite
from dashboard.marketdata.repository import ReferenceBook
from .instruments import UNDERLYINGS

MULTIPLIERS = {"IF":300, "IH":300, "IC":200, "IM":200}
FIELDS = ("open", "high", "low", "close", "volume", "open_interest", "turnover", "prev_close")
INPUTS = {"future":("真实期货价格", "点"), "basis":("分红调整基差", "bp"), "annual":("分红调整年化基差", "年化百分点")}


def prior(s, n=20):
    return s.shift().rolling(n, min_periods=n)


def statistics(s, n=20):
    sigma = prior(s,n).std(ddof=1)
    z = (s-prior(s,n).mean())/sigma.where(sigma > 1e-12)
    pct = s.rolling(n+1,min_periods=n+1).apply(lambda x:100*((x[:-1]<x[-1]).sum()+.5*(x[:-1]==x[-1]).sum())/n,raw=True)
    return z, pct, s.diff(5)


def weighted(delta, weight, n=5):
    valid = delta.notna() & weight.notna() & (weight >= 0)
    den = weight.where(valid).rolling(n,min_periods=n).sum()
    return (delta*weight).where(valid).rolling(n,min_periods=n).sum()/den.where(den>0)


def efficiency(s, n=5):
    den = s.diff().abs().rolling(n,min_periods=n).sum()
    return s.diff(n)/den.where(den>1e-12)


def positive(s):
    return s.where(s>0)


def frame_index(frame):
    if frame.empty: return pd.DataFrame(columns=FIELDS, index=pd.DatetimeIndex([],tz="UTC"))
    # Provenance remains on repository results. Research arithmetic uses the
    # frozen manifest separately; copying a full instrument registry on every
    # pandas slice/rolling operation is unnecessary and very expensive.
    frame = frame.copy(deep=False)
    frame.attrs = {}
    return frame.set_index("event_time").sort_index()


def single(f, spot, symbol, expiry, dividends, calendar):
    f = f.reindex(calendar).copy()
    for c in FIELDS:
        if c not in f: f[c] = np.nan
        else: f[c] = pd.to_numeric(f[c],errors='coerce')
    spot = spot.reindex(calendar)
    f["S"] = spot.get("close", pd.Series(np.nan,index=calendar))
    days = pd.Series([(pd.Timestamp(expiry).date()-t.tz_convert("Asia/Shanghai").date()).days for t in calendar], index=calendar) if expiry else pd.Series(np.nan,index=calendar)
    f["T"] = days
    f["D"] = [dividends.points(symbol,t.tz_convert("Asia/Shanghai").date()) for t in calendar]
    f["D"] = pd.to_numeric(f.D,errors="coerce")
    f["points"] = f.close-f.S+f.D
    f["basis"] = 10000*f.points/positive(f.S)
    f["annual"] = f.basis*365/(100*days.where(days>=5))
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
    if price_input == "future": x = f.close
    else:
        s = frame_index(spot).reindex(f.index)
        d = pd.Series([dividends.points(symbol,t.tz_convert("Asia/Shanghai").date()) for t in f.index],index=f.index,dtype=float)
        x = 10000*(f.close-s.get("close",np.nan)+d)/s.get("close",pd.Series(np.nan,index=f.index))
        if price_input == "annual":
            days = pd.Series([(pd.Timestamp(expiry).date()-t.tz_convert("Asia/Shanghai").date()).days for t in f.index],index=f.index) if expiry else pd.Series(np.nan,index=f.index)
            x = x*365/(100*days.where(days>=5))
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
        rows.append(dict(event_time=expected[-1], open=g.x.iloc[0], high=g.x.max(), low=g.x.min(), close=g.x.iloc[-1], center=center, center_gap=g.x.iloc[-1]-center))
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
    clean=series.replace([np.inf,-np.inf],np.nan)
    valid=clean.dropna()
    value=float(valid.iloc[-1]) if len(valid) else None
    stamp=valid.index[-1].isoformat() if len(valid) else None
    last_missing=bool(len(clean) and pd.isna(clean.iloc[-1]))
    plotted=clean.loc[valid.index[0]:] if len(valid) else clean.iloc[:0]
    return dict(id=code,title=title,value=value,unit=unit,time=stamp,scope=scope,formula=formula,meaning=meaning,
        reason=reason if value is None or last_missing else "",last_valid=last_missing,
        current=current if finite(current) else None,current_time=current_time,current_reason=current_reason,
        history=[dict(time=t.isoformat(),value=float(v) if pd.notna(v) else None) for t,v in plotted.tail(400).items()])


def collection_center(samples,left,right,category,price_input,dividends,metadata,live,now):
    """Receipt observations remain observations; no fabricated exchange minute bars."""
    legs=[left]
    if category!="basis":legs.append(right)
    if price_input!="future":legs.extend(UNDERLYINGS[s[:2]][0] for s in list(legs))
    legs=list(dict.fromkeys(legs))
    ok,reason=aligned_quotes([live.get(s) for s in legs],now)
    if not ok:return None,None,None,reason
    if samples.empty or "run_id" not in samples:return None,None,None,"尚无连续采集区间"
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
        if sid!=session or not ok or flags & (8|16|64|128):
            numerator=denominator=0.;first=None;session=sid
        if not ok or not finite(weight) or weight<=0 or flags & (8|16|64|128):continue
        def value(symbol):
            f=group[symbol]['close']
            if price_input=='future':return f
            d=dividends.points(symbol,day);expiry=metadata.get(symbol,{}).get('expiry_date')
            days=(pd.Timestamp(expiry).date()-day).days if expiry else None
            values=adjusted_basis(f,group[UNDERLYINGS[symbol[:2]][0]]['close'],d,days)
            return values['bp' if price_input=='basis' else 'annual_pct']
        x=value(left);y=value(right) if category!='basis' else 0.
        if not finite(x) or not finite(y):numerator=denominator=0.;first=None;continue
        x-=y;first=first or stamp;last_x=x
        numerator+=x*weight;denominator+=weight
    if not denominator:return None,None,None,"有效增量量权重不足；首次/重连/跨会话从新基准开始"
    center=numerator/denominator
    return center,last_x-center,str(tail['source_event_time']),f"采集区间 {first.tz_convert('Asia/Shanghai').strftime('%H:%M:%S')} 起；HTTP接收区间增量量加权，非开盘以来VWAP/交易所分钟线"


def calculate(left, right, category, price_input, data, minute_data, metadata, dividends, calendar, live, as_of):
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
    x=a[price_input] if b is None else a[price_input]-b[price_input]
    if category=="cross" and price_input=="future":
        # Different index points are not comparable: do not subtract raw index levels.
        x=pd.Series(np.nan,index=calendar)
    minute=ma.copy()
    if mb is not None and len(ma): minute["x"]=ma.x-mb.x.reindex(ma.index)
    if category=="cross" and price_input=="future" and len(minute): minute["x"]=np.nan
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
        rows.append(metric(code,title,s,u,formula,meaning,**kwargs))
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
        add("A02.annual","简单年化基差",a.annual,"%", "100 × (F−S+D) / S × 365/T","T为实际到期自然日；T<5隐藏当前值。",current=current.get("annual_pct"),current_time=current_time,current_reason="临到期T<5，当前年化隐藏" if days is not None and days<5 else why)
        add("A02.convergence","假设每日收敛量级",a.convergence,"bp/日","−调整基差bp / T (T>0)","假设线性归零的量级，不是已锁定收益。",current=current.get("convergence_bp_day"),current_time=current_time,current_reason=why)
    elif b is not None:
        if category=="calendar":
            points=a.close+a.D-b.close-b.D
            add("A04.points","分红调整跨期点差",points,"点","(F近+D近) − (F远+D远)","近减远；实际盘口与名义金额仍用真实期货。")
            add("A04.bp","分红调整标准化跨期价差",10000*points/positive(a.S),"bp","10000 × 调整点差 / S","两腿同指数、固定具体合约。")
            delta=(pd.Timestamp(metadata[right]["expiry_date"])-pd.Timestamp(metadata[left]["expiry_date"])).days if metadata.get(right,{}).get("expiry_date") and expiry else 0
            carry=100*((b.close+b.D)/(a.close+a.D)-1)*365/delta if delta>0 else x*np.nan
            add("A05","简单期限持有率",carry,"%","100 × [(F远+D远)/(F近+D近)−1] × 365/到期日间隔","简单口径；不与对数年化混用。")
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
            add("A07."+code,title,s.where(continuous),"bp",formula,"实际期货收益差=指数贡献+未调基差贡献；分红情景变换单列，不计作期货收益。")
    add("X","输入值" if b is None else "输入差",x,unit,"x_A" if b is None else "x_A − x_B","所选输入序列；双腿各按自己的指数、分红和到期日计算。")
    z,pct,change=statistics(x)
    for code,title,s,u,formula in (("z","历史Z",z,"倍","(x_t − mean(x[t−20:t−1])) / sample_std"),("percentile","历史半权分位",pct,"%","100 × (历史<x + 0.5×历史=x) / 20"),("change5","五期变化",change,unit,"x_t − x_(t−5)，需连续6个观测")):
        s=s.where(x.notna().rolling(6).sum().eq(6)) if code=="change5" else s
        add("A03."+code,title,s,u,formula,"按固定合约/固定合约对计算；参照窗口不含当前观测。")
    rv,events=minute_diagnostics(minute,price_input if b is None else "basis")
    if price_input!="basis" and category in ("basis","calendar"):
        em=minute_series(minute_data.get(left,pd.DataFrame()),minute_data.get(spot_a,pd.DataFrame()),left,expiry,dividends,"basis")
        if category=="calendar" and len(em):
            other=minute_series(minute_data.get(right,pd.DataFrame()),minute_data.get(spot_a,pd.DataFrame()),right,metadata.get(right,{}).get("expiry_date"),dividends,"basis")
            em["x"]=em.x-other.get("x",pd.Series(dtype=float)).reindex(em.index)
        _,events=minute_diagnostics(em,"basis")
    add("A11","短窗实现波动",rv,"bp" if price_input=="future" and b is None else unit,"sqrt(sum(最近30个连续分钟变化²))；真实单腿价格用10000ΔlnF","有符号基差用差分；缺分钟、午休、跨日重置。",scope="完整历史分钟·尾端30分钟")
    if category in ("basis","calendar"):
        add("A12","基差/跨期连续偏离确认",events,"次/会话","此前30分钟Z，同方向|Z|≥2连续3根，每个episode只计一次","此项固定使用调整基差/跨期bp；跨会话重置。",scope="完整历史分钟·会话累计")
    add("A13","理论价成本带",pd.Series(dtype=float),"bp","需融资、分红、方向性交易成本","未取得融资和成本输入，不硬编码为实测。",reason="缺少融资利率、交易成本及可交易现货腿")
    if category=="calendar" and b is not None:
        book_ok,book_reason=aligned_quotes([live.get(left),live.get(right)],as_of)
        qa,qb=live.get(left,{}),live.get(right,{})
        for side,title,la,lb in (("buy","买近卖远一档报价","ask_price_1","bid_price_1"),("sell","卖近买远一档报价","bid_price_1","ask_price_1")):
            valid=book_ok and all(finite(q.get(k)) and q[k]>0 for q in (qa,qb) for k in ("bid_price_1","ask_price_1","bid_volume_1","ask_volume_1")) and all(q["bid_price_1"]<=q["ask_price_1"] for q in (qa,qb))
            add("A14."+side,title,pd.Series(dtype=float),"点",f"真实{la}_近 − 真实{lb}_远","源行情日期仍待认证；这是观测报价，不保证成交。",current=qa[la]-qb[lb] if valid else None,current_time=str(qa.get("source_event_time")) if valid else None,current_reason=book_reason,reason="没有历史盘口")
    add("A14.etf","ETF折溢价",pd.Series(dtype=float),"bp","10000 × (ETF/IOPV−1)","需ETF、IOPV及同步时间。",reason="未提供ETF/IOPV")
    # B01/B07/B11: actual price OHLC or synchronized minute-close sample OHLC.
    oa=a if price_input=="future" else minute_daily(ma)
    ob=b if price_input=="future" else minute_daily(mb) if mb is not None else None
    if category in ("basis","calendar","cross"):
        opening_frame=oa if category=="basis" else minute_daily(minute)
        opening=opening_frame.get("open",x*np.nan).reindex(calendar)
        closing=opening_frame.get("close",x*np.nan).reindex(calendar)
        gap=opening-x.shift(); intra=closing-opening
        threshold=2 if price_input=="basis" else .02 if price_input=="annual" else .0002*a.close.shift()
        for code,title,s,u,formula in (("gap","开盘偏离",gap,unit,"开盘x − 前收x"),("repair","开盘偏离修复比",-intra/gap.where(gap.abs()>=threshold),"倍","−(收盘x−开盘x)/(开盘x−前收x)")):
            detail="以9:31首个同步分钟收盘观测替代开盘，非两腿日线开盘拼接。" if price_input!="future" or category!="basis" else "真实期货开盘。"
            add("B01."+code,title,s,u,formula,detail+"修复比分母门槛：基差2bp、年化0.02个百分点、真实价格为前收的2bp。")
    md=minute_daily(minute)
    add("B02.center","分钟成交量加权中枢",md.get("center",pd.Series(dtype=float)),unit,"Σ(x_m × V_A,m) / ΣV_A,m；完整240分钟","权重来自实际合约。分钟不完整时不称开盘以来中枢。",scope="完整历史日内·同步分钟收盘观测")
    add("B02.gap","收盘偏离加权中枢",md.get("center_gap",pd.Series(dtype=float)),unit,"收盘x − 成交量加权中枢","不是逐笔可成交VWAP。",scope="完整历史日内·同步分钟收盘观测")
    drift=weighted(a[price_input].diff(),a.doi.clip(lower=0))
    if b is not None: drift=drift-weighted(b[price_input].diff(),b.doi.clip(lower=0))
    add("B03","增仓加权漂移"+("差" if b is not None else ""),drift,unit,"Σ5(Δx × max(ΔOI,0)) / Σ5 max(ΔOI,0)，两腿各算后相减","零权重留空。OI来自具体合约有效历史；不使用实时零OI。")
    for code,title,col,u,formula in (("Q","A换手率","Q","倍","V_t / OI_(t−1)"),("K","A净持仓变化比","K","%","100 × ΔOI_t / V_t"),("doi","A净持仓变化","doi","手","OI_t − OI_(t−1)")):
        add("B04."+code,title,a[col]*(100 if code=="K" else 1),u,formula,"完整日量与前一交易日有效OI；到期归零不作减仓信号。")
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
        add("B07","收盘位置差",cv,"倍","(CLV_A−CLV_B)/2；CLV=(2C−H−L)/(H−L)","真实价用各腿日线OHLC；基差用同步分钟收盘观测聚合OHLC。")
        add("B07.volume","双腿量能条件",pd.Series(np.where((a.rvol>=1)&(b.rvol>=1),1.,0.),index=calendar).where(a.rvol.notna()&b.rvol.notna()),"0/1","RVOL_A≥1 且 RVOL_B≥1","保留位置差，不将量能条件当作资金方向。")
        add("B09","相对成交活跃度",np.log(positive(a.rvol)/positive(b.rvol)),"对数倍数","ln[(V_A/前20日量中位数)/(V_B/前20日量中位数)]","仅完整全日日量，不用盘中累计量混算。")
        ratio=pd.Series(1.,index=calendar) if category=="calendar" else a.close*MULTIPLIERS[left[:2]]/(b.close*MULTIPLIERS[right[:2]])
        cap=pd.concat([a.volume,b.volume/positive(ratio)],axis=1).min(axis=1,skipna=False)
        add("B12.A","双腿成交容量·A侧",cap,"手","min(V_A, V_B/h)；跨期h=1，跨指数h=等名义手数","按100%已发生成交量折算的容量基数。用户参与比例p时乘p；不是可成交承诺。")
        add("B12.B","双腿成交容量·B侧",cap*ratio,"手","A侧容量 × h","不依赖回归；名义折算使用真实价格。")
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
    add("B11","相对振幅压力" if b is not None else "振幅压力",np.log(positive(sa)/positive(sb)) if b is not None else sa,"对数倍数" if b is not None else "倍","真实价TR/前收→自身前20日中位归一；有符号输入用绝对振幅/前20期振幅中位", "基差OHLC须同步观测聚合；不从两腿日线高低价反推。")
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
                if delta>0:current_values["A05"]=100*((fb+db)/(fa+da)-1)*365/delta
                all_ok,_=aligned_quotes([qa,qb,live.get(spot_a)],as_of)
                if all_ok:current_values["A04.bp"]=10000*(fa+da-fb-db)/live[spot_a]["close"]
            if category=="cross":
                spot_b=UNDERLYINGS[right[:2]][0]
                all_ok,_=aligned_quotes([qa,qb,live.get(spot_a),live.get(spot_b)],as_of)
                if all_ok and da is not None and db is not None:
                    current_values["A06"]=10000*((fa-live[spot_a]["close"]+da)/live[spot_a]["close"]-(fb-live[spot_b]["close"]+db)/live[spot_b]["close"])
            va,vb=qa.get("volume_total"),qb.get("volume_total")
            if finite(va) and finite(vb) and va>=0 and vb>=0:
                ratio=1 if category=="calendar" else h
                cap=min(va,vb/ratio)
                current_values.update({"B12.A":cap,"B12.B":cap*ratio,"B12.balance":min(va*na,vb*nb)/max(va*na,vb*nb) if max(va*na,vb*nb)>0 else None})
        for r in rows:
            if r["id"].startswith(("A04","A05","A06","A09","B12")):
                r.update(current=current_values.get(r["id"]),current_time=pair_time,
                    current_reason=pair_reason if not pair_ok else "盘中截至当前累计成交容量，不能与全日量同比" if r["id"].startswith("B12") else "盘中同步观测；分红或指数腿缺失时留空，源日期推定")
    from .intraday import apply
    return apply(rows,left=left,right=right,category=category,price=price_input,a=a,b=b,x=x,
                 minute_data=minute_data,metadata=metadata,dividends=dividends,live=live,now=as_of)


class ResearchEngine:
    def __init__(self, model):
        self.model=model; self.cache={}; self.minute_cache={}; self.history_key=None; self.daily={}; self.calendar=None
        self.card_metric_cache={}
        self.observation_cache={}

    def snapshot(self, request):
        model=self.model
        repo=model.configure_repository(False); frozen=repo.freeze()
        ref=ReferenceBook(model.config.get("reference_file") or None)
        now=pd.Timestamp(request.get("as_of") or pd.Timestamp.now(tz="UTC"))
        symbols=repo.symbols(frozen)
        index_ids={v[0] for v in UNDERLYINGS.values()}
        for symbol in model.config.get("collection_symbols",[]):
            symbols.setdefault(symbol,dict(asset_type="cn_index" if symbol in index_ids else "cn_index_future",market_region="CN"))
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
            self.calendar=pd.DatetimeIndex(dates,tz="UTC") if not dates else pd.DatetimeIndex(dates)
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
        if not selection:
            for symbol in selected-{None}: minute_data[symbol]=load_minutes(symbol)
        metric_rows=[]
        pair_error=None
        if category=="calendar" and (not right or right[:2]!=left[:2] or right<=left): pair_error="跨期需要同品种近月/远月，且近月在前"
        if category=="cross" and (not right or right[:2]==left[:2] or (
            not request.get('allow_mixed_expiry') and (right[2:]!=left[2:] or metadata.get(left,{}).get("expiry_date")!=metadata.get(right,{}).get("expiry_date")))): pair_error="跨指数需要不同品种；普通同月视图要求相同到期日"
        if category=="cross" and price_input=="future":pair_error="跨指数点位不可直接相减；请选择各自分红调整基差或年化基差"
        if left and len(calendar) and not pair_error and not selection:
            metric_rows=calculate(left,right,category,price_input,daily,minute_data,metadata,dividends,calendar,live,now)
            center,gap,stamp,note=collection_center(model.live_rows,left,right,category,price_input,dividends,metadata,live,now)
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
                metric_rows.append(metric("B08","同组月份持仓扩张差",growth[0]-growth[1],"对数增长百分点","100 × [ln(OI_A合计/OI_A合计前5日) − ln(OI_B合计/OI_B合计前5日)]", "固定月份集合 "+", ".join(sorted(months))+"；全组齐备、到期前才更新，不拼接换月。"))
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
            dividend_info=dividends.info,dividend_reason=dividends.reason,dividend_mode=dividends.mode,dividend_version=dividends.version)
        if selection:
            from .card_data import dashboard_cards
            state.update(dashboard_cards(self,state,request,selection,daily,calendar,metadata,dividends,live,now,load_minutes))
        return state
