"""Dated indicator series and independent variable-window statistics.

No acquisition, research service, fixed 20/60 mutation or raw-data writes.
"""
from datetime import date, datetime, timedelta
from math import isfinite
from numbers import Real
from statistics import mean, median, stdev

from dashboard.indicator_v6.sources import dates_between, SPOTS
from dashboard.native.continuous import slot_map
from .overview_basis import dividend_record
from .overview_percentiles import historical_dividend, prior_days

SERIES = ('raw', 'adjusted', 'annual', 'calendar_03_02', 'calendar_02_01')
CHARTS = {'adjusted': ('raw', 'adjusted'), 'annual': ('annual',),
          'calendar_03_02': ('calendar_03_02',), 'calendar_02_01': ('calendar_02_01',)}
MAX_WINDOW = 365
MAX_STATS = 120


def finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def selection(root='IF', slot=0, window=90, stats=None):
    if root not in SPOTS or type(slot) is not int or slot not in range(4):
        raise ValueError('请选择 IF/IH/IC/IM 和 00–03 档位')
    if type(window) is not int or not 10 <= window <= MAX_WINDOW:
        raise ValueError('图像窗口为 10–365 自然日')
    stats = min(20, window//2) if stats is None else stats
    if type(stats) is not int or not 2 <= stats <= MAX_STATS:
        raise ValueError('统计窗口为 2–120 交易日')
    return dict(root=root, slot=slot, window=window, stats=stats)


def chart_selections(request):
    """Validate four chart windows; old single-window requests remain valid."""
    base = selection(*(request.get(k) for k in ('root', 'slot', 'window', 'stats')))
    charts = request.get('charts')
    if charts is None:
        return {key: dict(base) for key in CHARTS}
    if not isinstance(charts, dict) or set(charts) != set(CHARTS):
        raise ValueError('四张图须分别提供窗口')
    output = {}
    for key, value in charts.items():
        if not isinstance(value, dict) or set(value) != {'window', 'stats'}:
            raise ValueError('图像窗口格式无效')
        output[key] = selection(base['root'], base['slot'], value['window'], value['stats'])
    return output


def aggregate_selection(request):
    """Plan/read and repair the union of all chart windows once."""
    charts = chart_selections(request)
    first = next(iter(charts.values()))
    return selection(first['root'], first['slot'], max(c['window'] for c in charts.values()),
                     max(c['stats'] for c in charts.values()))


def plan(day, request, metadata):
    request = selection(**request)
    first = str(date.fromisoformat(day)-timedelta(days=request['window']-1))
    reference = prior_days(day, request['stats'])
    days = dates_between(min(first, reference[0]), day)
    if day not in days:
        raise ValueError('指标定价日不在已核验交易日历内')
    needed = set()
    mappings = {}
    for d in days:
        mapping, reason = slot_map(metadata, request['root'], d)
        mappings[d] = dict(mapping=mapping, reason=reason)
        needed.add((SPOTS[request['root']], d))
        for slot in {request['slot'], 1, 2, 3}:
            symbol = mapping.get(f"{request['root']}0{slot}.CFE")
            if symbol:
                needed.add((symbol, d))
    return dict(selection=request, pricing_day=day, start=first, end=day, days=days,
                reference_days=reference, mappings=mappings,
                rows=[dict(symbol=s, day=d) for s,d in sorted(needed, key=lambda r:(r[1],r[0]))])


def maintenance_rows(target, request, metadata):
    """Only the selected root's daily prices; never future closes or minute bars."""
    # Maintenance runs through the latest completed day. Include sufficient
    # history for a live comparison on the next session as well as a close view.
    return plan(target, request, metadata)['rows']


def point(day, symbols=(), *, value=None, reason=None, excluded=False, **extra):
    return dict(day=day, symbols=list(symbols), value=value, reason=reason,
                excluded=excluded, **extra)


def values(day, request, mapping, metadata, prices, book, *, current=False, at=None, source_at=None):
    """All legs belong to this day and use D known at the common pricing time."""
    root = request['root']
    spot = prices.get(SPOTS[root])
    legs = {}
    for slot in {request['slot'], 1, 2, 3}:
        symbol = mapping.get(f'{root}0{slot}.CFE')
        expiry = metadata.get(symbol, {}).get('expiry_date')
        t = (date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else None
        record = dividend_record(book, symbol, at or day) if current else historical_dividend(book, symbol, day)
        legs[slot] = dict(symbol=symbol, F=prices.get(symbol), D=record.get('points'), T=t,
                          dividend=record, expiry=expiry)
    result = {}

    def make(slots, kind):
        selected = [legs[s] for s in slots]
        symbols = [leg['symbol'] for leg in selected]
        zeros = [leg['symbol'] for leg in selected if leg['dividend'].get('estimated_zero')]
        inputs = dict(S=spot, legs=selected)
        extra = dict(inputs=inputs, zero_dividend_symbols=zeros, source_at=source_at,
                     http_session_inferred=bool(set([SPOTS[root],*symbols]) & set(prices.get('_http_session_inferred_symbols',[]))))
        if any(not leg['symbol'] or leg['T'] is None for leg in selected):
            return point(day, symbols, reason='mapping_missing', **extra)
        if any(leg['T'] < 5 for leg in selected):
            return point(day, symbols, reason='T_LT_5', excluded=True, **extra)
        if not finite(spot) or spot <= 0:
            return point(day, symbols, reason='index_close_missing', **extra)
        if any(not finite(leg['F']) or leg['F'] <= 0 for leg in selected):
            return point(day, symbols, reason='future_close_missing', **extra)
        if kind != 'raw' and any(not finite(leg['D']) or leg['D'] < 0 for leg in selected):
            return point(day, symbols, reason='dividend_missing_or_conflict', **extra)
        leg = selected[0]
        if kind == 'raw':
            value = leg['F']-spot
            extra['zero_dividend_symbols'] = []
        elif kind == 'adjusted':
            value = leg['F']-spot+leg['D']
        elif kind == 'annual':
            value = 100*(leg['F']-spot+leg['D'])/spot*365/leg['T']
        else:
            far, near = selected
            delta = far['T']-near['T']
            if delta <= 0:
                return point(day, symbols, reason='invalid_expiry_difference', **extra)
            value = 100*((far['F']-near['F'])+(far['D']-near['D']))/spot*365/delta
        return point(day, symbols, value=float(value), **extra)

    for key in ('raw', 'adjusted', 'annual'):
        result[key] = make([request['slot']], key)
    result['calendar_03_02'] = make([3,2], 'calendar')
    result['calendar_02_01'] = make([2,1], 'calendar')
    return result


def historical(plan_value, metadata, tables, book, *, stop=lambda: False):
    output = {key:[] for key in SERIES}
    request = plan_value['selection']
    for day in plan_value['days']:
        if stop():
            raise InterruptedError()
        mapped = plan_value['mappings'][day]
        if mapped['reason']:
            calculated = {key:point(day, reason='mapping_missing') for key in SERIES}
        else:
            rows = {s:table.get(day, {}) for s,table in tables.items()}
            prices = {s:r.get('close') for s,r in rows.items()}
            prices['_http_session_inferred_symbols'] = [s for s,r in rows.items() if r.get('source_date_basis') == 'corroborated_live_session']
            calculated = values(day, request, mapped['mapping'], metadata, prices, book,
                                source_at=day+'T15:00:00+08:00')
        for key in SERIES:
            output[key].append(calculated[key])
    return output


def statistics(rows, reference_days, current):
    by_day = {r['day']:r for r in rows}
    reference = [by_day.get(d, point(d, reason='history_missing')) for d in reference_days]
    excluded = [r['day'] for r in reference if r['excluded']]
    missing = [dict(day=r['day'], reason=r.get('reason') or 'history_missing') for r in reference
               if not r['excluded'] and not finite(r.get('value'))]
    valid = [r for r in reference if not r['excluded'] and finite(r.get('value'))]
    samples = [r['value'] for r in valid]
    complete = not missing and bool(samples)
    avg = mean(samples) if complete else None
    mid = median(samples) if complete else None
    sigma = stdev(samples) if complete and len(samples) >= 2 else None
    x = current.get('value')
    usable = complete and finite(x)
    reason=('历史样本缺项' if missing else '有效历史样本不足' if not samples else
            current.get('reason') or '当前比较值缺失' if not finite(x) else
            '历史标准差为零' if sigma == 0 else '有效样本不足2个' if sigma is None else '')
    return dict(mean=avg, median=mid, std=sigma, reason=reason,
                z=(x-avg)/sigma if usable and sigma is not None and sigma > 0 else None,
                percentile=100*(sum(v < x for v in samples)+.5*sum(v == x for v in samples))/len(samples) if usable else None,
                complete=complete, samples=len(samples), requested=len(reference_days),
                excluded_dates=excluded, missing=missing,
                zero_dividend_dates=[r['day'] for r in valid if r.get('zero_dividend_symbols')],
                http_session_inferred_dates=[r['day'] for r in valid if r.get('http_session_inferred')],
                start=reference_days[0], end=reference_days[-1])


def display(plan_value, history, current):
    result = {}
    for key in SERIES:
        latest = current[key]
        rows = [r for r in history[key] if plan_value['start'] <= r['day'] < plan_value['pricing_day']]
        rows.append(latest)
        result[key] = dict(rows=rows, current=latest,
                           statistics=statistics(history[key], plan_value['reference_days'], latest))
    return dict(schema='indicator-analysis-v1', selection=plan_value['selection'],
                pricing_day=plan_value['pricing_day'], start=plan_value['start'], end=plan_value['end'], series=result,
                history_start=plan_value['days'][0], reference_days=plan_value['reference_days'],
                mapping_policy='逐日挂牌/到期重建，换实际合约断线；非当时可得映射',
                statistics_policy='指标计算窗口取定价日前交易日；样本标准差ddof=1；等值半权；未知缺项不跳过',
                network_requested=False)


def display_charts(plan_value, history, current, request):
    """Slice one shared historical read into four independent chart results."""
    if 'charts' not in request:
        return display(plan_value, history, current)
    selections = chart_selections(request)
    day = plan_value['pricing_day']
    output = None
    chart_info = {}
    combined = {}
    for key, channels in CHARTS.items():
        choice = selections[key]
        start = str(date.fromisoformat(day)-timedelta(days=choice['window']-1))
        individual = {**plan_value, 'selection': choice, 'start': start,
                      'reference_days': prior_days(day, choice['stats'])}
        rendered = display(individual, history, current)
        if output is None:output = rendered
        chart_info[key] = {k:rendered[k] for k in ('selection', 'start', 'end', 'reference_days')}
        combined.update({channel:rendered['series'][channel] for channel in channels})
    output.update(selection=request, charts=chart_info, series=combined)
    return output


def summary(result):
    """Small explicit whitelist for same-run company evidence, no raw records."""
    if not isinstance(result,dict):return None
    output={k:result.get(k) for k in ('schema','selection','pricing_day','start','end','mode','as_of','version','cache_hit','history_reads','completed_target','reference_fallback','error')}
    if isinstance(output['selection'],dict):
        request=output['selection']
        output['selection']={k:request.get(k) for k in ('root','slot','window','stats')}
        if isinstance(request.get('charts'),dict):
            output['selection']['charts']={key:{k:value.get(k) for k in ('window','stats')}
                for key,value in request['charts'].items() if key in CHARTS and isinstance(value,dict)}
    else:output['selection']=None
    output['series']={}
    channels=result.get('series') if isinstance(result.get('series'),dict) else {}
    for key in SERIES:
        channel=channels.get(key)
        if not isinstance(channel,dict):continue
        current=channel.get('current') if isinstance(channel.get('current'),dict) else {}
        stats=channel.get('statistics') if isinstance(channel.get('statistics'),dict) else {}
        inputs=current.get('inputs') or current.get('calculation_inputs') or {}
        if not isinstance(inputs,dict):inputs={}
        legs=[];raw_legs=inputs.get('legs') if isinstance(inputs.get('legs'),list) else []
        for leg in raw_legs[:3]:
            if not isinstance(leg,dict):continue
            record=leg.get('dividend') if isinstance(leg.get('dividend'),dict) else {}
            legs.append({**{k:leg.get(k) for k in ('symbol','F','D','T','expiry')},
                'dividend_source':leg.get('dividend_source') or record.get('source_snapshot') or record.get('source_business_date'),
                'dividend_kind':leg.get('dividend_kind') or record.get('source_kind')})
        current_safe={k:current.get(k) for k in ('day','symbols','value','reason','excluded','source_at','http_session_inferred')}
        current_safe['calculation_inputs']=dict(S=inputs.get('S'),legs=legs)
        output['series'][key]=dict(current=current_safe,
            statistics={k:stats.get(k) for k in ('mean','median','std','z','percentile','reason','complete','samples','requested',
                'excluded_dates','missing','zero_dividend_dates','http_session_inferred_dates','start','end')})
    return output


def draw_summary(value):
    """Bounded evidence of actual GUI draws; no raw market or config records."""
    if not isinstance(value,dict):return None
    def stamp(item):
        if not isinstance(item,str) or len(item)>64:return None
        try:
            parsed=datetime.fromisoformat(item)
            return item if parsed.tzinfo is not None else None
        except ValueError:return None
    def event(item):
        if not isinstance(item,dict):return None
        try:
            original=item['selection'];charts=chart_selections(original)
            request=selection(*(original.get(k) for k in ('root','slot','window','stats')))
            if 'charts' in original:
                request['charts']={key:{k:choice[k] for k in ('window','stats')} for key,choice in charts.items()}
        except (TypeError,KeyError,ValueError,AttributeError):request=None
        channels=item.get('series') if isinstance(item.get('series'),dict) else {}
        output=dict(draw_at=stamp(item.get('draw_at')),reason=item.get('reason') if item.get('reason') in ('timer','manual') else None,
            selection=request,mode=item.get('mode') if item.get('mode') in ('realtime','completed_daily') else None,
            calculation_at=stamp(item.get('calculation_at')),pricing_day=None,series={})
        try:output['pricing_day']=date.fromisoformat(item['pricing_day']).isoformat()
        except (TypeError,KeyError,ValueError):pass
        for key in SERIES:
            channel=channels.get(key)
            if not isinstance(channel,dict):continue
            output['series'][key]=dict(source_at=stamp(channel.get('source_at')),
                **{k:float(channel[k]) if finite(channel.get(k)) else None for k in ('current','z','percentile')})
        return output
    events=value.get('timer_draws') if isinstance(value.get('timer_draws'),list) else []
    interval=value.get('interval_ms')
    return dict(active=value.get('active') is True,frozen=value.get('frozen') is True,
        interval_ms=interval if type(interval) is int and 0<=interval<=3600000 else None,
        last_draw=event(value.get('last_draw')),timer_draws=[e for x in events[-3:] if (e:=event(x)) is not None])
