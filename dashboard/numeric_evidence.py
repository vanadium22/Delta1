"""Refresh evidence, independent of clocks, collection attempts and Excel saves."""
import hashlib
import json
from pathlib import Path

from dashboard.percentile_audit import clean


def digest(value):
    return hashlib.sha256(json.dumps(clean(value), ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode('utf8')).hexdigest()


def cache_scope(config):
    # Only data identity, never credentials or UI settings. A different source
    # must not inherit another configuration's daily calculation cache.
    paths = ('reference_file', 'realtime_root', 'dividend_root',
             'dividend_scenario_file', 'daily_dividend_file')
    identity = {key: str(Path(config[key]).resolve()) if config.get(key) else '' for key in paths}
    identity['history_roots'] = sorted(str(Path(p).resolve()) for p in config.get('history_roots', []))
    for key in ('realtime_id', 'dividend_mode', 'dividend_missing_policy', 'allow_unverified'):
        identity[key] = config.get(key)
    for key in ('research_carry_inputs','research_etf_iopv_mapping'):
        identity[key] = config.get(key)
    # Invalidate old result schemas without changing any market-data file.
    from dashboard.indicator_catalog import FORMULA_VERSION
    identity['formula_version'] = FORMULA_VERSION
    return digest(identity)


def evidence(payload):
    rows = []
    for state in payload['snapshots']:
        for card in state.get('overview', []):
            rows.append(dict(slot=card['alias'], contract=card['symbol'], kind=card.get('display_kind'),
                future_time=card['quote'].get('source_event_time'),
                spot_time=card['spot'].get('source_event_time'),
                future=card['quote'].get('close'), spot=card['spot'].get('close')))
    times = [r[key] for r in rows for key in ('future_time', 'spot_time') if r[key]]
    # Parse offsets: lexical ordering of ISO strings is not chronological.
    from datetime import datetime
    times.sort(key=lambda x: datetime.fromisoformat(x.replace('Z', '+00:00')))
    return dict(display_input_revision=digest(rows), rows=rows,
                oldest_source_time=times[0] if times else None,
                newest_source_time=times[-1] if times else None)


def annotate(feed, payload, *, previous=None, completed_at=None, duration=None,
             acquisition='快照回看', runtime=None):
    current = evidence(payload)
    old = (previous or {}).get('evidence')
    changed = old is not None and old['display_input_revision'] != current['display_input_revision']
    current['display_inputs_changed'] = changed if old else None
    # A different fallback/contract/price is not proof of newly arrived quotes.
    if not old:
        note = '首次读取；是否有新行情需后续对比'
    elif not changed:
        note = '未观察到源时/报价变化；重算不代表新行情'
    else:
        note = '展示输入变化；行情新旧以逐行原始时点为准'
    current['note'] = note
    feed.update(evidence=current, calculation_completed_at=completed_at or feed['generated_at'],
                calculation_seconds=duration, acquisition=acquisition, runtime=runtime or {})
    source = feed['sheets']['来源与状态']
    source.extend([['采集状态', acquisition], ['行情变化核验', note],
                   ['最早源时', current['oldest_source_time']], ['最新源时', current['newest_source_time']]])
    for row in current['rows']:
        source.append([row['slot']+' '+row['contract']+' 原始源时',
                       '期货 '+str(row['future_time'] or '缺失')+'；指数 '+str(row['spot_time'] or '缺失')])
    for key, label in (('config_path', '实际配置'), ('realtime_root', '实时缓存目录'),
                       ('python', '实际 Python'), ('cache_scope', '计算缓存配置标识')):
        if (runtime or {}).get(key):
            source.append([label, runtime[key]])
    # Operational timestamps and poll counters never force a full table write.
    feed['sheet_revisions'] = {name: digest(rows) for name, rows in feed['sheets'].items()}
    feed['content_revision'] = digest(feed['sheet_revisions'])
    return feed
