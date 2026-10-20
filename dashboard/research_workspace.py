"""Shared bounded watchlist and metric catalogue for Excel and both local Apps."""
import json
from pathlib import Path
import re
import pandas as pd

from dashboard.native.instruments import UNDERLYINGS

CATEGORIES={'期现':'basis','跨期':'calendar','跨指数':'cross'}
INPUTS={'期货价':'future','基差bp':'basis','年化':'annual'}
GROUPS=('全部','定价与期限','位置与趋势','波动与形态','成交与活跃','持仓与结构','盘口与规模')
TIMINGS=('盘中优先','日终','历史日')
FIELDS=('category','left','right','input','timing','date')
COMPARE_HEADERS=['输入值','单位','路径效率','Z','A腿日内换手','同刻活跃','振幅','源时','日终日期','状态']
DETAIL_HEADERS=['分类','指标','单位','盘中值','盘中源时','盘中口径','日终值','日终日期','说明']


def group(code):
    if code.startswith(('A01','A02','A04','A05','A06','A13')) or code=='X':return GROUPS[1]
    if code.startswith(('A03','A07','B10')):return GROUPS[2]
    if code.startswith(('A11','A12','B01','B07','B11')):return GROUPS[3]
    if code.startswith(('B02','B04.Q','B09')):return GROUPS[4]
    if code.startswith(('B03','B04','B05','B06','B08')):return GROUPS[5]
    return GROUPS[6]


def defaults(contracts):
    result=[]
    for product in UNDERLYINGS:
        matches=sorted(s for s in contracts if s.startswith(product))
        if matches:
            result.append(dict(category='期现',left=matches[0],right=UNDERLYINGS[product][0],
                               input='年化',timing='盘中优先',date=''))
    return dict(rows=result,group='全部',detail_row=1)


def load_preferences(local_root):
    path=Path(local_root)/'research_watchlist.json'
    try:
        value=json.loads(path.read_text(encoding='utf8'))
        if isinstance(value,dict) and isinstance(value.get('rows'),list) and len(value['rows'])<=8:return value
    except (OSError,ValueError):pass
    return None


def save_preferences(local_root, selection):
    # Independent file: never update native.json or any VPN/database credentials.
    from dashboard.numeric_snapshot import save_snapshot
    value={k:selection[k] for k in ('rows','group','detail_row') if k in selection}
    save_snapshot(value,Path(local_root)/'research_watchlist.json')


def validate(row, contracts, today):
    row={k:str(row.get(k) or '').strip() for k in FIELDS}
    if not row['left']:return row,None
    if row['category'] not in CATEGORIES or row['input'] not in INPUTS or row['timing'] not in TIMINGS:
        return row,'选择类型、输入和时点'
    if row['left'] not in contracts or row['left'][:2] not in UNDERLYINGS:return row,'合约A无参考'
    category=CATEGORIES[row['category']]
    if category=='basis':
        expected=UNDERLYINGS.get(row['left'][:2],('',))[0]
        if row['right'] and row['right']!=expected:return row,'期现需对应指数'
        row['right']=expected
    elif row['right'] not in contracts or row['right'][:2] not in UNDERLYINGS:return row,'合约B无参考'
    elif category=='calendar' and (row['left'][:2]!=row['right'][:2] or row['left']>=row['right']):return row,'同品种，近月在前'
    elif category=='cross' and (row['left'][:2]==row['right'][:2] or row['input']=='期货价'):return row,'跨指数选不同品种及基差/年化'
    if row['timing']=='历史日':
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',row['date']):return row,'日期用YYYY-MM-DD'
        try:day=pd.Timestamp(row['date']).date()
        except ValueError:return row,'历史日期无效'
        if day>=today:return row,'历史日需早于今天'
    return row,None


def evaluate(model, selection=None, now=None):
    from dashboard.marketdata.repository import ReferenceBook
    from dashboard.marketdata.contract_reference import latest_contracts
    now=pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    metadata=latest_contracts(ReferenceBook(model.config.get('reference_file')).data)
    today=now.tz_convert('Asia/Shanghai').date()
    active=[s for s,r in metadata.items() if r['listing_date']<=str(today)<=r['expiry_date']]
    selection=selection if selection is not None else load_preferences(model.local_root) or defaults(active)
    if not isinstance(selection,dict):selection=defaults(active)
    rows=selection.get('rows',[])[:8] if isinstance(selection.get('rows',[]),list) else []
    selected_group=selection.get('group','全部')
    detail_row=selection.get('detail_row',1)
    try:detail_row=max(1,min(8,int(detail_row)))
    except (ValueError,TypeError):detail_row=1
    comparisons=[]; details=[]; entities=[];normalized=[]
    for i,original in enumerate(rows):
        spec,error=validate(original if isinstance(original,dict) else {},metadata,today);normalized.append(spec)
        metrics=[]
        if spec['left'] and not error:
            at=pd.Timestamp(spec['date']+' 15:01',tz='Asia/Shanghai') if spec['timing']=='历史日' else now
            request=dict(cards=False,left=spec['left'],right=spec['right'],category=CATEGORIES[spec['category']],
                         price_input=INPUTS[spec['input']],as_of=at.isoformat(),allow_mixed_expiry=True)
            state=model.snapshot(request)
            error=state.get('pair_error')
            metrics=[{k:v for k,v in r.items() if k!='history'} for r in state.get('metrics',[])]
            if spec['timing']!='盘中优先':
                # Hide provisional values in an explicit daily / historical selection.
                metrics=[{**r,'current':None,'current_time':None,'current_scope':'','current_reason':'','current_n':None} for r in metrics]
            if spec['category']=='跨指数' and spec['left'][2:6]!=spec['right'][2:6]:
                metrics=[{**r,'title':r['title'].replace('同月','跨月份')} for r in metrics]
        def get(code):
            return next((m for m in metrics if m['id']==code),{})
        def selected(code):
            m=get(code)
            # One comparison row has one timing. Missing live metrics stay blank.
            return m.get('current') if live else m.get('value') if m.get('time')==x.get('time') else None
        x=get('X')
        live=x.get('current') is not None
        status=error or ('盘中' if live else '日终参考' if x.get('value') is not None else '缺数据') if spec['left'] else ''
        if spec['category']=='跨指数' and spec['left'][2:6]!=spec['right'][2:6] and spec['left']:
            status+=' · 跨月份'
        stress=get('B11')
        stress_val=stress.get('current') if live else selected('B11')
        if stress_val is None and live:
            stress_val=get('B11.sample').get('current')
            if stress_val is not None:status+=' · 振幅为采集段'
        if live and get('B09.same_time').get('current') is not None:status+=' · 活跃按分钟'
        comparisons.append([selected('X'),x.get('unit'),selected('B10'),selected('A03.z'),
            get('B04.Q.intraday').get('current') if live else None,
            get('B09.same_time').get('current') if live else None,stress_val,
            x.get('current_time'),x.get('time'),status])
        entities.append(dict(spec=spec,metrics=metrics,error=error))
        if i+1==detail_row:
            for m in metrics:
                g=group(m['id'])
                if selected_group not in ('全部',g):continue
                scope=m.get('current_scope') or ('盘中' if m.get('current') is not None else '')
                if m.get('current_n') is not None:scope+=' n='+str(m['current_n'])
                details.append([g,m['id']+' '+m['title'],m['unit'],m.get('current'),m.get('current_time'),scope,
                    m.get('value'),m.get('time'),
                    (m.get('current_reason') or '')+'；'+(m.get('reason') or '')])
    return dict(request_id=selection.get('request_id'),selection={**selection,'rows':normalized},
                comparisons=comparisons,details=details,entities=entities,contracts=sorted(metadata),
                active=sorted(active),observed_at=now.isoformat())
