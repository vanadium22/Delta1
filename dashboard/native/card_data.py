"""Continuous overview distributions and fixed-contract research, one frozen snapshot."""
from copy import deepcopy
import numpy as np
import pandas as pd

from dashboard.marketdata.dividends import adjusted_basis
from dashboard.marketdata.quote_quality import aligned_quotes, finite, quote_quality
from .instruments import UNDERLYINGS

PRODUCTS = tuple(UNDERLYINGS)
CROSS_PAIRS = (("IM", "IC"), ("IF", "IH"), ("IF", "IC"), ("IF", "IM"), ("IH", "IC"), ("IH", "IM"))
WINDOWS = (("20d", "20交易日"), ("3m", "3个月"), ("6m", "6个月"), ("12m", "12个月"))


def selections(request, contracts, active, default, metadata=None, as_of=None):
    months = sorted({s[2:6] for s in contracts})
    active_months = sorted({s[2:6] for s in active})
    fallback = default[2:6] if default and default[2:6] in months else next(iter(active_months or months), "")
    month = request.get("research_month") or fallback
    overview = request.get("overview_month") or fallback
    far = request.get("far_month") or next((m for m in active_months if m > month), next((m for m in months if m > month), ""))
    category = request.get("category", "basis")
    def symbol(root, expiry_month): return f"{root}{expiry_month}.CFE" if expiry_month else root
    if category == "cross":
        chosen = request.get("cross_pair", "all")
        pairs = [(f"{a} − {b}", symbol(a, month), symbol(b, month)) for a, b in CROSS_PAIRS if chosen in ("all", f"{a}/{b}")]
    else:
        pairs = [(root, symbol(root, month), UNDERLYINGS[root][0] if category == "basis" else symbol(root, far)) for root in PRODUCTS]
    overview_symbols=[symbol(root, overview) for root in PRODUCTS]
    slot=request.get('overview_slot')
    if metadata is not None:
        from .continuous import slot_map
        if slot is None:slot=active_months.index(overview) if overview in active_months else 2
        if type(slot) is not int or slot not in range(4):raise ValueError('连续档位必须是00—03')
        overview_symbols=[slot_map(metadata,root,as_of)[0].get(f'{root}0{slot}.CFE',root) for root in PRODUCTS]
        overview=overview_symbols[0][2:6] if len(overview_symbols[0])>2 else ''
    return dict(months=months, active_months=active_months, research_month=month, overview_month=overview,
                overview_slot=slot,far_month=far, pairs=pairs, overview_symbols=overview_symbols)


def distributions(series, calendar, observation_time, current, *, listing=None, expiry=None, annual=False, eligibility=None, allow_partial=False):
    """Prior-only windows; continuous overview may expose explicitly incomplete samples."""
    day = pd.Timestamp(observation_time).tz_convert("Asia/Shanghai").normalize()
    dates = calendar.tz_convert("Asia/Shanghai").normalize()
    history = series.reindex(calendar).loc[dates < day].replace([np.inf, -np.inf], np.nan)
    results = []
    for key, title in WINDOWS:
        if key == "20d":
            sample = history.tail(20)
            covered = len(sample) == 20
        else:
            start = day - pd.DateOffset(months=int(key[:-1]))
            sample = history.loc[history.index.tz_convert("Asia/Shanghai").normalize() >= start]
            covered = bool(len(calendar) and dates.min() <= start and listing and pd.Timestamp(listing).date() <= start.date())
        expected = len(sample)
        if annual and expiry:
            eligible = np.array([(pd.Timestamp(expiry).date() - t.tz_convert("Asia/Shanghai").date()).days >= 5 for t in sample.index])
            # A 20-observation window requires 20 eligible observations, not fewer.
            covered = covered and (bool(eligible.all()) if key == "20d" else True)
            sample = sample.loc[eligible]
        if eligibility is not None:
            # Known T<5 days are ineligible, whereas unknown mappings remain a
            # missing observation and invalidate the window rather than vanishing.
            sample=sample.loc[eligibility.reindex(sample.index).fillna(True).astype(bool)]
        valid = sample.dropna()
        missing = sample[sample.isna()]
        reason = "窗口起点覆盖不足" if not covered else "有效样本不足 2 日" if len(valid)<2 else f"窗口缺 {len(missing)} 日" if len(missing) else ""
        available = covered and len(valid)>=2 and (allow_partial or not len(missing))
        row = dict(key=key, title=title, n=len(valid), complete=not reason, reason=reason,
                   available=available, missing=len(missing), excluded=expected-len(sample),
                   missing_dates=[str(t.tz_convert('Asia/Shanghai').date()) for t in missing.index],
                   start=sample.index[0].isoformat() if len(sample) else None,
                   end=sample.index[-1].isoformat() if len(sample) else None, percentile=None)
        if available:
            row.update({name:float(valid.quantile(q)) for name,q in (("p05",.05),("p25",.25),("p50",.5),("p75",.75),("p95",.95))})
            if finite(current): row["percentile"] = float(100*((valid<current).sum()+.5*(valid==current).sum())/len(valid))
        results.append(row)
    return results


def overview_card(symbol, daily, calendar, metadata, dividends, live, now, chart_input, continuous=None):
    from .nonregression import single
    root = symbol[:2]; spot = UNDERLYINGS[root][0]
    ref = metadata.get(symbol, {}); expiry = ref.get("expiry_date")
    f = single(daily.get(symbol,pd.DataFrame()), daily.get(spot,pd.DataFrame()), symbol, expiry, dividends, calendar)
    continuity=None
    if continuous is not None:f,continuity=continuous
    quote = live.get(symbol, {}); index = live.get(spot, {})
    quality = quote_quality(quote, now); ok, reason = aligned_quotes([quote,index], now)
    day = now.tz_convert("Asia/Shanghai").date()
    days = (pd.Timestamp(expiry).date()-day).days if expiry else None
    d = dividends.points(symbol, day)
    current = adjusted_basis(quote.get("close") if ok else None, index.get("close"), d, days)
    chart_field = "annual" if chart_input == "annual" else "basis"
    value = current["annual_pct" if chart_field == "annual" else "bp"]
    marker_time = now if value is not None else None
    marker_kind = "盘中观测" if value is not None else "无有效历史"
    valid = f[chart_field].replace([np.inf,-np.inf],np.nan).dropna()
    if value is None and len(valid):
        value = float(valid.iloc[-1]); marker_time = valid.index[-1]; marker_kind = "历史"
    chart = dict(value=value, time=marker_time.isoformat() if marker_time is not None else None,
                 kind=marker_kind, unit="%" if chart_field=="annual" else "bp", rows=[])
    if marker_time is not None:
        chart["rows"] = distributions(f[chart_field], calendar, marker_time, value,
            listing=str(calendar[0].date()) if continuity and len(calendar) else ref.get("listing_date"),
            expiry=None if continuity else expiry, annual=chart_field=="annual",
            eligibility=(f['T'].isna()|f['T'].ge(5)) if continuity and chart_field=='annual' else None,
            allow_partial=bool(continuity))
    chart["reference_end"]=max((r['end'] for r in chart['rows'] if r['end']),default=None)
    legacy_history=f[chart_field].loc[f.index.tz_convert('Asia/Shanghai').normalize()<pd.Timestamp(marker_time).tz_convert('Asia/Shanghai').normalize()].tail(30) if marker_time is not None else pd.Series(dtype=float)
    legacy_ok=len(legacy_history)==30 and legacy_history.notna().all() and finite(value)
    chart['legacy_percentile30']=dict(
        variant_id='overview.legacy_percentile30::'+(continuity['alias'] if continuity else symbol),
        scope='连续到期档位' if continuity else '固定具体合约',n=int(legacy_history.notna().sum()),
        percentile=float(100*(legacy_history<=value).sum()/30) if legacy_ok else None,
        reference_end=legacy_history.index[-1].isoformat() if len(legacy_history) else None,
        formula='100 × N(此前30期x≤当前x)/30；排除当前',
        reason='' if legacy_ok else '需完整此前30期；与20期半权分位独立')
    hist = {}
    for field in ("points","basis","annual"):
        s=f[field].replace([np.inf,-np.inf],np.nan).dropna()
        hist[field] = dict(value=float(s.iloc[-1]) if len(s) else None,time=s.index[-1].isoformat() if len(s) else None)
    if not reason and current["bp"] is None: reason = dividends.reason or "缺少该具体合约的分红映射"
    return dict(symbol=symbol, root=root, name=UNDERLYINGS[root][1], expiry=expiry, days=days, dividend=d,
        dividend_inherited_from=dividends.info.get('mapping',{}).get(symbol,{}).get('inherited_from'),
        quote=quote, quality=quality, spot=index, spot_symbol=spot, aligned=ok, reason=reason,
        current=current, historical=hist, chart=chart,continuity=continuity,
        alias=continuity['alias'] if continuity else None)


# A family contains meaningful submetrics; the primary submetric is explicit.
FAMILIES = (
    ("A02.convergence", "假设每日收敛量级", "A02.convergence"),
    ("A03.z", "历史 Z", "A03.z"),
    ("A03.change5", "五期变化", "A03.change5"),
    ("A03.percentile", "历史分位", "A03.percentile"),
    ("A04", "分红调整跨期价差", "A04.bp"),
    ("A05", "期限持有率", "A05"),
    ("A06", "同月跨品种基差差", "A06"),
    ("A07", "非回归收益分解", "A07.actual"),
    ("A09", "等名义手数与金额", "A09.h"),
    ("A11", "短窗实现波动", "A11"),
    ("A12", "连续偏离确认", "A12"),
    ("A14.book", "一档双向跨期报价", "A14.buy"),
    ("B01", "开盘偏离与修复", "B01.gap"),
    ("B02", "量加权中枢", "B02.center"),
    ("B03", "增仓加权漂移", "B03"),
    ("B04", "换手与净持仓变化", "B04.Q"),
    ("B05", "跨期迁移代理", "B05.M"),
    ("B06", "成交与持仓份额偏移", "B06"),
    ("B07", "收盘位置差", "B07"),
    ("B08", "同组月份持仓扩张差", "B08"),
    ("B09", "相对成交活跃度", "B09"),
    ("B10", "路径效率", "B10"),
    ("B11", "相对振幅压力", "B11"),
    ("B12", "双腿成交容量", "B12.A"),
    ("A13", "理论价成本带", "A13"),
    ("A14.etf", "ETF / IOPV", "A14.etf"),
)


def group_metrics(entities, category, price_input):
    from dashboard.pair_catalog import FAMILIES as PAIR_FAMILIES
    groups=[]
    for key,title,primary in FAMILIES:
        if category in ('calendar','cross') and key in PAIR_FAMILIES:title=PAIR_FAMILIES[key][0]
        items=[]
        for entity in entities:
            if key=="A14.book": rows=[r for r in entity["metrics"] if r["id"].startswith("A14.") and r["id"]!="A14.etf"]
            else: rows=[r for r in entity["metrics"] if r["id"]==key or r["id"].startswith(key+".")]
            if rows: items.append({**entity,"metrics":rows})
        if not items: continue
        ids={r["id"] for e in items for r in e["metrics"]}
        selected=primary if primary in ids else items[0]["metrics"][0]["id"]
        groups.append(dict(id=key,title=title,primary=selected,entities=items,extra=key in ("A13","A14.etf")))
    return groups


def oi_expansion(left, right, data, metadata, calendar):
    from .nonregression import positive,metric
    if not len(calendar): return None
    end=str(calendar[-1].tz_convert("Asia/Shanghai").date())
    months={s[2:] for s,r in metadata.items() if s.startswith(left[:2]) and r["listing_date"]<=end<r["expiry_date"]}&{s[2:] for s,r in metadata.items() if s.startswith(right[:2]) and r["listing_date"]<=end<r["expiry_date"]}
    growth=[]
    for product in (left[:2],right[:2]):
        frames=[]
        for s in sorted(product+m for m in months):
            f=data.get(s,pd.DataFrame()).reindex(calendar)
            oi=f.get("open_interest",pd.Series(np.nan,index=calendar))
            frames.append(oi.where(calendar.tz_convert("Asia/Shanghai").strftime("%Y-%m-%d")<metadata[s]["expiry_date"]).rename(s))
        total=pd.concat(frames,axis=1).sum(axis=1,min_count=len(frames)) if frames else pd.Series(np.nan,index=calendar)
        growth.append((100*np.log(positive(total)/positive(total.shift(5)))).where(total.notna().rolling(6).sum().eq(6)))
    row=metric("B08.legacy_collection","原同组月份持仓扩张差（辅助）",growth[0]-growth[1],"对数增长百分点",
        "100 × [ln(OI_A合计/OI_A合计前5日) − ln(OI_B合计/OI_B合计前5日)]", "固定月份集合 "+", ".join(sorted(months))+"；全组齐备、到期前才更新，不拼接换月。")
    row['role']='auxiliary'
    return row


def dashboard_cards(engine, state, request, selection, daily, calendar, metadata, dividends, live, now, load_minutes):
    from .nonregression import calculate,collection_center,metric,INPUTS
    from .pair_metrics import PAIR_FORMULA_VERSION,ratio_for_day,pair_definition
    category=state["category"]; price=state["price_input"]
    entities=[]
    # Source data/quality, local date, dataset and scenario versions participate in caching.
    live_key=tuple((s,repr(sorted((k,str(v)) for k,v in q.items())),quote_quality(q,now)["status"]) for s,q in sorted(live.items()))
    reference_key=tuple((s,r.get('listing_date'),r.get('expiry_date'),r.get('known_at')) for s,r in sorted(metadata.items()))
    cache=engine.card_metric_cache
    for title,left,right in selection["pairs"]:
        error=None
        if left not in metadata or (category!="basis" and right not in metadata):error="具体合约参考缺失"
        elif category=="calendar" and metadata[left]["expiry_date"]>=metadata[right]["expiry_date"]:error="请选择近月和更晚的远月"
        elif category=="cross" and metadata[left]["expiry_date"]!=metadata[right]["expiry_date"]:error="两腿到期日不一致"
        if error:
            entities.append(dict(title=title,left=left,right=right,metrics=[],error=error));continue
        config=getattr(engine.model,'config',{})
        carry=config.get('research_carry_inputs',{}).get(left)
        mappings=config.get('research_etf_iopv_mapping',{})
        mapping=mappings.get(left,mappings.get(left[:2]))
        key=(PAIR_FORMULA_VERSION,engine.history_key, reference_key, dividends.mode, dividends.version, dividends.reason, category, price, left, right, str(now.tz_convert("Asia/Shanghai").date()),live_key,repr(carry),repr(mapping),repr(request.get('participation')))
        if key not in cache:
            symbols={left,right,UNDERLYINGS[left[:2]][0]}
            if category!="basis":symbols.add(UNDERLYINGS[right[:2]][0])
            minutes={s:load_minutes(s) for s in symbols}
            rows=calculate(left,right,category,price,daily,minutes,metadata,dividends,calendar,live,now,
                carry_inputs=carry,etf_mapping=mapping,participation=request.get('participation')) if len(calendar) else []
            if category=="cross":
                row=oi_expansion(left,right,daily,metadata,calendar)
                if row:rows.append(row)
            if len(cache)>=48:cache.clear()
            cache[key]=rows
        rows=deepcopy(cache[key])
        from .intraday import observations
        symbols={left,right,UNDERLYINGS[left[:2]][0]}
        if category!='basis': symbols.add(UNDERLYINGS[right[:2]][0])
        observations(rows,engine.model.live_rows,left,right,category,price,daily,
                     {s:load_minutes(s) for s in symbols},metadata,dividends,now,getattr(engine,'observation_cache',None))
        pair_ratio=ratio_for_day(daily.get(left,pd.DataFrame()),daily.get(right,pd.DataFrame()),category,left,right,now) if category!='basis' else None
        center,gap,stamp,note=collection_center(engine.model.live_rows,left,right,category,price,dividends,metadata,live,now,pair_ratio=pair_ratio)
        for suffix,title2,value in (("collection_center","采集区间成交量加权中枢",center),("collection_gap","采集区间中枢偏离",gap)):
            unit=INPUTS[price][1] if category=='basis' else pair_definition(category,price)['unit']
            formula='Σ(同步X × min(有效ΔV_A,有效ΔV_B/h前)) / Σ匹配增量量' if category!='basis' else 'Σ(同步观测x × 有效增量V_A) / Σ有效增量V_A'
            rows.append(metric("B02."+suffix,title2,pd.Series(dtype=float),unit,formula,note,
                scope="采集以来·HTTP观测",reason="此项不是完整历史分钟指标",current=value,current_time=stamp,current_reason=note))
            rows[-1]['current_scope']='采集区间'
        entities.append(dict(title=title,left=left,right=right,metrics=rows,error=None))
    overview=[]
    for s in selection['overview_symbols']:
        continuous=None
        if selection.get('overview_slot') is not None:
            from .continuous import slot_history
            ckey=(engine.history_key,reference_key,dividends.version,dividends.mode,dividends.reason,s,selection['overview_slot'],str(now.tz_convert('Asia/Shanghai').date()))
            if not hasattr(engine,'continuous_cache'):engine.continuous_cache={}
            if ckey not in engine.continuous_cache:
                if len(engine.continuous_cache)>32:engine.continuous_cache.clear()
                engine.continuous_cache[ckey]=slot_history(s[:2],selection['overview_slot'],daily,calendar,metadata,dividends,s,now)
            continuous=engine.continuous_cache[ckey]
        overview.append(overview_card(s,daily,calendar,metadata,dividends,live,now,request.get('distribution_input','basis'),continuous))
    errors=[e['title']+'：'+e['error'] for e in entities if e['error']]
    return dict(overview=overview,entities=entities,metric_groups=group_metrics(entities,category,price),
        selection=selection,metrics=entities[0]["metrics"] if entities else [],
        comparison_note="；".join(errors) if errors else "固定具体合约 / 合约对 · 各品种有效日期分别标注 · 参考统计排除当前观测")
