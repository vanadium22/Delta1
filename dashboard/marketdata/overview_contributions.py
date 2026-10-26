"""Minute equity snapshots and index-internal attribution, without acquisition."""
from collections import defaultdict
import json
from pathlib import Path

import pandas as pd

from .overview_reference import finite
from .quote_quality import quote_quality


def equity_path(config, local_root):
    return Path(config.get('overview_equity_file') or Path(local_root)/'overview_equities/latest.json')


def read_equities(config, local_root):
    try:
        data = json.loads(equity_path(config, local_root).read_text(encoding='utf8'))
        if (not isinstance(data,dict) or data.get('schema') != 'overview-equities-v1' or
            not isinstance(data.get('quotes'), dict) or not isinstance(data.get('snapshot_id'),str) or
            any(not isinstance(q,dict) for q in data['quotes'].values())):
            raise ValueError('成分快照格式无效')
        return data
    except (OSError, ValueError, TypeError):
        return {}


def contributions(group, snapshot, index_row, now, previous, reference_version):
    rows = group.get('rows', [])
    result = dict(rows=[], industries=[], leaders=[], laggards=[], source_at=None,
                  snapshot_at=snapshot.get('finished_at'), coverage_pct=None, covered=0,
                  expected=len(rows), up=None, down=None, flat=None, up_pct=None,
                  actual_points=None, contribution_points=None, residual_points=None,
                  weight_date=group.get('as_of'), industry_standard=group.get('industry_standard'),
                  reason='待成分权重与行情', estimate=True)
    if not rows:
        return result
    # Do not mix a previous membership generation with a newly reviewed index.
    same_generation = snapshot.get('reference_version') == reference_version
    try:
        cutoff = pd.Timestamp(snapshot.get('finished_at'))
        if pd.isna(cutoff) or cutoff.tzinfo is None or cutoff > now:
            raise ValueError('快照截止时间无效')
    except (ValueError, TypeError):
        cutoff = None
    # Freeze quote validity at this snapshot's own cutoff, not page repaint time.
    # Older snapshots remain visible with their original date and an explicit status.
    valid_cutoff = cutoff is not None and same_generation
    quotes = snapshot.get('quotes', {}) if valid_cutoff else {}
    previous_weights = group.get('as_of') == previous and group.get('effective_date', group.get('as_of')) <= str(now.date())
    same_day = cutoff is not None and cutoff.tz_convert('Asia/Shanghai').date() == now.tz_convert('Asia/Shanghai').date()
    valid_cutoff = valid_cutoff and same_day
    quotes = snapshot.get('quotes', {}) if valid_cutoff else {}
    base = quotes.get(index_row['symbol'], {}).get('prev_close')
    base_valid = finite(base) and base > 0
    industries = defaultdict(list)
    times = []
    for member in rows:
        q = quotes.get(member['symbol'], {})
        quality = quote_quality(q, cutoff) if q else {'usable': False}
        prior = q.get('prev_close')
        valid = quality['usable'] and finite(prior) and prior > 0
        ret = 100*(q['close']/prior-1) if valid else None
        point = base*member['weight_pct']/100*ret/100 if valid and previous_weights and base_valid else None
        item = dict(symbol=member['symbol'], name=member.get('name') or member['symbol'],
                    industry=member.get('industry') or '待分类', weight_pct=member['weight_pct'],
                    change_pct=ret, contribution_points=point, source_at=q.get('source_event_time') if valid else None)
        result['rows'].append(item)
        industries[item['industry']].append(item)
        if valid:
            times.append(pd.Timestamp(q['source_event_time']))
    covered = [r for r in result['rows'] if r['change_pct'] is not None]
    result.update(covered=len(covered), coverage_pct=sum(r['weight_pct'] for r in covered),
                  up=sum(r['change_pct'] > 0 for r in covered), down=sum(r['change_pct'] < 0 for r in covered),
                  flat=sum(r['change_pct'] == 0 for r in covered),
                  up_pct=100*sum(r['change_pct'] > 0 for r in covered)/len(covered) if covered else None,
                  source_at=min(times).isoformat() if times else None)
    for name, members in industries.items():
        priced = [r for r in members if r['change_pct'] is not None]
        weight = sum(r['weight_pct'] for r in members)
        good_weight = sum(r['weight_pct'] for r in priced)
        # A partial industry return is not the full basket return.
        complete = len(priced) == len(members)
        points = [r['contribution_points'] for r in priced if r['contribution_points'] is not None]
        result['industries'].append(dict(name=name, weight_pct=weight, covered_weight_pct=good_weight,
            change_pct=sum(r['weight_pct']*r['change_pct'] for r in priced)/weight if complete and weight else None,
            contribution_points=sum(points) if points else None, complete=complete, members=members))
    result['industries'].sort(key=lambda r: (-r['weight_pct'], r['name']))
    eligible = [r for r in result['industries'] if r['complete'] and r['name'] != '待分类' and r['contribution_points'] is not None]
    result['leaders'] = sorted((r for r in eligible if r['contribution_points'] > 0), key=lambda r: -r['contribution_points'])[:3]
    result['laggards'] = sorted((r for r in eligible if r['contribution_points'] < 0), key=lambda r: r['contribution_points'])[:3]
    points = [r['contribution_points'] for r in covered if r['contribution_points'] is not None]
    result['contribution_points'] = sum(points) if points else None
    # Match the actual index change to the same cycle, never to a later headline.
    index_quote = quotes.get(index_row['symbol'], {})
    if valid_cutoff and quote_quality(index_quote, cutoff)['usable'] and finite(index_quote.get('prev_close')) and index_quote['prev_close'] > 0:
        result['actual_points'] = index_quote['close']-index_quote['prev_close']
    if result['actual_points'] is not None and result['contribution_points'] is not None:
        result['residual_points'] = result['actual_points']-result['contribution_points']
    if not valid_cutoff:
        result['reason'] = '待匹配当前权重版本的分钟行情'
    elif not previous_weights:
        result['reason'] = '权重日期不是准确上一交易日；展示权重与涨跌，贡献待滚动核验'
    elif not covered:
        result['reason'] = '本分钟无有效成分报价；未将缺失视为零'
    elif (now-cutoff).total_seconds() > 90:
        result['reason'] = '分钟快照已停更，保留原始截止时间'
    else:
        result['reason'] = '上一交易日权重估算；仅完整行业参与贡献排名'
    return result
