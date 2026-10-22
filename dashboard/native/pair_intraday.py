"""Read-only, fixed-contract pair observations against completed-history pools.

HTTP observations never become exchange bars. Invalid batches are segment
boundaries, including a latest missing leg; they are not silently skipped.
"""
from numbers import Real

import numpy as np
import pandas as pd

from .instruments import UNDERLYINGS
from .pair_metrics import (MULTIPLIERS, pair_definition, pair_series, quote_value,
                           required_symbols)

PAIR_INTRADAY_VERSION = 'contract-pair-intraday-v1'
ZONE = 'Asia/Shanghai'


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and np.isfinite(value)


def _stamp(value):
    try:
        result = pd.Timestamp(value)
        return result.tz_convert('UTC') if result.tzinfo is not None and not pd.isna(result) else None
    except (TypeError, ValueError):
        return None


def _session(at):
    from dashboard.session_clock import session_policy
    if at is None or not session_policy(at.to_pydatetime())['allowed']:
        return None
    local = at.tz_convert(ZONE)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    part = 'am' if 34200 <= seconds <= 41400 else 'pm' if 46800 <= seconds <= 54000 else None
    return (local.date(), part) if part else None


def _days(now, count=21):
    from .intraday import previous_day
    days = []
    for _ in range(count):
        day = previous_day(now)
        if day is None:
            return []
        days.append(day)
        now = pd.Timestamp(day).tz_localize(ZONE)
    return list(reversed(days))


def _frame(raw, *, index=None, days=None):
    if raw is None or raw.empty:
        return None
    frame = raw.set_index('event_time') if 'event_time' in raw else raw
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        return None
    if index is not None:
        frame = frame.loc[frame.index.isin(index)]
    if days is not None:
        frame = frame.loc[np.isin(frame.index.tz_convert(ZONE).date, days)]
    if frame.index.has_duplicates:
        return None
    return frame


def _complete(raw, index, fields):
    frame = _frame(raw, index=index)
    if frame is None or any(name not in frame for name in (*fields, 'trade_date', 'session_id')):
        return None
    frame = frame.reindex(index).copy()
    frame[list(fields)] = frame[list(fields)].apply(pd.to_numeric, errors='coerce')
    if frame[list(fields)].isna().any().any():
        return None
    if not np.isfinite(frame[list(fields)].to_numpy(dtype=float)).all():
        return None
    if frame.session_id.isna().any() or frame.trade_date.isna().any():
        return None
    sessions = np.where(index.tz_convert(ZONE).hour < 12, 'am', 'pm')
    if not np.array_equal(frame.session_id.to_numpy(), sessions):
        return None
    actual_dates = pd.to_datetime(frame.trade_date, errors='coerce').dt.date.to_numpy()
    if not np.array_equal(actual_dates, index.tz_convert(ZONE).date):
        return None
    if 'is_final' in frame and not frame.is_final.eq(True).all():
        return None
    return frame


def _ratios(data, left, right, category, days):
    """Every historical ratio uses the preceding completed daily close."""
    if category == 'calendar':
        return np.ones(len(days)), None, {}
    closes, source_times = [], {}
    for symbol in (left, right):
        frame = _frame(data.get(symbol), days=days)
        if frame is None or 'close' not in frame:
            return None, None, {}
        values = []
        for day in days:
            part = frame.loc[frame.index.tz_convert(ZONE).date == day]
            if len(part) != 1 or not _finite(part.close.iloc[0]) or part.close.iloc[0] <= 0:
                return None, None, {}
            if 'is_final' in part and not part.is_final.eq(True).all():
                return None, None, {}
            values.append(float(part.close.iloc[0]))
            source_times[symbol] = part.index[0]
        closes.append(values)
    ratios = np.ones(len(days)) if category == 'calendar' else (
        np.asarray(closes[0]) * MULTIPLIERS[left[:2]] / np.asarray(closes[1]) / MULTIPLIERS[right[:2]])
    return ratios, max(source_times.values()), {symbol:at.isoformat() for symbol,at in source_times.items()}


def _volume_baseline(data, minutes, left, right, category, now, boundary):
    from .intraday import expected_minutes
    days = _days(now)
    info = dict(denominator=None, baseline_n=0, baseline_start=None, baseline_end=None,
                effective_h=None, ratio_source_time=None, ratio_source_times={}, minute_count=None)
    if len(days) != 21:
        return info, '缺连续21个历史交易日'
    ratios, ratio_time, ratio_source_times = _ratios(data, left, right, category, days)
    if ratios is None:
        return info, '缺连续21交易日完整双腿日价；无法确认前收换算比例'
    info.update(effective_h=float(ratios[-1]), ratio_source_time=ratio_time.isoformat() if ratio_time is not None else None,
                ratio_source_times=ratio_source_times)
    local = boundary.tz_convert(ZONE)
    totals = []
    for i, day in enumerate(days[1:]):
        end = pd.Timestamp(day).tz_localize(ZONE) + pd.Timedelta(hours=local.hour, minutes=local.minute)
        index = expected_minutes(day, end)
        if not len(index) or index[-1] != end:
            return info, '当前分钟不属于完整交易分钟'
        info['minute_count'] = len(index)
        a, b = (_complete(minutes.get(s), index, ('volume',)) for s in (left, right))
        if a is None or b is None or not a.session_id.equals(b.session_id):
            return info, '缺此前连续20日同刻之前完整同步双腿分钟'
        if a.volume.lt(0).any() or b.volume.lt(0).any():
            return info, '历史分钟成交量无效'
        # Match cumulative capacity, not the sum of separately matched minutes.
        totals.append(min(float(a.volume.sum()), float(b.volume.sum()) / ratios[i]))
        info.update(baseline_n=len(totals), baseline_end=end.isoformat())
        if info['baseline_start'] is None:
            info['baseline_start'] = end.isoformat()
    denominator = float(np.median(totals))
    info['denominator'] = denominator
    return info, '' if denominator > 0 else '此前20日同刻匹配量中位数为0，不能作分母'


def _range_baseline(minutes, left, right, category, price, metadata, dividends, now):
    from .intraday import expected_minutes
    days = _days(now)
    info = dict(denominator=None, baseline_n=0, baseline_start=None, baseline_end=None)
    if len(days) != 21:
        return info, '缺连续21个完整历史交易日'
    symbols = required_symbols(category, price, left, right)
    ohlc = []
    for day in days:
        index = expected_minutes(day)
        frames = {symbol: _complete(minutes.get(symbol), index, ('close',)) for symbol in symbols}
        if any(frame is None or frame.close.le(0).any() for frame in frames.values()):
            return info, '缺连续21日每个交易日240个有效同步分钟输入'
        if any(not frames[left].session_id.equals(frame.session_id) for frame in frames.values()):
            return info, '合约或指数分钟会话失配'
        legs = []
        for symbol in (left, right):
            frame = frames[symbol].copy()
            spot = frames.get(UNDERLYINGS[symbol[:2]][0])
            frame['S'] = spot.close if spot is not None else np.nan
            frame['D'] = dividends.points(symbol, day)
            expiry = metadata.get(symbol, {}).get('expiry_date')
            frame['T'] = (pd.Timestamp(expiry).date() - day).days if expiry else np.nan
            legs.append(frame)
        x = pair_series(*legs, category, price)
        if not np.isfinite(x.to_numpy()).all():
            return info, '历史合约对输入无效或年化任一腿T<5'
        ohlc.append((float(x.max()), float(x.min()), float(x.iloc[-1])))
    tr = [max(high-low, abs(high-ohlc[i-1][2]), abs(low-ohlc[i-1][2]))
          for i, (high, low, close) in enumerate(ohlc) if i]
    denominator = float(np.median(tr))
    info.update(denominator=denominator, baseline_n=20,
                baseline_start=expected_minutes(days[1])[-1].isoformat(),
                baseline_end=expected_minutes(days[-1])[-1].isoformat())
    return info, '' if denominator > 0 else '此前20个合约对绝对TR中位数为0，不能作分母'


def _quotes(quotes, symbols, at, now):
    """Strict source synchronization; never borrow a later source observation."""
    if any(symbol not in quotes for symbol in symbols):
        return None, '最新批次缺腿/缺对应指数'
    stamps = []
    for symbol in symbols:
        q = quotes[symbol]
        source, received = _stamp(q.get('source_event_time')), _stamp(q.get('observed_at', q.get('received_at')))
        if source is None or received is None or source > now or received > now or source > at or source > received:
            return None, '观测时间无效或含未来时间'
        if _session(source) is None or _session(source) != _session(at):
            return None, '行情非同一交易会话'
        if (at-source).total_seconds() > 30 or (at-received).total_seconds() > 30:
            return None, '最新行情陈旧超过30秒'
        if not _finite(q.get('close')) or q['close'] <= 0:
            return None, '最新合约对价格输入无效'
        stamps.append(source)
    if len(set(stamps)) != 1:
        return None, '双腿/对应指数source时间不一致'
    return stamps[0], ''


def _segments(samples, symbols, left, right, category, price, metadata, dividends, now, *, volume_only=False):
    """Iterate every relevant batch in receipt order, including invalid batches."""
    if samples is None or samples.empty:
        return [], '尚无同步HTTP采集样本', False
    required = ('instrument_id', 'observed_at', 'source_event_time', 'run_id', 'poll', 'batch')
    if any(column not in samples for column in required):
        return [], '采集样本缺批次或时间字段', True
    # Keep the poll envelope before selecting symbols. A latest successful poll
    # for other instruments is evidence that this pair is missing, even when
    # neither leg has a row. Unrelated chunks within a poll are not failures.
    selected = samples.copy()
    selected['_received'] = selected.observed_at.map(_stamp)
    selected = selected.loc[selected._received.isna() | selected._received.le(now)]
    if selected.empty:
        return [], '尚无截至当前的合约对采集样本', False
    groups = []
    for _, poll in selected.groupby(['run_id', 'poll'], sort=False, dropna=False):
        relevant = poll.loc[poll.instrument_id.isin(symbols)]
        if relevant.empty:
            at = poll._received.max() if poll._received.notna().all() else now
            groups.append((at, relevant))
        else:
            for _, group in relevant.groupby('batch', sort=False, dropna=False):
                at = group._received.max() if group._received.notna().all() else now
                groups.append((at, group))
    groups.sort(key=lambda item: item[0])
    segment, reason = [], '尚无有效同步采集段'
    for at, group in groups:
        quotes = {q['instrument_id']: q for q in group.to_dict('records')}
        stamp, reason = _quotes(quotes, symbols, at, now)
        if group.instrument_id.duplicated().any():
            stamp, reason = None, '同批次同合约重复，不能确认同步输入'
        if stamp is None:
            segment = []
            continue
        if volume_only:
            value = 0. if all(_finite(quotes[s].get('volume_total')) and quotes[s]['volume_total'] >= 0 for s in (left,right)) else None
        else:
            value = quote_value(category, price, left, right, quotes, metadata, dividends, stamp.tz_convert(ZONE).date())
        if not _finite(value):
            segment, reason = [], '双腿累计量缺失/无效' if volume_only else '合约对输入无效或年化任一腿T<5'
            continue
        reset = any(int(q['quality_flags']) & (8 | 16 | 64 | 128) for q in quotes.values() if _finite(q.get('quality_flags')))
        if segment and (reset or quotes[left]['run_id'] != segment[-1][2][left]['run_id'] or
                        _session(stamp) != _session(segment[-1][0]) or
                        (stamp-segment[-1][0]).total_seconds() > 30 or stamp < segment[-1][0]):
            segment = []
        if segment and stamp == segment[-1][0]:
            old_quotes = segment[-1][2]
            changed = value != segment[-1][1] or any(quotes[s].get('close') != old_quotes[s].get('close') for s in symbols)
            if volume_only:
                changed = changed or any(quotes[s].get('volume_total') != old_quotes[s].get('volume_total') for s in (left,right))
            if changed:
                segment, reason = [], '相同source时间价格修订；采集段重置'
            continue
        segment.append((stamp, float(value), quotes))
    if segment and (_session(segment[-1][0]) != _session(now) or (now-segment[-1][0]).total_seconds() > 30):
        segment, reason = [], '最新采集样本陈旧或交易会话已变'
    return segment, reason, True


def _row(rows, code, category, price):
    from .nonregression import metric
    row = next((r for r in rows if r['id'] == code), None)
    if row is None:
        row = metric(code, '合约对同刻匹配量活跃度' if code == 'B09.same_time' else '合约对采集段振幅',
                     pd.Series(dtype=float), '倍', '', '')
        rows.append(row)
    definition = pair_definition(category, price)
    if code == 'B09.same_time':
        definition = dict(definition, construction='同刻累计匹配容量 min(V_A,V_B/h_day)，非实际配对成交', unit='手（A腿等价容量代理）')
    definition['formula_version'] = PAIR_INTRADAY_VERSION
    row.update(formula_version=PAIR_INTRADAY_VERSION, pair_construction=definition['construction'])
    row['formula'] = ('min(累计V_A,累计V_B/h_today) / median(此前20日同分钟min(累计V_A,累计V_B/h_day))'
                      if code == 'B09.same_time' else '最新连续同步HTTP合约对X极差 / median(此前20完整交易日合约对绝对TR)')
    row['pair_metadata'] = definition
    return row


def _publish(row, value, stamp, info, reason, *, source_times=None, history=None):
    supported = _finite(value)
    row.update(current=float(value) if supported else None, current_time=stamp.isoformat() if supported else None,
               current_reason=reason, current_scope=info['scope'], current_supported=True,
               current_n=info.get('sample_n') if row['id'] == 'B11.sample' else info['baseline_n'],
               current_source_times=source_times or {}, pair_intraday=info,
               current_history=history or [], current_reference_end=info.get('baseline_end'),
               current_history_cutoff=info.get('ratio_source_time') or info.get('baseline_end'))


def update_pair_intraday(rows, *, left, right, category, price, data, minute_data,
                         metadata, dividends, now, live=None, samples=None, cache=None):
    """Update only the two intraday children; daily values/history are immutable.

    cache is accepted for caller compatibility; no identity-only cache is used,
    so revised minute inputs and clock aging are always validated again.
    """
    if category == 'basis':
        return rows
    now = _stamp(now)
    if now is None:
        raise ValueError('盘中计算需要带时区的当前时间')
    volume_row = _row(rows, 'B09.same_time', category, price)
    range_row = _row(rows, 'B11.sample', category, price)
    symbols = required_symbols(category, price, left, right)
    segment, segment_reason, have_samples = _segments(samples, symbols, left, right, category, price, metadata, dividends, now)
    volume_segment, volume_segment_reason, have_volume_samples = _segments(
        samples, [left,right], left, right, category, price, metadata, dividends, now, volume_only=True)
    boundary = now.floor('min')
    candidates = [item for item in volume_segment if 0 <= (boundary-item[0]).total_seconds() <= 3
                  and 0 <= (now-item[0]).total_seconds() <= 30]
    # A supplied invalid latest batch takes precedence over an older live dict.
    if not have_volume_samples and live:
        stamp, _ = _quotes(live, [left, right], now, now)
        if stamp is not None and 0 <= (boundary-stamp).total_seconds() <= 3:
            candidates = [(stamp, None, live)]
    # Daily-only snapshots have no current observation to compare. In particular
    # apply() must not calculate the expensive TR pool before samples arrive in
    # observations(). Freshness and segments are still checked on every call.
    have_current = bool(live) or (samples is not None and not samples.empty) or _finite(volume_row.get('current'))
    if have_current:
        volume_info, volume_reason = _volume_baseline(data, minute_data, left, right, category, now, boundary)
    else:
        volume_info = dict(denominator=None, baseline_n=0, baseline_start=None, baseline_end=None,
                           effective_h=1. if category=='calendar' else None, ratio_source_time=None, ratio_source_times={}, minute_count=None)
        volume_reason = '尚无当前同步累计量；完整日终指标保留'
    volume_info.update(numerator=None, scope='盘中同刻匹配容量代理', approximation=False,
                       segment_start=volume_segment[0][0].isoformat() if volume_segment else None,
                       segment_end=volume_segment[-1][0].isoformat() if volume_segment else None)
    volume, volume_stamp, source_times = None, None, {}
    if candidates and _session(now) is not None:
        volume_stamp, _, quotes = candidates[-1]
        source_times = {s: str(quotes[s]['source_event_time']) for s in (left, right)}
        va, vb = (quotes[s].get('volume_total') for s in (left, right))
        h = volume_info['effective_h']
        if _finite(va) and _finite(vb) and va >= 0 and vb >= 0 and _finite(h) and h > 0:
            volume_info['numerator'] = min(float(va), float(vb) / h)
        volume_info.update(approximation=volume_stamp != boundary, boundary=boundary.isoformat())
        if not volume_reason and volume_info['numerator'] is not None:
            volume = volume_info['numerator'] / volume_info['denominator']
            volume_reason = '前20日同分钟累计匹配容量；当前分钟前0—3秒近似，未插值' if volume_info['approximation'] else '双腿整分钟同刻累计匹配容量 / 前20日同刻中位数；非实际配对成交'
        elif not volume_reason:
            volume_reason = '缺双腿有效累计量或前收换算比例'
    elif not volume_reason:
        volume_reason = volume_segment_reason if have_volume_samples and not volume_segment else '等待整分钟同刻或分钟末前0—3秒的同步累计量'
    # apply() may supply an exact fresh live quote while the observation store is
    # empty. Retain only that newly computed point after rechecking the clock.
    if samples is not None and not have_volume_samples and live is None:
        prior_stamp = _stamp(volume_row.get('current_time'))
        prior_info = volume_row.get('pair_intraday', {})
        if prior_stamp is not None and _session(prior_stamp) == _session(now) and 0 <= (boundary-prior_stamp).total_seconds() <= 3 and (now-prior_stamp).total_seconds() <= 30:
            numerator = prior_info.get('numerator')
            if _finite(numerator) and not volume_reason.startswith('缺') and _finite(volume_info['denominator']) and volume_info['denominator'] > 0:
                volume, volume_stamp = numerator / volume_info['denominator'], prior_stamp
                source_times = volume_row.get('current_source_times', {})
                volume_info.update(numerator=numerator, approximation=prior_stamp != boundary, boundary=boundary.isoformat())
                volume_reason = volume_row.get('current_reason', '')
    _publish(volume_row, volume, volume_stamp, volume_info, volume_reason, source_times=source_times,
             history=[dict(time=volume_stamp.isoformat(), value=float(volume))] if _finite(volume) else [])

    if samples is not None and not samples.empty:
        range_info, range_reason = _range_baseline(minute_data, left, right, category, price, metadata, dividends, now)
    else:
        range_info = dict(denominator=None, baseline_n=0, baseline_start=None, baseline_end=None)
        range_reason = '尚无同步HTTP采集样本；完整日终指标保留'
    range_info.update(numerator=None, scope='HTTP连续采集段；非全天振幅', approximation=False,
                      effective_h=None, ratio_source_time=None,
                      segment_start=segment[0][0].isoformat() if segment else None,
                      segment_end=segment[-1][0].isoformat() if segment else None, sample_n=len(segment))
    value, stamp, history, source_times = None, None, [], {}
    if segment:
        values = [item[1] for item in segment]
        range_info['numerator'] = max(values)-min(values)
        stamp = segment[-1][0]
        source_times = {s: str(segment[-1][2][s]['source_event_time']) for s in symbols}
        if len(segment) >= 2 and not range_reason:
            value = range_info['numerator'] / range_info['denominator']
            high, low = values[0], values[0]
            for i, (at, x, _) in enumerate(segment):
                high, low = max(high, x), min(low, x)
                if i:
                    history.append(dict(time=at.isoformat(), value=(high-low)/range_info['denominator']))
            range_reason = '最新连续同步HTTP合约对X极差 / 此前20完整交易日绝对TR中位数；非全天振幅'
        elif not range_reason:
            range_reason = '连续采集段不足2个不同source时间样本'
    elif not range_reason:
        range_reason = segment_reason
    _publish(range_row, value, stamp, range_info, range_reason, source_times=source_times, history=history)
    return rows
