"""Same offline/live display values for Excel and local presentation editions.

Raw ResearchEngine snapshots keep their strict freshness semantics for diagnosis.
This adapter labels cached observations and historical closes explicitly.
"""
from copy import deepcopy
import json
import pandas as pd
from dashboard.marketdata.dividends import DividendBook, adjusted_basis
from dashboard.marketdata.quote_quality import finite
from dashboard.marketdata.repository import ReferenceBook
from dashboard.marketdata.contract_reference import latest_contracts
from dashboard.session_clock import session_policy


def cached_pair_time(quote, spot, now):
    """Accept only coherent saved intraday observations, never mix two dates."""
    try:
        source = [pd.Timestamp(q['source_event_time']) for q in (quote, spot)]
        received = [pd.Timestamp(q.get('observed_at', q.get('received_at'))) for q in (quote, spot)]
        if any(pd.isna(t) or t.tzinfo is None or t > now for t in source + received): return None
        if any(not finite(q.get('close')) or q['close'] <= 0 for q in (quote, spot)): return None
        if (max(source)-min(source)).total_seconds() > 3 or (max(received)-min(received)).total_seconds() > 3: return None
        for s, r in zip(source, received):
            if not -3 <= (r-s).total_seconds() <= 30: return None
            local = s.tz_convert('Asia/Shanghai')
            seconds = local.hour*3600+local.minute*60+local.second
            if not (34200 <= seconds <= 41400 or 46800 <= seconds <= 54000): return None
            if not session_policy(local.to_pydatetime())['allowed']: return None
        return max(source)
    except (KeyError, TypeError, ValueError):
        return None


def latest_saved_pair(model, symbol, spot_symbol, now):
    """A later stale poll must not hide the last coherent saved observation."""
    rows=getattr(model,'live_rows',pd.DataFrame())
    if rows.empty:return None
    eligible=rows[rows.instrument_id.isin([symbol,spot_symbol]) & rows.observed_at.le(now)]
    for _,batch in reversed(list(eligible.groupby('observed_at',sort=True))):
        quotes={str(r.instrument_id):r.to_dict() for _,r in batch.iterrows()}
        q,s=quotes.get(symbol,{}),quotes.get(spot_symbol,{})
        stamp=cached_pair_time(q,s,now)
        if stamp is not None:return q,s,stamp
    return None


def daily_saved_pairs(now):
    """Recover calculated final states even if the SQLite tail has moved on."""
    from dashboard.marketdata.paths import DATA_ROOT
    today=str(now.tz_convert('Asia/Shanghai').date())
    paths=sorted((p for p in (DATA_ROOT/'cache/dashboard/numeric').glob('????-??-??/latest.json') if p.parent.name<=today),reverse=True)
    result={}
    for path in paths[:10]:
        try:
            payload=json.loads(path.read_text(encoding='utf8'))
            for state in payload['snapshots']:
                for card in state['overview']:
                    symbol=card['symbol']
                    if symbol in result:continue
                    q,s=card['quote'],card['spot'];stamp=cached_pair_time(q,s,now)
                    if stamp is not None:result[symbol]=(q,s,stamp)
        except (OSError,ValueError,KeyError,TypeError):continue
    return result


def display_snapshot(model, request, *, now=None):
    from dashboard.native.continuous import slot_history, slot_map
    from dashboard.native.card_data import distributions
    from dashboard.native.nonregression import single
    now = pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    policy = session_policy(now.to_pydatetime())
    request = {**request, 'as_of': now.isoformat(), 'save': False}
    metadata = latest_contracts(ReferenceBook(model.config.get('reference_file')).data)
    if request.get('category','basis')=='basis':
        actual=slot_map(metadata,'IF',now)[0].get(f"IF0{request.get('overview_slot',0)}.CFE")
        if actual:request['research_month']=actual[2:6]
    state = model.snapshot(request)
    engine = model.research_engine
    dividends = DividendBook.load(model.config.get('dividend_root', ''), model.config.get('dividend_scenario_file'),
        model.config.get('daily_dividend_file'), model.config.get('dividend_mode', 'fixed_snapshot'),
        contracts=metadata, as_of=now.tz_convert('Asia/Shanghai'), missing_policy=model.config.get('dividend_missing_policy'))
    state = deepcopy(state)
    saved_daily=daily_saved_pairs(now)
    for card in state.get('overview', []):
        symbol = card['symbol']; slot = state['selection']['overview_slot']
        cached=next((v for k,v in getattr(engine,'continuous_cache',{}).items() if k[5]==symbol and k[6]==slot),None)
        continuous, continuity = cached or slot_history(card['root'], slot, engine.daily, engine.calendar, metadata, dividends, symbol, now)
        fixed = single(engine.daily.get(symbol, pd.DataFrame()), engine.daily.get(card['spot_symbol'], pd.DataFrame()),
                       symbol, card['expiry'], dividends, engine.calendar)
        fixed = fixed.assign(F=fixed.close, S=fixed.S, D=fixed.D, symbol=symbol, expiry=card['expiry'])
        # Prefer this concrete contract. New listings may only have slot history;
        # in that case expose the historical concrete identity, never relabel it.
        valid = fixed.loc[fixed.F.notna() & fixed.S.notna() & fixed.S.gt(0)]
        if valid.empty: valid = continuous.loc[continuous.F.notna() & continuous.S.notna() & continuous.S.gt(0)]
        hist_time = valid.index[-1] if len(valid) else None
        cache_time = cached_pair_time(card['quote'], card['spot'], now)
        fresh = policy['allowed'] and card['aligned'] and card['quality']['usable']
        if not fresh and cache_time is None:
            saved=latest_saved_pair(model,symbol,card['spot_symbol'],now)
            if saved is not None:card['quote'],card['spot'],cache_time=saved
        saved=saved_daily.get(symbol)
        if not fresh and saved is not None and (cache_time is None or saved[2]>cache_time):
            card['quote'],card['spot'],cache_time=saved
        use_cache = not fresh and cache_time is not None and (hist_time is None or cache_time > hist_time)
        kind = '盘中观测' if fresh else '保存行情回看' if use_cache else '历史收盘'
        stamp = pd.Timestamp(card['quote']['source_event_time']) if fresh else cache_time if use_cache else hist_time
        card['active_symbol'] = symbol
        if fresh or use_cache:
            day = stamp.tz_convert('Asia/Shanghai').date()
            days = (pd.Timestamp(card['expiry']).date()-day).days if card['expiry'] else None
            d = dividends.points(symbol, day)
            values = adjusted_basis(card['quote'].get('close'), card['spot'].get('close'), d, days)
            card.update(days=days, dividend=d, current=values)
        elif hist_time is not None:
            h = valid.iloc[-1]
            card.update(symbol=h.symbol, expiry=h.expiry, days=int(h['T']) if pd.notna(h['T']) else None,
                        dividend=float(h.D) if finite(h.D) else None,
                        quote=dict(close=float(h.F), source_event_time=hist_time.isoformat(), received_at=None),
                        spot=dict(close=float(h.S), source_event_time=hist_time.isoformat(), received_at=None))
            card['current'] = adjusted_basis(float(h.F), float(h.S), card['dividend'], card['days'])
        else:
            kind = '缺少可用数据'
            card.update(quote={}, spot={}, current=adjusted_basis(None, None, None, None))
        card['display_kind'] = kind
        card['display_time'] = stamp.isoformat() if stamp is not None else None
        if not fresh:
            card['quality'] = dict(usable=False, status=kind, reason=policy['reason'])
            card['aligned'] = False
            card['reason'] = ('最后保存的同步观测，源日期按接收日推定；不保证为收盘最终报价' if use_cache else '最新可用同步历史收盘；不是实时行情')
        field = 'annual' if request.get('distribution_input') == 'annual' else 'basis'
        value = card['current']['annual_pct' if field == 'annual' else 'bp']
        chart = dict(kind=kind, value=value, time=card['display_time'], unit='%' if field == 'annual' else 'bp', rows=[])
        if stamp is not None:
            chart['rows'] = distributions(continuous[field], engine.calendar, stamp, value,
                listing=str(engine.calendar[0].date()) if len(engine.calendar) else None,
                annual=field == 'annual', eligibility=(continuous['T'].isna() | continuous['T'].ge(5)) if field == 'annual' else None,
                allow_partial=True)
        chart['reference_end'] = max((r['end'] for r in chart['rows'] if r['end']), default=None)
        card['chart'] = chart
    # The numeric/presentation basis view follows the selected slot, not the
    # independent research-tab month. Recalculate each displayed concrete month.
    if request.get('category', 'basis') == 'basis':
        entities = []
        for month in dict.fromkeys(c['symbol'][2:6] for c in state.get('overview', [])):
            part = state if month == request.get('research_month') else model.snapshot({**request, 'research_month': month})
            for entity in part.get('entities', []):
                card = next((c for c in state['overview'] if c['symbol'] == entity['left']), None)
                if not card: continue
                entity = deepcopy(entity)
                for row in entity['metrics']:
                    mapping = {'A01.points':'points', 'A01.bp':'bp', 'A02.annual':'annual_pct', 'A02.convergence':'convergence_bp_day'}
                    if row['id'] in mapping:
                        row.update(current=card['current'].get(mapping[row['id']]), current_time=card['display_time'], current_reason=card['reason'], display_kind=card['display_kind'])
                    elif row.get('current') is not None:
                        row['display_kind'] = '盘中观测' if policy['allowed'] else '保存行情回看'
                entities.append(entity)
        state['entities'] = entities
    state['display_policy'] = policy
    state['display_updated_at'] = now.isoformat()
    return state
