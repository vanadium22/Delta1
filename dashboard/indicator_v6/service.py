"""Shared result API for desktop and browser, including explicit archive provenance."""
from copy import deepcopy
from datetime import date
import hashlib,json,threading
from pathlib import Path
from . import daily,minute
from .core import *
from .sources import Archive,Published,ROOT,SPOTS

CATALOG=json.loads((Path(__file__).parent/'catalog.json').read_text(encoding='utf8'))
CARDS={c['id']:c for c in CATALOG['indicators']}
REASONS={**CATALOG['reason_codes'],'ARCHIVE_REASON_UNKNOWN':'历史归档为空，具体原因尚未定位；不能推断为零或某个已知原因'}
CHOICE_LABELS={'b':'对数基差','a':'年化基差','cal':'标准化价差','l':'对数价差','ac':'年化跨期价差','G':'基差差','Ga':'年化基差差',
               'fixed':'原始数量 / 收益口径','e':'模型偏离','ea':'年化模型偏离','returns':'期现对数收益','restored':'由年化差还原归因'}
FIXED_LABELS={'A06':'成交量与持仓量','A12':'价格与合约乘数','B04':'双腿成交与持仓','B06':'双腿成交与真实 OHLC','B10':'数量与固定手数比',
              'C03':'原始价格收益归因','C04':'指数收益与价格乘数','C06':'固定挂牌集合持仓','C07':'双腿真实 OHLC','C10':'数量与指数 β 手数比'}
def variant_label(code,x):return FIXED_LABELS.get(code,CHOICE_LABELS[x]) if x=='fixed' else CHOICE_LABELS[x]
LABELS={'points':'期现点差','B':'比例基差','b':'对数基差','a':'年化基差','Q':'成交与前日持仓之比','K':'净持仓变化占成交',
 'P':'正增仓加权推进','C1':'量仓加权推进','Pa':'年化增仓加权推进','Wa':'年化量仓加权推进','C2':'候选方向','candidate_a':'年化候选方向',
 'fair':'情景理论价格','fair_dev':'模型偏离','fair_space':'扣成本绝对空间','space_short':'空期货方向成本空间','space_long':'多期货方向成本空间',
 'annual_model_gap':'年化模型偏离','annual_space':'年化绝对空间','annual_short':'年化空期货方向空间','annual_long':'年化多期货方向空间',
 'nominal':'每手名义金额','basis_cash':'每手基差金额','cal_points':'近月减远月点差','cal':'标准化价差','l':'对数价差','ac':'年化跨期价差',
 'M':'近减远增匹配量','R':'匹配量占前日持仓','N':'合计持仓净增率','share_diff':'远月成交与持仓份额差',
 'C3':'移仓量能加权推进','P_ac':'年化移仓推进','P_l':'对数价差移仓推进','C3_weight5':'五日迁移权重合计',
 'B_rvol_diff':'近远月相对成交活跃差','B_clv':'近远月收盘位置差','B_volume_cap':'成交约束容量','B_cap':'双约束连续容量','B_integer':'整数容量上限',
 'G':'基差差','Ga':'年化基差差','fret5':'期货收益差','sret5':'指数收益贡献','weighted_futures5':'β 加权期货收益差',
 'weighted_spot5':'β 加权指数贡献','weighted_basis5':'β 加权基差贡献','restored_basis5':'年化差还原的基差贡献',
 'index_beta':'指数收益敏感度 β','index_r2':'指数回归解释度 R²','h_equal':'等名义配对手数比','h_beta':'β 配对手数比','integer_residual':'2:1 取整后的敏感度余量',
 'IC_C1':'IC 量仓推进','C4':'双腿量仓推进差','C_Wu':'IF 年化量仓推进','C_Wv':'IC 年化量仓推进','C_Wa':'双腿年化量仓推进差',
 'IF_totalOI':'IF 挂牌集合总持仓','IC_totalOI':'IC 挂牌集合总持仓','IF_totalgrowth':'IF 同集合持仓增长','IC_totalgrowth':'IC 同集合持仓增长',
 'oi_growth_diff':'双腿持仓增长差','rvol_diff':'所选合约相对成交活跃差','clv_diff':'收盘位置差','stress':'IF 真实波幅压力','IC_stress':'IC 真实波幅压力',
 'C_vol20':'期货收益差 20 日波动','C_Gvol20':'基差差变化 20 日波动','C_Gavol20':'年化基差差变化 20 日波动',
 'C_regbeta':'期货收益回归 β','C_resid':'期货收益残差','C_resid_z':'收益残差 Z','capV_A':'成交约束 IF 容量','capOI_A':'持仓约束 IF 容量','C6':'双约束 IF 连续容量','C6_B':'对应 IC 连续数量',
 'A_rv30':'期货收益 30 分钟波动','B_rv30':'近远月收益差 30 分钟波动','B_c_rv30':'标准化价差变化波动','A_arv30':'年化基差变化波动','B_acrv30':'年化跨期价差变化波动'}
for c in CARDS.values():
    for panel in c['plot']['panels']:
        for series in panel['series']:LABELS.setdefault(series['field'],series['label'])
for prefix in ('A','B'):
    for suffix,name in [('minbeta','分钟收益回归 β'),('resid','当前分钟收益残差'),('resid_z','分钟残差 Z')]:LABELS[prefix+'_'+suffix]=name
for x in ('b','a','cal','l','ac','G','Ga','c'):
    name=CHOICE_LABELS.get(x,'标准化价差')
    for suffix,title in [('pct','历史分位'),('z','历史偏离 Z'),('d5','五日变化'),('E','五日路径效率')]:LABELS[x+'_'+suffix]=name+' · '+title
    for prefix,title in [('center','成交加权中枢'),('D','当前偏离中枢'),('gap','开盘较前收偏离'),('intra','开盘至当前变化'),('repair','盘中回吐比'),('event','当前确认事件'),('count','日内累计确认'),('events','完整交易日确认'),('candidate','候选方向')]:LABELS[prefix+'_'+x]=name+' · '+title


def variants(code):
    for rule in ('direct_price','calendar_price','cross_price'):
        r=CATALOG['variant_rules'][rule]
        if code in r['ids']:return r['choices']
    return ['e','ea'] if code=='A10' else ['returns'] if code=='A07' else ['fixed','restored'] if code=='C03' else ['fixed']


def field_specs(code,x):
    c=CARDS[code];fs={f['key']:deepcopy(f) for f in c['fields']}
    keys=list(fs)
    def extra(key,unit,freq='1d'):fs[key]=dict(key=key,unit=unit,frequency=freq);return key
    if code=='A01':keys=[x,'points','B']
    elif code in ('A02','B02','C02'):keys=[x+'_pct',x+'_z',x+'_d5']
    elif code=='A03':keys=[p+'_'+x for p in ('gap','intra','repair')]
    elif code=='A04':keys=['center_'+x,'D_'+x]
    elif code=='A05':keys=['P','C1'] if x=='b' else ['Pa','Wa']
    elif code=='A08':keys=[x+'_E','A_rv30']+([extra('A_arv30','pp','1m')] if x=='a' else [])
    elif code=='A09':keys=['event_'+x,'count_'+x,'events_'+x]
    elif code=='A10':keys=['fair','fair_dev','fair_space',extra('space_short','bp'),extra('space_long','bp')] if x=='e' else ['fair']+[extra(k,'pp') for k in ('annual_model_gap','annual_space','annual_short','annual_long')]
    elif code=='A11':keys=['C2' if x=='b' else 'candidate_a']
    elif code=='B01':keys=[x,'cal_points']
    elif code=='B03':keys=['center_'+('c' if x=='cal' else x),'D_'+('c' if x=='cal' else x)]
    elif code=='B05':keys=[{'cal':'C3','ac':'P_ac','l':'P_l'}[x],'C3_weight5']
    elif code=='B07':keys=[x+'_E','B_rv30','B_c_rv30']+([extra('B_acrv30','pp','1m')] if x=='ac' else [])
    elif code=='B08':keys=['B_minbeta','B_resid','B_resid_z']+[p+'_'+('c' if x=='cal' else x) for p in ('event','count','events')]
    elif code=='B09':keys=['candidate_'+x]
    elif code=='B10':keys+= [extra('B_integer','lot')]
    elif code=='C01':keys=[x]
    elif code=='C03' and x=='restored':keys=['fret5','sret5',extra('restored_basis5','bp')]
    elif code=='C05':keys=['C1','IC_C1','C4'] if x=='G' else ['C_Wu','C_Wv','C_Wa']
    elif code=='C08':keys=[x+'_E','C_vol20','C_Gvol20']+([extra('C_Gavol20','pp')] if x=='Ga' else [])
    elif code=='C09':keys=['C_regbeta','C_resid','C_resid_z','candidate_'+x]
    # Legal log-calendar variants have their own field names and are recomputed.
    for k in keys:
        if k not in fs:
            unit='pct' if k.endswith('_pct') else 'ratio' if k.endswith(('_z','_E')) else 'direction' if k.startswith('candidate') else 'count' if k.startswith(('count','events')) else 'flag' if k.startswith('event') else 'bp'
            freq='1m' if code in ('B03','B08') and not k.startswith('events') else '1d'
            extra(k,unit,freq)
    return [{**fs[k],'label':LABELS.get(k,k)} for k in keys]


class Service:
    def __init__(self,config=None,config_provider=None):
        self.config=deepcopy(config or {});self.config_provider=config_provider;self.sources={};self.single_cache={};self.pair_cache={};self.cross_cache={};self.result_cache={};self.lock=threading.RLock();self.config_token=None
    def source(self,mode):
        if mode not in ('replay','published'):raise ValueError('未知数据来源')
        if mode=='published' and self.config_provider:
            current=deepcopy(self.config_provider());token=json.dumps({k:current.get(k) for k in ('history_roots','reference_file','allow_unverified','indicator_v6_sessions')},sort_keys=True)
            if token!=self.config_token:
                self.config=current;self.config_token=token;self.sources.pop('published',None);self.result_cache.clear()
        if mode not in self.sources:self.sources[mode]=Archive() if mode=='replay' else Published(self.config)
        return self.sources[mode]
    def refresh(self,mode):
        with self.lock:
            self.sources.pop(mode,None);self.result_cache.clear();self.single_cache.clear();self.pair_cache.clear();self.cross_cache.clear()
    def single(self,s,symbol):
        key=(s.version,symbol)
        if key not in self.single_cache:
            meta=s.contracts.get(symbol,{})
            spot=SPOTS.get((symbol or '')[:2])
            rows=[{**s.raw.get((symbol,day),{}),'spot':s.raw.get((spot,day),{}).get('close'),
                   '_missing_row':(symbol,day) not in s.raw and meta.get('listing','9999')<=day<=meta.get('expiry',''),
                   '_spot_missing':(spot,day) not in s.raw} for day in s.days]
            self.single_cache[key]=daily.single(rows,s.days,meta.get('expiry'),meta.get('multiplier'))
        return self.single_cache[key]
    def pair(self,s,n,f):
        key=(s.version,n,f)
        if key not in self.pair_cache:self.pair_cache[key]=daily.pair(self.single(s,n),self.single(s,f),s.days,s.contracts.get(n,{}).get('expiry'),s.contracts.get(f,{}).get('expiry'),bool(n and f and n[:2]==f[:2] and n!=f))
        return self.pair_cache[key]
    def cross(self,s,f,c):
        key=(s.version,f,c)
        if key not in self.cross_cache:self.cross_cache[key]=daily.cross_pair(self.single(s,f),self.single(s,c),s.days,s.contracts.get(f,{}).get('expiry'),s.contracts.get(c,{}).get('expiry'),s.contracts.get(f,{}).get('multiplier'),s.contracts.get(c,{}).get('multiplier'),bool(f and c and f[:2]!=c[:2]))
        return self.cross_cache[key]
    def options(self,mode='replay',group='A'):
        with self.lock:
            s=self.source(mode);pairs=[]
            for r in s.selections:
                ids=self.identities(r,group)
                if all(ids) and ids not in pairs:pairs.append(ids)
            available=sorted({sym for sym,day in s.raw if sym in s.contracts})
            if group=='A' and available:pairs=[[sym] for sym in available]
            elif group=='B' and available:
                pairs=sorted({tuple(p) for p in pairs}|{(a,b) for a in available for b in available if a[:2]==b[:2] and s.contracts[a]['expiry']<s.contracts[b]['expiry'] and max(s.contracts[a]['listing'],s.contracts[b]['listing'])<=s.contracts[a]['expiry']})
                pairs=[list(p) for p in pairs]
            elif group=='C' and available:pairs=[[a,b] for a in available for b in available if a.startswith('IF') and b.startswith('IC') and s.contracts[a]['expiry']==s.contracts[b]['expiry']]
            return dict(days=sorted({r['trading_date'] for r in s.selections}),identities=pairs,source=s.source,version=s.version,raw_available=bool(s.raw),
                        minute_day='2026-10-09' if mode=='replay' else (s.days[-1] if s.days else None))
    @staticmethod
    def identities(r,group):return [r.get('far')] if group=='A' else [r.get('near'),r.get('far')] if group=='B' else [r.get('far'),r.get('cross')]
    def query(self,code,x=None,mode='replay',identity=None,day=None):
        with self.lock:return self._query(code,x,mode,identity,day)
    def _query(self,code,x,mode,identity,day):
        if code not in CARDS:raise ValueError('指标不存在')
        x=x or variants(code)[0]
        if x not in variants(code):raise ValueError('此指标不适用该输入')
        if identity is not None and (not isinstance(identity,list) or len(identity)!=(1 if code.startswith('A') else 2) or not all(isinstance(v,str) for v in identity)):
            raise ValueError('合约身份数量不符合该研究对象')
        s=self.source(mode);card=CARDS[code];specs=field_specs(code,x)
        if not s.available:raise ValueError('未安装第六版真实回放资料；请选择现有数据服务')
        def supported(v):return bool(s.raw) or v not in ('l','ea','restored')
        unavailable='当前适配器缺少该变体可重算的固定身份历史输入；不能用其他归档序列代替'
        if not supported(x):raise ValueError(unavailable)
        is_minute=any(f['frequency']=='1m' for f in specs)
        day=day or ('2026-10-09' if mode=='replay' and is_minute else s.days[-1] if s.days else None)
        params=card['parameters'];key=json.dumps([s.version,mode,code,x,identity,day,[f['frequency'] for f in specs],params],sort_keys=True,ensure_ascii=False)
        if key in self.result_cache:return deepcopy(self.result_cache[key])
        selected=[r for r in s.selections if r['trading_date']<=day]
        if not selected:raise ValueError('该来源没有指定日期的合法合约观测')
        latest=selected[-1];series={f['key']:[] for f in specs};group=code[0];last_ids=None;index={d:i for i,d in enumerate(s.days)}
        for j,selection in enumerate(selected):
            ids=identity or self.identities(selection,group);d=selection['trading_date'];i=index[d]
            f=ids[0] if group!='B' else ids[1];n=ids[0] if group=='B' else selection.get('near');c=ids[1] if group=='C' else selection.get('cross')
            values={};sets=None
            if s.raw:
                values=self.single(s,f)[i] if group=='A' else self.pair(s,n,f)[i] if group=='B' else self.cross(s,f,c)[i]
                if code=='C06':
                    values=dict(values);sets=[]
                    for root in ('IF','IC'):
                        oi,growth,syms=daily.collection_growth(d,i,s.days,root,s.contracts,s.raw);sets+=syms
                        values[root+'_totalOI']=oi;values[root+'_totalgrowth']=growth
                    values['oi_growth_diff']=values['IF_totalgrowth']-values['IC_totalgrowth']
            ids=sets or ids;changed=last_ids is not None and ids!=last_ids;last_ids=ids
            for field in specs:
                if field['frequency']!='1d':continue
                k=field['key'];v=values.get(k)
                # Existing archived results are evidence, never inputs for recomputing rolling statistics.
                archived=not identity and k in selection.get('values',{}) and v is None
                if archived:
                    val=selection['values'][k];v=raw(val) if val is not None else invalid('ARCHIVE_REASON_UNKNOWN')
                if v is None:v=invalid('INPUT_MISSING')
                series[k].append(self.point(code,field,v,d+'T15:00:00+08:00',j,ids,x,changed,source='已完成历史归档' if archived else s.source))
        if is_minute:
            selection=next((r for r in s.selections if r['trading_date']==day),latest)
            ids=identity or self.identities(selection,group)
            f=ids[0] if group!='B' else ids[1];n=ids[0] if group=='B' else selection.get('near')
            meta=s.contracts.get(f,{});expiry=meta.get('expiry');en=s.contracts.get(n,{}).get('expiry')
            t=(date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else selection.get('T')
            gap=(date.fromisoformat(expiry)-date.fromisoformat(en)).days if expiry and en else selection.get('gap_days')
            grid=minute_grid(day,getattr(s,'sessions',None) or CATALOG['coordinates']['minute']['sessions'])
            previous=self.single(s,f)[index[day]-1] if s.raw and day in index and index[day]>0 else None
            computed=minute.compute(s.minutes(day,f,n),grid,t,gap,previous)
            for field in specs:
                k=field['key']
                if field['frequency']=='1m':
                    series[k]=[self.point(code,field,v.get(k,invalid('INPUT_MISSING')),m['timestamp'],m['trade_minute_index'],ids,x,False,session=m['session_id'],source=s.source) for m,v in zip(grid,computed)]
                elif k.startswith('events') and series[k] and series[k][-1]['trading_date']==day:
                    series[k][-1].update(computed[-1].get(k,invalid('INPUT_MISSING')).json())
        latest_points=[p[-1] for p in series.values() if p];valid=sum(p['value'] is not None for p in latest_points)
        state='VALID' if valid==len(latest_points) and valid else 'PARTIAL' if valid else 'INVALID'
        disabled=[]
        if code in CATALOG['variant_rules']['regression']['ids']:
            disabled.append('年化差分回归暂未开放：需要显式配置新单位下的解释变量方差阈值和残差阈值，不能沿用收益回归阈值。')
        if not s.raw:disabled.append('当前仅有归档输出；缺少固定合约完整历史原始输入的新增变体不能重算。')
        colors=CATALOG['coordinates']['chart']['color'];annual=x in ('a','ac','Ga','ea')
        result=dict(schema_version=CATALOG['schema_version'],calculation_version='v6-runtime-1',id=code,title=card['title'],group=group,purpose=card['purpose'],variant=x,variant_label=variant_label(code,x),
                    chart_colors=[colors['annual' if annual else 'original'],colors['third'],colors['original' if annual else 'annual'],'#815399'],
                    variants=[dict(id=v,label=variant_label(code,v),enabled=supported(v),reason='' if supported(v) else unavailable) for v in variants(code)],
                    status=state,source=s.source,mode=mode,observed_at=max((p['timestamp'] for p in latest_points),default=None),
                    fields=specs,series=series,card=card,parameters=params,limitations=disabled,
                    cache_key=hashlib.sha256(key.encode()).hexdigest(),data_version=s.version,
                    units=CATALOG['units'],reason_labels=REASONS,choices=self.options(mode,group),
                    volume_note='分钟样例成交合计 72833 手；日线 72931 手，保留各自口径。' if mode=='replay' and is_minute else '')
        # Parameters are immutable edition defaults; include them in every request/cache identity.
        self.result_cache[key]=deepcopy(result)
        return result
    @staticmethod
    def point(code,field,value,stamp,index,ids,x,break_before,session=None,source=''):
        return dict(indicator_id=code,field=field['key'],unit=field['unit'],frequency=field['frequency'],timestamp=stamp,trading_date=stamp[:10],
                    contract_ids=ids,variant=x,break_before=break_before,session_id=session,source=source,
                    **({'trade_minute_index':index} if field['frequency']=='1m' else {'trade_day_index':index}),**value.json())


def display(point,units=None):
    units=units or CATALOG['units'];v=point['value'];u=point['unit'];dec=units[u]['display_decimals']
    if point['field']=='K':return ('—' if v is None else f'{100*v:.2f}'),'%'
    return ('—' if v is None else f'{v:,.{dec}f}'),units[u]['label']
