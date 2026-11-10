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
    result=deepcopy({k:v for k,v in row.items() if k not in ('series','premium_series','display_saved')})
    history=result.get('continuous_percentiles')
    if isinstance(history,dict):
        history.pop('rows',None)
        for window in history.get('windows',{}).values():
            for key in ('rows','zero_dividend_rows'):window.pop(key,None)
    return result


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
                value=deepcopy(old);value.update(display_saved=True,status='上次显示',display_kind='saved_display',
                    reason='当前缺行情，保留原始源时间的上次显示值',quality=dict(usable=False,status='上次显示',reason='待本轮重新核验'))
                data[kind][i]=value;restored.append(kind+':'+row['symbol'])
            elif finite(row.get('price')):saved[row['symbol']]=compact_quote(row)
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
            except OSError as exc:errors.append(dict(section=name,error_type=type(exc).__name__))
    model._display_sections=proposed
    data['display_cache']=dict(schema=SCHEMA,restored=restored,written=writes,errors=errors,
        writable=bool(getattr(model,'overview_write_cache',False)),source_times_preserved=True)
    return data
