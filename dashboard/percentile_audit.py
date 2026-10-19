"""Freeze local observations and independently reproduce all four slot percentiles.

No network calls or repairs. Evidence is private and must stay outside Git.
"""
import argparse
from copy import deepcopy
import csv
import hashlib
import json
import math
from pathlib import Path
import pandas as pd


def clean(value):
    if isinstance(value, dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, (pd.Timestamp,)): return value.isoformat()
    if hasattr(value,'item'): return clean(value.item())
    return value


def independent_value(f, s, d, t):
    if any(v is None or not math.isfinite(float(v)) for v in (f,s,d,t)) or s<=0:
        return None
    return 100*(f-s+d)/s*365/t if t>=5 else None


def independent_rank(values, current):
    valid=[v for v in values if v is not None and math.isfinite(v)]
    if current is None or not math.isfinite(current) or len(valid)<2:return None
    return 100*(sum(v<current for v in valid)+.5*sum(v==current for v in valid))/len(valid)


def scan_saved_feedback(report, realtime_root):
    """Same-day stored observations only; no claim of matching the user's moment."""
    import sqlite3
    from dashboard.marketdata.quote_quality import aligned_quotes
    path=Path(realtime_root)/'live/quotes.sqlite3'
    result=[]
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        day=report['replay_as_of'][:10]
        for case in report['cases']:
            if case['alias'] not in ('IF00.CFE','IF03.CFE'):continue
            records=db.execute('''SELECT f.*, s.close AS spot_close,s.source_event_time AS spot_event,
                s.received_at AS spot_received FROM quotes f JOIN quotes s
                ON f.run_id=s.run_id AND f.poll=s.poll AND f.batch=s.batch
                WHERE f.symbol=? AND s.symbol='000300.SH' AND f.received_at LIKE ?
                ORDER BY f.sequence''',(case['symbol'],day+'%')).fetchall()
            observations=[]
            for r in records:
                q=dict(r);spot=dict(close=r['spot_close'],source_event_time=r['spot_event'],received_at=r['spot_received'])
                as_of=max(pd.Timestamp(q['received_at']),pd.Timestamp(spot['received_at']))+pd.Timedelta(seconds=1)
                ok,reason=aligned_quotes([q,spot],as_of)
                value=independent_value(q['close'],spot['close'],case['D'],case['T']) if ok else None
                rank=independent_rank([r['annual'] for r in case['rows']],value)
                observations.append(dict(received_at=q['received_at'],F=q['close'],S=spot['close'],D=case['D'],T=case['T'],
                    annual=value,percentile=rank,reason=reason))
            valid=[r for r in observations if r['percentile'] is not None]
            result.append(dict(alias=case['alias'],n=case['n'],saved_observations=len(observations),valid_observations=len(valid),
                minimum_percentile=min((r['percentile'] for r in valid),default=None),
                zero_examples=[r for r in valid if r['percentile']==0][:5],observations=observations))
    return result


def audit_card(card, daily, calendar, metadata):
    marker=pd.Timestamp(card['chart']['time']) if card['chart']['time'] else None
    if marker is None:return dict(symbol=card['symbol'],alias=card.get('alias'),rows=[],n=0,matches=True,reason='无有效定位值')
    prior=[t for t in calendar if t.tz_convert('Asia/Shanghai').date()<marker.tz_convert('Asia/Shanghai').date()][-20:]
    rows=[];slot=int(card['alias'][3])
    mapping={r['date']:r for r in card['continuity']['mappings']}
    for stamp in prior:
        day=str(stamp.tz_convert('Asia/Shanghai').date())
        active=sorted((s for s,r in metadata.items() if s.startswith(card['root']) and r['listing_date']<=day<=r['expiry_date']),key=lambda s:metadata[s]['expiry_date'])
        symbol=active[slot] if len(active)==4 else None
        ref=metadata.get(symbol,{})
        def price(s):
            value=daily.get(s,pd.DataFrame()).get('close',pd.Series(dtype=float)).get(stamp)
            return float(value) if value is not None and math.isfinite(value) else None
        f=price(symbol);s=price(card['spot_symbol'])
        d=card['dividend'] if card['continuity']['mode']=='continuous_fixed_scenario' else mapping.get(day,{}).get('dividend')
        t=(pd.Timestamp(ref['expiry_date']).date()-pd.Timestamp(day).date()).days if ref else None
        annual=independent_value(f,s,d,t)
        points=f-s+d if all(v is not None for v in (f,s,d)) else None
        reason='映射缺失' if not symbol else 'T<5，排除年化' if t<5 else 'F/S/D缺失' if annual is None else ''
        rows.append(dict(date=day,symbol=symbol,F=f,S=s,D=d,T=t,points=points,bp=10000*points/s if points is not None and s else None,
                         annual=annual,reason=reason,mapping_matches=symbol==mapping.get(day,{}).get('symbol')))
    marker_inputs=dict(symbol=card['symbol'],F=card['quote'].get('close'),S=card['spot'].get('close'),D=card['dividend'],T=card['days'])
    if card['chart']['kind']!='盘中观测':
        day=str(marker.tz_convert('Asia/Shanghai').date());m=mapping.get(day,{})
        symbol=m.get('symbol')
        def historical_price(s):
            v=daily.get(s,pd.DataFrame()).get('close',pd.Series(dtype=float)).get(marker)
            return float(v) if v is not None and math.isfinite(v) else None
        marker_inputs=dict(symbol=symbol,F=historical_price(symbol),S=historical_price(card['spot_symbol']),D=m.get('dividend'),T=m.get('days'))
    current=independent_value(*(marker_inputs[k] for k in ('F','S','D','T')))
    rank=independent_rank([r['annual'] for r in rows],current) if len(prior)==20 else None
    code=next(r for r in card['chart']['rows'] if r['key']=='20d')
    n=sum(r['annual'] is not None for r in rows)
    matches=n==code['n'] and all(r['mapping_matches'] for r in rows) and ((rank is None and code['percentile'] is None) or
        rank is not None and code['percentile'] is not None and abs(rank-code['percentile'])<1e-10)
    valid=[r['annual'] for r in rows if r['annual'] is not None]
    return dict(symbol=card['symbol'],alias=card['alias'],kind=card['chart']['kind'],marker_time=card['chart']['time'],
        F=card['quote'].get('close'),S=card['spot'].get('close'),D=card['dividend'],T=card['days'],
        dividend_inherited_from=card['dividend_inherited_from'],quality=card['quality'],reason=card['reason'],
        future_time=card['quote'].get('source_event_time'),spot_time=card['spot'].get('source_event_time'),
        received_at=card['quote'].get('received_at'),marker_inputs=marker_inputs,current_annual=current,code_marker_value=card['chart']['value'],n=n,less=sum(v<current for v in valid) if current is not None else None,
        equal=sum(v==current for v in valid) if current is not None else None,min=min(valid) if valid else None,max=max(valid) if valid else None,
        independent_percentile=rank,code_percentile=code['percentile'],display=f"{code['percentile']:.0f}%" if code['percentile'] is not None else '—',
        matches=matches,rows=rows)


def capture(local_root=None, output=None):
    from dashboard.native.model import NativeModel
    from dashboard.marketdata.repository import ReferenceBook
    from dashboard.marketdata.contract_reference import latest_contracts
    output=Path(output or Path(__file__).parent/'runtime/diagnosis_20261019');output.mkdir(parents=True,exist_ok=True)
    model=NativeModel(local_root);model.config['dashboard_mode']='nonregression'
    generated=pd.Timestamp.now(tz='Asia/Shanghai')
    frozen_live={};original=model._live
    def live(*args):
        if not frozen_live:frozen_live.update(deepcopy(original(*args)))
        return deepcopy(frozen_live)
    model._live=live
    request=dict(cards=True,category='basis',price_input='annual',distribution_input='annual',overview_slot=0,save=False)
    try:
        initial=model.snapshot({**request,'as_of':generated})
        received=[pd.Timestamp(q['received_at']) for q in frozen_live.values() if q.get('received_at')]
        replay=max(received)+pd.Timedelta(seconds=1) if received else generated
        metadata=latest_contracts(ReferenceBook(model.config.get('reference_file')).data)
        report=dict(original_feedback='用户反馈00与03；原时刻未知。此处为保存行情的新冻结回放，不能证明原时刻。',
                    generated_at=generated.isoformat(),replay_as_of=replay.isoformat(),versions=initial['versions'],cases=[],current_status=[],current_cases=[])
        snapshots=[]
        for slot in range(4):
            state=model.snapshot({**request,'as_of':replay,'overview_slot':slot})
            for card in state['overview']:
                report['cases'].append(audit_card(card,model.research_engine.daily,model.research_engine.calendar,metadata))
            snapshots.append({k:state[k] for k in ('as_of','versions','overview','dividend_version','dividend_mode','selection')})
            current=model.snapshot({**request,'as_of':generated,'overview_slot':slot})
            report['current_cases'].extend(audit_card(c,model.research_engine.daily,model.research_engine.calendar,metadata) for c in current['overview'])
            report['current_status'].extend(dict(symbol=c['symbol'],quality=c['quality']['status'],current=c['current'],kind=c['chart']['kind']) for c in current['overview'])
        payload=clean(dict(generated_at=generated.isoformat(),mode='保存行情冻结回放（非当前实时）',snapshots=snapshots))
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf8')
        report['snapshot_sha256']=hashlib.sha256(raw).hexdigest()
        (output/'snapshot.json').write_bytes(raw)
        report['saved_feedback_scan']=scan_saved_feedback(report,model.config['realtime_root'])
        (output/'diagnosis.json').write_text(json.dumps(clean(report),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
        for filename,cases in [('IF_20d_daily.csv',report['cases']),('IF_20d_historical_marker.csv',report['current_cases'])]:
            details=[dict(alias=c['alias'],marker_time=c.get('marker_time'),**r) for c in cases if c['symbol'].startswith('IF') for r in c['rows']]
            if details:
                with (output/filename).open('w',encoding='utf-8-sig',newline='') as handle:
                    writer=csv.DictWriter(handle,fieldnames=list(details[0]));writer.writeheader();writer.writerows(details)
        assert all(c['matches'] for c in report['cases']+report['current_cases']), 'Independent calculation disagrees; inspect private diagnosis'
        return clean(report)
    finally:model.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--local-root',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=capture(args.local_root,args.output)
    print(json.dumps({**{k:result[k] for k in ('generated_at','replay_as_of','snapshot_sha256')},
                     'IF':[{k:v for k,v in r.items() if k!='rows'} for r in result['cases'] if r['symbol'].startswith('IF')]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
