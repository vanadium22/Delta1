"""Original source definitions and their independently calculated explanations."""
import numpy as np
import pandas as pd


def minute_events(frame):
    """Per-X event state; third bar confirms, first below threshold recovers."""
    from .nonregression import statistics
    names=('first','last','peak','duration','confirmed','recovered','confirmed_at','recovered_at')
    result={k:[] for k in names}
    if frame.empty:
        return {k:pd.Series(dtype=float) for k in names}
    for _,session in frame.groupby(['trade_date','session_id']):
        session=session.sort_index()
        blocks=(session.index.to_series().diff()!=pd.Timedelta(minutes=1)).cumsum()
        for _,chunk in session.groupby(blocks):
            z,_,_=statistics(chunk.x,30)
            state=None; sign=0; values={k:[] for k in names}
            for stamp,value in z.items():
                direction=int(np.sign(value)) if pd.notna(value) and abs(value)>=2 else 0
                if pd.isna(value):
                    state=None;sign=0
                elif direction:
                    if direction!=sign:
                        state=dict(first=stamp.timestamp(),last=stamp.timestamp(),peak=abs(value),duration=1.,confirmed=0.,recovered=0.,confirmed_at=np.nan,recovered_at=np.nan)
                    else:
                        state.update(last=stamp.timestamp(),peak=max(state['peak'],abs(value)),duration=state['duration']+1)
                    if state['duration']==3:state.update(confirmed=1.,confirmed_at=stamp.timestamp())
                    sign=direction
                else:
                    if state and state['confirmed'] and not state['recovered']:state.update(recovered=1.,recovered_at=stamp.timestamp())
                    elif state and not state['confirmed']:state=None
                    sign=0
                for key in names:values[key].append(state[key] if state else np.nan)
            for key in names:result[key].append(pd.Series(values[key],index=chunk.index))
    return {k:pd.concat(v).sort_index() if v else pd.Series(dtype=float) for k,v in result.items()}


def add_original_and_components(add,a,b,x,ma,mb,oa,ob,minute,calendar,category,price,metadata,left,right,participation,*,quantities=None):
    from .nonregression import prior,positive,statistics,weighted,minute_daily
    from .metric_inputs import INPUTS
    unit=INPUTS[price][1]
    leg_unit=unit
    if b is not None:
        from .pair_metrics import pair_definition, pair_quantities, pair_ohlc_statistics, pair_daily
        unit=pair_definition(category,price)['unit']
        if quantities is None:quantities=pair_quantities(a,b,category,left,right)
    blank=pd.Series(np.nan,index=calendar)

    def emit(code,title,s,u,formula,meaning='独立计算的解释量；不合成评分。'):
        add(code,title,s,u,formula,meaning)

    def stats(prefix,series,u):
        z,pct,change=statistics(series)
        full6=series.notna().rolling(6).sum().eq(6)
        for suffix,title,values,units,formula in (
            ('mean','此前20期均值',prior(series).mean(),u,'mean(x[t−20:t−1])'),
            ('std','此前20期样本标准差',prior(series).std(ddof=1),u,'sample_std(x[t−20:t−1]), ddof=1'),
            ('z','自身历史Z',z,'倍','(x−自身前20期均值)/自身样本标准差'),
            ('percentile','自身半权分位',pct,'%','100 × [N(历史<x)+0.5N(历史=x)]/20'),
            ('change5','自身五期变化',change.where(full6),u,'x_t−x_(t−5)，连续6点')):
            emit(prefix+suffix,title,values,units,formula)

    if category=='basis':
        for code,col,title,u,formula in (
            ('A01.raw_points','raw_points','未调整点基差','点','F−S'),
            ('A01.raw_bp','raw_basis','未调整普通基差','bp','10000 × (F−S)/S'),
            ('A01.log_bp','log_basis','未调整对数基差','bp','10000 × ln(F/S)'),
            ('A02.raw_annual','raw_annual','未调整简单年化基差','年化百分点','100 × (F/S−1) × 365/T, T≥5'),
            ('A02.log_annual','log_annual','未调整对数年化基差','年化百分点','100 × ln(F/S) × 365/T, T≥5'),
            ('A02.log_convergence','log_convergence','原稿对数每日收敛量级','bp/日','−10000ln(F/S)/T, T>0')):
            emit(code,title,a[col],u,formula,'原稿未调整口径；与分红调整定义独立保留。')
    if b is not None and category=='calendar':
        raw_points=a.close-b.close
        raw_bp=10000*raw_points/positive(a.S)
        emit('A04.raw_points','未调整跨期点差',raw_points,'点','F近−F远')
        emit('A04.raw_bp','未调整标准化跨期价差',raw_bp,'bp','10000 × (F近−F远)/S')
        stats('A04.raw_',raw_bp,'bp')
        ea,eb=(metadata.get(s,{}).get('expiry_date') for s in (left,right))
        delta=(pd.Timestamp(eb)-pd.Timestamp(ea)).days if ea and eb else 0
        carry=100*np.log(positive(b.close)/positive(a.close))*365/delta if delta>0 else blank
        emit('A05.legacy_log_carry','原对数期限持有率（未设近到期门槛，辅助）',carry,'年化百分点','100 × ln(F远/F近) × 365/(T远−T近)','旧口径辅助；主值要求两腿T≥5。')
        carry=carry.where(a['T'].ge(5)&b['T'].ge(5))
        emit('A05.log_carry','对数期限持有率',carry,'年化百分点','100 × ln(F远/F近) × 365/(T远−T近)，两腿T≥5')
        stats('A05.log_',carry,'年化百分点')
        emit('A09.one_to_one_pnl5','固定1:1五期未扣成本金额变化',(raw_points.diff(5)*({'IF':300,'IH':300,'IC':200,'IM':200}[left[:2]])).where(raw_points.notna().rolling(6).sum().eq(6)),'元','乘数 × Δ5(F近−F远)','固定一手近月减一手远月的金额变化；不是策略回测或年化bp损益。')
    if b is not None and category=='cross':
        for suffix,col,title in (('raw','raw_basis','未调整普通基差差'),('log','log_basis','原稿对数基差差G')):
            series=a[col]-b[col]
            emit('A06.'+suffix+'_bp',title,series,'bp',f'{col}_A−{col}_B')
            stats('A06.'+suffix+'_',series,'bp')

    # B01 explanations use exactly the open/close sampling used by the result.
    opening=oa if category=='basis' else pair_daily(minute)
    o=opening.get('open',blank).reindex(calendar)
    c=opening.get('close',blank).reindex(calendar)
    threshold=pd.Series(.02 if price.endswith('annual') or price=='annual' else 2.,index=calendar) if price!='future' or category=='cross' else .0002*a.close.shift()
    for suffix,title,values,formula in (
        ('prev','前收输入',x.shift(),'x_(t−1)'),('open','开盘输入',o,'同步09:31分钟代理；单腿真实期货使用日开盘'),
        ('close','收盘输入',c,'完整日终输入'),('d','日内修复变化',c-o,'收盘x−开盘x'),('threshold','修复比分母门槛',threshold,'bp输入2bp；年化输入0.02百分点；价格前收2bp')):
        emit('B01.'+suffix,title,values,unit,formula)
    md=minute_daily(minute) if b is None else pair_daily(minute)
    for suffix,title,u,formula in (('n','有效分钟数','根','完整同步分钟数'),('weight_sum','A腿权重和','手','ΣV_A,m'),('weighted_sum','A腿加权和',unit+'×手','Σx_m V_A,m')):
        if b is not None and suffix!='n':
            title='匹配容量代理权重和' if suffix=='weight_sum' else '合约对匹配量加权和'
            formula='Σ min(V_A,m,V_B,m/h_t)' if suffix=='weight_sum' else 'Σ X_m min(V_A,m,V_B,m/h_t)'
        emit('B02.'+suffix,title,md.get(suffix,pd.Series(dtype=float)),u,formula)
    if b is not None:
        emit('B03.pair.positive_weight','合约对五期正增仓匹配权重',quantities.positive_weight.rolling(5,min_periods=5).sum(),'手','Σ5 min(max(ΔOI_A,0),max(ΔOI_B,0)/h_t)')
        for suffix,col,title,u in (('volume','volume','匹配成交容量','手'),('previous_oi','previous_oi','同h前期匹配持仓','手'),('oi','oi','当期匹配持仓','手'),('h','h','前收匹配比例','手/手')):
            emit('B04.pair.'+suffix,title,quantities[col],u,'匹配容量代理；同h折算，不代表实际配对成交或账户持仓')
        for field in ('open','high','low','close'):
            emit('B07.pair.'+field,'合约对同步分钟 '+field,md.get(field,pd.Series(dtype=float)),unit,'完整240个同步X分钟收盘观测聚合OHLC')
        for suffix,col in (('total','oi'),('base','growth_base'),('h','h')):
            emit('B08.pair.'+suffix,'合约对匹配持仓 '+suffix,quantities[col],'手/手' if suffix=='h' else '手','当期与五期前固定同一h_t比较；完整6点')
        emit('B09.pair.baseline','合约对匹配量基准',prior(quantities.volume).median(),'手','median(此前20期 min(V_A,V_B/h_t))')
        pair_ohlc=pair_ohlc_statistics(md,calendar)
        for suffix in ('tr','baseline'):
            emit('B11.pair.'+suffix,'合约对真实波幅' if suffix=='tr' else '合约对波幅基准',pair_ohlc[suffix],unit,'绝对TR_X' if suffix=='tr' else 'median(此前20期TR_X)')

    legs=[('A',a,oa)]+([('B',b,ob)] if b is not None else [])
    for leg,f,ohlc in legs:
        w=f.doi.clip(lower=0)
        for suffix,title,values,u,formula in (
            ('drift','增仓漂移',weighted(f[price].diff(),w),leg_unit,'Σ5(Δx max(ΔOI,0))/Σ5max(ΔOI,0)'),
            ('doi','净持仓变化',f.doi,'手','OI_t−OI_(t−1)'),
            ('positive_weight','五期正增仓权重和',w.rolling(5,min_periods=5).sum(),'手','Σ5max(ΔOI,0)')):
            emit(f'B03.{leg}.{suffix}',leg+title,values,u,formula)
        for suffix,title,values,u,formula in (
            ('volume','成交量',f.volume,'手','V_t'),('previous_oi','昨日有效持仓',f.oi_valid.shift(),'手','OI_(t−1)'),
            ('doi','净持仓变化',f.doi,'手','OI_t−OI_(t−1)'),('Q','换手率',f.Q,'倍','V_t/OI_(t−1)'),('K','净持仓变化比例',100*f.K,'%','100 ΔOI_t/V_t')):
            emit(f'B04.{leg}.{suffix}',leg+title,values,u,formula)
        baseline=prior(f.volume).median()
        for family in ('B07','B09'):
            emit(f'{family}.{leg}.rvol',leg+'相对成交量',f.rvol,'倍','V_t/此前20日V中位数')
            emit(f'{family}.{leg}.'+('volume_baseline' if family=='B07' else 'baseline'),leg+'成交量基准',baseline,'手','median(V[t−20:t−1])')
        if ohlc is None or ohlc.empty:
            clv=tr=amp=blank
        else:
            q=ohlc.reindex(calendar)
            clv=(2*q.close-q.high-q.low)/(q.high-q.low).where(q.high>q.low)
            tr=pd.concat([q.high-q.low,(q.high-q.close.shift()).abs(),(q.low-q.close.shift()).abs()],axis=1).max(axis=1,skipna=False)
            amp=10000*tr/positive(q.close.shift()) if price=='future' else tr
        if category=='basis':clv=f.clv
        emit(f'B07.{leg}.clv',leg+'收盘位置',clv,'倍','(2C−H−L)/(H−L)；期现使用真实OHLC')
        den=prior(amp).median()
        emit(f'B11.{leg}.tr',leg+'真实波幅',amp,'bp' if price=='future' else leg_unit,'真实价格10000TR/前收；有符号X用绝对TR')
        emit(f'B11.{leg}.baseline',leg+'振幅基准',den,'bp' if price=='future' else leg_unit,'median(此前20期振幅)')
        emit(f'B11.{leg}.pressure',leg+'振幅压力',amp/positive(den),'倍','当期振幅/自身此前20期中位数')
    if category=='basis':
        # Preserve the real index leg of the source CLV diagnostic.
        emit('B07.B.clv','指数收盘位置',a.spot_clv,'倍','真实指数(2C−H−L)/(H−L)')
        emit('B07.B.rvol','指数相对成交量',a.spot_volume/positive(prior(a.spot_volume).median()),'倍','指数V/此前20日指数V中位数；非可交易篮子容量')
        emit('B07.B.volume_baseline','指数成交量基准',prior(a.spot_volume).median(),'原始量单位','此前20日指数成交量中位数')
    if b is not None and category=='calendar':
        den=a.oi_valid.shift()+b.oi_valid.shift()
        for code,title,values,u,formula in (
            ('B05.doi_near','近月净变化',a.doi,'手','ΔOI近'),('B05.doi_far','远月净变化',b.doi,'手','ΔOI远'),('B05.denominator','昨日合计持仓',den,'手','OI近前+OI远前'),
            ('B06.volume_share','远月成交份额',b.volume/positive(a.volume+b.volume),'倍','V远/(V近+V远)'),('B06.oi_share','远月昨日OI份额',b.oi_valid.shift()/positive(den),'倍','OI远前/(OI近前+OI远前)'),
            ('B06.volume_denominator','成交份额分母',a.volume+b.volume,'手','V近+V远'),('B06.oi_denominator','持仓份额分母',den,'手','OI近前+OI远前')):
            emit(code,title,values,u,formula)
    full=x.notna().rolling(6).sum().eq(6)
    emit('B10.net','五期净变化',x.diff(5).where(full),unit,'x_t−x_(t−5)')
    emit('B10.path','五期路径长度',x.diff().abs().rolling(5,min_periods=5).sum(),unit,'Σ5|Δx|')
    emit('B10.n','路径观测数',pd.Series(6.,index=calendar).where(full),'根','6个连续有效观测，5个变化')
    if b is not None:
        from .nonregression import MULTIPLIERS
        h=quantities.h
        cap=pd.concat([a.volume.where(a.volume>=0),b.volume.where(b.volume>=0)/positive(h)],axis=1).min(axis=1,skipna=False)
        emit('B12.h','前收匹配B/A手数',h,'手/手','同品种1:1；跨品种上一完整交易日FAmA/(FBmB)')
        valid_p=isinstance(participation,(int,float)) and not isinstance(participation,bool) and np.isfinite(participation) and 0<=participation<=1
        p=pd.Series(float(participation) if valid_p else np.nan,index=calendar)
        emit('B12.p','显式参与比例',p,'倍','用户明确输入0≤p≤1；未给不默认1%')
        emit('B12.A_p','按显式p折算A容量',cap*p,'手','p × min(V_A,V_B/h)')
        emit('B12.B_p','按显式p折算B容量',cap*p*h,'手','h × p × min(V_A,V_B/h)')
