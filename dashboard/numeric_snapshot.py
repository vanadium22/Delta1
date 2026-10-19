"""Sanitized numeric snapshot contract shared by current UI and Excel export."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from dashboard.percentile_audit import clean


def freeze_state(state, *, mode='当前窗口冻结快照'):
    selected={k:state[k] for k in ('as_of','versions','overview','dividend_version','dividend_mode','selection',
        'display_policy','display_updated_at') if k in state}
    selected['entities']=[{**e,'metrics':[{k:v for k,v in r.items() if k!='history'} for r in e['metrics']]}
                          for e in state.get('entities',[])]
    return clean(dict(generated_at=pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),mode=mode,snapshots=[selected]))


def save_snapshot(payload, path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(clean(payload),ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf8')
    from dashboard.marketdata.bars import _atomic_bytes
    _atomic_bytes(path,raw)
    return hashlib.sha256(raw).hexdigest()


def numeric_rows(payload):
    rows=[]
    for state in payload['snapshots']:
        for card in state['overview']:
            fields=card['current']
            rows.append(dict(product=card['root'],slot=card['alias'],contract=card['symbol'],
                future=card['quote'].get('close'),spot=card['spot'].get('close'),dividend=card['dividend'],
                inherited_from=card.get('dividend_inherited_from') or '',T=card['days'],
                points=fields.get('points'),bp=fields.get('bp'),annual_pct=fields.get('annual_pct'),
                marker=card['chart']['value'],marker_kind=card['chart']['kind'],marker_unit=card['chart']['unit'],
                marker_time=card['chart']['time'],reference_end=card['chart']['reference_end'],
                quote_time=card['quote'].get('source_event_time'),spot_time=card['spot'].get('source_event_time'),
                received_at=card['quote'].get('received_at'),generated_at=payload['generated_at'],
                status=payload['mode']+'；'+card['quality']['status']+'；'+card['reason'],
                windows=card['chart']['rows'],versions=state['versions'],dividend_version=state['dividend_version']))
    return clean(rows)
