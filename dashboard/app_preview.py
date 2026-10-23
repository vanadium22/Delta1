"""Exact-profile startup overview cache. Never labels old values as live."""
from copy import deepcopy
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'runtime/app_cache'


def save(config,state):
    from dashboard.numeric_evidence import cache_scope
    from dashboard.numeric_snapshot import freeze_state,save_snapshot
    payload=freeze_state(state);scope=cache_scope(config);payload['cache_scope']=scope
    save_snapshot(payload,ROOT/scope/'latest.json')


def load(config):
    from dashboard.numeric_evidence import cache_scope
    from dashboard.marketdata.paths import DATA_ROOT
    scope=cache_scope(config)
    paths=[ROOT/scope/'latest.json']
    paths+=sorted((DATA_ROOT/'cache/dashboard/numeric').glob('????-??-??/latest.json'),reverse=True)[:10]
    for path in paths:
        try:
            payload=json.loads(path.read_text(encoding='utf8'))
            if payload.get('cache_scope')!=scope:continue
            state=deepcopy(next(s for s in payload['snapshots'] if s['selection']['overview_slot']==0))
            for card in state['overview']:
                card.update(display_kind='启动缓存回看',aligned=False,quality=dict(usable=False,status='启动缓存回看',reason='等待本轮重新核验'))
                card['chart']['kind']='启动缓存回看'
            return state
        except (OSError,ValueError,KeyError,StopIteration):continue
    return None
