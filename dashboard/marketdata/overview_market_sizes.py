"""ETF assets and futures OI notionals, retaining real quantities and dates."""
from .overview_reference import ROOTS,finite,ranking
from .quote_quality import aligned_quotes
from dashboard.native.pair_metrics import MULTIPLIERS
from pandas import Timestamp


def dated(frame,last):
    if frame is None or frame.empty:return {}
    return {str(r['trade_date'])[:10]:r for r in frame.to_dict('records') if r.get('is_final') is True
        and str(r['trade_date'])[:10]<=last and finite(r.get('close')) and r['close']>0
        and finite(r.get('open_interest')) and r['open_interest']>=0}


def etf_assets(reference,root,today):
    chosen,meta=ranking(reference,root,today=today)
    result=dict(status='missing',as_of=meta.get('as_of'),total_cny=None,known_total_cny=None,rows=[],reason=meta.get('reason'))
    if not chosen:return result
    whole=reference['etfs'][root]['rows'];total=sum(r['aum_cny'] for r in whole)
    selected={r['symbol'] for r in chosen}
    rows=[dict(symbol=r['symbol'],name=r.get('name') or r['symbol'],amount_cny=r['aum_cny'],share_pct=100*r['aum_cny']/total) for r in chosen]
    other=sum(r['aum_cny'] for r in whole if r['symbol'] not in selected)
    rows.append(dict(symbol='other',name='其它同指数ETF',amount_cny=other,share_pct=100*other/total))
    return dict(result,status='complete',total_cny=total,known_total_cny=total,rows=rows,universe_count=len(whole),
        source=meta.get('source'),reason='同一日期完整同指数普通ETF；前三只与其它之和等于总规模')


def futures_notionals(root,contracts,daily,live,now,metadata,completed_day,preferred_day):
    rows=sorted((r for r in contracts if r['root']==root),key=lambda r:r.get('slot',99))
    result=dict(status='missing',as_of=None,total_cny=None,known_total_cny=None,rows=[],covered=0,expected=4,
        reason='待四个实际合约的持仓手数、同刻价格和合约乘数')
    if len(rows)!=4 or {r.get('slot') for r in rows}!=set(range(4)) or len({r['symbol'] for r in rows})!=4:return result
    quotes=[live.get(r['symbol'],{}) for r in rows]
    realtime=aligned_quotes(quotes,now)[0] and all(finite(q.get('open_interest')) and q['open_interest']>0 for q in quotes)
    last=completed_day or preferred_day or str(now.tz_convert('Asia/Shanghai').date())
    frames={r['symbol']:dated(daily.get(r['symbol']),last) for r in rows}
    common=set.intersection(*(set(v) for v in frames.values()))
    day=preferred_day if preferred_day in common else max(common) if common else last
    result.update(as_of=max(Timestamp(q['source_event_time']) for q in quotes).isoformat() if realtime else day,
        source='HTTP持仓与同步价格，源日期推定' if realtime else '已完成日线持仓与同日收盘',
        basis='current_http' if realtime else 'completed_daily',formula='open_interest_lots * price * multiplier')
    missing=[]
    for row in rows:
        symbol=row['symbol'];q=live[symbol] if realtime else frames[symbol].get(day,{})
        price=q.get('close');oi=q.get('open_interest');multiplier=metadata.get(symbol,{}).get('multiplier',MULTIPLIERS[root])
        if not finite(price) or price<=0 or not finite(oi) or oi<0 or not finite(multiplier) or multiplier<=0:
            missing.append(symbol);continue
        at=Timestamp(q['source_event_time']).isoformat() if realtime else day+'T15:00:00+08:00'
        result['rows'].append(dict(symbol=symbol,name=symbol.replace('.CFE',''),slot=row['slot'],price=price,
            open_interest_lots=oi,multiplier=multiplier,amount_cny=oi*price*multiplier,price_at=at,oi_at=at))
    known=sum(r['amount_cny'] for r in result['rows']);complete=not missing
    for row in result['rows']:row['share_pct']=100*row['amount_cny']/known if known else 0.
    result.update(status='complete' if complete else 'partial' if result['rows'] else 'missing',covered=len(result['rows']),
        missing_symbols=missing,known_total_cny=known if result['rows'] else None,total_cny=known if complete else None,
        reason=('持仓手数×价格×乘数，按源持仓口径计一次；不使用成交量' if complete else
            '仅显示已知 '+str(len(result['rows']))+'/4 档；缺项不补零，完整总规模待补'))
    return result


def build(reference,contracts,daily,live,now,metadata,completed_day):
    groups={};today=str(now.tz_convert('Asia/Shanghai').date())
    for root in ROOTS:
        assets=etf_assets(reference,root,today)
        futures=futures_notionals(root,contracts,daily,live,now,metadata,completed_day,assets['as_of'])
        a,b=assets.get('total_cny'),futures.get('total_cny')
        groups[root]=dict(etfs=assets,futures=futures,futures_to_etf=b/a if finite(a) and a>0 and finite(b) else None,
            same_day=bool(assets.get('as_of') and futures.get('as_of') and str(futures['as_of'])[:10]==assets['as_of']))
    return groups
