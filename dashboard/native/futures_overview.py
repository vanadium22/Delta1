"""Overview pricing changes under the same explicit Excel dividend scenario."""
import pandas as pd

from dashboard.marketdata.quote_quality import aligned_quotes, finite
from .instruments import UNDERLYINGS


def previous_basis_change(row, spot,dividends=None):
    f, s = row.get('basis_prev_future',row.get('prev_close')), row.get('basis_prev_spot',spot.get('prev_close'))
    if row.get('basis_points') is None or not finite(f) or not finite(s) or min(f, s) <= 0:
        return None
    previous=row.get('basis_prev_day') or spot.get('prev_date') or spot.get('yesterday_date')
    dividend=dividends.points(row['symbol'],previous) if dividends is not None and previous else row.get('dividend_points')
    old=f-s+dividend if finite(dividend) else None
    return row['basis_points']-old if old is not None else None


def five_minute_basis_change(row, spot_id, observations, now,dividends=None):
    if row.get('basis_points') is None or not row.get('basis_source_at') or observations.empty:
        return None
    target = pd.Timestamp(row['basis_source_at'])-pd.Timedelta(minutes=5)
    frame = observations[observations.instrument_id.isin([row['symbol'], spot_id])].copy()
    sources = pd.to_datetime(frame.source_event_time, utc=True, errors='coerce')
    receipts = pd.to_datetime(frame.observed_at, utc=True, errors='coerce')
    frame = frame[sources.between(target-pd.Timedelta(seconds=3),target+pd.Timedelta(seconds=3)) &
                  receipts.le(min(now, target+pd.Timedelta(seconds=3)))]
    futures = frame[frame.instrument_id.eq(row['symbol'])].to_dict('records')
    spots = frame[frame.instrument_id.eq(spot_id)].to_dict('records')
    pairs = []
    for f in futures:
        for s in spots:
            cutoff=max(pd.Timestamp(f['observed_at']),pd.Timestamp(s['observed_at']))
            if aligned_quotes([f,s],cutoff)[0]:
                at=max(pd.Timestamp(f['source_event_time']),pd.Timestamp(s['source_event_time']))
                pairs.append((abs((at-target).total_seconds()), f, s))
    if not pairs:
        return None
    _, f, s = min(pairs,key=lambda p:p[0])
    at=max(pd.Timestamp(f['source_event_time']),pd.Timestamp(s['source_event_time']))
    dividend=dividends.points(row['symbol'],at) if dividends is not None else row.get('dividend_points')
    old=f['close']-s['close']+dividend if finite(dividend) else None
    return row['basis_points']-old if old is not None else None


def details(rows, indices, live, observations, now,*,dividends=None):
    groups = {}
    by_root = {r['root']:r for r in indices}
    for root, (spot_id, _, _) in UNDERLYINGS.items():
        contracts=sorted((r for r in rows if r['root']==root),key=lambda r:r.get('slot',99))
        spot=by_root.get(root,{})
        group=dict(basis_change_previous=None,basis_change_5m=None,calendar_points=None,
                   distribution=[],distribution_reason='待四个到期合约的完整有效成交数据',
                   position_distribution=[],position_reason='待四个合约同日持仓数据',
                   previous_reason='较准确昨日收盘；不使用昨结算替代',
                   five_minute_reason='需要五分钟前同一合约及现货的同步观测')
        for contract in contracts:
            contract['basis_change_previous']=previous_basis_change(contract,spot,dividends)
        if contracts:
            near=contracts[0]
            group['basis_kind']=near.get('basis_kind')
            if near.get('basis_kind')=='completed_daily':group['previous_reason']='已完成收盘 '+str(near.get('pricing_day'))+' 相对其准确上一交易日；非当前盘中变化'
            group['basis_change_previous']=previous_basis_change(near,spot,dividends)
            group['basis_change_5m']=five_minute_basis_change(near,spot_id,observations,now,dividends)
        if len(contracts)>=2:
            near,far=contracts[:2]
            try:gap=(pd.Timestamp(far['expiry'])-pd.Timestamp(near['expiry'])).days
            except (TypeError,ValueError,KeyError):gap=None
            ok,_=aligned_quotes([live.get(near['symbol']),live.get(far['symbol']),live.get(spot_id)],now)
            closed=near.get('basis_kind')==far.get('basis_kind')=='completed_daily' and near.get('source_at')==far.get('source_at')==spot.get('source_at') and spot.get('display_kind')=='completed_daily'
            if (ok or closed) and gap is not None and near.get('basis_points') is not None and far.get('basis_points') is not None:
                group['calendar_points']=near['price']-far['price']
        closed=len(contracts)==4 and all(r.get('display_kind')=='completed_daily' for r in contracts) and len({r.get('source_at') for r in contracts})==1
        if len(contracts)==4 and all((r.get('quality',{}).get('usable') or closed) and finite(r.get('volume')) and r['volume']>=0 for r in contracts):
            ok,reason=aligned_quotes([live.get(r['symbol']) for r in contracts],now)
            total=sum(r['volume'] for r in contracts)
            if (ok or closed) and total>0:
                group['distribution']=[dict(symbol=r['symbol'],slot=r['slot'],volume=r['volume'],share_pct=100*r['volume']/total) for r in contracts]
                group['distribution_reason']=('已完成同日收盘 · ' if closed else '')+'同一品种四个到期合约累计成交占比'
            elif ok and total==0:
                group['distribution_reason']='本时点四个合约累计成交合计为0'
            elif not ok:
                group['distribution_reason']=reason
        if len(contracts)==4 and {r.get('slot') for r in contracts}==set(range(4)) and len({r['symbol'] for r in contracts})==4:
            quotes=[live.get(r['symbol'],{}) for r in contracts]
            realtime=aligned_quotes(quotes,now)[0] and all(finite(q.get('open_interest')) and q['open_interest']>0 for q in quotes)
            dates={r.get('yesterday_oi_date') for r in contracts}
            positions=[q['open_interest'] for q in quotes] if realtime else [r.get('yesterday_open_interest') for r in contracts]
            dated=len(dates)==1 and None not in dates and all(finite(v) and v>=0 for v in positions)
            if realtime or dated:
                position_day=(max(pd.Timestamp(q['source_event_time']) for q in quotes).tz_convert('Asia/Shanghai').isoformat()
                              if realtime else next(iter(dates)))
                total=sum(positions)
                if total>0:
                    group['position_distribution']=[dict(symbol=r['symbol'],slot=r['slot'],open_interest=v,
                        share_pct=100*v/total) for r,v in zip(contracts,positions)]
                    group['position_reason']=('实时' if realtime else '已完成日')+'持仓手数占比 · '+position_day
                    group['position_mode']='current_http' if realtime else 'completed_daily'
                    group['position_date']=position_day
                else:group['position_reason']='同日四档持仓合计为0 · '+position_day
        groups[root]=group
    return groups
