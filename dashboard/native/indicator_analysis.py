"""Bounded local reader for the indicator page, run on the overview worker."""
from collections import OrderedDict

import pandas as pd

from dashboard.indicator_v6.sources import SPOTS
from dashboard.marketdata.dividends import digest
from dashboard.marketdata.indicator_analysis import SERIES, plan, historical, display, point, values
from dashboard.marketdata.overview_daily import directory, read_day, merge_daily
from dashboard.marketdata.overview_percentiles import final_rows
from dashboard.marketdata.quote_quality import aligned_quotes
from dashboard.native.continuous import slot_map
from dashboard.session_clock import market_phase


class IndicatorAnalysisEngine:
    def __init__(self, model):
        self.model = model
        self.cache = OrderedDict()
        self.history_reads = 0

    def stopped(self):
        event = getattr(self.model, 'overview_stop', None)
        return event is not None and event.is_set()

    def snapshot(self, request, *, now, completed, metadata, dividends, repo, frozen, refresh_clock=False, _reference_day=None):
        phase = market_phase(now.to_pydatetime())
        continuous = phase['continuous']
        day = _reference_day or (str(now.tz_convert('Asia/Shanghai').date()) if continuous else completed)
        if not day:
            raise ValueError('缺少已核验完成交易日')
        planned = plan(day, request, metadata)
        paths = [directory(self.model.config, self.model.local_root)/'days'/(d+'.json') for d in planned['days'] if d <= completed]
        signatures = []
        for path in paths:
            if self.stopped():
                raise InterruptedError()
            try:
                info = path.stat()
                signatures.append((str(path), info.st_mtime_ns, info.st_size))
            except OSError:
                signatures.append((str(path), None, None))
        key = digest(dict(selection=planned['selection'], day=day, completed=completed,
                          versions={k:v['version'] for k,v in frozen.items()}, side=signatures,
                          metadata={s:r for s,r in metadata.items() if s.startswith(request['root'])},
                          dividend=getattr(dividends,'version',None), roots=self.model.config.get('history_roots',[]),
                          repo_available=repo is not None))
        cached = self.cache.get(key)
        cache_hit = cached is not None
        if cached is None:
            tables, errors = {}, []
            symbols = sorted({r['symbol'] for r in planned['rows']})
            sides = {p.stem:read_day(self.model.config, self.model.local_root, p.stem) for p in paths}
            cutoff = pd.Timestamp(completed+'T23:59:59+08:00')
            for symbol in symbols:
                if self.stopped():
                    raise InterruptedError()
                frame = pd.DataFrame()
                if repo is not None:
                    try:
                        frame = repo.read_window(symbol, '1d', count=len(planned['days'])+2,
                                                 as_of=cutoff, fields=('close',), frozen=frozen)
                        self.history_reads += 1
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        errors.append(dict(symbol=symbol, error_type=type(exc).__name__))
                additions = [dict(r, event_time=pd.Timestamp(r['source_at'])) for v in sides.values()
                             if (r := v.get('rows',{}).get(symbol))]
                tables[symbol] = {d:r for d,r in final_rows(merge_daily(frame, additions)).items()
                                  if planned['days'][0] <= d <= completed}
            cached = dict(history=historical(planned, metadata, tables, dividends, stop=self.stopped), tables=tables, errors=errors)
            self.cache[key] = cached
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        if self.stopped():
            raise InterruptedError()
        if continuous:
            if refresh_clock:
                now = pd.Timestamp.now(tz='UTC')
            current = self.current(planned, metadata, dividends, now)
        else:
            mapping = planned['mappings'][day]['mapping']
            if not mapping:
                current = {k:point(day,reason='mapping_missing') for k in SERIES}
            else:
                rows = {s:table.get(day,{}) for s,table in cached['tables'].items()}
                prices = {s:r.get('close') for s,r in rows.items()}
                prices['_http_session_inferred_symbols'] = [s for s,r in rows.items() if r.get('source_date_basis')=='corroborated_live_session']
                current = values(day,planned['selection'],mapping,metadata,prices,dividends,current=True,
                                 at=day+'T15:00:00+08:00',source_at=day+'T15:00:00+08:00')
                for item in current.values():
                    if item['value'] is None:item['source_at']=None
            # An unavailable completed-day price may fall back to a real older
            # common close. Re-plan the whole reference window for that day;
            # missing current D, mapping or expiry never triggers substitution.
            price_missing={'index_close_missing','future_close_missing'}
            if (_reference_day is None and not any(v['value'] is not None for v in current.values()) and
                    any(v.get('reason') in price_missing for v in current.values()) and
                    all(v.get('reason') in price_missing for v in current.values())):
                candidates=sorted({r['day'] for rows in cached['history'].values() for r in rows
                                   if r['day']<day and r.get('value') is not None},reverse=True)
                if candidates:
                    return self.snapshot(request,now=now,completed=completed,metadata=metadata,dividends=dividends,
                        repo=repo,frozen=frozen,refresh_clock=False,_reference_day=candidates[0])
        output = display(planned, cached['history'], current)
        output.update(mode='realtime' if continuous else 'completed_daily', as_of=now.isoformat(),
                      completed_target=completed,reference_fallback=bool(_reference_day and _reference_day!=completed),
                      version=key, cache_hit=cache_hit, history_reads=self.history_reads, errors=cached['errors'])
        return output

    def current(self, planned, metadata, dividends, now):
        request = planned['selection'];day = planned['pricing_day']
        mapping, error = slot_map(metadata, request['root'], day)
        if error:
            return {k:point(day, reason='mapping_missing') for k in SERIES}
        live = getattr(self.model, '_overview_latest', {})
        output = {}
        for keys, slots in [(('raw','adjusted','annual'), [request['slot']]),
                            (('calendar_03_02',), [3,2]), (('calendar_02_01',), [2,1])]:
            symbols = [mapping[f"{request['root']}0{s}.CFE"] for s in slots]
            codes = [SPOTS[request['root']], *symbols]
            quotes = [live.get(s) for s in codes]
            ok, reason = aligned_quotes(quotes, now)
            if not market_phase(now.to_pydatetime())['continuous']:
                ok, reason = False, '当前已离开连续交易时段，等待切换收盘参考'
            if ok:
                times = [pd.Timestamp(q['source_event_time']) for q in quotes]
                if any(str(t.tz_convert('Asia/Shanghai').date()) != day for t in times):
                    ok, reason = False, '实时两腿定价日不一致'
            if not ok:
                for key in keys:
                    output[key] = point(day, symbols, reason=reason)
                continue
            at = max(times)
            prices = {s:q['close'] for s,q in zip(codes,quotes)}
            calculated = values(day, request, mapping, metadata, prices, dividends, current=True,
                                at=at, source_at=at.isoformat())
            for key in keys:
                output[key] = calculated[key]
                output[key]['source_times'] = {s:q['source_event_time'] for s,q in zip(codes,quotes)}
                output[key]['source_date_basis'] = [q.get('source_date_basis') for q in quotes]
        return output
