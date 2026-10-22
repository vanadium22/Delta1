"""Fixed-contract pair inputs and matched-capacity proxies, without data access.

Price statistics consume one synchronized pair series. Quantities are proxies:
neither a minimum of volumes nor a minimum of OI identifies matched trades.
"""
from numbers import Real

import numpy as np
import pandas as pd

PAIR_FORMULA_VERSION = 'contract-pair-v3'
MULTIPLIERS = {'IF': 300, 'IH': 300, 'IC': 200, 'IM': 200}


def _numeric(value):
    if value is None or isinstance(value, (bool, np.bool_)):
        return np.nan
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors='coerce').to_numpy(dtype=float)
    try:
        return np.asarray(value, dtype=float)
    except (ValueError, TypeError):
        return np.nan


def _positive(value):
    value = _numeric(value)
    return np.where(np.isfinite(value) & (value > 0), value, np.nan)


def _input(category, price, fa, fb, sa=None, sb=None, da=None, db=None, ta=None, tb=None):
    if category not in ('calendar', 'cross'):
        raise ValueError('合约对只支持同品种跨期或跨品种')
    if price not in ('future', 'basis', 'annual', 'raw_basis', 'log_basis', 'raw_annual', 'log_annual'):
        raise ValueError('未知合约对输入')
    fa, fb = _positive(fa), _positive(fb)
    sa, sb = _positive(sa), _positive(sb)
    da, db, ta, tb = map(_numeric, (da, db, ta, tb))
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        if category == 'calendar':
            if price == 'future':
                value = fa - fb
            elif price == 'basis':
                value = 10000 * ((fa + da) - (fb + db)) / sa
            elif price == 'raw_basis':
                value = 10000 * (fa - fb) / sa
            elif price == 'log_basis':
                value = 10000 * np.log(fa / fb)
            else:
                interval = np.where((ta >= 5) & (tb >= 5) & (tb > ta), tb - ta, np.nan)
                ratio = _positive(fb + db) / _positive(fa + da) if price == 'annual' else fb / fa
                value = 36500 * (np.log(ratio) if price == 'log_annual' else ratio - 1) / interval
            # An explicitly reversed/same expiry pair must not silently flip.
            value = np.where(np.isfinite(ta) & np.isfinite(tb) & (tb <= ta), np.nan, value)
        elif price == 'future':
            value = 10000 * np.log(fa / fb)
        else:
            if price in ('basis', 'annual'):
                va, vb = (fa - sa + da) / sa, (fb - sb + db) / sb
            elif price in ('log_basis', 'log_annual'):
                va, vb = np.log(fa / sa), np.log(fb / sb)
            else:
                va, vb = (fa - sa) / sa, (fb - sb) / sb
            value = 36500 * (va / ta - vb / tb) if price.endswith('annual') or price == 'annual' else 10000 * (va - vb)
            if price.endswith('annual') or price == 'annual':
                value = np.where((ta >= 5) & (tb >= 5), value, np.nan)
    return np.where(np.isfinite(value), value, np.nan)


def pair_value(category, price, *, future_a, future_b, spot_a=None, spot_b=None,
               dividend_a=None, dividend_b=None, days_a=None, days_b=None):
    """Scalar version of exactly the vector formula used for completed history."""
    value = _input(category, price, future_a, future_b, spot_a, spot_b,
                   dividend_a, dividend_b, days_a, days_b)
    return float(value) if np.ndim(value) == 0 and np.isfinite(value) else None


def required_symbols(category, price, left, right):
    from .instruments import UNDERLYINGS
    symbols = [left, right]
    if (category == 'cross' and price != 'future') or (category == 'calendar' and price in ('basis', 'raw_basis')):
        symbols.extend(UNDERLYINGS[s[:2]][0] for s in (left, right))
    return list(dict.fromkeys(symbols))


def quote_value(category, price, left, right, quotes, metadata, dividends, day):
    from .instruments import UNDERLYINGS
    day = pd.Timestamp(day).date()
    def leg(symbol):
        expiry = metadata.get(symbol, {}).get('expiry_date')
        return (quotes.get(symbol, {}).get('close'), quotes.get(UNDERLYINGS[symbol[:2]][0], {}).get('close'),
                dividends.points(symbol, day), (pd.Timestamp(expiry).date()-day).days if expiry else None)
    fa, sa, da, ta = leg(left)
    fb, sb, db, tb = leg(right)
    return pair_value(category, price, future_a=fa, future_b=fb, spot_a=sa, spot_b=sb,
                      dividend_a=da, dividend_b=db, days_a=ta, days_b=tb)


def pair_series(a, b, category, price):
    b = b.reindex(a.index)
    value = _input(category, price, a.close, b.close, a.get('S'), b.get('S'),
                   a.get('D'), b.get('D'), a.get('T'), b.get('T'))
    return pd.Series(value, index=a.index, dtype=float)


def pair_definition(category, price):
    calendar = {
        'future': ('F近−F远', '点'),
        'basis': ('10000 × [(F近+D近)−(F远+D远)] / S', 'bp'),
        'raw_basis': ('10000 × (F近−F远) / S', 'bp'),
        'log_basis': ('10000 × ln(F近/F远)', '对数bp'),
        'annual': ('100 × [(F远+D远)/(F近+D近)−1] × 365/(T远−T近)，两腿T≥5', '年化百分点'),
        'raw_annual': ('100 × (F远/F近−1) × 365/(T远−T近)，两腿T≥5', '年化百分点'),
        'log_annual': ('100 × ln(F远/F近) × 365/(T远−T近)，两腿T≥5', '年化百分点'),
    }
    cross = {
        'future': ('10000 × ln(F_A/F_B)', '对数bp'),
        'basis': ('10000 × [(F_A−S_A+D_A)/S_A−(F_B−S_B+D_B)/S_B]', 'bp'),
        'raw_basis': ('10000 × [(F_A−S_A)/S_A−(F_B−S_B)/S_B]', 'bp'),
        'log_basis': ('10000 × ln[(F_A/S_A)/(F_B/S_B)]', 'bp'),
        'annual': ('36500 × [(F_A−S_A+D_A)/(S_A T_A)−(F_B−S_B+D_B)/(S_B T_B)]，两腿T≥5', '年化百分点'),
        'raw_annual': ('36500 × [(F_A−S_A)/(S_A T_A)−(F_B−S_B)/(S_B T_B)]，两腿T≥5', '年化百分点'),
        'log_annual': ('36500 × [ln(F_A/S_A)/T_A−ln(F_B/S_B)/T_B]，两腿T≥5', '年化百分点'),
    }
    construction, unit = (calendar if category == 'calendar' else cross)[price]
    return dict(formula_version=PAIR_FORMULA_VERSION, construction=construction, unit=unit,
                ratio='h=1' if category == 'calendar' else 'h_t=F_A,前一完整交易日 M_A/(F_B,前一完整交易日 M_B)',
                weight='匹配容量代理 min(V_A,V_B/h_t)；非实际配对成交或账户仓位',
                synchronization='固定具体合约、同刻观测；缺腿不填充，不拼接换月')


def lagged_ratio(a, b, category, left, right):
    if category == 'calendar':
        return pd.Series(1., index=a.index)
    value = a.close.shift() * MULTIPLIERS[left[:2]] / b.close.reindex(a.index).shift() / MULTIPLIERS[right[:2]]
    from .intraday import previous_day
    dates=list(a.index.tz_convert('Asia/Shanghai').date)
    previous=[None]+dates[:-1]
    complete=pd.Series([prior==previous_day(at) for prior,at in zip(previous,a.index)],index=a.index)
    return value.where(a.close.shift().gt(0) & b.close.reindex(a.index).shift().gt(0) & complete)


def ratio_for_day(a, b, category, left, right, day):
    """Only the previous complete exchange session can set a current-day ratio."""
    if category == 'calendar':
        return 1.
    from .intraday import previous_day
    day = pd.Timestamp(day)
    if day.tzinfo is None:
        day = day.tz_localize('Asia/Shanghai')
    previous = previous_day(day)
    if previous is None:
        return None
    values = []
    for frame in (a, b):
        if frame.empty or 'close' not in frame or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            return None
        rows = frame.loc[frame.index.tz_convert('Asia/Shanghai').date == previous]
        if len(rows) != 1 or not np.isfinite(rows.close.iloc[0]) or rows.close.iloc[0] <= 0:
            return None
        values.append(rows.close.iloc[0])
    return float(values[0] * MULTIPLIERS[left[:2]] / (values[1] * MULTIPLIERS[right[:2]]))


def pair_quantities(a, b, category, left, right):
    """All current and previous OI comparisons use the same h_t at each row."""
    b = b.reindex(a.index)
    h = lagged_ratio(a, b, category, left, right)
    def minimum(x, y):
        return pd.concat([x, y], axis=1).min(axis=1, skipna=False)
    volume = minimum(a.volume.where(a.volume.ge(0)), b.volume.where(b.volume.ge(0)) / h)
    oi = minimum(a.oi_valid, b.oi_valid / h)
    previous = minimum(a.oi_valid.shift(), b.oi_valid.shift() / h)
    delta = (oi - previous).where(a.doi.notna() & b.doi.notna())
    positive_weight = minimum(a.doi.clip(lower=0), b.doi.clip(lower=0) / h)
    base = minimum(a.oi_valid.shift(5), b.oi_valid.shift(5) / h)
    full = a.oi_valid.notna().rolling(6).sum().eq(6) & b.oi_valid.notna().rolling(6).sum().eq(6)
    growth = (100 * np.log(oi.where(oi.gt(0)) / base.where(base.gt(0)))).where(full)
    return pd.DataFrame(dict(h=h, volume=volume, previous_oi=previous, oi=oi, doi=delta,
                             positive_weight=positive_weight, growth_base=base, growth=growth), index=a.index)


def pair_minute_frame(ma, mb, spot_a, spot_b, left, right, metadata, dividends, category, price, quantities):
    """Build pair OHLC inputs only from exact synchronized minute observations."""
    columns = ['x', 'volume', 'session_id', 'trade_date']
    if ma.empty or mb is None or mb.empty:
        return pd.DataFrame(columns=columns, index=ma.index[:0])
    def leg(frame, spot, symbol):
        frame = frame.copy()
        frame['S'] = spot.get('close', pd.Series(dtype=float)).reindex(frame.index)
        days = frame.index.tz_convert('Asia/Shanghai').date
        expiry = metadata.get(symbol, {}).get('expiry_date')
        cache = {day: (dividends.points(symbol, day), (pd.Timestamp(expiry).date() - day).days if expiry else np.nan) for day in set(days)}
        frame['D'] = [cache[day][0] for day in days]
        frame['T'] = [cache[day][1] for day in days]
        return frame
    a, b = leg(ma, spot_a, left), leg(mb, spot_b, right).reindex(ma.index)
    valid = a.trade_date.eq(b.trade_date) & a.session_id.eq(b.session_id)
    x = pair_series(a, b, category, price).where(valid)
    h_by_day = {t.tz_convert('Asia/Shanghai').date(): h for t, h in quantities.h.items()}
    hs = pd.Series([h_by_day.get(t.tz_convert('Asia/Shanghai').date(), np.nan) for t in a.index], index=a.index)
    volume = pd.concat([a.volume.where(a.volume.ge(0)), b.volume.where(b.volume.ge(0)) / hs], axis=1).min(axis=1, skipna=False).where(valid)
    return a.assign(x=x, volume=volume)[columns]


def pair_daily(frame):
    """Price OHLC needs all synchronized X; weighted centers also need all weights."""
    from .intraday import expected_minutes
    rows = []
    if frame.empty:
        return pd.DataFrame()
    for day, group in frame.groupby('trade_date'):
        index = expected_minutes(day)
        group = group.reindex(index)
        if not group.x.notna().all():
            continue
        complete_weights = group.volume.notna().all() and group.volume.ge(0).all()
        weight_sum = group.volume.sum() if complete_weights else np.nan
        weighted_sum = (group.x*group.volume).sum() if complete_weights else np.nan
        center = weighted_sum/weight_sum if complete_weights and weight_sum > 0 else np.nan
        rows.append(dict(event_time=index[-1], open=group.x.iloc[0], high=group.x.max(), low=group.x.min(),
                         close=group.x.iloc[-1], center=center, center_gap=group.x.iloc[-1]-center,
                         n=len(index), weight_sum=weight_sum, weighted_sum=weighted_sum))
    return pd.DataFrame(rows).set_index('event_time') if rows else pd.DataFrame()


def pair_ohlc_statistics(ohlc, calendar):
    """Absolute pair TR; no division by a signed/near-zero pair level."""
    blank = pd.Series(np.nan, index=calendar)
    if ohlc.empty:
        return dict(clv=blank, tr=blank, baseline=blank, pressure=blank)
    q = ohlc.reindex(calendar)
    clv = (2*q.close-q.high-q.low) / (q.high-q.low).where(q.high.gt(q.low))
    tr = pd.concat([q.high-q.low, (q.high-q.close.shift()).abs(), (q.low-q.close.shift()).abs()], axis=1).max(axis=1, skipna=False)
    baseline = tr.shift().rolling(20, min_periods=20).median()
    return dict(clv=clv, tr=tr, baseline=baseline, pressure=tr / baseline.where(baseline.gt(0)))
