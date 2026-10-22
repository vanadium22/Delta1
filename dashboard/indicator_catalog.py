"""Shared, explicit indicator identities for the three research pages.

The catalogue describes applicability, not data availability. A registered
formula can be implemented while its real inputs remain absent.
"""
from copy import deepcopy

FORMULA_VERSION = 'nonregression-v2'
PAGES = {'basis': '期现', 'calendar': '同品种跨期', 'cross': '跨品种'}
INPUTS = {
    'future': ('真实期货价格', '点'),
    'basis': ('分红调整基差', 'bp'),
    'annual': ('分红调整简单年化', '年化百分点'),
    'raw_basis': ('未调整普通基差', 'bp'),
    'log_basis': ('未调整对数基差', 'bp'),
    'raw_annual': ('未调整简单年化', '年化百分点'),
    'log_annual': ('未调整对数年化', '年化百分点'),
}
ALL = tuple(PAGES)
PAIR = ('calendar', 'cross')
SIGNED = tuple(k for k in INPUTS if k != 'future')


def _entry(family, title, primary, metrics, unit, *, input_id='fixed',
           categories=ALL, source=None, fields=(), frequency='daily', window=None,
           timing='完整日终；仅有独立实时分支时可盘中', entity_kind='contract_pair',
           same_expiry=False):
    if not fields and input_id!='fixed':
        fields=('F',) if input_id=='future' else ('F','S')
        if input_id in ('basis','annual'):fields+=('D',)
        if input_id.endswith('annual') or input_id=='annual':fields+=('expiry_date',)
        if family in ('B02','B03','B07','B11'):fields+=('volume',)
        if family=='B03':fields+=('open_interest',)
        if frequency=='minute' or family in ('B02','B07','B11'):fields+=('synchronized_minutes','session_id')
    unit_by_category={c:unit for c in categories}
    if family=='A11' and input_id=='future':unit_by_category.update(basis='bp',calendar='点')
    if family=='B09':unit_by_category.update(basis='倍',calendar='对数倍数',cross='对数倍数')
    if family=='B11':unit_by_category.update(basis='倍',calendar='对数倍数',cross='对数倍数')
    return dict(family_id=family, variant_id=family+'::'+input_id+'::v1',
                title=title, primary=primary, metric_ids=list(metrics), unit=unit,
                unit_by_category=unit_by_category,
                input_id=input_id, categories=list(categories), category=list(categories),
                source_ref=source or ('V2-'+family[1:3] if family.startswith('B') else 'V1-研究章节'),
                formula_version=FORMULA_VERSION, required_fields=list(fields),
                fixed_inputs=[] if input_id!='fixed' else list(fields), frequency=frequency,
                window=window, timing=timing, missing_policy='不填充；分别报告缺输入/不适用/旧历史/未实现',
                implementation_status='implemented', entity_kind=entity_kind,
                same_expiry=same_expiry,
                visibility_policy='无可核验发布时间及参考版本则标修订历史参考/可见性未认证')


def _build():
    rows=[]
    def fixed(family,title,primary,metrics,unit,**kw):
        rows.append(_entry(family,title,primary,metrics,unit,**kw))
    def x(family,title,primary,metrics,unit='x',**kw):
        for key,(label,xunit) in INPUTS.items():
            cats=tuple(c for c in kw.get('categories',ALL) if not (c=='cross' and key=='future'))
            if family=='B07' and key!='future': cats=tuple(c for c in cats if c!='basis')
            if not cats: continue
            options={**kw,'categories':cats}
            selected_unit=xunit if unit=='x' else unit
            if family=='A11':selected_unit='收益bp' if key=='future' else xunit
            rows.append(_entry(family,label+' · '+title,primary,metrics,selected_unit,input_id=key,**options))
    for code,title,unit in (
        ('points','分红调整点基差','点'),('bp','分红调整普通基差','bp'),
        ('raw_points','未调整点基差','点'),('raw_bp','未调整普通基差','bp'),
        ('log_bp','未调整对数基差','bp')):
        fixed('A01.'+code,title,'A01.'+code,['A01.'+code],unit,categories=('basis',),source='V1-3',fields=('F','S')+(('D',) if code in ('points','bp') else ()))
    for code,title,unit in (
        ('annual','分红调整简单年化','年化百分点'),('raw_annual','未调整简单年化','年化百分点'),
        ('log_annual','未调整对数年化','年化百分点'),('convergence','调整基差每日收敛量级','bp/日'),
        ('log_convergence','对数基差每日收敛量级','bp/日')):
        fixed('A02.'+code,title,'A02.'+code,['A02.'+code],unit,categories=('basis',),source='V1-3',fields=('F','S','expiry_date'))
    for code,title,unit in (('mean','前20期均值','x'),('std','前20期样本标准差','x'),
                            ('z','历史 Z','倍'),('percentile','固定合约半权分位','%'),('change5','五期变化','x')):
        x('A03.'+code,title,'A03.'+code,['A03.'+code],unit,source='V1-4',window=20 if code!='change5' else 5)
    x('A03.legacy_percentile30','原概览30期≤分位（固定实体独立扩展）','A03.legacy_percentile30',
      ['A03.legacy_percentile30'],'%',source='V1-4-Plegacy',window=30)
    for code,title,unit in (('points','分红调整跨期点差','点'),('bp','分红调整跨期标准化差','bp'),
                            ('raw_points','未调整跨期点差','点'),('raw_bp','未调整跨期标准化差','bp')):
        metrics=['A04.'+code]
        if code=='raw_bp':metrics+=['A04.raw_'+s for s in ('mean','std','z','percentile','change5')]
        fixed('A04.'+code,title,'A04.'+code,metrics,unit,categories=('calendar',),source='V1-5',fields=('F_A','F_B','expiry_date'))
    fixed('A05','分红调整简单期限持有率','A05',['A05'],'年化百分点',categories=('calendar',),source='V1-5',fields=('F_A','F_B','D_A','D_B','expiry_date'))
    fixed('A05.log_carry','未调整对数期限持有率及自身统计','A05.log_carry',
          ['A05.log_carry']+['A05.log_'+s for s in ('mean','std','z','percentile','change5')],
          '年化百分点',categories=('calendar',),source='V1-5',fields=('F_A','F_B','expiry_date'),window=20)
    fixed('A06','同到期分红调整基差差','A06',['A06'],'bp',categories=('cross',),source='V1-6',same_expiry=True,fields=('F_A','S_A','D_A','F_B','S_B','D_B'))
    for prefix,title in (('raw','未调整普通基差差'),('log','未调整对数基差差')):
        fixed('A06.'+prefix,title+'及自身统计','A06.'+prefix+'_bp',
              ['A06.'+prefix+'_bp']+['A06.'+prefix+'_'+s for s in ('mean','std','z','percentile','change5')],
              'bp',categories=('cross',),source='V1-6',same_expiry=True,window=20,fields=('F_A','S_A','F_B','S_B'))
    fixed('A07','非回归等名义收益归因','A07.actual',['A07.'+s for s in ('actual','spot','basis','scenario')],'收益bp',categories=PAIR,source='V1-7',window=5,fields=('F_A','F_B','S_A','S_B'))
    fixed('A09','真实金额与等名义手数','A09.h',['A09.'+s for s in ('h','amountA','amountB','rounding')],'手数比',categories=PAIR,source='V1-2/V1-9',fields=('F_A','F_B','multiplier'))
    fixed('A09.one_to_one_pnl5','固定1:1五期未扣成本金额变化','A09.one_to_one_pnl5',['A09.one_to_one_pnl5'],'元',categories=('calendar',),source='V1-5/V1-9',window=5,fields=('F_A','F_B','multiplier'))
    x('A11','同会话30分钟实现波动','A11',['A11'],frequency='minute',window=30,source='V1-11')
    x('A12','非回归连续偏离事件','A12',['A12']+['A12.'+s for s in ('first','last','peak','duration','confirmed','recovered','confirmed_at','recovered_at')],
      '次',frequency='minute',window=30,source='V1-11')
    fixed('A13','理论价与方向性成本带','A13.fair',['A13']+['A13.'+s for s in ('fair','deviation','upper','lower','long_space','short_space')],
          '点',categories=('basis',),source='V1-12',frequency='live',fields=(
              'F','S','expiry_date','financing_rate','dividend_yield','long_cost_bp','short_cost_bp',
              'spot_leg_id','effective_from','effective_to','known_at','version'))
    fixed('A14.book','双向一档跨期盘口','A14.buy',['A14.buy','A14.sell'],'点',categories=('calendar',),source='V1-12',fields=('bid_A','ask_A','bid_B','ask_B','quote_sizes','source_times'),frequency='live')
    fixed('A14.etf','ETF / IOPV 同刻偏离','A14.etf',['A14.etf'],'bp',categories=('basis',),source='V1-12',fields=('ETF','IOPV','mapping','source_times'),frequency='live')
    x('B01','开盘偏离与修复','B01.gap',['B01.'+s for s in ('gap','repair','prev','open','close','d','threshold')],source='V2-01')
    x('B02','同步分钟量加权中枢','B02.center',['B02.'+s for s in ('center','gap','n','weight_sum','weighted_sum','collection_center','collection_gap')],frequency='minute',source='V2-02')
    x('B03','各腿独立增仓加权漂移','B03',['B03']+['B03.'+leg+'.'+s for leg in ('A','B') for s in ('drift','doi','positive_weight')],window=5,source='V2-03')
    fixed('B04','真实换手与增仓','B04.Q',['B04.Q','B04.K','B04.doi','B04.Q.intraday']+['B04.'+leg+'.'+s for leg in ('A','B') for s in ('volume','previous_oi','doi','Q','K')],
          '倍',source='V2-04',fields=('volume_A','OI_A','volume_B','OI_B'))
    fixed('B05','跨期持仓迁移形态代理','B05.M',['B05.'+s for s in ('M','R','N','doi_near','doi_far','denominator')],'手',categories=('calendar',),source='V2-05',fields=('OI_A','OI_B'))
    fixed('B06','成交和昨日持仓份额偏移','B06',['B06']+['B06.'+s for s in ('volume_share','oi_share','volume_denominator','oi_denominator')],'百分点',categories=('calendar',),source='V2-06',fields=('volume_A','volume_B','OI_A','OI_B'))
    x('B07','收盘位置与真实量能条件','B07',['B07','B07.volume']+['B07.'+leg+'.'+s for leg in ('A','B') for s in ('clv','rvol','volume_baseline')],'比值',source='V2-07')
    fixed('B08','固定集合持仓扩张','B08',['B08']+['B08.'+leg+'.'+s for leg in ('A','B') for s in ('total','base','growth','members')],
          '对数增长百分点',categories=PAIR,source='V2-08',window=5,fields=('fixed_members','OI'),entity_kind='collection')
    fixed('B09','真实成交相对活跃','B09',['B09','B09.same_time']+['B09.'+leg+'.'+s for leg in ('A','B') for s in ('baseline','rvol')],
          '倍/对数比',source='V2-09',window=20,fields=('volume_A','volume_B'))
    x('B10','路径效率','B10',['B10','B10.net','B10.path','B10.n'],'比值',window=5,source='V2-10')
    x('B11','各腿振幅压力','B11',['B11','B11.max','B11.sample']+['B11.'+leg+'.'+s for leg in ('A','B') for s in ('tr','baseline','pressure')],
      '倍/对数比',window=20,source='V2-11')
    fixed('B12','真实量双腿容量与参与比例演算','B12.A',['B12.'+s for s in ('A','B','balance','h','p','A_p','B_p')],
          '手',categories=PAIR,source='V2-12',fields=('F_A','F_B','volume_A','volume_B','multiplier','optional_p'))
    return tuple(rows)


_CATALOG = _build()


def _metric_applies(code,entry,category):
    if code=='B11.sample' and entry['input_id']=='future':return False
    if category=='basis':
        if code.startswith(('B03.B.','B04.B.','B09.B.','B11.B.')):return False
        if code in ('B11.max','B07.volume'):return False
    if category=='calendar' and code.startswith('B08.B.'):return False
    return True


def metric_definition(code,entry,category):
    """Per-output schema used only when its implemented branch lacks inputs.

    Formula and dimensions mirror the production calculations. A missing child
    must not inherit a family's primary unit (e.g. weight_sum is hands, not bp).
    """
    price=entry['input_id'];xunit=INPUTS.get(price,('',entry['unit']))[1]
    unit=entry.get('unit_by_category',{}).get(category,entry['unit'])
    title=code;formula='';scope='完整历史日线';supported=False
    reason='缺本子项真实输入或完整连续窗口：'+', '.join(entry['required_fields'])
    stat=code.rsplit('_',1)[-1] if code.startswith(('A04.raw_','A05.log_','A06.raw_','A06.log_')) else code.rsplit('.',1)[-1] if code.startswith('A03.') else None
    if stat in ('mean','std','z','percentile','change5','legacy_percentile30'):
        base='年化百分点' if code.startswith('A05.log_') else 'bp' if code.startswith(('A04.raw_','A06.')) else xunit
        title,unit,formula={
            'mean':('此前20期均值',base,'mean(x[t−20:t−1])'),
            'std':('此前20期样本标准差',base,'sample_std(x[t−20:t−1]), ddof=1'),
            'z':('自身历史Z','倍','(x_t−mean(x[t−20:t−1]))/sample_std(x[t−20:t−1])'),
            'percentile':('此前20期半权分位','%','100 × [N(历史<x)+0.5N(历史=x)]/20'),
            'legacy_percentile30':('原30期≤分位','%','100 × N(此前30期x<=当前x)/30'),
            'change5':('五期变化',base,'x_t−x_(t−5)，连续6个观测'),
        }[stat]
    elif code.startswith('A01.'):
        title,unit,formula={
            'A01.points':('分红调整点基差','点','F−S+D'),
            'A01.bp':('分红调整普通基差','bp','10000 × (F−S+D)/S'),
            'A01.raw_points':('未调整点基差','点','F−S'),
            'A01.raw_bp':('未调整普通基差','bp','10000 × (F−S)/S'),
            'A01.log_bp':('未调整对数基差','bp','10000 × ln(F/S)'),
        }[code]
    elif code.startswith('A02.'):
        title,unit,formula={
            'A02.annual':('分红调整简单年化','年化百分点','100 × (F−S+D)/S × 365/T，T≥5'),
            'A02.raw_annual':('未调整简单年化','年化百分点','100 × (F/S−1) × 365/T，T≥5'),
            'A02.log_annual':('未调整对数年化','年化百分点','100 × ln(F/S) × 365/T，T≥5'),
            'A02.convergence':('调整基差每日收敛','bp/日','−调整基差bp/T，T>0'),
            'A02.log_convergence':('对数基差每日收敛','bp/日','−10000 ln(F/S)/T，T>0'),
        }[code]
    elif code.startswith('A04.'):
        points='(F近+D近)−(F远+D远)' if code in ('A04.points','A04.bp') else 'F近−F远'
        title='固定近远跨期价差';unit='点' if code.endswith('points') else 'bp'
        formula=points if unit=='点' else '10000 × ('+points+')/S'
    elif code in ('A05','A05.log_carry'):
        title='期限持有率';unit='年化百分点'
        formula='100 × [(F远+D远)/(F近+D近)−1] × 365/(T远−T近)' if code=='A05' else '100 × ln(F远/F近) × 365/(T远−T近)'
    elif code=='A06' or code.startswith('A06.'):
        title='同到期标准化基差差';unit='bp'
        formula={'A06':'10000 × [(F_A−S_A+D_A)/S_A−(F_B−S_B+D_B)/S_B]',
                 'A06.raw_bp':'10000 × [(F_A−S_A)/S_A−(F_B−S_B)/S_B]',
                 'A06.log_bp':'10000 × [ln(F_A/S_A)−ln(F_B/S_B)]'}[code]
    elif code.startswith('A07.'):
        title='固定五期收益归因';unit='bp'
        formula={'actual':'10000 × (Δ5lnF_A−Δ5lnF_B)','spot':'10000 × (Δ5lnS_A−Δ5lnS_B)',
                 'basis':'10000 × Δ5[ln(F_A/S_A)−ln(F_B/S_B)]',
                 'scenario':'10000 × Δ5[ln((F_A+D_A)/F_A)−ln((F_B+D_B)/F_B)]'}[code.split('.')[1]]
    elif code.startswith('A09.'):
        title,unit,formula={
            'A09.h':('等名义B/A手数','手/手','F_A M_A/(F_B M_B)'),
            'A09.amountA':('A每手真实名义金额','元','F_A M_A'),
            'A09.amountB':('B每手真实名义金额','元','F_B M_B'),
            'A09.rounding':('就近整数手金额差','元','F_A M_A−round(h)F_B M_B'),
            'A09.one_to_one_pnl5':('固定1:1五期金额变化','元','M × Δ5(F近−F远)，连续6观察'),
        }[code]
    elif code=='A11':
        title='同会话30分钟实现波动';scope='完整连续分钟'
        unit='bp' if price=='future' and category=='basis' else xunit
        formula='sqrt(Σ30(10000 ΔlnF)^2)' if price=='future' and category=='basis' else 'sqrt(Σ30(Δx)^2)，同会话31个连续分钟'
    elif code=='A12' or code.startswith('A12.'):
        suffix=code.split('.')[-1];scope='完整历史分钟·事件状态'
        unit='Unix秒' if suffix in ('first','last','confirmed_at','recovered_at') else '倍' if suffix=='peak' else '根' if suffix=='duration' else '0/1' if suffix in ('confirmed','recovered') else '次/会话'
        title='非回归事件 '+suffix;formula='前30分钟Z，同方向|Z|≥2连续3根确认；退出阈值恢复，缺口/会话重置'
    elif code=='A13' or code.startswith('A13.'):
        suffix=code.split('.')[-1] if code!='A13' else 'deviation'
        unit='点' if suffix in ('fair','upper','lower') else 'bp';supported=True
        title='理论价与方向成本 '+suffix
        formula={'fair':'S × [1+(r−q)T/365]','deviation':'10000 × (F−Ffair)/S',
                 'upper':'Ffair+S×short_cost_bp/10000','lower':'Ffair−S×long_cost_bp/10000',
                 'long_space':'−deviation−long_cost_bp','short_space':'deviation−short_cost_bp'}[suffix]
        reason='缺真实融资、股息、方向性成本、可执行现货腿及有效期/发布时间/版本；不使用演示参数'
    elif code.startswith('A14.'):
        supported=True;scope='实时同步观测'
        unit='bp' if code=='A14.etf' else '点'
        title='ETF/IOPV偏离' if code=='A14.etf' else '买近卖远盘口' if code.endswith('buy') else '卖近买远盘口'
        formula='10000 × (ETF/IOPV−1)' if code=='A14.etf' else 'Ask近−Bid远' if code.endswith('buy') else 'Bid近−Ask远'
        reason='缺显式映射及同刻有效ETF/IOPV' if code=='A14.etf' else '缺双腿同步有效一档价格和正盘口量；不造历史盘口'
    elif code.startswith('B01.'):
        suffix=code.split('.')[-1];title='开盘修复 '+suffix
        unit='倍' if suffix=='repair' else xunit
        formula={'gap':'开盘x−前收x','repair':'−(收x−开x)/(开x−前收x)，须满足分母门槛',
                 'prev':'x_(t−1)','open':'真实单腿期货开盘；其他为同步09:31分钟代理',
                 'close':'完整日终x','d':'收x−开x','threshold':'基差2bp；年化0.02百分点；真实价前收2bp'}[suffix]
    elif code.startswith('B02.'):
        suffix=code.split('.')[-1];title='同步量加权 '+suffix;unit=xunit
        formula={'center':'Σ(x_m V_A,m)/ΣV_A,m，完整240同步分钟','gap':'日终x−分钟量加权中枢',
                 'n':'完整同步分钟数','weight_sum':'ΣV_A,m','weighted_sum':'Σ(x_m V_A,m)',
                 'collection_center':'Σ(同步HTTP观测x × 有效增量V_A)/Σ有效增量V_A',
                 'collection_gap':'最新同步观测x−采集区间量加权中枢'}[suffix]
        if suffix=='n':unit='根'
        elif suffix=='weight_sum':unit='手'
        elif suffix=='weighted_sum':unit=xunit+'×手'
        if suffix.startswith('collection_'):
            scope='采集区间·HTTP同步观测';supported=True
            reason='缺连续同步采集观测或有效增量量权重；首次/重连/跨会话需新基准；非开盘以来VWAP，非完整历史分钟'
    elif code=='B03' or code.startswith('B03.'):
        suffix=code.split('.')[-1];title='各腿独立增仓 '+suffix
        unit='手' if suffix in ('doi','positive_weight') else xunit
        formula='OI_t−OI_(t−1)' if suffix=='doi' else 'Σ5max(ΔOI,0)' if suffix=='positive_weight' else 'Σ5(Δx max(ΔOI,0))/Σ5max(ΔOI,0)，双腿独算后相减'
    elif code.startswith('B04.'):
        suffix=code.split('.')[-1];title='真实量和持仓 '+suffix
        unit='%' if suffix=='K' else '倍' if suffix in ('Q','intraday') else '手'
        formula='累计V_当前/OI_昨日' if suffix=='intraday' else {'volume':'V_t','previous_oi':'OI_(t−1)','doi':'OI_t−OI_(t−1)','Q':'V_t/OI_(t−1)','K':'100 ΔOI_t/V_t'}[suffix]
        if suffix=='intraday':supported=True;scope='盘中累计成交量；非全日量'
    elif code.startswith('B05.'):
        suffix=code.split('.')[-1];title='迁移形态 '+suffix;unit='%' if suffix in ('R','N') else '手'
        formula={'M':'min(max(−ΔOI近,0),max(ΔOI远,0))','R':'100 M/(OI近前+OI远前)',
                 'N':'100 (ΔOI近+ΔOI远)/(OI近前+OI远前)','doi_near':'ΔOI近','doi_far':'ΔOI远','denominator':'OI近前+OI远前'}[suffix]
    elif code=='B06' or code.startswith('B06.'):
        suffix=code.split('.')[-1];title='流量/存量份额 '+suffix
        unit='百分点' if code=='B06' else '倍' if suffix in ('volume_share','oi_share') else '手'
        formula={'B06':'100 × [V远/(V近+V远)−OI远前/(OI近前+OI远前)]',
                 'volume_share':'V远/(V近+V远)','oi_share':'OI远前/(OI近前+OI远前)',
                 'volume_denominator':'V近+V远','oi_denominator':'OI近前+OI远前'}[suffix]
    elif code=='B07' or code.startswith('B07.'):
        suffix=code.split('.')[-1];title='收盘位置/量能 '+suffix
        unit='0/1' if suffix=='volume' else '原始量单位' if code=='B07.B.volume_baseline' and category=='basis' else '手' if suffix=='volume_baseline' else '倍'
        formula='(CLV_A−CLV_B)/2' if code=='B07' else '两腿各自RVOL≥1' if suffix=='volume' else '(2C−H−L)/(H−L)' if suffix=='clv' else 'V_t/median(V[t−20:t−1])' if suffix=='rvol' else 'median(V[t−20:t−1])'
    elif code=='B08' or code.startswith('B08.'):
        suffix=code.split('.')[-1];title='固定成员集合 '+suffix
        unit='手' if suffix in ('total','base') else '份合约' if suffix=='members' else '对数增长百分点'
        formula='Σ固定成员OI_t' if suffix=='total' else 'Σ固定成员OI_(t−5)' if suffix=='base' else '冻结成员数量' if suffix=='members' else '100 × [ln(ΣOI_A,t/ΣOI_A,t−5)−ln(ΣOI_B,t/ΣOI_B,t−5)]' if code=='B08' and category=='cross' else '100 ln(Σ固定成员OI_t/Σ固定成员OI_(t−5))'
    elif code=='B09' or code.startswith('B09.'):
        suffix=code.split('.')[-1];title='真实成交活跃 '+suffix
        unit='手' if suffix=='baseline' else '倍' if category=='basis' or suffix=='rvol' else '对数倍数'
        formula='median(V[t−20:t−1])' if suffix=='baseline' else 'V_t/median(V[t−20:t−1])' if suffix=='rvol' else '当前完整分钟累计量/此前20日同分钟累计量中位；双腿取ln比' if suffix=='same_time' else 'V_t/此前20日量中位；双腿取ln(RVOL_A/RVOL_B)'
        if suffix=='same_time':supported=True;scope='盘中同刻累计量；非整日量同比'
    elif code=='B10' or code.startswith('B10.'):
        suffix=code.split('.')[-1];title='五期路径 '+suffix
        unit='根' if suffix=='n' else xunit if suffix in ('net','path') else '倍'
        formula='6个连续观察、5个变化' if suffix=='n' else 'x_t−x_(t−5)' if suffix=='net' else 'Σ5|Δx|' if suffix=='path' else '(x_t−x_(t−5))/Σ5|Δx|'
    elif code=='B11' or code.startswith('B11.'):
        suffix=code.split('.')[-1];title='各腿振幅压力 '+suffix
        unit=('bp' if price=='future' else xunit) if suffix in ('tr','baseline') else '倍' if category=='basis' or suffix in ('max','pressure') else '对数倍数'
        formula='10000 TR/前收' if suffix=='tr' and price=='future' else '同步分钟x的绝对TR' if suffix=='tr' else '此前20期自身TR中位' if suffix=='baseline' else 'TR/此前20期自身TR中位' if suffix=='pressure' else 'max(压力A,压力B)' if suffix=='max' else '自身振幅压力；双腿取ln(压力A/压力B)'
        if suffix=='sample':
            supported=True;scope='采集区间·非全天振幅'
            formula='采集区间同步x极差/此前20日完整分钟绝对TR中位；双腿取ln比'
            reason='缺连续同步采集区间或此前20日完整分钟振幅基准；采集区间非全天振幅，不用当前样本伪造完整历史'
    elif code.startswith('B12.'):
        suffix=code.split('.')[-1];title='双腿真实量容量 '+suffix
        unit='倍' if suffix in ('p','balance') else '手/手' if suffix=='h' else '手'
        formula={'A':'min(V_A,V_B/h)','B':'h × min(V_A,V_B/h)','balance':'min(V_A F_A M_A,V_B F_B M_B)/max(...)',
                 'h':'同品种h=1；跨品种h=F_A M_A/(F_B M_B)','p':'用户显式0≤p≤1；未给不默认',
                 'A_p':'p × min(V_A,V_B/h)','B_p':'h p × min(V_A,V_B/h)'}[suffix]
        if suffix in ('p','A_p','B_p'):reason='未给合法显式参与比例p或真实双腿量价缺失；不默认1%'
    if not formula:raise ValueError('指标子项缺显式公式契约：'+code)
    return dict(id=code,title=title,unit=unit,formula=formula,scope=scope,
                missing_reason=reason,current_supported=supported)


def catalog(category=None):
    """Return independent copies so a renderer cannot alter the shared registry."""
    entries=deepcopy([r for r in _CATALOG if category is None or category in r['categories']])
    for entry in entries:
        if category=='basis' and entry['family_id'] in ('B03','B04','B09','B11'):
            entry['required_fields']=[field for field in entry['required_fields'] if not field.endswith('_B')]
            entry['fixed_inputs']=[field for field in entry['fixed_inputs'] if not field.endswith('_B')]
        matrix={code:[c for c in entry['categories'] if _metric_applies(code,entry,c)] for code in entry['metric_ids']}
        entry['metric_categories']=matrix
        entry['metric_ids']=[code for code,cats in matrix.items() if cats and (category is None or category in cats)]
        if category:
            entry['metric_definitions']={code:metric_definition(code,entry,category) for code in entry['metric_ids']}
    return entries


def find_variant(variant_id=None, *, family_id=None, input_id=None, category=None):
    candidates=catalog(category)
    if variant_id:
        return next((r for r in candidates if r['variant_id']==variant_id),None)
    return next((r for r in candidates if (not family_id or r['family_id']==family_id)
                 and (not input_id or r['input_id']==input_id)),None)


def applicability(variant, entity):
    if entity['category'] not in variant['categories']:return False,'指标不适用此页面'
    if variant['entity_kind']=='collection' and entity.get('kind')!='collection':return False,'此项要求冻结成员集合'
    if variant['same_expiry'] and entity.get('expiry_type')!='same':return False,'原稿同到期指标不适用异期组合'
    if entity['category']=='cross' and variant['input_id']=='future':return False,'不同指数原始点位不可直接相减'
    return True,''
