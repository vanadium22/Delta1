"""Read-only enrichment for the two overview pages; no Wind calls here."""
from copy import deepcopy
from bisect import bisect_left, bisect_right

import pandas as pd

from dashboard.marketdata.overview_reference import load, ranking, finite
from dashboard.marketdata.overview_contributions import contributions, read_equities
from dashboard.marketdata.quote_quality import aligned_quotes, quote_quality
from .instruments import UNDERLYINGS


def load_reference(model, now):
    if not hasattr(model, 'local_root'):
        return dict(data={},version=None,due=True,error='尚无已核验低频资料')
    return load(model.config, model.local_root, now=now.to_pydatetime())


def five_minute(row, now):
    points = row.get('series', [])
    if not points or not row['quality'].get('usable'):
        return None
    latest = points[-1]
    target = pd.Timestamp(latest['source_at'])-pd.Timedelta(minutes=5)
    candidates = [p for p in points if p['session'] == latest['session'] and
                  abs((pd.Timestamp(p['source_at'])-target).total_seconds()) <= 3]
    if not candidates:
        return None
    old = min(candidates, key=lambda p: abs((pd.Timestamp(p['source_at'])-target).total_seconds()))
    return 100*((1+latest['value']/100)/(1+old['value']/100)-1)


def premium_pairs(symbol, iopv_id, observations, now):
    if observations.empty or not iopv_id:
        return None, []
    frame = observations[observations.instrument_id.isin([symbol, iopv_id]) & observations.observed_at.le(now)]
    funds = []
    for q in frame[frame.instrument_id.eq(symbol)].to_dict('records'):
        s,r=pd.Timestamp(q.get('source_event_time')),pd.Timestamp(q.get('observed_at'))
        if not pd.isna(s) and not pd.isna(r):funds.append((s.value,r.value,q))
    funds.sort(key=lambda p:p[0]);sources=[p[0] for p in funds]
    refs = frame[frame.instrument_id.eq(iopv_id)].drop_duplicates('source_event_time', keep='last').to_dict('records')
    series = []; current = None
    for ref in refs:
        source, receipt = pd.Timestamp(ref['source_event_time']), pd.Timestamp(ref['observed_at'])
        if pd.isna(source) or pd.isna(receipt):
            continue
        start,end=bisect_left(sources,source.value-3_000_000_000),bisect_right(sources,source.value+3_000_000_000)
        matches = [item for item in funds[start:end] if abs(item[1]-receipt.value)<=3_000_000_000]
        if not matches:
            continue
        q = min(matches,key=lambda item:abs(item[0]-source.value))[2]
        cutoff = max(receipt, pd.Timestamp(q['observed_at']))
        ok, _ = aligned_quotes([q, ref], cutoff)
        if not ok:
            continue
        value = 10000*(q['close']/ref['close']-1)
        local = source.tz_convert('Asia/Shanghai')
        minutes = local.hour*60+local.minute
        point = dict(source_at=source.isoformat(), value=value,
                     x=(minutes-570 if minutes <= 690 else minutes-660)+local.second/60,
                     session='am' if minutes <= 690 else 'pm', etf_price=q['close'])
        if str(local.date()) == str(now.tz_convert('Asia/Shanghai').date()):
            series.append(point)
        if aligned_quotes([q, ref], now)[0] and (current is None or source > pd.Timestamp(current['source_at'])):
            current = point
    return current, sorted(series, key=lambda p: p['source_at'])


def enrich(model, data, reference, now):
    source = reference['data']
    today = str(now.tz_convert('Asia/Shanghai').date())
    data['reference'] = dict(due=reference['due'], error=reference['error'], fetched_at=source.get('fetched_at'))
    equity = read_equities(model.config, model.local_root) if hasattr(model, 'local_root') else {}
    # All four indices share one immutable minute generation. An ordinary page
    # repaint never advances its source cutoff or recalculates with later legs.
    key = (reference['version'], equity.get('snapshot_id'), today, data.get('previous_session'))
    if getattr(model, '_overview_contribution_key', None) != key:
        model._overview_contribution_key = key
        model._overview_contributions = {row['root']: contributions(source.get('indices', {}).get(row['root'], {}),
            equity, row, now, data.get('previous_session'), reference['version']) for row in data['indices']}
    data['index_details'] = deepcopy(model._overview_contributions)
    for detail in data['index_details'].values():
        cutoff = detail.get('snapshot_at')
        if cutoff and (now-pd.Timestamp(cutoff)).total_seconds() > 90:
            detail['stale'] = True
            detail['reason'] = '分钟快照已停更，保留原始截止时间'
    for row in data['indices']:
        row['change_5m_pct'] = five_minute(row, now)
    groups = {}
    for root in UNDERLYINGS:
        selected, meta = ranking(source, root, today=today)
        rows = [r for r in data['etfs'] if r['root'] == root]
        by_symbol = {r['symbol']: r for r in rows}
        if selected:
            visible = [dict(by_symbol.get(r['symbol'], {}), **r) for r in selected]
        else:
            # Keep available representative quotes visible, but never give them
            # a fabricated size rank or a fabricated 100% market share.
            visible = [dict(r, rank=None, aum_cny=None, aum_share_pct=None) for r in rows[:1]]
        groups[root] = dict(rows=visible, ranking=meta,
            flow=dict(daily_cny=None, five_day_cny=None, top_daily_cny=None, top_five_day_cny=None,
                      as_of=None, reason='待已披露总份额、净值及份额折算核验'),
            pcf=dict(as_of=None, reason='待当日申赎清单'))
    data['etf_groups'] = groups
    for row in data['etfs']:
        row['spread_bp'] = None
        q = getattr(model, '_overview_latest', {}).get(row['symbol'], {})
        bid, ask = q.get('bid_price_1'), q.get('ask_price_1')
        if row['quality'].get('usable') and finite(bid) and finite(ask) and 0 < bid <= ask:
            row['spread_bp'] = 10000*(ask-bid)/((ask+bid)/2)
        pair, series = premium_pairs(row['symbol'], row.get('iopv_id'), model.live_rows, now)
        row['premium_series'] = series
        row['premium_source_at'] = pair['source_at'] if pair else row.get('iopv_source_at') if row.get('premium_bp') is not None else None
        if pair:
            row.update(premium_bp=pair['value'], premium_source_at=pair['source_at'],
                       premium_reason='已配对ETF与IOPV观测；两腿源时和接收时差均不超过3秒')
    # Copies above must include the final premium/spread enrichment.
    for root, group in groups.items():
        newest = {r['symbol']: r for r in data['etfs'] if r['root'] == root}
        group['rows'] = [dict(newest.get(r['symbol'], {}), **{k:v for k,v in r.items() if k in
            ('symbol','name','root','rank','aum_cny','aum_date','aum_share_pct')}) for r in group['rows']]
    return data
