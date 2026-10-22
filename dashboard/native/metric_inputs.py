"""Pure non-regression input transforms and explicit executable-input contracts."""
import math
import pandas as pd


INPUTS = {
    'future': ('真实期货价格', '点'),
    'basis': ('分红调整基差', 'bp'),
    'annual': ('分红调整简单年化基差', '年化百分点'),
    'raw_basis': ('未调整普通基差', 'bp'),
    'log_basis': ('未调整对数基差', 'bp'),
    'raw_annual': ('未调整简单年化基差', '年化百分点'),
    'log_annual': ('未调整对数年化基差', '年化百分点'),
}


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def input_value(price, future, spot=None, dividend=None, days=None):
    """Scalar X; no inferred zero dividend and no log of a signed basis."""
    if price not in INPUTS:
        raise ValueError('未知价格输入')
    if not valid_number(future) or future <= 0:
        return None
    if price == 'future':
        return float(future)
    if not valid_number(spot) or spot <= 0:
        return None
    if price in ('basis', 'annual'):
        if not valid_number(dividend):
            return None
        value = 10000 * (future - spot + dividend) / spot
    elif price in ('log_basis', 'log_annual'):
        value = 10000 * math.log(future / spot)
    else:
        value = 10000 * (future - spot) / spot
    if price in ('annual', 'raw_annual', 'log_annual'):
        return value * 365 / (100 * days) if valid_number(days) and days >= 5 else None
    return float(value)


def theoretical_cost_band(future, spot, days, inputs, as_of, *, expiry=None):
    """Original simple carry fair value plus independently supplied directional costs.

    Rates use decimal annual units. long_cost_bp is the cost to buy future/sell
    the executable spot leg; short_cost_bp is the reverse direction. Validity
    and publication timestamps are supplied, never inferred from a bar date.
    """
    missing = {k: None for k in ('fair','deviation','upper','lower','long_space','short_space')}
    if not isinstance(inputs, dict):
        return missing, '缺真实融资、股息率和方向性成本输入'
    required = ('financing_rate','dividend_yield','long_cost_bp','short_cost_bp',
                'spot_leg_id','expiry_date','effective_from','effective_to','known_at','version')
    if any(inputs.get(k) is None or inputs.get(k) == '' for k in required):
        return missing, '成本输入契约不完整：需融资/股息/双向成本、可执行现货腿、有效期、发布时间和版本'
    if not all(valid_number(inputs[k]) for k in required[:4]) or min(inputs['long_cost_bp'], inputs['short_cost_bp']) < 0:
        return missing, '利率或方向性成本非法；成本须非负且单位为bp'
    if not all(valid_number(v) and v > 0 for v in (future, spot, days)):
        return missing, '真实期现价格或到期天数无效'
    now = pd.Timestamp(as_of)
    try:
        known = pd.Timestamp(inputs['known_at'])
        start, end = (pd.Timestamp(inputs[k]).date() for k in ('effective_from','effective_to'))
        if now.tzinfo is None or known.tzinfo is None or known > now:
            return missing, '成本发布时间缺时区或晚于估值时点'
        if not start <= now.tz_convert('Asia/Shanghai').date() <= end:
            return missing, '融资与成本条款不在有效期内'
        if expiry is None or pd.Timestamp(inputs['expiry_date']).date() != pd.Timestamp(expiry).date():
            return missing, '成本到期日与固定合约不一致'
    except (ValueError, TypeError):
        return missing, '成本有效期或发布时间不可解析'
    fair = spot * (1 + (inputs['financing_rate']-inputs['dividend_yield']) * days / 365)
    if fair <= 0:
        return missing, '模型理论价格非正'
    deviation = 10000 * (future-fair) / spot
    return dict(fair=fair, deviation=deviation,
                upper=fair+spot*inputs['short_cost_bp']/10000,
                lower=fair-spot*inputs['long_cost_bp']/10000,
                long_space=-deviation-inputs['long_cost_bp'],
                short_space=deviation-inputs['short_cost_bp']), ''


def etf_premium(mapping, live, now, *, underlying):
    from dashboard.marketdata.quote_quality import aligned_quotes
    if not isinstance(mapping, dict) or any(not mapping.get(k) for k in ('etf_id','iopv_id','underlying_id')):
        return None, None, '缺ETF/IOPV及对应指数的显式映射'
    if mapping['underlying_id'] != underlying or mapping['etf_id'] == mapping['iopv_id']:
        return None, None, 'ETF/IOPV映射与对应指数不匹配'
    a, b = (live.get(mapping[k]) for k in ('etf_id','iopv_id'))
    ok, reason = aligned_quotes([a,b], now)
    if not ok:
        return None, None, reason
    if not all(valid_number(q.get('close')) and q['close'] > 0 for q in (a,b)):
        return None, None, 'ETF或IOPV价格须为正'
    return 10000*(a['close']/b['close']-1), max(pd.Timestamp(q['source_event_time']) for q in (a,b)).isoformat(), ''
