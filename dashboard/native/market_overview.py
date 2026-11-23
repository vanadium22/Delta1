"""Latest observations and prior-session references, independent of research warmup.

Reads one frozen publication and one receipt cutoff. Never acquires data, repairs
history, changes a profile, or presents receipt time as the market source clock.
"""
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
import pandas as pd

from dashboard.marketdata.overview_basis import (calculate, FORMULA, input_token, load_dividends, dividend_record,
    historical_dividend, dividend_history, dividend_estimate_label, annual_min_days)
from dashboard.indicator_v6.sources import dates_between
from dashboard.marketdata.contract_reference import latest_contracts
from dashboard.marketdata.quote_quality import aligned_quotes, finite, quote_quality
from dashboard.marketdata.repository import ReferenceBook
from dashboard.session_clock import market_phase
from .instruments import UNDERLYINGS
from .overview_instruments import etfs, quote_registry


@lru_cache(maxsize=32)
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


def quote_card(symbol, name, root, live, daily, now, previous, *, finalized=None):
    phase=market_phase(now.to_pydatetime())
    reference_mode=phase['phase'] not in ('morning','lunch','afternoon')
    q = live.get(symbol) or {}
    source = timestamp(q.get('source_event_time'))
    receipt = timestamp(q.get('observed_at', q.get('received_at')))
    valid_clock = bool(source is not None and receipt is not None and receipt <= now and source <= now + pd.Timedelta(seconds=3))
    if finalized is None:
        history = daily_rows(daily.get(symbol))
    else:
        if symbol not in finalized:
            finalized[symbol] = daily_rows(daily.get(symbol))
        history = finalized[symbol]
    prior = history.get(previous, {})
    last_day = max(history, default=None)
    h = history.get(last_day, {})
    # A valid saved observation can still be stale. Display it with its own date;
    # do not let a later bad clock suppress a real completed historical close.
    use_quote = positive(q.get('close')) and valid_clock and (not h or source > pd.Timestamp(h['event_time']) or
        source==pd.Timestamp(h['event_time']) and not reference_mode)
    if use_quote and h and reference_mode and last_day>=str(source.tz_convert('Asia/Shanghai').date()):
        use_quote=False
    quality = quote_quality(q, now) if valid_clock else dict(usable=False, status='源时间缺失或倒置')
    if quality.get('usable') and not phase['continuous']:
        quality = dict(quality, usable=False, status='午休 / 缓存行情' if phase['phase']=='lunch' else '盘前盘后 / 缓存行情')
    price = q['close'] if use_quote else h.get('close')
    if use_quote:
        at = source.isoformat()
        kind = quality['status'] if quality['usable'] else ('盘前盘后快照 · ' if q.get('observation_mode')=='off_session_snapshot' else '缓存行情 · ') + source.tz_convert('Asia/Shanghai').strftime('%m-%d')
        base = q.get('prev_close') if positive(q.get('prev_close')) else None
        base_day = None
        base_reason = '源端昨收 yesterdayClosePrice；'+q.get('source_date_basis','源交易日期按接收日推定')
        quote_day = str(source.tz_convert('Asia/Shanghai').date())
        if base is None and quote_day == str(now.tz_convert('Asia/Shanghai').date()) and positive(prior.get('close')):
            base, base_day, base_reason = prior['close'], previous, '上一交易日已完成历史收盘'
        volume = q.get('volume_total')
    elif h:
        at = pd.Timestamp(h['event_time']).tz_convert('Asia/Shanghai').isoformat()
        kind = '昨日收盘' if last_day == previous else '历史收盘 · ' + last_day
        before = previous_session(last_day)
        base = history.get(before,{}).get('close')
        base = base if positive(base) else None
        base_day = before if base is not None else None
        base_reason = '收盘日的准确上一交易日历史收盘' if base is not None else '历史收盘缺准确前一交易日，不跳过缺口'
        volume = h.get('volume')
        quality = dict(usable=False, status=kind)
    else:
        at, kind, base, base_day, volume = None, '等待行情', None, None, None
        base_reason = '尚未收到有效报价和源端昨收'
        quality = dict(usable=False, status=kind)
    delta = float(price - base) if positive(price) and positive(base) else None
    historical_receipt=timestamp(h.get('fetched_at')) or timestamp(h.get('recorded_at'))
    amount=q.get('amount_cny') if use_quote else h.get('turnover') if finite(h.get('turnover')) else h.get('amount')
    return dict(symbol=symbol, name=name, root=root, price=price if positive(price) else None,
                change=delta, change_pct=100*delta/base if delta is not None else None,
                prev_close=base, prev_date=base_day, prev_reason=base_reason,
                yesterday_close=prior.get('close') if positive(prior.get('close')) else None,
                yesterday_date=previous if positive(prior.get('close')) else None,
                yesterday_open_interest=prior.get('open_interest') if finite(prior.get('open_interest')) and prior['open_interest']>=0 else None,
                yesterday_oi_date=previous if finite(prior.get('open_interest')) and prior['open_interest']>=0 else None,
                source_at=at, received_at=receipt.isoformat() if use_quote else historical_receipt.isoformat() if historical_receipt is not None else None,
                source_date_basis=q.get('source_date_basis','接收日推定，非交易所认证日期') if use_quote else '已完成日线交易日',
                display_kind='http_snapshot' if use_quote and q.get('observation_mode')=='off_session_snapshot' else 'observation' if use_quote else 'completed_daily' if h else 'missing',
                quality=quality, status=kind, volume=volume if finite(volume) else None,
                volume_unit='手' if symbol.endswith('.CFE') else '源单位' if use_quote else '手' if symbol in {v[0] for v in UNDERLYINGS.values()} else '份',
                open=q.get('open') if use_quote else h.get('open'),
                high=q.get('high') if use_quote else h.get('high'),
                low=q.get('low') if use_quote else h.get('low'),
                amount_cny=amount if finite(amount) and amount>=0 else None,
                series=[], reason=quality.get('reason', kind))


def observed_series(row, observations, now):
    return observed_series_many([row],observations,now).get(row['symbol'],[])


def observed_series_many(rows, observations, now):
    if observations.empty:
        return {}
    cards={r['symbol']:r for r in rows if r.get('source_at') and positive(r.get('prev_close'))}
    if not cards:
        return {}
    frame=observations.loc[observations.instrument_id.isin(cards),
                           ['instrument_id','source_event_time','observed_at','close']]
    if frame.empty:
        return {}
    sources, receipts = frame.source_event_time, frame.observed_at
    native_sources=isinstance(sources.dtype,pd.DatetimeTZDtype)
    if not native_sources:
        sources = sources.map(timestamp)
    source_clock = sources if native_sources else pd.to_datetime(sources, utc=True)
    receipt_clock = receipts if isinstance(receipts.dtype,pd.DatetimeTZDtype) else pd.to_datetime(receipts.map(timestamp), utc=True)
    local = source_clock.dt.tz_convert('Asia/Shanghai')
    pricing_dates={s:pd.Timestamp(r['source_at']).tz_convert('Asia/Shanghai').normalize() for s,r in cards.items()}
    minute = local.dt.hour*60+local.dt.minute
    am = minute.between(570,690)
    keep = (receipt_clock.le(now) & source_clock.le(now+pd.Timedelta(seconds=3))
            & local.dt.normalize().eq(frame.instrument_id.map(pricing_dates))
            & (receipt_clock-source_clock).dt.total_seconds().between(-3,30)
            & (am | minute.between(780,900)) & frame.close.map(positive))
    x = minute[keep]-(660-90*am[keep].astype(int)) + local[keep].dt.second/60
    symbols=frame.instrument_id[keep]
    changes = 100*(frame.close[keep]/symbols.map({s:r['prev_close'] for s,r in cards.items()})-1)
    if native_sources:
        labels={source:source.isoformat() for source in sources[keep].unique()}
        source_labels=sources[keep].map(labels)
    else:
        source_labels=sources[keep].map(lambda source:source.isoformat())
    grouped={}
    for symbol,x_value,change,source,morning in zip(symbols,x,changes,source_labels,am[keep]):
        # Keep the last representation of a duplicate source timestamp.
        grouped.setdefault(symbol,{})[source]=dict(x=float(x_value),value=float(change),source_at=source,
                                                  session='am' if morning else 'pm')
    return {symbol:[points[key] for key in sorted(points)] for symbol,points in grouped.items()}


def futures_values(row, live, daily, metadata, now,spot_row=None,*,dividends=None,observations=None,min_annual_days=1):
    symbol = row['symbol']; spot = UNDERLYINGS[row['root']][0]
    q, s = live.get(symbol), live.get(spot)
    ok, reason = aligned_quotes([q, s], now)
    phase=market_phase(now.to_pydatetime())
    if ok and not phase['continuous']:
        ok, reason = False, '午休，仅展示保存行情' if phase['phase']=='lunch' else '盘前盘后，仅展示保存行情或同日收盘参考'
    expiry = metadata.get(symbol, {}).get('expiry_date')
    day = str(now.tz_convert('Asia/Shanghai').date())
    known_days=(date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else None
    row.update(expiry=expiry, basis_points=None, raw_basis_points=None,log_basis_bp=None, annual_pct=None,dividend_points=None,
               percentile=None, percentile_samples=0, basis_reason=reason,
               percentile_reason='需要当前同步期现报价和此前20个完整交易日', basis_source_at=None,
               basis_future_price=None,basis_spot_price=None,basis_future_source_at=None,basis_spot_source_at=None,dividend_carried_forward=False,
               basis_kind=None,pricing_day=None,days=known_days,percentile_start=None,percentile_end=None,min_annual_days=min_annual_days)
    mode='realtime'
    at=max(pd.Timestamp(q['source_event_time']),pd.Timestamp(s['source_event_time'])) if ok else now
    if not ok:
        if phase['continuous']:return
        from .overview_pairing import reference_pair
        pair=reference_pair(symbol,spot,live,observations,daily,now)
        if not pair:return
        q,s=pair['future'],pair['spot'];day=pair['day'];at=pair['at'];mode=pair['mode']
        # The visible futures price and its derived basis use the same saved leg.
        prior=previous_session(day)
        prior_f=daily_rows(daily.get(symbol)).get(prior,{})
        prior_s=daily_rows(daily.get(spot)).get(prior,{})
        row.update(price=q['close'],source_at=pd.Timestamp(q.get('source_event_time',q.get('event_time'))).isoformat(),
            received_at=q.get('observed_at',q.get('received_at',q.get('fetched_at'))),
            display_kind=mode,status=('收盘参考 ' if mode=='completed_daily' else '缓存参考 ')+day,
            quality=dict(usable=False,status='收盘参考' if mode=='completed_daily' else '缓存参考'),
            prev_close=prior_f.get('close') if positive(prior_f.get('close')) else q.get('prev_close'),
            prev_date=prior,volume=q.get('volume_total',q.get('volume')),
            basis_prev_future=prior_f.get('close') if positive(prior_f.get('close')) else q.get('prev_close'),
            basis_prev_spot=prior_s.get('close') if positive(prior_s.get('close')) else s.get('prev_close'),
            basis_prev_day=prior,yesterday_date=prior,yesterday_close=prior_f.get('close'),
            open=q.get('open'),high=q.get('high'),low=q.get('low'),amount_cny=q.get('amount_cny',q.get('turnover',q.get('amount'))),
            source_date_basis=q.get('source_date_basis','保存报价的原源日期' if mode=='cached_pair' else '已完成日线交易日'))
        base=row.get('prev_close')
        row.update(change=q['close']-base if positive(base) else None,
            change_pct=100*(q['close']/base-1) if positive(base) else None)
    else:
        prior=previous_session(day)
        row.update(basis_prev_future=row.get('prev_close',q.get('prev_close')),
            basis_prev_spot=spot_row.get('prev_close') if spot_row else s.get('prev_close'),basis_prev_day=prior)
    t = (date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else None
    record=(historical_dividend(dividend_history(dividends,day,now),symbol,day) if mode=='completed_daily'
            else dividend_record(dividends,symbol,at));dividend=record.get('points')
    current=calculate(q.get('close'),s.get('close'),dividend,t,min_annual_days=min_annual_days)
    scenario=record
    row.update(basis_points=current['points'],raw_basis_points=q['close']-s['close'],
               annual_pct=current['annual_pct'], days=t,dividend_points=dividend,
               dividend_inherited_from=scenario.get('inherited_from'),dividend_source_contract=scenario.get('value_source_contract'),
               dividend_snapshot=scenario.get('source_snapshot'),dividend_version=getattr(dividends,'version',None),
               dividend_carried_forward=bool(scenario.get('source_snapshot') and scenario['source_snapshot']<day),
               dividend_file_sha256=record.get('file_sha256'),dividend_source_kind=record.get('source_kind'),
               dividend_estimated=record.get('estimated',False),dividend_interpolation=record.get('interpolation'),
               basis_source_at=at.isoformat(),
               basis_kind=mode,pricing_day=day,pricing_at=at.isoformat(),basis_future_price=q['close'],basis_spot_price=s['close'],
               basis_future_source_at=pd.Timestamp(q.get('source_event_time',q.get('event_time'))).isoformat(),
               basis_spot_source_at=pd.Timestamp(s.get('source_event_time',s.get('event_time'))).isoformat(),
               dividend_revision=record.get('revision'),dividend_effective_from=record.get('effective_from'),dividend_precision=record.get('precision'))
    row['basis_reason'] = (('收盘参考 ' if mode=='completed_daily' else '缓存参考 ')+day+' · ' if mode!='realtime' else '')+(FORMULA+f'；T<{min_annual_days}年化留空' if dividend is not None else record.get('reason') or '缺可用分红；保留原始点基差')
    estimate = dividend_estimate_label(scenario.get('inherited_from'), scenario.get('interpolation'))
    if estimate:row['basis_reason']+='；分红'+estimate
    if row['dividend_carried_forward']:row['basis_reason']+='；D来源 '+scenario['source_snapshot']+'，早于定价日'
    if t is None:row['basis_reason']+='；到期日缺失，年化留空'


class MarketOverviewEngine:
    def __init__(self, model):
        self.model = model
        self.daily_key = None
        self.daily = {}
        self.finalized = {}
        self.daily_errors=[]
        self.percentiles={}
        self.side_cache={}
        self.dividend_key=None;self.dividends=None
        self.requirement_cache={};self.dividend_versions={}
        self.reference_key=None
        self.reference_version=None
        from dashboard.marketdata.overview_dividends import DerivedCache,directory
        self.derived=DerivedCache(directory(model.config,model.local_root),writable=getattr(model,'overview_write_cache',False)) if hasattr(model,'local_root') else None

    def snapshot(self, *, now=None, equity_snapshot=None):
        from dashboard.refresh_evidence import begin, calculated
        model = self.model; trace = begin(model);min_days=annual_min_days(model.config)
        def check_stop():
            if getattr(model,'overview_stop',None) is not None and model.overview_stop.is_set():raise InterruptedError()
        check_stop();explicit_now=now is not None
        now = pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
        from dashboard.marketdata.overview_contributions import read_equities
        phase=market_phase(now.to_pydatetime())
        reference_mode=phase['phase'] not in ('morning','lunch','afternoon')
        day = str(now.tz_convert('Asia/Shanghai').date())
        from dashboard.marketdata.overview_sessions import latest_completed_session
        from dashboard.marketdata.overview_daily import read_day,directory
        try:completed=latest_completed_session(now.to_pydatetime())
        except ValueError:completed=None
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
        except (OSError,ValueError,KeyError,TypeError) as exc:
            repo, frozen, instruments = None, {}, {}
            errors.append('历史参考不可用，仅显示可用最新报价（'+type(exc).__name__+'）')
        try:
            reference_file = model.config.get('reference_file')
            stat = Path(reference_file).stat() if reference_file else None
            reference_key = (reference_file, stat.st_mtime_ns, stat.st_size, stat.st_ino) if stat else (None,)
            if reference_key != self.reference_key:
                reference = ReferenceBook(reference_file)
                self.metadata = latest_contracts(reference.data)
                self.reference_version = reference.version
                self.reference_key = reference_key
                self.requirement_cache.clear()
            metadata = self.metadata
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.reference_key = self.reference_version = None
            self.requirement_cache.clear()
            metadata = latest_contracts(ReferenceBook().data)
            errors.append('合约参考不可用（'+type(exc).__name__+'）')
        from dashboard.marketdata.overview_percentiles import requirements,prepare,apply,compile_windows,HISTORICAL_DIVIDEND_POLICY
        def required_history(target):
            key = (target,min_days)
            if key not in self.requirement_cache:
                if len(self.requirement_cache)>=8:
                    self.requirement_cache.clear()
                self.requirement_cache[key] = requirements(metadata,target,min_annual_days=min_days)
            return self.requirement_cache[key]
        pricing_day=completed if reference_mode else day
        try:required=required_history(pricing_day) if pricing_day else dict(rows=[])
        except ValueError:
            required=dict(rows=[]);errors.append('连续档位前60日交易日历不完整')
        try:registry_day=day if dates_between(day,day) else completed or day
        except ValueError:registry_day=day
        contracts = sorted((s for s, r in metadata.items() if r['listing_date'] <= registry_day <= r['expiry_date']),key=lambda s:(s[:2],metadata[s]['expiry_date']))
        if not contracts:
            errors.append('当前挂牌目录缺失，请在数据更新页核对合约参考')
        for s in contracts:
            instruments[s] = dict(asset_type='cn_index_future', market_region='CN')
        for s, _, _ in UNDERLYINGS.values():
            instruments[s] = dict(asset_type='cn_index', market_region='CN')
        registry=quote_registry(model.config,reference_data['data'],day)
        instruments.update(registry)
        token=input_token(model.config,metadata,pricing_day or day,getattr(model,'local_root',None))
        if token!=self.dividend_key:
            self.dividends=load_dividends(model.config,metadata,pricing_day or day,getattr(model,'local_root',None));self.dividend_key=token
        versions = {k:v['version'] for k,v in frozen.items()}
        symbols={*[v[0] for v in UNDERLYINGS.values()],*contracts,*registry,*(r['symbol'] for r in required['rows'])}
        symbol_key = tuple(sorted(symbols))
        side={}
        if completed and hasattr(model,'local_root'):
            for d in sorted({completed,previous_session(completed),*(r['day'] for r in required['rows'])}-{None}):
                path=directory(model.config,model.local_root)/'days'/(d+'.json')
                try:stat=path.stat();token=(str(path),stat.st_mtime_ns,stat.st_size,symbol_key)
                except OSError:token=(str(path),None,None,symbol_key)
                cached=self.side_cache.get(d,{})
                if cached.get('token')!=token:
                    value=read_day(model.config,model.local_root,d)
                    cached=dict(token=token,value={**value,'rows':{s:r for s,r in value.get('rows',{}).items() if s in symbols}})
                    self.side_cache[d]=cached
                side[d]=cached['value']
        key = (tuple(versions.items()), self.reference_version, completed,pricing_day,
            tuple((d,self.side_cache[d]['token']) for d in side),symbol_key,tuple(model.config.get('history_roots', ())),repo is not None,registry_day,min_days)
        if key != self.daily_key:
            self.daily = {}
            self.finalized = {}
            self.daily_errors=[]
            cutoff = (pd.Timestamp(completed, tz='Asia/Shanghai') + pd.Timedelta(hours=23, minutes=59, seconds=59)) if completed else now.normalize()-pd.Timedelta(seconds=1)
            for s in sorted(symbols):
                check_stop()
                if repo is None:
                    self.daily[s] = pd.DataFrame()
                else:
                    try:
                        self.daily[s] = repo.read_window(s, '1d', count=90, as_of=cutoff,
                            fields=('open','high','low','close','volume','turnover','open_interest'), frozen=frozen)
                    except (OSError,ValueError,KeyError,TypeError) as exc:
                        self.daily[s] = pd.DataFrame()
                        self.daily_errors.append('历史参考缺项 '+s+'（'+type(exc).__name__+'）；保留可用最新报价')
                additions=[dict(r,event_time=pd.Timestamp(r['source_at']),is_final=True,fetched_at=v.get('fetched_at'),
                                open_interest=r.get('oi'),turnover=r.get('amount')) for d,v in side.items() if (r:=v.get('rows',{}).get(s))]
                if additions:
                    from dashboard.marketdata.overview_daily import merge_daily
                    try:self.daily[s]=merge_daily(self.daily[s],additions)
                    except (OSError,ValueError,KeyError,TypeError) as exc:
                        self.daily_errors.append('补充日线缺项 '+s+'（'+type(exc).__name__+'）；保留其他有效输入')
            self.daily_key = key
            self.percentiles={};self.dividend_versions={}
        errors.extend(self.daily_errors)
        check_stop()
        # Cold history/dividend reads must not freeze the live receipt cutoff.
        if equity_snapshot is None:
            equity_snapshot=read_equities(model.config,model.local_root) if hasattr(model,'local_root') else {}
        if not explicit_now:
            now=pd.Timestamp.now(tz='UTC');phase=market_phase(now.to_pydatetime())
        live=model._live(instruments,now)
        if not phase['continuous'] and hasattr(model,'local_root'):
            from .latest_snapshot import load as load_snapshot
            for symbol,q in load_snapshot(model.local_root).get('quotes',{}).items():
                old=timestamp(live.get(symbol,{}).get('source_event_time'));source=timestamp(q.get('source_event_time'))
                if symbol in instruments and source is not None and (old is None or source>=old):live[symbol]=q
        model._overview_latest=live
        indices = [quote_card(s, name, root, live, self.daily, now, previous, finalized=self.finalized)
                   for root, (s, name, _) in UNDERLYINGS.items()]
        funds = []
        for info in etfs(model.config, reference_data['data'], day):
            row = quote_card(info['symbol'], info['name'], info['root'], live, self.daily, now, previous, finalized=self.finalized)
            row.update(underlying=info['underlying'], iopv=None, premium_bp=None, iopv_source_at=None,
                       iopv_id=info.get('iopv_id'), premium_reason='现有源尚无可核验IOPV字段或明确映射')
            if info.get('iopv_id'):
                a, b = live.get(row['symbol']), live.get(info['iopv_id'])
                ok, reason = aligned_quotes([a, b], now)
                row['premium_reason'] = reason
                if b and quote_quality(b, now)['usable'] and phase['continuous']:
                    row.update(iopv=b['close'], iopv_source_at=b['source_event_time'])
                if ok and phase['continuous'] and positive(b.get('close')):
                    row.update(iopv=b['close'], premium_bp=10000*(a['close']/b['close']-1),
                               iopv_source_at=b['source_event_time'], premium_reason='ETF与IOPV源时及接收时差均不超过3秒')
            funds.append(row)
        futures = []
        dated_dividends = {}
        for root, (_, name, _) in UNDERLYINGS.items():
            for slot, s in enumerate(s for s in contracts if s.startswith(root)):
                row = quote_card(s, name, root, live, self.daily, now, previous, finalized=self.finalized)
                row['slot'] = slot
                row['dividend_policy_version'] = HISTORICAL_DIVIDEND_POLICY
                try:
                    futures_values(row, live, self.daily, metadata, now,next(r for r in indices if r['root']==root),dividends=self.dividends,observations=model.live_rows,min_annual_days=min_days)
                except ValueError:
                    row.update(percentile=None, percentile_reason='交易日历缺失')
                target=row.get('pricing_day') or pricing_day
                history=None
                compiled=None
                if target:
                    try:
                        price_requirements = required_history(target)
                        if target not in dated_dividends:
                            dated_dividends[target] = dividend_history(self.dividends,target,now)
                        history_dividends = dated_dividends[target]
                        revision_key=(history_dividends.version,target)
                        if revision_key not in self.dividend_versions:
                            self.dividend_versions[revision_key]=(history_dividends.history_version(price_requirements['rows'])
                                if hasattr(history_dividends,'history_version') else history_dividends.version)
                        history_key=(root,slot,target,registry_day)
                        revision = self.dividend_versions[revision_key]
                        cached = self.percentiles.get(history_key)
                        if cached is None or cached[0] != revision:
                            prepared=prepare(root,slot,metadata,self.daily,target,dividends=history_dividends,
                                cache=self.derived,current_day=registry_day,min_annual_days=min_days,finalized=self.finalized)
                            self.percentiles[history_key]=(revision,prepared,compile_windows(prepared))
                        _,history,compiled=self.percentiles[history_key]
                    except ValueError:pass
                apply(row,history,compiled=compiled)
                futures.append(row)
        if self.derived is not None:
            check_stop()
            try:self.derived.flush()
            except (OSError,ValueError) as exc:errors.append('历史计算缓存未保存（'+type(exc).__name__+'）')
        observations = model.live_rows
        chart_rows = [*indices, *funds, *futures]
        check_stop()
        curves = observed_series_many(chart_rows, observations, now)
        for row in chart_rows:
            row['series'] = curves.get(row['symbol'],[])
        dividend_dates=[r.get('source_business_date') for r in getattr(self.dividends,'records',[])]
        dividend_dates += [r.get('dividend_snapshot') for r in futures]
        latest_dividend=max((d for d in dividend_dates if isinstance(d,str) and len(d)==10 and d<=day),default=None)
        state = dict(as_of=now.isoformat(), versions=versions, selection=dict(overview_slot=0), overview=[], entities=[],
                     market_overview=dict(schema='market-overview-v1', indices=indices, etfs=funds, futures=futures,
                                          previous_session=previous,completed_session=completed,market_session=phase, errors=errors, source_date_basis='每值保留日期依据',
                                          basis_formula=FORMULA,min_annual_days=min_days,dividend_version=self.dividends.version,dividend_reason=self.dividends.reason,dividend_latest_business_day=latest_dividend,
                                          dividend_policy=self.dividends.info.get('historical_policy'),slot_day=registry_day),
                     research_pages=None)
        enrich(model, state['market_overview'], reference_data, now,equity_snapshot=equity_snapshot)
        from .futures_overview import details
        state['market_overview']['futures_details']=details(futures,indices,live,observations,now,dividends=self.dividends)
        from dashboard.marketdata.overview_display_cache import preserve
        preserve(model,state['market_overview'],now)
        from dashboard.marketdata.overview_market_sizes import build as market_sizes
        state['market_overview']['market_sizes']=market_sizes(reference_data['data'],state['market_overview']['futures'],self.daily,live,now,metadata,completed)
        request=getattr(model,'indicator_analysis_request',None)
        if request:
            from .indicator_analysis import IndicatorAnalysisEngine
            if not hasattr(self,'indicator_analysis'):self.indicator_analysis=IndicatorAnalysisEngine(model)
            try:
                state['indicator_analysis']=self.indicator_analysis.snapshot(dict(request),now=now,completed=completed,
                    metadata=metadata,dividends=self.dividends,repo=repo,frozen=frozen,refresh_clock=not explicit_now)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                state['indicator_analysis']=dict(selection=dict(request),error='本地日线/日历/映射缺项（'+type(exc).__name__+'）')
        return calculated(model, state, trace)


def capture(model):
    if not hasattr(model, 'market_overview_engine'):
        model.market_overview_engine = MarketOverviewEngine(model)
    return model.market_overview_engine.snapshot()
