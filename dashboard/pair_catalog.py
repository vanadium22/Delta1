"""User-facing definitions for the contract-pair revision of 2026-10-22.

The original manuscript's single-leg comparisons remain auxiliary outputs.
This module describes the new definitions; it performs no calculations.
"""
from dashboard.native.pair_metrics import PAIR_FORMULA_VERSION, pair_definition

INPUT_LABELS = {
    'calendar': {'future':'跨期价差 close（近−远）','basis':'分红调整跨期基差（bp）',
                 'annual':'分红调整期限持有率（年化）','raw_basis':'未调整跨期基差（bp）',
                 'log_basis':'未调整跨期对数价比','raw_annual':'未调整简单期限持有率',
                 'log_annual':'未调整对数期限持有率'},
    'cross': {'future':'跨品种对数价比 close','basis':'分红调整相对基差（bp）',
              'annual':'分红调整相对基差年化','raw_basis':'未调整相对基差（bp）',
              'log_basis':'未调整相对对数基差','raw_annual':'未调整相对简单年化',
              'log_annual':'未调整相对对数年化'},
}
QUANTITY = ('h 为每1手A配多少手B：跨期 h=1；跨品种 h=前一完整交易日的'
            ' F_A×合约乘数_A/(F_B×合约乘数_B)。V配=min(V_A,V_B/h)，'
            'OI配=min(OI_A,OI_B/h)，均折算成A腿手数；同次持仓变化的两端使用同一个h。')
LIMITS = ('固定具体合约与方向，日线按交易日、分钟按同一时刻及会话对齐，不补齐缺值。'
          '年化两腿剩余期限均须≥5天。量仓匹配量只是容量代理，不能证明真实配对成交或同一账户移仓。'
          '旧历史及缺输入均显示原因；盘中分支不具备时显示有日期的日终参考。')
SYMBOLS = 'F=真实期货价，S=对应现货指数，D=该合约剩余分红点数，T=剩余自然日，V=成交量，OI=持仓量；1bp=万分之一，年化1表示1个百分点。'

# title, meaning, sign/dimension interpretation
FAMILIES = {
 'A03.mean': ('合约对历史均值','对合约对序列X取此前20个完整观察的均值，当前值不进入参考窗口。','与X同单位；表示这对合约自身的近期中心。'),
 'A03.std': ('合约对历史标准差','对X的此前20个完整观察计算样本标准差（ddof=1）。','与X同单位；越大表示这对合约近期波动越大。'),
 'A03.z': ('合约对历史Z','当前X减此前20期X均值，再除以该窗口样本标准差。','倍；正值在自身中心之上，负值在中心之下；并非两腿Z相减。'),
 'A03.percentile': ('合约对历史分位','将当前X放入此前20期自身分布，历史相等值计半权。','0—100%；高分位表示当前X处于自身近期较高位置，不直接代表收益方向。'),
 'A03.change5': ('合约对五期变化','当前X减五期前的X，要求连续6个有效观察。','与X同单位；正值表示X扩大，负值表示X缩小。'),
 'A03.legacy_percentile30': ('合约对30期分位','保留原30期≤分位规则，但统计对象使用明确构造的合约对X。','0—100%；是独立的30期规则，不能与20期半权分位混用。'),
 'A04.points': ('分红调整跨期点差','把两腿各自加入剩余分红后，以近月减远月。','点；正值表示调整后的近月高于远月。'),
 'A04.bp': ('分红调整跨期标准化差','分红调整后的近远点差除以共同现货指数，再乘10000。','bp；1bp是共同现货点位的万分之一。'),
 'A04.raw_points': ('未调整跨期点差','直接用近月期货收盘减远月期货收盘，不加入分红。','点；正值表示近月高于远月。'),
 'A04.raw_bp': ('未调整跨期标准化差','近远期货点差除以共同现货指数，附带这条价差自身的历史统计。','bp；近−远方向。'),
 'A05': ('分红调整期限持有率','以调整后远月相对近月的价格比例，按两腿到期日之差年化。','年化百分点；正值表示调整后远月较贵，方向为远/近，与近−远价差相反。'),
 'A05.log_carry': ('未调整对数期限持有率','对远月/近月价格取对数，再按到期日间隔年化；附带自身历史统计。','年化百分点；正值表示远月高于近月。'),
 'A06': ('同到期分红调整相对基差','两腿分别用自己的现货和分红标准化，在同一到期日比较A−B。','bp；正值表示A相对自身现货的调整基差高于B。'),
 'A06.raw': ('同到期未调整相对基差','比较两腿各自期货/现货的未调整普通基差，统计对象为该相对基差序列。','bp；A−B方向；要求两腿实际到期日相同。'),
 'A06.log': ('同到期相对对数基差','计算10000ln[(F_A/S_A)/(F_B/S_B)]及其自身历史统计。','bp；正值表示A的期现价格比例更高；要求实际到期日相同。'),
 'A07': ('合约对五期收益归因','对同一合约对五期对数价比变化，分别展示期货、现货、基差及分红情景分量。','收益bp；主项为10000Δ5ln(F_A/F_B)，未扣成本，也不是实际调仓策略收益。'),
 'A09': ('合约对当前名义金额','用当前两腿价格及合约乘数给出名义金额、等名义手数比和取整误差。','h的单位为B手/A手；这里是当前金额说明，量仓指标使用前一完整交易日h。'),
 'A09.one_to_one_pnl5': ('跨期1:1五期金额变化','固定近月1手、远月1手，计算近−远价差五期变化乘合约乘数。','元；正值表示该固定1:1多近空远组合价格变化为正，未扣成本。'),
 'A11': ('合约对30分钟实现波动','先构造同刻X，再对同一会话连续30个一分钟变化平方求和开方。','与X同单位；衡量合约对自身波动，不是两腿波动率相减。'),
 'A12': ('合约对连续偏离事件','以X自身此前30分钟均值和标准差形成Z；同方向|Z|≥2连续3根确认，按恢复规则记录事件。','次、倍、根及时间；只描述该对合约的连续偏离，不自动生成交易指令。'),
 'A14.book': ('双向跨期一档盘口','买近卖远看Ask近−Bid远；卖近买远看Bid近−Ask远，并检查两腿报价同刻及盘口量。','点；两种方向分别展示，缺真实有效盘口就留空。'),
 'B01': ('合约对开盘偏离与修复','先形成X；比较开盘X与前收X，再衡量日内向前收方向回归的比例。','gap与X同单位；repair为倍，正值表示回归，1表示恰好修复，负值表示继续偏离。'),
 'B02': ('合约对匹配量加权中枢','逐分钟先形成同刻X，再以min(V_A,m,V_B,m/h)加权；日终需完整240个同步分钟。','center/gap与X同单位；gap=日终X−中枢，权重为折算A腿的匹配容量代理。'),
 'B03': ('合约对共同增仓加权漂移','每期先计算ΔX，再以W+=min(max(ΔOI_A,0),max(ΔOI_B,0)/h)加权，汇总连续5期。','与X同单位；正值表示双腿共同增仓时X倾向扩大；一腿独增仓不产生共同权重。'),
 'B04': ('合约对匹配换手与增仓','Q=V配/OI配前；ΔOI配使用同一个h比较今日与昨日；K=100ΔOI配/V配。','Q为倍，K为%，ΔOI配为A腿折算手数；不是只显示A腿换手。'),
 'B05': ('跨期持仓迁移形态代理','同时使用近月减仓和远月增仓，取可对应部分的较小值，并显示迁移占比和两腿净增仓。','M为手，R/N为%；只描述持仓形态，不能断言同一账户真实移仓。'),
 'B06': ('跨期流量与存量份额偏移','远月当日成交占两腿成交的比例，减远月昨日持仓占两腿持仓的比例。','百分点；正值表示成交分布比昨日持仓分布更偏向远月。'),
 'B07': ('合约对收盘位置','先从完整同刻分钟X形成合约对自己的开高低收，再算(2C−H−L)/(H−L)。','−1到1；1在合约对当日最高点，−1在最低点；高低相等时留空。'),
 'B08': ('合约对匹配持仓扩张','用当期前一完整交易日h固定两端，比较当前与五期前min(OI_A,OI_B/h)的对数增长。','对数增长百分点；正值表示这对具体合约的匹配持仓容量扩大。原固定品种集合增长仅作辅助。'),
 'B09': ('合约对成交活跃度','以V配除以自身此前20个完整交易日V配的中位数，当前日不进入基准。','倍；1为自身历史典型水平，2为两倍；两腿同时放量也能反映为活跃。'),
 'B10': ('合约对路径效率','使用同一X的五期净变化除以五期绝对变化之和。','−1到1；绝对值越大表示路径越单向，符号表示X变化方向；路径为0时留空。'),
 'B11': ('合约对振幅压力','以完整同步分钟X形成高低收，TR=max(H−L,|H−前收|,|L−前收|)，再除自身此前20期TR中位数。','倍；1为自身历史典型振幅，越大波动压力越高；不将两腿振幅比当合约对压力。'),
 'B12': ('合约对匹配容量','按前一完整交易日h折算两腿真实成交，A容量=min(V_A,V_B/h)，B容量=h×A容量；可另输入参与比例p。','手；只是已观察成交的容量上限代理，不是可保证成交量；未填p不默认比例。'),
}

EXTRA_IDS = {
 'A05':['A05.legacy_carry'],
 'A05.log_carry':['A05.legacy_log_carry'],
 'B03':['B03.legacy_difference','B03.pair.positive_weight'],
 'B04':['B04.pair.volume','B04.pair.previous_oi','B04.pair.oi','B04.pair.h'],
 'B07':['B07.legacy_difference']+['B07.pair.'+s for s in ('open','high','low','close')],
 'B08':['B08.legacy_collection','B08.pair.total','B08.pair.base','B08.pair.h'],
 'B09':['B09.legacy_log_ratio','B09.legacy_same_time','B09.pair.baseline'],
 'B11':['B11.legacy_log_ratio','B11.legacy_sample','B11.pair.tr','B11.pair.baseline'],
 'B12':['B12.legacy_A','B12.legacy_B','B12.legacy_h'],
}

def enrich(entry, category):
    if category not in ('calendar','cross'):
        return entry
    family=entry['family_id']; price=entry['input_id']; old=entry['title']
    title,explanation,direction=FAMILIES[family]
    entry['legacy_title']=old
    entry['title']=(INPUT_LABELS[category][price]+' · ' if price!='fixed' else '')+title
    definition=pair_definition(category,price if price!='fixed' else 'basis')
    construction=('A=近月，B=远月。' if category=='calendar' else 'A=界面左腿，B=右腿，方向固定。')
    construction+=('X='+definition['construction']+'。' if price!='fixed' else explanation)
    if family.startswith('B') and family not in ('B01','B10'):
        construction+=' '+QUANTITY
    limits=LIMITS
    if category=='cross' and price=='future':
        limits+=' 对数价比绝对水平依赖各指数基准，只与这对合约自身历史比较；不是回归残差或可交易组合盈亏。'
    if category=='cross' and price in ('annual','raw_annual','log_annual'):
        limits+=' 异到期组合按各腿自己的T年化，同时含期限差异；仅同到期组合才是同期比较。'
    if category=='calendar' and price in ('annual','raw_annual','log_annual'):
        direction+=' 输入X采用远/近，正值表示远月较贵；与近−远价差的方向不同。'
    entry.update(formula_version=PAIR_FORMULA_VERSION,source_ref='合约对重构-2026-10-22；原 '+entry['source_ref'],
                 pair_construction=construction,explanation=explanation+' '+SYMBOLS,direction=direction,limitations=limits,
                 pair_metadata=definition,entity_kind='contract_pair')
    if family=='B08':entry.update(required_fields=['OI_A','OI_B','lagged_F_A','lagged_F_B','multiplier'],fixed_inputs=['OI_A','OI_B','lagged_F_A','lagged_F_B','multiplier'])
    if family in ('B02','B03','B04','B08','B09','B12'):
        entry['required_fields']=list(dict.fromkeys(entry['required_fields']+['previous_complete_pair_prices','multiplier']))
    if price=='fixed':
        entry['pair_metadata']={**definition,'construction':construction,'unit':entry['unit_by_category'][category]}
    if price!='fixed':
        if entry['unit'] in ('点','bp','对数bp','年化百分点','收益bp'):
            entry['unit_by_category'][category]=definition['unit']
        if family=='A11':entry['unit_by_category'][category]=definition['unit']
        entry['metric_ids'].append('pair.legacy_input')
        if family.startswith('A03.') and family.split('.')[-1] in ('mean','std','z','percentile','change5'):
            entry['metric_ids'].append('pair.legacy_'+family.split('.')[-1])
    if family in ('B09','B11'):entry['unit_by_category'][category]='倍'
    entry['metric_ids']=list(dict.fromkeys(entry['metric_ids']+EXTRA_IDS.get(family,[])))
    # The stable variant has one designated headline; all components remain visible.
    entry['metric_roles']={code:'primary' if code==entry['primary'] else 'auxiliary' for code in entry['metric_ids']}
    return entry

def definition(code, entry, category):
    """Return overrides for changed pair math; None retains an original component."""
    if category not in ('calendar','cross'):return None
    price=entry['input_id']; xu=pair_definition(category,price if price!='fixed' else 'basis')['unit']
    formula=None;unit=xu;title=code;scope='完整历史日线';supported=False
    reason='缺双腿真实输入、上一完整交易日h或完整连续窗口；不填充缺值'
    if code.startswith('pair.legacy_'):
        suffix=code[len('pair.legacy_'):]
        title='原单腿输入差'+(' · '+suffix if suffix!='input' else '')
        formula='辅助：原各腿'+price+'算完后作A−B'+('；再对该旧序列取'+suffix if suffix!='input' else '')
        unit='倍' if suffix=='z' else '%' if suffix=='percentile' else '点' if price=='future' else xu
    elif code in ('A05.legacy_carry','A05.legacy_log_carry'):
        title='原期限持有率（未加双腿T≥5守卫，仅辅助）';unit='年化百分点'
        formula='100×[(F远+D远)/(F近+D近)−1]×365/(T远−T近)' if code=='A05.legacy_carry' else '100×ln(F远/F近)×365/(T远−T近)'
    elif code in ('B03.legacy_difference','B07.legacy_difference','B09.legacy_log_ratio','B11.legacy_log_ratio','B09.legacy_same_time','B11.legacy_sample'):
        title='原单腿比较 · 辅助解释'
        formula={'B03.legacy_difference':'独立增仓加权漂移_A−独立增仓加权漂移_B',
                 'B07.legacy_difference':'(CLV_A−CLV_B)/2',
                 'B09.legacy_log_ratio':'ln(RVOL_A/RVOL_B)',
                 'B11.legacy_log_ratio':'ln(单腿振幅压力_A/单腿振幅压力_B)',
                 'B09.legacy_same_time':'ln(各腿同刻累计成交活跃度_A/各腿同刻累计成交活跃度_B)',
                 'B11.legacy_sample':'ln(各腿采集区间振幅压力_A/各腿采集区间振幅压力_B)'}[code]
        unit=('点' if price=='future' else 'bp' if price in ('basis','raw_basis','log_basis') else '年化百分点') if code.startswith('B03') else '比值' if code.startswith('B07') else '对数倍数'
    elif code=='B08.legacy_collection':
        title='原固定品种集合增长 · 辅助解释';unit='对数增长百分点'
        formula='100 ln(Σ固定成员OI_t/Σ固定成员OI_(t−5))；跨品种时为两集合增长之差'
    elif code.startswith('B12.legacy_'):
        title='原当前手数比容量 · 辅助解释';unit='手/手' if code.endswith('_h') else '手'
        formula='原当前h=F_A M_A/(F_B M_B)，跨期为1；A=min(V_A,V_B/h)，B=hA'
    elif '.pair.' in code:
        title='合约对构造分量 '+code.split('.pair.')[1]
        suffix=code.split('.pair.')[1]
        unit='手/手' if suffix=='h' else xu if code.startswith(('B07','B11')) else '手'
        formula={
          'B03.pair.positive_weight':'Σ5min(max(ΔOI_A,0),max(ΔOI_B,0)/h)',
          'B04.pair.volume':'min(V_A,V_B/h)','B04.pair.previous_oi':'min(OI_A前,OI_B前/h)',
          'B04.pair.oi':'min(OI_A,OI_B/h)','B04.pair.h':'前一完整交易日等名义B/A手数比；跨期1',
          'B07.pair.open':'首个同步分钟X','B07.pair.high':'max(当日同步分钟X)',
          'B07.pair.low':'min(当日同步分钟X)','B07.pair.close':'最后同步分钟X',
          'B08.pair.total':'min(OI_A,t,OI_B,t/h_t)','B08.pair.base':'min(OI_A,t−5,OI_B,t−5/h_t)',
          'B08.pair.h':'h_t使用前一完整交易日；五期比较两端固定此h_t',
          'B09.pair.baseline':'median(V配[t−20:t−1])',
          'B11.pair.tr':'max(H_X−L_X,|H_X−C_X前|,|L_X−C_X前|)',
          'B11.pair.baseline':'median(TR配[t−20:t−1])'}[code]
    elif code in ('B03','B04.Q','B04.K','B04.doi','B04.Q.intraday','B07','B08','B09','B09.same_time','B11','B11.sample'):
        title=FAMILIES[entry['family_id']][0]
        formula,unit={
          'B03':('Σ5(ΔX W+)/Σ5W+；W+=min(max(ΔOI_A,0),max(ΔOI_B,0)/h)',xu),
          'B04.Q':('V配/OI配前','倍'),'B04.K':('100 ΔOI配/V配','%'),
          'B04.doi':('min(OI_A,t,OI_B,t/h_t)−min(OI_A,t−1,OI_B,t−1/h_t)','手'),
          'B04.Q.intraday':('盘中累计V配/昨日OI配，使用上一完整交易日h','倍'),
          'B07':('(2C_X−H_X−L_X)/(H_X−L_X)，完整同刻分钟X形成OHLC','比值'),
          'B08':('100 ln[min(OI_A,t,OI_B,t/h_t)/min(OI_A,t−5,OI_B,t−5/h_t)]','对数增长百分点'),
          'B09':('V配_t/median(V配[t−20:t−1])','倍'),
          'B09.same_time':('合约对同刻累计V配/此前20日同刻V配中位','倍'),
          'B11':('TR_X/median(TR_X[t−20:t−1])','倍'),
          'B11.sample':('采集区间同步X极差/此前20日完整分钟合约对TR中位','倍')}[code]
        if code in ('B04.Q.intraday','B09.same_time','B11.sample'):
            scope='盘中合约对分支';reason='当前合约对分支缺完整同步输入或历史同刻基准；不代入原单腿比较'
            if code=='B11.sample':scope='采集区间·非全天振幅';reason+='；非全天振幅'
    elif code.startswith('B02.'):
        suffix=code.split('.')[-1];title='合约对匹配量加权 '+suffix
        formula={'center':'Σ(X_m min(V_A,m,V_B,m/h))/Σmin(V_A,m,V_B,m/h)',
                 'gap':'日终X−合约对匹配量中枢','n':'完整240个同步分钟',
                 'weight_sum':'Σmin(V_A,m,V_B,m/h)','weighted_sum':'Σ(X_m min(V_A,m,V_B,m/h))',
                 'collection_center':'Σ(同步X×min(有效ΔV_A,有效ΔV_B/h))/Σ匹配增量量',
                 'collection_gap':'最新同步X−采集区间匹配量中枢'}[suffix]
        unit='根' if suffix=='n' else '手' if suffix=='weight_sum' else xu+'×手' if suffix=='weighted_sum' else xu
        if suffix.startswith('collection_'):
            scope='采集区间·非全日VWAP';supported=True
            reason='缺同刻双腿采集量或前一完整交易日h；非完整历史分钟，重连/跨会话需新基准'
    elif code.startswith('B12.'):
        suffix=code.split('.')[-1]
        formula={'A':'min(V_A,V_B/h前)','B':'h前×min(V_A,V_B/h前)',
                 'h':'跨期1；跨品种前一完整交易日F_A M_A/(F_B M_B)',
                 'balance':'min(V_A F_A M_A,V_B F_B M_B)/max(...)（当前名义平衡辅助）',
                 'p':'用户显式0≤p≤1','A_p':'p×min(V_A,V_B/h前)','B_p':'p×h前×min(V_A,V_B/h前)'}[suffix]
        unit='手/手' if suffix=='h' else '倍' if suffix in ('p','balance') else '手'
    if formula is None:return None
    return dict(id=code,title=title,unit=unit,formula=formula,scope=scope,
                missing_reason=reason,current_supported=supported)
