"""00/01/02/03 dated slots: Excel-style dividend-adjusted simple annual windows.

This is an overview distribution, separate from v6 A02's concrete-contract b.
No network, future-day close or back-adjusted continuous price. Each historical
day uses its actual dated contract and that time's dividend version.
"""
from bisect import bisect_left, bisect_right
from datetime import date,timedelta
from statistics import mean,median
import pandas as pd

from dashboard.indicator_v6.core import raw
from .overview_basis import calculate,FORMULA,historical_dividend,DEFAULT_MIN_ANNUAL_DAYS
from .dividends import digest
from dashboard.indicator_v6.sources import dates_between,SPOTS
from dashboard.native.continuous import slot_map

WINDOWS=(20,60)
SLOTS=(0,1,2,3)
HISTORICAL_DIVIDEND_POLICY='按实际合约取历史截止时刻前最后有效分红；没有记录或同刻冲突时留空'


def rank_in_sorted(samples, value):
    left = bisect_left(samples, value)
    right = bisect_right(samples, value)
    return 100*(left+.5*(right-left))/len(samples)


def prior_days(day,count=60):
    days=dates_between(str(date.fromisoformat(day)-timedelta(days=count*3+30)),day)
    days=[d for d in days if d<day]
    if len(days)<count:raise ValueError('已核验交易日历不足'+str(count)+'日')
    return days[-count:]


def dated_slots(metadata,root,slot,days,*,min_annual_days=DEFAULT_MIN_ANNUAL_DAYS):
    alias=f'{root}0{slot}.CFE';rows=[]
    for day in days:
        mapping,reason=slot_map(metadata,root,day)
        symbol=mapping.get(alias);expiry=metadata.get(symbol,{}).get('expiry_date')
        t=(date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else None
        excluded=t is not None and t<min_annual_days
        rows.append(dict(day=day,alias=alias,symbol=symbol,expiry=expiry,days=t,
            excluded=excluded,reason='mapping_missing' if reason else f'T_LT_{min_annual_days}' if excluded else None))
    return rows


def requirements(metadata,day,*,min_annual_days=DEFAULT_MIN_ANNUAL_DAYS):
    days=prior_days(day);needed=set();gaps=[]
    for root,spot in SPOTS.items():
        for slot in SLOTS:
            for row in dated_slots(metadata,root,slot,days,min_annual_days=min_annual_days):
                if row['reason']=='mapping_missing':gaps.append(dict(root=root,**row))
                elif not row['excluded']:
                    needed.add((spot,row['day']));needed.add((row['symbol'],row['day']))
    return dict(pricing_day=day,start=days[0],end=days[-1],calendar_days=len(days),min_annual_days=min_annual_days,
        rows=[dict(symbol=s,day=d) for s,d in sorted(needed,key=lambda r:(r[1],r[0]))],mapping_gaps=gaps)


def final_rows(frame):
    if frame is None or frame.empty:return {}
    return {str(row['trade_date'])[:10]:row for row in frame.to_dict('records') if row.get('is_final')==True}


def prepare(root,slot,metadata,daily,day,*,dividends=None,cache=None,current_day=None,min_annual_days=DEFAULT_MIN_ANNUAL_DAYS,
            finalized=None):
    days=prior_days(day);rows=dated_slots(metadata,root,slot,days,min_annual_days=min_annual_days)
    tables = {} if finalized is None else finalized
    if SPOTS[root] not in tables:
        tables[SPOTS[root]] = final_rows(daily.get(SPOTS[root]))
    spot = tables[SPOTS[root]]
    for item in rows:
        symbol=item['symbol'];item['annual_pct']=None;item['dividend_estimated_zero']=False
        if item['reason']:continue
        if symbol not in tables:tables[symbol]=final_rows(daily.get(symbol))
        f=tables[symbol].get(item['day'],{});s=spot.get(item['day'],{})
        item['http_session_inferred']=any(r.get('source_date_basis')=='corroborated_live_session' for r in (f,s))
        record=historical_dividend(dividends,symbol,item['day']);dividend=record.get('points')
        item['dividend_points']=dividend
        item['dividend_source_date']=record.get('source_business_date') or record.get('source_snapshot')
        item['dividend_effective_from']=record.get('effective_from')
        item['dividend_file_sha256']=record.get('file_sha256')
        item['dividend_reason']=record.get('reason')
        item['dividend_source_kind']=record.get('source_kind')
        item['dividend_revision']=record.get('revision');item['dividend_inherited_from']=record.get('inherited_from')
        values=(cache.calculate(symbol,item['day'],f.get('close'),s.get('close'),dividend,item['days'],
            dividend_record=record,price_version=digest([f,s]),min_annual_days=min_annual_days) if cache is not None else
            calculate(f.get('close'),s.get('close'),dividend,item['days'],min_annual_days=min_annual_days))
        value=values['annual_pct']
        item['annual_pct']=value
        if value is None:
            item['missing_symbols']=[]
            if raw(f.get('close'),'price').value is None:item['missing_symbols'].append(symbol)
            if raw(s.get('close'),'price').value is None:item['missing_symbols'].append(SPOTS[root])
            item['reason']='future_close_missing' if symbol in item['missing_symbols'] else 'index_close_missing' if item['missing_symbols'] else 'dividend_missing'
    current,error=slot_map(metadata,root,current_day or day)
    return dict(alias=f'{root}0{slot}.CFE',pricing_day=day,current_symbol=current.get(f'{root}0{slot}.CFE'),
        current_mapping_error=bool(error),slot_day=current_day or day,rows=rows,method='continuous_slot_dividend_simple_annual',
        min_annual_days=min_annual_days,formula=FORMULA+f'；已知T<{min_annual_days}另列排除；不调整期现价格',
        dividend_version=getattr(dividends,'version',None),dividend_policy=HISTORICAL_DIVIDEND_POLICY,
        dividend_source_policy=(getattr(dividends,'info',{}) or {}).get('historical_policy'),
        mapping_policy='按历日挂牌/到期重建；交割日保留旧档，下一交易日换月；非当时可得映射')


def compile_windows(history):
    """Prepare fixed historical statistics once per input revision."""
    min_days=history.get('min_annual_days',5)
    compiled={}
    for length in WINDOWS:
        rows=history['rows'][-length:]
        excluded=[r for r in rows if r['excluded']]
        missing=[r for r in rows if not r['excluded'] and r['annual_pct'] is None]
        good=[r for r in rows if not r['excluded'] and r['annual_pct'] is not None]
        estimated=[r for r in rows if not r['excluded'] and r.get('dividend_estimated_zero')]
        inferred=[r for r in good if r.get('http_session_inferred')]
        values=sorted(float(r['annual_pct']) for r in good)
        available=len(rows)==length and not missing and len(values)>=2
        counts={kind:sum(r['reason']==kind for r in missing) for kind in ('dividend_missing','future_close_missing','index_close_missing','mapping_missing')}
        missing_reason='；'.join(title+str(counts[k])+'日' for k,title in [('dividend_missing','分红缺'),('future_close_missing','期货收盘缺'),('index_close_missing','指数收盘缺'),('mapping_missing','映射缺')] if counts[k])
        suffix = ''
        if estimated:suffix+='；历史缺分红暂按0估算 '+str(len(estimated))+'日'
        if inferred:suffix+='；HTTP连续盘中核验昨收 '+str(len(inferred))+'日（日期推定）'
        static=dict(mean=mean(values) if available else None,median=median(values) if available else None,
            samples=len(good),calendar_days=length,expected_eligible=length-len(excluded),excluded=len(excluded),complete=available,
            estimated=bool(estimated),zero_dividend_count=len(estimated),zero_dividend_dates=[r['day'] for r in estimated],
            zero_dividend_rows=[dict(day=r['day'],symbol=r['symbol']) for r in estimated],
            http_session_inferred_count=len(inferred),http_session_inferred_dates=[r['day'] for r in inferred],
            dividend_observations_complete=not estimated and not any(r['reason']=='dividend_missing' for r in missing),
            start=rows[0]['day'] if rows else None,end=rows[-1]['day'] if rows else None,missing_counts=counts,
            missing=[dict(day=r['day'],symbol=r['symbol'],reason=r['reason'],missing_symbols=r.get('missing_symbols',[])) for r in missing],
            excluded_dates=[r['day'] for r in excluded])
        compiled[str(length)]=(values,static,missing_reason,suffix,
            f'前{length}交易日窗口；排除当前日，等值半权，已知T<{min_days}日另列排除')
    return compiled


def evaluate(history,current_annual,current_symbol,*,current_reason=None,compiled=None):
    output={k:v for k,v in history.items() if k!='rows'}
    output['min_annual_days']=history.get('min_annual_days',5);output['windows']={}
    current=raw(current_annual).value
    matches=history['current_symbol']==current_symbol and not history['current_mapping_error']
    for length,(values,static,missing_reason,suffix,normal_reason) in (compiled or compile_windows(history)).items():
        pct=rank_in_sorted(values,current) if static['complete'] and matches and current is not None else None
        reason=(missing_reason if static['missing'] else
                '当前连续档位合约映射不完整' if not matches else
                current_reason or '当前年化基差不可用' if current is None else
                '有效年化样本不足' if not static['complete'] else normal_reason)
        output['windows'][length]=dict(static,percentile=pct,reason=reason+suffix)
    return output


def apply(row,history,*,compiled=None):
    row.update(percentile=None,percentile_20=None,percentile_60=None,percentile_samples=0,
        percentile_reason='等待当前具体合约对应00/01/02/03档位的年化分位')
    row.pop('continuous_percentiles',None)
    if history is None:return
    same_day=row.get('pricing_day')==history['pricing_day']
    unavailable_current=not row.get('pricing_day') and raw(row.get('annual_pct')).value is None
    reason=(row.get('basis_reason') or '当前年化基差不可用') if same_day or unavailable_current else '当前价格的定价日不匹配目标交易日；保留原源时'
    value=evaluate(history,row.get('annual_pct') if same_day else None,row['symbol'],
        current_reason=reason,compiled=compiled)
    row['continuous_percentiles']=value
    for length in WINDOWS:row['percentile_'+str(length)]=value['windows'][str(length)]['percentile']
    short=value['windows']['20']
    row.update(percentile=row['percentile_20'],percentile_samples=short['samples'],
        percentile_start=short['start'],percentile_end=short['end'],percentile_reason=short['reason'])
