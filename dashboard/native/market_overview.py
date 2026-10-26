"""Latest observations and prior-session references, independent of research warmup.

Reads one frozen publication and one receipt cutoff. Never acquires data, repairs
history, changes a profile, or presents receipt time as the market source clock.
"""
from datetime import date, timedelta
import pandas as pd

from dashboard.indicator_v6.core import basis, raw, statistic
from dashboard.indicator_v6.sources import dates_between
from dashboard.marketdata.contract_reference import latest_contracts
from dashboard.marketdata.quote_quality import aligned_quotes, finite, quote_quality
from dashboard.marketdata.repository import ReferenceBook
from dashboard.session_clock import session_policy
from .instruments import UNDERLYINGS
from .overview_instruments import etfs, quote_registry


def previous_session(day):
    days = dates_between(str(date.fromisoformat(day) - timedelta(days=35)), day)
    return next((d for d in reversed(days) if d < day), None)


def timestamp(value):
    try:
        t = pd.Timestamp(value)
        return t if not pd.isna(t) and t.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def positive(value):
    return finite(value) and not isinstance(value, bool) and value > 0


def daily_rows(frame):
    if frame is None or frame.empty:
        return {}
    return {str(r['trade_date'])[:10]: r for r in frame.to_dict('records') if r.get('is_final') == True}


def quote_card(symbol, name, root, live, daily, now, previous):
    q = live.get(symbol) or {}
    source = timestamp(q.get('source_event_time'))
    receipt = timestamp(q.get('observed_at', q.get('received_at')))
    valid_clock = bool(source is not None and receipt is not None and receipt <= now and source <= now + pd.Timedelta(seconds=3))
    history = daily_rows(daily.get(symbol))
    prior = history.get(previous, {})
    last_day = max(history, default=None)
    h = history.get(last_day, {})
    # A valid saved observation can still be stale. Display it with its own date;
    # do not let a later bad clock suppress a real completed historical close.
    use_quote = positive(q.get('close')) and valid_clock and (not h or source >= pd.Timestamp(h['event_time']))
    quality = quote_quality(q, now) if valid_clock else dict(usable=False, status='源时间缺失或倒置')
    if quality.get('usable') and not session_policy(now.to_pydatetime())['allowed']:
        quality = dict(quality, usable=False, status='休市 / 缓存行情')
    price = q['close'] if use_quote else h.get('close')
    if use_quote:
        at = source.isoformat()
        kind = quality['status'] if quality['usable'] else '缓存行情 · ' + source.tz_convert('Asia/Shanghai').strftime('%m-%d')
        base = q.get('prev_close') if positive(q.get('prev_close')) else None
        base_day = None
        base_reason = '源端昨收 yesterdayClosePrice；源交易日期按接收日推定'
        quote_day = str(source.tz_convert('Asia/Shanghai').date())
        if base is None and quote_day == str(now.tz_convert('Asia/Shanghai').date()) and positive(prior.get('close')):
            base, base_day, base_reason = prior['close'], previous, '上一交易日已完成历史收盘'
        volume = q.get('volume_total')
    elif h:
        at = str(h['event_time'])
        kind = '昨日收盘' if last_day == previous else '历史收盘 · ' + last_day
        # Do not relabel a multi-day history gap as yesterday's reference.
        base, base_day, base_reason = None, None, '仅有历史收盘，缺同日源端昨收'
        volume = h.get('volume')
        quality = dict(usable=False, status=kind)
    else:
        at, kind, base, base_day, volume = None, '等待行情', None, None, None
        base_reason = '尚未收到有效报价和源端昨收'
        quality = dict(usable=False, status=kind)
    delta = float(price - base) if positive(price) and positive(base) else None
    return dict(symbol=symbol, name=name, root=root, price=price if positive(price) else None,
                change=delta, change_pct=100*delta/base if delta is not None else None,
                prev_close=base, prev_date=base_day, prev_reason=base_reason,
                yesterday_close=prior.get('close') if positive(prior.get('close')) else None,
                yesterday_date=previous if positive(prior.get('close')) else None,
                source_at=at, received_at=receipt.isoformat() if use_quote else None,
                source_date_basis='接收日推定，非交易所认证日期' if use_quote else '历史交易日',
                quality=quality, status=kind, volume=volume if finite(volume) else None,
                volume_unit='源单位' if not symbol.endswith('.CFE') else '手',
                open=q.get('open') if use_quote else h.get('open'),
                high=q.get('high') if use_quote else h.get('high'),
                low=q.get('low') if use_quote else h.get('low'),
                series=[], reason=quality.get('reason', kind))


def observed_series(row, observations, now):
    if observations.empty or not row.get('source_at') or not positive(row.get('prev_close')):
        return []
    day = str(pd.Timestamp(row['source_at']).tz_convert('Asia/Shanghai').date())
    frame = observations[observations.instrument_id.eq(row['symbol']) & observations.observed_at.le(now)]
    result = []
    for q in frame.to_dict('records'):
        s, r = timestamp(q.get('source_event_time')), timestamp(q.get('observed_at'))
        if s is None or r is None or s > now + pd.Timedelta(seconds=3) or str(s.tz_convert('Asia/Shanghai').date()) != day:
            continue
        if not positive(q.get('close')) or not -3 <= (r-s).total_seconds() <= 30:
            continue
        local = s.tz_convert('Asia/Shanghai')
        m = local.hour*60 + local.minute
        if not (570 <= m <= 690 or 780 <= m <= 900):
            continue
        x = (m-570 if m <= 690 else m-660) + local.second/60
        result.append(dict(x=x, value=100*(q['close']/row['prev_close']-1), source_at=s.isoformat(),
                           session='am' if m <= 690 else 'pm'))
    # Duplicate source snapshots are one observation, not evidence of activity.
    return list({p['source_at']:p for p in sorted(result, key=lambda p:p['source_at'])}.values())


def futures_values(row, live, daily, metadata, now):
    symbol = row['symbol']; spot = UNDERLYINGS[row['root']][0]
    q, s = live.get(symbol), live.get(spot)
    ok, reason = aligned_quotes([q, s], now)
    if ok and not session_policy(now.to_pydatetime())['allowed']:
        ok, reason = False, '休市，仅展示保存行情'
    expiry = metadata.get(symbol, {}).get('expiry_date')
    row.update(expiry=expiry, basis_points=None, log_basis_bp=None, annual_pct=None,
               percentile=None, percentile_samples=0, basis_reason=reason,
               percentile_reason='需要当前同步期现报价和此前20个完整交易日', basis_source_at=None)
    if not ok:
        return
    day = str(now.tz_convert('Asia/Shanghai').date())
    t = (date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else None
    current = basis(raw(q.get('close'), 'price'), raw(s.get('close'), 'price'), t)
    row.update(basis_points=current['points'].value, log_basis_bp=current['b'].value,
               annual_pct=current['a'].value, days=t,
               basis_source_at=max(pd.Timestamp(q['source_event_time']), pd.Timestamp(s['source_event_time'])).isoformat())
    row['basis_reason'] = '第六版A01：未调整对数基差；年化T<5留空' if t is not None else '到期日缺失，年化留空'
    frows, srows = daily_rows(daily.get(symbol)), daily_rows(daily.get(spot))
    days = dates_between(str(date.fromisoformat(day)-timedelta(days=60)), day)
    days = [d for d in days if d < day][-20:]
    history = []
    for d in days:
        f, s = frows.get(d, {}), srows.get(d, {})
        history.append(basis(raw(f.get('close'), 'price'), raw(s.get('close'), 'price'),
                             (date.fromisoformat(expiry)-date.fromisoformat(d)).days if expiry else None)['b'])
    row['percentile_samples'] = sum(v.value is not None for v in history)
    p, _ = statistic([*history, current['b']], len(history))
    row['percentile'] = p.value
    row['percentile_reason'] = ('第六版A02：当前未调整对数基差相对自身此前20交易日的半权分位；排除当前日' if p.value is not None else
                                '此前20个交易日缺少同步期现收盘；不拼连续合约、不跳过缺口')
    row['percentile_start'] = days[0] if days else None
    row['percentile_end'] = days[-1] if days else None


class MarketOverviewEngine:
    def __init__(self, model):
        self.model = model
        self.daily_key = None
        self.daily = {}

    def snapshot(self, *, now=None):
        from dashboard.refresh_evidence import begin, calculated
        model = self.model; trace = begin(model)
        now = pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
        day = str(now.tz_convert('Asia/Shanghai').date())
        from .overview_details import load_reference, enrich
        reference_data = load_reference(model, now)
        errors = []
        try:
            previous = previous_session(day)
        except ValueError:
            previous = None; errors.append('交易日历缺失，昨日参照与分位暂不可用')
        try:
            repo = model.configure_repository(False)
            frozen = repo.freeze()
            instruments = repo.symbols(frozen)
        except (OSError,ValueError) as exc:
            repo, frozen, instruments = None, {}, {}
            errors.append('历史参考不可用，仅显示可用最新报价（'+type(exc).__name__+'）')
        try:
            reference = ReferenceBook(model.config.get('reference_file'))
        except (OSError,ValueError) as exc:
            reference = ReferenceBook()
            errors.append('合约参考不可用（'+type(exc).__name__+'）')
        metadata = latest_contracts(reference.data)
        contracts = sorted(s for s, r in metadata.items() if r['listing_date'] <= day <= r['expiry_date'])
        if not contracts:
            errors.append('当前挂牌目录缺失，请在数据更新页核对合约参考')
        for s in contracts:
            instruments[s] = dict(asset_type='cn_index_future', market_region='CN')
        for s, _, _ in UNDERLYINGS.values():
            instruments[s] = dict(asset_type='cn_index', market_region='CN')
        instruments.update(quote_registry(model.config, reference_data['data'], day))
        live = model._live(instruments, now)
        model._overview_latest = live
        versions = {k:v['version'] for k,v in frozen.items()}
        key = (tuple(versions.items()), reference.version, previous, tuple(model.config.get('history_roots', ())),repo is not None)
        if key != self.daily_key:
            self.daily = {}
            cutoff = (pd.Timestamp(previous, tz='Asia/Shanghai') + pd.Timedelta(hours=23, minutes=59, seconds=59)) if previous else now.normalize()-pd.Timedelta(seconds=1)
            for s in [*[v[0] for v in UNDERLYINGS.values()], *contracts]:
                if repo is None:
                    self.daily[s] = pd.DataFrame();continue
                try:
                    self.daily[s] = repo.read_window(s, '1d', count=25, as_of=cutoff,
                        fields=('open','high','low','close','volume'), frozen=frozen)
                except ValueError:
                    self.daily[s] = pd.DataFrame()
            self.daily_key = key
        indices = [quote_card(s, name, root, live, self.daily, now, previous)
                   for root, (s, name, _) in UNDERLYINGS.items()]
        funds = []
        for info in etfs(model.config, reference_data['data'], day):
            row = quote_card(info['symbol'], info['name'], info['root'], live, self.daily, now, previous)
            row.update(underlying=info['underlying'], iopv=None, premium_bp=None, iopv_source_at=None,
                       iopv_id=info.get('iopv_id'), premium_reason='现有源尚无可核验IOPV字段或明确映射')
            if info.get('iopv_id'):
                a, b = live.get(row['symbol']), live.get(info['iopv_id'])
                ok, reason = aligned_quotes([a, b], now)
                row['premium_reason'] = reason
                if b and quote_quality(b, now)['usable'] and session_policy(now.to_pydatetime())['allowed']:
                    row.update(iopv=b['close'], iopv_source_at=b['source_event_time'])
                if ok and session_policy(now.to_pydatetime())['allowed'] and positive(b.get('close')):
                    row.update(iopv=b['close'], premium_bp=10000*(a['close']/b['close']-1),
                               iopv_source_at=b['source_event_time'], premium_reason='ETF与IOPV源时及接收时差均不超过3秒')
            funds.append(row)
        futures = []
        for root, (_, name, _) in UNDERLYINGS.items():
            for slot, s in enumerate(s for s in contracts if s.startswith(root)):
                row = quote_card(s, name, root, live, self.daily, now, previous)
                row['slot'] = slot
                try:
                    futures_values(row, live, self.daily, metadata, now)
                except ValueError:
                    row.update(percentile=None, percentile_reason='交易日历缺失')
                futures.append(row)
        observations = model.live_rows
        for row in [*indices, *funds, *futures]:
            row['series'] = observed_series(row, observations, now)
        state = dict(as_of=now.isoformat(), versions=versions, selection=dict(overview_slot=0), overview=[], entities=[],
                     market_overview=dict(schema='market-overview-v1', indices=indices, etfs=funds, futures=futures,
                                          previous_session=previous, errors=errors, source_date_basis='接收日推定'),
                     research_pages=None)
        enrich(model, state['market_overview'], reference_data, now)
        return calculated(model, state, trace)


def capture(model):
    if not hasattr(model, 'market_overview_engine'):
        model.market_overview_engine = MarketOverviewEngine(model)
    return model.market_overview_engine.snapshot()
