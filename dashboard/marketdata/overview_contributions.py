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
                  weight_date=group.get('as_of'),official_weight_date=group.get('official_as_of',group.get('as_of')),
                  weight_method=group.get('weight_method','official_previous_close'),weight_reason=group.get('weight_reason'),
                  weight_source_dates=group.get('weight_source_dates',[]),
                  industry_standard=group.get('industry_standard'),mode=snapshot.get('mode','minute'),
                  reason='缺成分名单；股票数据缺口数量尚未知', estimate=True,
                  inputs=dict(membership_available=bool(rows),missing_weights=0,missing_industries=0,
                    missing_quotes=0,missing_previous_closes=0,index_previous_close_valid=False,
                    reference_matches=False,previous_weights_valid=False))
    if not rows:
        for key in ('missing_weights','missing_industries','missing_quotes','missing_previous_closes'):result['inputs'][key]=None
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
    verified_weights=group.get('weights_complete') is not False
    result['weights_complete']=verified_weights
    if not verified_weights:result.update(weight_date=None,official_weight_date=None)
    previous_weights = verified_weights and group.get('as_of') == previous and group.get('effective_date', group.get('as_of')) <= str(now.date())
    closed=snapshot.get('mode')=='completed_daily'
    same_day = (snapshot.get('pricing_day')<=str(now.tz_convert('Asia/Shanghai').date()) if closed and snapshot.get('pricing_day') else
                cutoff is not None and cutoff.tz_convert('Asia/Shanghai').date() == now.tz_convert('Asia/Shanghai').date())
    valid_cutoff = valid_cutoff and same_day
    quotes = snapshot.get('quotes', {}) if valid_cutoff else {}
    base = quotes.get(index_row['symbol'], {}).get('prev_close')
    base_valid = finite(base) and base > 0
    result['inputs'].update(missing_weights=sum(not finite(r.get('weight_pct')) for r in rows),
        missing_industries=sum(not r.get('industry') for r in rows),index_previous_close_valid=bool(base_valid),
        reference_matches=bool(same_generation),previous_weights_valid=bool(previous_weights),snapshot_valid=bool(valid_cutoff))
    industries = defaultdict(list)
    times = []
    def usable(q):
        if closed:
            return (q.get('source_kind')=='completed_daily' and q.get('trade_date')==snapshot.get('pricing_day') and
                q.get('source_event_time')==snapshot.get('pricing_at') and finite(q.get('close')) and q['close']>0)
        return bool(q) and quote_quality(q,cutoff)['usable']
    for member in rows:
        q = quotes.get(member['symbol'], {})
        prior = q.get('prev_close')
        if not usable(q):result['inputs']['missing_quotes']+=1
        if not finite(prior) or prior<=0:result['inputs']['missing_previous_closes']+=1
        valid = usable(q) and finite(prior) and prior > 0
        ret = 100*(q['close']/prior-1) if valid else None
        point = base*member['weight_pct']/100*ret/100 if valid and previous_weights and base_valid and finite(member.get('weight_pct')) else None
        item = dict(symbol=member['symbol'], name=member.get('name') or member['symbol'],
                    industry=member.get('industry') or '待分类', weight_pct=member['weight_pct'],
                    change_pct=ret, contribution_points=point, source_at=q.get('source_event_time') if valid else None)
        result['rows'].append(item)
        industries[item['industry']].append(item)
        if valid:
            times.append(pd.Timestamp(q['source_event_time']))
    covered = [r for r in result['rows'] if r['change_pct'] is not None]
    result.update(covered=len(covered), coverage_pct=sum(r['weight_pct'] for r in covered) if verified_weights else None,
                  up=sum(r['change_pct'] > 0 for r in covered), down=sum(r['change_pct'] < 0 for r in covered),
                  flat=sum(r['change_pct'] == 0 for r in covered),
                  up_pct=100*sum(r['change_pct'] > 0 for r in covered)/len(covered) if covered else None,
                  source_at=min(times).isoformat() if times else None)
    for name, members in industries.items():
        priced = [r for r in members if r['change_pct'] is not None]
        weights_known=all(finite(r['weight_pct']) for r in members)
        weight = sum(r['weight_pct'] for r in members) if weights_known else None
        good_weight = sum(r['weight_pct'] for r in priced) if weights_known else None
        # A partial industry return is not the full basket return.
        complete = len(priced) == len(members) and weights_known and verified_weights
        points = [r['contribution_points'] for r in priced if r['contribution_points'] is not None]
        missing_prices=len(members)-len(priced)
        issues=[]
        if missing_prices:issues.append('缺有效行情/昨收 '+str(missing_prices)+'只')
        if not weights_known or not verified_weights:issues.append('权重未完整核验')
        if not previous_weights:issues.append('权重未滚动至准确昨日')
        if not base_valid:issues.append('缺指数准确昨收')
        result['industries'].append(dict(name=name, weight_pct=weight, covered_weight_pct=good_weight,
            change_pct=sum(r['weight_pct']*r['change_pct'] for r in priced)/weight if complete and weight else None,
            contribution_points=sum(points) if complete and len(points)==len(members) else None,
            reason='；'.join(issues) or '完整行业估算',complete=complete,members=members))
    result['industries'].sort(key=lambda r: (r['weight_pct'] is None, -(r['weight_pct'] or 0), r['name']))
    eligible = [r for r in result['industries'] if r['complete'] and r['name'] != '待分类' and r['contribution_points'] is not None]
    result['leaders'] = sorted((r for r in eligible if r['contribution_points'] > 0), key=lambda r: -r['contribution_points'])[:3]
    result['laggards'] = sorted((r for r in eligible if r['contribution_points'] < 0), key=lambda r: r['contribution_points'])[:3]
    points = [r['contribution_points'] for r in covered if r['contribution_points'] is not None]
    result['contribution_points'] = sum(points) if points else None
    # Match the actual index change to the same cycle, never to a later headline.
    index_quote = quotes.get(index_row['symbol'], {})
    if valid_cutoff and usable(index_quote) and finite(index_quote.get('prev_close')) and index_quote['prev_close'] > 0:
        result['actual_points'] = index_quote['close']-index_quote['prev_close']
    if result['actual_points'] is not None and result['contribution_points'] is not None:
        result['residual_points'] = result['actual_points']-result['contribution_points']
    if not valid_cutoff:
        result['reason'] = '待匹配当前权重版本的分钟行情'
    elif not verified_weights:
        result['reason'] = '权重缺失或参考日期混合；完整行业篮子和贡献待核验'
    elif not previous_weights:
        result['reason'] = '权重日期不是准确上一交易日；展示权重与涨跌，贡献待滚动核验'
    elif not covered:
        result['reason'] = '本分钟无有效成分报价；未将缺失视为零'
    elif not closed and (now-cutoff).total_seconds() > 90:
        result['reason'] = '分钟快照已停更，保留原始截止时间'
    else:
        result['reason'] = ('收盘参考 '+snapshot['pricing_day']+' · ' if closed else '')+('全成分收盘价滚动权重估算；非官方昨日权重' if group.get('weight_method')=='fixed_quantity_estimate' else '上一交易日权重估算')+'；仅完整行业参与贡献排名'
    missing=result['inputs']
    explanation=[]
    for key,label in [('missing_weights','缺权重'),('missing_industries','缺行业'),('missing_quotes','缺有效报价'),('missing_previous_closes','缺准确昨收')]:
        if missing[key]:explanation.append(label+str(missing[key])+'只')
    if not base_valid:explanation.append('缺指数准确昨收')
    if explanation:result['reason']+='；'+'，'.join(explanation)
    return result
