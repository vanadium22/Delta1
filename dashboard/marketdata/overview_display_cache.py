"""Small, atomic latest display sections. Never upgrades saved inputs to live."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from .bars import _atomic_bytes, _json_bytes
from .overview_reference import finite

SCHEMA='overview-display-v1'


def scope(config):
    from dashboard.numeric_evidence import cache_scope,digest
    return digest([cache_scope(config),{k:str(config.get(k) or '') for k in ('overview_reference_file','overview_equity_file','overview_etfs')}])


def read(directory, name, identity, now):
    try:
        path=directory/(name+'.json')
        if path.stat().st_size>4*1024*1024:return {}
        value=json.loads(path.read_text(encoding='utf8'))
        if value.get('schema')!=SCHEMA or value.get('scope')!=identity:return {}
        stamp=datetime.fromisoformat(value['computed_at'])
        if stamp.tzinfo is None or stamp>now.to_pydatetime():return {}
        return value['data'] if isinstance(value.get('data'),dict) else {}
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return {}


def compact_quote(row):
    result=deepcopy({k:v for k,v in row.items() if k not in ('series','premium_series','display_saved','basis_display')})
    history=result.get('continuous_percentiles')
    if isinstance(history,dict):
        history.pop('rows',None)
        for window in history.get('windows',{}).values():
            for key in ('rows','zero_dividend_rows'):window.pop(key,None)
    return result


def basis_bundle(row):
    keys=('symbol','slot','root','expiry','days','pricing_day','pricing_at','annual_pct','raw_basis_points','continuous_percentiles')
    return compact_quote({k:v for k,v in row.items() if k in keys or k.startswith(('basis_','dividend_','percentile_'))})


def preserve_basis(row,old,now):
    """Retain one complete priced bundle; never replace the raw current result."""
    previous=old.get('_last_basis') or basis_bundle(old)
    if (previous.get('symbol')!=row['symbol'] or previous.get('slot')!=row.get('slot') or
        previous.get('expiry') and row.get('expiry') and previous['expiry']!=row['expiry']):previous={}
    current=basis_bundle(row)
    days=row.get('days')
    excluded=days is not None and days<5
    if excluded:
        row.update(annual_pct=None,percentile_20=None,percentile_60=None)
        for window in ((row.get('continuous_percentiles') or {}).get('windows') or {}).values():
            window.update(percentile=None,reason='当前剩余T<5，规则排除')
        current=basis_bundle(row)
    valid=finite(row.get('basis_points')) and (finite(row.get('annual_pct')) or excluded)
    lost=any(finite(previous.get(k)) and not finite(current.get(k)) for k in ('basis_points','annual_pct','percentile_20','percentile_60'))
    if valid and (not lost or excluded):return current
    if finite(previous.get('basis_points')):
        display=deepcopy(previous)
        display.update(saved=True,current_reason=row.get('basis_reason'),current_source_at=row.get('source_at'))
        if excluded:
            display.update(days=days,annual_pct=None,percentile_20=None,percentile_60=None)
            for window in display.get('continuous_percentiles',{}).get('windows',{}).values():
                window.update(percentile=None,reason='当前剩余T<5，规则排除')
        row['basis_display']=display
    return previous if finite(previous.get('basis_points')) else current if valid else {}


def preserve(model, data, now):
    """Fresh partial results win; a wholly missing section retains its last view."""
    if not hasattr(model,'local_root'):return data
    from dashboard.numeric_evidence import digest
    identity=scope(model.config);directory=Path(model.local_root)/'overview_display'
    if getattr(model,'_display_scope',None)!=identity:
        model._display_sections={k:read(directory,k,identity,now) for k in ('indices','etfs','quotes')}
        model._display_tokens={k:digest(v) for k,v in model._display_sections.items()};model._display_scope=identity
    sections=model._display_sections;restored=[]
    indices=deepcopy(sections['indices'])
    for root,current in data.get('index_details',{}).items():
        old=indices.get(root,{})
        if not current.get('covered') and old.get('covered'):
            value=deepcopy(old);value.update(display_saved=True,stale=True,current_missing=current.get('inputs'),
                reason='保留上次显示结果；原成分源 '+str(old.get('source_at') or '—')+'；'+str(current.get('reason') or ''))
            data['index_details'][root]=value;restored.append('index:'+root)
        elif current.get('covered'):
            indices[root]=deepcopy(current)
    quotes=deepcopy(sections['quotes'])
    for kind in ('indices','etfs','futures'):
        saved=quotes.setdefault(kind,{})
        for i,row in enumerate(data.get(kind,[])):
            old=saved.get(row['symbol'],{})
            if not finite(row.get('price')) and finite(old.get('price')):
                value=deepcopy({k:v for k,v in old.items() if k!='_last_basis'});value.update(display_saved=True,status='上次显示',display_kind='saved_display',
                    reason='当前缺行情，保留原始源时间的上次显示值',quality=dict(usable=False,status='上次显示',reason='待本轮重新核验'))
                if kind=='futures' and row.get('days') is not None:value['days']=row['days']
                if kind=='futures' and (old.get('slot')!=row.get('slot') or old.get('expiry')!=row.get('expiry')):
                    for key in basis_bundle(old):
                        if key not in ('symbol','root'):value.pop(key,None)
                    value.update(deepcopy(basis_bundle(row)))
                data[kind][i]=value;restored.append(kind+':'+row['symbol'])
            value=data[kind][i]
            if kind=='futures':
                basis=preserve_basis(value,old,now)
                if value.get('basis_display'):restored.append('futures_basis:'+row['symbol'])
            if finite(value.get('price')) and not value.get('display_saved'):
                saved[row['symbol']]=compact_quote(value)
                if kind=='futures' and basis:saved[row['symbol']]['_last_basis']=basis
        wanted={r['symbol'] for r in data.get(kind,[])}
        quotes[kind]={s:r for s,r in saved.items() if s in wanted}
    funds=deepcopy(sections['etfs'])
    newest={r['symbol']:r for r in data.get('etfs',[])}
    for root,current in data.get('etf_groups',{}).items():
        old=funds.get(root,{})
        if not current.get('ranking',{}).get('as_of') and old.get('ranking',{}).get('as_of'):
            value=deepcopy(old);value['display_saved']=True
            for row in value.get('rows',[]):
                quote=newest.get(row['symbol'])
                if quote and finite(quote.get('price')):
                    row.update({k:v for k,v in quote.items() if k not in ('aum_cny','aum_date','aum_share_pct','aum_share_date','aum_series','rank')})
            data['etf_groups'][root]=value;restored.append('etf_group:'+root)
        else:
            # Refresh a quote independently of the dated ranking/history.
            for row in current.get('rows',[]):
                quote=newest.get(row.get('symbol'))
                if quote and quote.get('display_saved'):
                    row.update({k:v for k,v in quote.items() if k not in ('aum_cny','aum_date','aum_share_pct','aum_share_date','aum_series','rank')})
            if current.get('ranking',{}).get('as_of'):
                funds[root]=deepcopy(current)
                funds[root]['rows']=[compact_quote(r) for r in current.get('rows',[])]
    proposed=dict(indices=indices,etfs=funds,quotes=quotes);writes=[];errors=[]
    stop=getattr(model,'overview_stop',None)
    if getattr(model,'overview_write_cache',False) and not (stop and stop.is_set()):
        for name,value in proposed.items():
            token=digest(value)
            if token==model._display_tokens.get(name):continue
            try:
                _atomic_bytes(directory/(name+'.json'),_json_bytes(dict(schema=SCHEMA,scope=identity,computed_at=now.isoformat(),data=value)))
                model._display_tokens[name]=token;writes.append(name)
            except (OSError,ValueError,TypeError) as exc:errors.append(dict(section=name,error_type=type(exc).__name__))
    model._display_sections=proposed
    data['display_cache']=dict(schema=SCHEMA,restored=restored,written=writes,errors=errors,
        writable=bool(getattr(model,'overview_write_cache',False)),source_times_preserved=True)
    return data
