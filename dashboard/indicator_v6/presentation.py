"""Chinese explanations and typeset formulas shared by the two renderers."""
from html import escape as esc
import json
from pathlib import Path
import struct
from .service import CATALOG,CHOICE_LABELS,LABELS,display

SYMBOLS=[('F','当前具体期货合约价格'),('S','该合约对应的现货指数价格'),('T','到期日减观测日的剩余自然日'),('ΔT','远月到期日减近月到期日的固定自然日差'),
 ('n / f','近月 / 远月合约'),('u / v','组合第一腿 / 第二腿；跨指数样例为 IF / IC'),('X','当前选择的完整历史输入序列'),('t / τ','交易日 / 日内分钟结束时刻'),
 ('b / a','对数基差（bp）/ 年化基差（%）'),('c / ℓ / aₙբ','标准化价差 / 对数价差 / 年化跨期价差'),('G / Gₐ','跨指数基差差 / 年化基差差'),
 ('V','对应观测区间的成交量，单位为手'),('OI','当前持仓量，单位为手'),('ΔOI','相邻观测的持仓净变化'),('w','非负成交或量仓权重'),
 ('RVOL','当前成交量除以前期成交中位数'),('O / H / L / C','同一序列的开盘、最高、最低、收盘价'),('N / M','参照观测数 / 回归训练收益数'),
 ('k','变化、路径或加权窗口的交易日数'),('μ / s','历史均值 / 样本标准差（ddof=1）'),('r','对数收益；理论定价公式中另指融资年利率'),
 ('α / β / ε','回归截距 / 回归斜率 / 当前残差'),('E / RV','有符号路径效率 / 未额外年化的实现波动'),('m','合约乘数，单位为元每指数点'),
 ('h','第二腿手数除以第一腿手数'),('p / q','容量的成交参与比例 / 持仓占用比例；模型定价中的 q 为股息年利率'),('L','连续确认所需根数；OHLC 中的 L 为最低价')]
SYMBOLS=[(k.strip(),v) for symbols,v in SYMBOLS for k in symbols.split(' / ')]
SYMBOLS=[(k.replace('aₙբ','aₙf'),v) for k,v in SYMBOLS]
_precise={'n':'近月合约下标','f':'远月合约下标','u':'组合第一腿；跨指数样例为 IF','v':'组合第二腿；跨指数样例为 IC',
 't':'交易日观测时点','τ':'分钟结束时刻','b':'对数基差，单位 bp','a':'年化基差，单位 %','c':'标准化跨期价差，单位 bp','ℓ':'对数跨期价差，单位 bp','aₙf':'年化跨期价差，单位 %',
 'G':'两腿对数基差之差，单位 bp','Gₐ':'两腿年化基差之差，单位百分点','O':'开盘价','H':'最高价','L':'最低价；连续确认参数中表示根数','C':'收盘价',
 'N':'历史参照观测数；B04 中表示合计持仓净增率','M':'回归训练收益数；B04 中表示匹配迁移量','μ':'历史参照均值','s':'样本标准差，ddof=1',
 'α':'带截距回归中的截距','β':'带截距回归中的斜率或敏感度','ε':'当前回归残差','E':'有符号路径效率','RV':'实现波动，不额外年化',
 'p':'成交参与比例','q':'容量中的持仓占用比例；A10 中为股息年利率'}
SYMBOLS=list(dict((k,_precise.get(k,v)) for k,v in SYMBOLS).items())+[('x','回归解释变量；默认取对应现货或第二腿收益'),('y','回归被解释变量；默认取期货或第一腿收益'),('I','条件成立取 1，否则取 0 的指示函数')]

MATH={
 'A01':'b = 10⁴ ln(F / S)　　a = 365 b / (100 T)',
 'A02':'P = 100 [Σ 𝟙(Xᵢ < Xₜ) + ½ Σ 𝟙(Xᵢ = Xₜ)] / N　　Z = (Xₜ − μ) / s',
 'A03':'g = X₀ − Xₚᵣₑᵥ　　d = Xτ − X₀　　R = −d / g',
 'A04':'μw = Σ(wⱼ Xⱼ) / Σwⱼ　　D = Xτ − μw',
 'A05':'P = Σ(wᵢ ΔXᵢ) / Σwᵢ　　wᵛᵒⁱ = min(RVOL, 3) max(ΔOI / OIₚᵣₑᵥ, 0)',
 'A06':'Q = Vₜ / OIₜ₋₁　　K = (OIₜ − OIₜ₋₁) / Vₜ',
 'A07':'εₜ = yₜ − α − βxₜ　　Zε = εₜ / sε,train',
 'A08':'E = (Xₜ − Xₜ₋ₖ) / Σ|ΔXᵢ|　　RV = 10⁴ √(Σrᵢ²)',
 'A09':'Eventτ = 𝟙(同方向 |Z| ≥ 2 的连续根数恰为 3)',
 'A10':'Ffair = S [1 + (r − q) T / 365]　　e = 10⁴ (F − Ffair) / S',
 'A11':'候选 = −sign(Z) × 𝟙(全部依赖有效且所有门槛满足)',
 'A12':'名义金额 = F × m　　基差金额 = (F − S) × m',
 'B01':'c = 10⁴ (Fₙ − Fբ) / S　　ℓ = 10⁴ ln(Fₙ / Fբ)　　aₙբ = 365 ℓ / (100 ΔT)',
 'B04':'M = min[max(−ΔOIₙ, 0), max(ΔOIբ, 0)]',
 'B05':'P = Σ(wᵢ ΔXᵢ) / Σwᵢ　　wᵢ = Mᵢ min(RVOLpair,ᵢ, 3)',
 'B06':'Dᵥ = ln(RVOLₙ / RVOLբ)　　Dclv = (CLVₙ − CLVբ) / 2',
 'B10':'cap = min(pVᵤ, pVᵥ / h, qOIᵤ, qOIᵥ / h)',
 'C01':'G = bᵤ − bᵥ　　Gₐ = aᵤ − aᵥ',
 'C03':'10⁴(Rꜰᵤ − βRꜰᵥ) = 10⁴(Rₛᵤ − βRₛᵥ) + Δbᵤ − βΔbᵥ',
 'C04':'β = Cov(rₛᵥ, rₛᵤ) / Var(rₛᵥ)　　hβ = β Fᵤmᵤ / (Fᵥmᵥ)',
 'C05':'ΔP = Σ(wᵤ ΔXᵤ) / Σwᵤ − Σ(wᵥ ΔXᵥ) / Σwᵥ',
 'C06':'g = 100 ln(Σ OIₘ,ₜ / Σ OIₘ,ₜ₋₅)　　D = gᵤ − gᵥ',
 'C07':'CLV = (2C − H − L) / (H − L)　　压力 = TRbp / median(TRbp,hist)'}
for target,source in {'B02':'A02','C02':'A02','B03':'A04','B07':'A08','C08':'A08','B08':'A07','C09':'A07','B09':'A11','C10':'B10'}.items():MATH[target]=MATH[source]
MATH={k:v.replace('բ','f').replace('ꜰ','F').replace('𝟙','I') for k,v in MATH.items()}
PARAM_UNITS={'calendar_days':'自然日','trading_days':'交易日','minute_bars':'根分钟','observations':'个观测','returns':'个收益 / 变化','count':'个',
             'ratio':'比率','decimal_rate':'小数年利率','decimal_return_squared':'小数收益方差','decimal_return':'小数收益','bp':'bp','enum':'口径','boolean':'是否启用'}
PARAM_LABELS={'IF_multiplier':('IF 合约乘数','元/指数点'),'open_bar':('首个分钟结束时刻','时:分'),'weight':('成交权重','手'),'accumulation':('累计范围','交易日'),
 'intercept':('回归包含截距','是否'),'reset':('重新预热条件','会话'),'model':('理论定价模型','情景'),'same_expiry':('要求两腿同到期','是否'),
 'beta_default':('默认归因 β','无量纲'),'beta_diagnostic':('归因 β 的固定方式','诊断口径'),'m_IF':('IF 合约乘数','元/指数点'),'m_IC':('IC 合约乘数','元/指数点'),
 'integer_IF':('示例 IF 整数手数','手'),'integer_IC':('示例 IC 整数手数','手'),'set':('持仓合约集合','集合'),'return_weight':('组合收益第二腿权重','无量纲'),'thresholds':('候选筛选门槛','规则')}
PARAM_VALUES={'V_F_min':'期货分钟成交量','min(V_n,V_f)':'两腿分钟成交量较小值','trading_day':'当日累计，午休保留','session_or_gap':'会话切换或实际缺失后重新预热',
 'simple_carry_scenario':'简单持有成本情景','analysis_date_fixed':'区间固定分析日 β','same_current_listed_months_on_both_endpoints':'两端固定当日挂牌月份集合',
 'index_beta matched':'按指数收益 β 匹配','same_as_B09':'同跨期修复条件筛选'}


def detail_html(result,advanced=False,formula_url=None):
    c=result['card'];x=result['variant'];code=result['id'];unit=next(iter(result['fields']))['unit']
    if advanced:
        technical={k:result[k] for k in ('id','variant','parameters','cache_key','data_version')}
        technical['规范公式']=c['formula']
        technical['最新逐字段契约']={k:v[-1] if v else None for k,v in result['series'].items()}
        return '<h3>高级详情</h3><pre style="white-space:pre-wrap">'+esc(json.dumps(technical,ensure_ascii=False,indent=2))+'</pre>'
    asset=Path(__file__).parent/'formula_assets'/f'{code}_public.png'
    width=min(760,struct.unpack('>I',asset.read_bytes()[16:20])[0]) if asset.exists() else 760
    equation=('<p><img width="'+str(width)+'" src="'+esc(formula_url)+'" alt="'+esc(MATH[code])+'"></p>') if formula_url else '<div style="font-family:Cambria Math,serif;font-size:22px;padding:12px">'+esc(MATH[code])+'</div>'
    parts=['<h3>经济含义与解读</h3><p>'+esc(c['purpose'])+'</p>',
           '<h3>数学公式</h3>'+equation,
           '<p><b>当前 X：</b>'+esc(result['variant_label'])+'；'+esc(c['x_adjustment']['recompute'])+'</p>']
    direction=next(g['direction'] for g in CATALOG['groups'] if g['id']==result['group'])
    if any(f['unit']=='direction' for f in result['fields']):parts.append('<p>'+esc(direction)+'；−1 为反向；0 表示依赖完整有效但候选条件未满足。</p>')
    if x in ('a','Ga'):parts.append('<p>a<sub>t</sub> = 365 b<sub>t</sub> / (100 T<sub>t</sub>)；逐日 T 随历史日期变化。年化变化用百分点。</p>')
    if x in ('ac','l'):parts.append('<p>ℓ<sub>t</sub> = 10000 ln(F<sub>n,t</sub> / F<sub>f,t</sub>)；a<sub>c,t</sub> = 365 ℓ<sub>t</sub> / (100 ΔT)。固定合约对内 ΔT 不变。</p>')
    if x=='ea':parts.append('<p>e<sub>a</sub> = 365 e / (100 T)；多空方向成本分别乘相同系数后扣除，单位为百分点。</p>')
    if x=='restored':parts.append('<p>G<sub>t</sub> = 100 T<sub>t</sub> G<sub>a,t</sub> / 365；先逐端点还原，再计算 ΔG。此分支 β=1，单个 Gₐ 不足以支持 β≠1 的归因。</p>')
    if code=='A12':parts.append('<p>每手名义金额显示为万元，公式结果须除以 10000；点差金额显示为元。</p>')
    parts+=['<h3>符号释义</h3><table cellspacing="8">']
    parts += ['<tr><td><b>'+esc(k)+'</b></td><td>'+esc(v)+'</td></tr>' for k,v in SYMBOLS]
    parts+=['</table><h3>输入替换</h3><p>'+esc(c['x_adjustment']['summary'])+'</p><p>'+esc(c['x_adjustment']['detail'])+'</p>',
            '<h3>参数与默认值</h3><table cellspacing="8"><tr><th>参数</th><th>默认值</th><th>单位</th><th>作用及范围</th></tr>']
    for p in c['parameter_definitions']:
        label=p['label'];constraint=p.get('constraint','');u=PARAM_UNITS.get(p['unit'],p['unit'])
        if p['key'] in PARAM_LABELS:label,u=PARAM_LABELS[p['key']]
        if code=='A10' and p['key']=='q':label='股息年利率';u='小数年利率';constraint='固定研究情景，缺失时不能默认零'
        default=p['default'];default=('是' if default else '否') if isinstance(default,bool) else PARAM_VALUES.get(str(default),default)
        parts.append('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in (label,default,u,constraint))+'</tr>')
    parts+=['</table><h3>何时不产生数值</h3>']
    parts+=['<p>• '+esc(rule['condition'])+'</p>' for rule in c['null_rules']]
    parts+=['<p>每个输出独立判断。空值显示 —，有效的零仍显示为 0。分位、Z、回归和量能参照均排除当前观测。</p>',
            '<h3>真实数据示例</h3><p>下表来自当前选中的真实来源与观测时间；研究回放不代表实时行情。</p><table cellspacing="8">']
    for f in result['fields']:
        if not result['series'][f['key']]:continue
        p=result['series'][f['key']][-1];v,u=display(p)
        parts.append('<tr>'+''.join('<td>'+esc(str(a))+'</td>' for a in (f['label'],v+' '+u,p['timestamp'],' / '.join(str(i or '缺合约') for i in p['contract_ids'])))+'</tr>')
    parts.append('</table>')
    for note in result['limitations']:parts.append('<p>'+esc(note)+'</p>')
    return ''.join(parts)
