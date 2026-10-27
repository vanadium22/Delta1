"""00/01/02/03 dated slots: unadjusted annual log-basis reference windows.

This is an overview distribution, separate from v6 A02's concrete-contract b.
No network, future-day close, dividend scenario or adjusted continuous price.
"""
from datetime import date,timedelta
import pandas as pd

from dashboard.indicator_v6.core import basis,raw,statistic
from dashboard.indicator_v6.sources import dates_between,SPOTS
from dashboard.native.continuous import slot_map

WINDOWS=(20,60)
SLOTS=(0,1,2,3)


def prior_days(day,count=60):
    days=dates_between(str(date.fromisoformat(day)-timedelta(days=count*3+30)),day)
    days=[d for d in days if d<day]
    if len(days)<count:raise ValueError('已核验交易日历不足'+str(count)+'日')
    return days[-count:]


def dated_slots(metadata,root,slot,days):
    alias=f'{root}0{slot}.CFE';rows=[]
    for day in days:
        mapping,reason=slot_map(metadata,root,day)
        symbol=mapping.get(alias);expiry=metadata.get(symbol,{}).get('expiry_date')
        t=(date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else None
        rows.append(dict(day=day,alias=alias,symbol=symbol,expiry=expiry,days=t,
            excluded=t is not None and t<5,reason='mapping_missing' if reason else 'T_LT_5' if t<5 else None))
    return rows


def requirements(metadata,day):
    days=prior_days(day);needed=set();gaps=[]
    for root,spot in SPOTS.items():
        for slot in SLOTS:
            for row in dated_slots(metadata,root,slot,days):
                if row['reason']=='mapping_missing':gaps.append(dict(root=root,**row))
                elif not row['excluded']:
                    needed.add((spot,row['day']));needed.add((row['symbol'],row['day']))
    return dict(pricing_day=day,start=days[0],end=days[-1],calendar_days=len(days),
        rows=[dict(symbol=s,day=d) for s,d in sorted(needed,key=lambda r:(r[1],r[0]))],mapping_gaps=gaps)


def final_rows(frame):
    if frame is None or frame.empty:return {}
    return {str(row['trade_date'])[:10]:row for row in frame.to_dict('records') if row.get('is_final')==True}


def prepare(root,slot,metadata,daily,day):
    days=prior_days(day);rows=dated_slots(metadata,root,slot,days)
    spot=final_rows(daily.get(SPOTS[root]));tables={}
    for item in rows:
        symbol=item['symbol'];item['annual_pct']=None
        if item['reason']:continue
        if symbol not in tables:tables[symbol]=final_rows(daily.get(symbol))
        f=tables[symbol].get(item['day'],{});s=spot.get(item['day'],{})
        value=basis(raw(f.get('close'),'price'),raw(s.get('close'),'price'),item['days'])['a']
        item['annual_pct']=value.value
        if value.value is None:
            item['missing_symbols']=[]
            if raw(f.get('close'),'price').value is None:item['missing_symbols'].append(symbol)
            if raw(s.get('close'),'price').value is None:item['missing_symbols'].append(SPOTS[root])
            item['reason']='future_close_missing' if symbol in item['missing_symbols'] else 'index_close_missing'
    current,error=slot_map(metadata,root,day)
    return dict(alias=f'{root}0{slot}.CFE',pricing_day=day,current_symbol=current.get(f'{root}0{slot}.CFE'),
        current_mapping_error=bool(error),rows=rows,method='continuous_slot_annual_log_basis',
        formula='100 × ln(F/S) × 365/T; T<5留空；不调整价格，不加分红',
        mapping_policy='按历日挂牌/到期重建；交割日保留旧档，下一交易日换月；非当时可得映射')


def evaluate(history,current_annual,current_symbol,*,current_reason=None):
    output={k:v for k,v in history.items() if k!='rows'};output['windows']={}
    current=raw(current_annual)
    matches=history['current_symbol']==current_symbol and not history['current_mapping_error']
    for length in WINDOWS:
        rows=history['rows'][-length:];excluded=[r for r in rows if r['excluded']]
        missing=[r for r in rows if not r['excluded'] and r['annual_pct'] is None]
        good=[r for r in rows if not r['excluded'] and r['annual_pct'] is not None]
        values=[raw(r['annual_pct']) for r in good]
        available=len(rows)==length and not missing and len(values)>=2
        pct=None
        if available and matches and current.value is not None:
            pct=statistic([*values,current],len(values),n=len(values))[0].value
        reason=('历史窗口不完整，缺'+str(len(missing))+'日' if missing else
                '当前连续档位合约映射不完整' if not matches else
                current_reason or '当前年化基差不可用' if current.value is None else
                '有效年化样本不足' if not available else '前'+str(length)+'交易日窗口；排除当前日，等值半权，已知T<5日另列排除')
        output['windows'][str(length)]=dict(percentile=pct,samples=len(good),calendar_days=length,
            expected_eligible=length-len(excluded),excluded=len(excluded),complete=available,
            start=rows[0]['day'] if rows else None,end=rows[-1]['day'] if rows else None,reason=reason,
            missing=[dict(day=r['day'],symbol=r['symbol'],reason=r['reason'],missing_symbols=r.get('missing_symbols',[])) for r in missing],
            excluded_dates=[r['day'] for r in excluded])
    return output


def apply(row,history):
    row.update(percentile=None,percentile_20=None,percentile_60=None,percentile_samples=0,
        percentile_reason='等待当前具体合约对应00/01/02/03档位的年化分位')
    row.pop('continuous_percentiles',None)
    if history is None:return
    same_day=row.get('pricing_day')==history['pricing_day']
    unavailable_current=not row.get('pricing_day') and raw(row.get('annual_pct')).value is None
    reason=(row.get('basis_reason') or '当前年化基差不可用') if same_day or unavailable_current else '当前价格的定价日不匹配目标交易日；保留原源时'
    value=evaluate(history,row.get('annual_pct') if same_day else None,row['symbol'],
        current_reason=reason)
    row['continuous_percentiles']=value
    for length in WINDOWS:row['percentile_'+str(length)]=value['windows'][str(length)]['percentile']
    short=value['windows']['20']
    row.update(percentile=row['percentile_20'],percentile_samples=short['samples'],
        percentile_start=short['start'],percentile_end=short['end'],percentile_reason=short['reason'])
