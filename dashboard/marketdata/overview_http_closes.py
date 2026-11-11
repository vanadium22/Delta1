"""Promote explicitly dated HTTP previous closes into the overview daily cache.

The existing network owner calls this module; it never prepares a VPN, loads
credentials, queries historical HTTP dates, or uses receipt dates as source dates.
Only the current source session's exact previous trading day may be filled.
"""
from datetime import date
import re
import uuid

import pandas as pd

from index_strategy.instant_dld.quotes import price_number,source_time
from index_strategy.instant_dld.raw_store import publish_raw_batch
from .bars import _atomic_bytes,_json_bytes
from .overview_daily import directory,read_day,publish_day
from .overview_reference import ROOTS
from .overview_sessions import latest_completed_session

DATE_FIELDS=('tradeDate','tradingDate','tradingDay')


def _clock(value=None):
    stamp=pd.Timestamp(value if value is not None else pd.Timestamp.now(tz='Asia/Shanghai'))
    if pd.isna(stamp) or stamp.tzinfo is None:raise ValueError('aware_clock_required')
    return stamp.tz_convert('Asia/Shanghai')


def _source_day(quote):
    days=[]
    for key in DATE_FIELDS:
        value=quote.get(key)
        if value is None:continue
        text=str(value)
        if re.fullmatch(r'\d{8}',text):text=text[:4]+'-'+text[4:6]+'-'+text[6:]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',text):raise ValueError('invalid_source_trade_date')
        try:date.fromisoformat(text)
        except ValueError:raise ValueError('invalid_source_trade_date') from None
        days.append(text)
    if not days:raise ValueError('source_trade_date_missing')
    if len(set(days))!=1:raise ValueError('source_trade_date_conflict')
    return days[0]


def _session(clock):
    from dashboard.indicator_v6.sources import dates_between
    from dashboard.native.market_overview import previous_session
    today=str(clock.date())
    if not dates_between(today,today):raise ValueError('not_a_trading_day')
    target=previous_session(today)
    if target is None or target>latest_completed_session(clock.to_pydatetime()):raise ValueError('previous_session_not_completed')
    return today,target


def _identities(metadata,today,target):
    from dashboard.native.continuous import slot_map
    result=set(ROOTS.values())
    for root in ROOTS:
        current,_=slot_map(metadata,root,today)
        previous,_=slot_map(metadata,root,target)
        # New listings have no previous close for a day before their listing.
        result.update(set(current.values())&set(previous.values()))
    return result


def _save(config,local_root,value):
    _atomic_bytes(directory(config,local_root)/'http_previous_close/status.json',_json_bytes(value))
    return value


def status(config,local_root):
    """Read-only safe evidence; no raw response, arbitrary strings or secrets."""
    import json
    try:
        value=json.loads((directory(config,local_root)/'http_previous_close/status.json').read_text(encoding='utf8'))
        return safe_status(value) if isinstance(value,dict) and value.get('schema')=='overview-http-previous-close-v1' else {}
    except (OSError,ValueError,TypeError):return {}


def safe_status(value):
    if not isinstance(value,dict):return {}
    result={k:v for k,v in value.items() if k in ('schema','status','target','inserted','already_present','examined',
        'source_trade_dates','date_policy','received_at','updated_at','reason','error_type','network_requested','maintenance_target')}
    result['rejected']=[{k:r[k] for k in ('symbol','reason') if k in r}
        for r in value.get('rejected',[])[:20] if isinstance(r,dict)]
    return result


def ingest(record,config,local_root,metadata,*,now=None,target=None,raw_root=None,raw_reference=None,wanted=None,stop=lambda:False):
    """Fill absent prices only. Keep HTTP date/identity/raw evidence on every row.

    No current OI, OHLC, settlement price or calendar-inferred date is copied into
    the prior day's close. One bad quote leaves other independently valid legs usable.
    """
    clock=_clock(now)
    value=dict(schema='overview-http-previous-close-v1',status='unavailable',target=target,
        inserted=0,already_present=0,examined=0,rejected=[],source_trade_dates=[],
        date_policy='explicit_source_trade_date_only',updated_at=clock.isoformat())
    try:today,expected=_session(clock)
    except ValueError as exc:
        value.update(status='not_applicable',reason=str(exc));return _save(config,local_root,value)
    if target is not None and target!=expected:
        value.update(status='not_applicable',reason='target_not_latest_previous_session');return _save(config,local_root,value)
    value['target']=expected
    try:
        received=_clock(record.get('received_at')) if record.get('received_at') else None
        if received is None or not -3<=(clock-received).total_seconds()<=60:raise ValueError('receipt_not_current')
    except (ValueError,TypeError):
        value.update(reason='receipt_not_current');return _save(config,local_root,value)
    value['received_at']=received.isoformat()
    if record.get('status') not in ('success','partial'):
        value['reason']='http_response_unavailable';return _save(config,local_root,value)
    payload=record.get('source_response',record.get('response'))
    data=payload.get('data') if isinstance(payload,dict) else None
    if not isinstance(data,dict):
        value['reason']='invalid_response';return _save(config,local_root,value)
    allowed=_identities(metadata,today,expected)
    requested=set(record.get('requested_symbols',record.get('symbols',[])))
    candidates=sorted(requested if wanted is None else requested&set(wanted))
    saved=read_day(config,local_root,expected).get('rows',{})
    rows={};capture_id=uuid.uuid4().hex
    for symbol in candidates:
        # ETF/stock prev-close adjustment conventions are outside this policy.
        if symbol not in ROOTS.values() and not symbol.endswith('.CFE'):continue
        value['examined']+=1
        try:
            if symbol not in allowed:raise ValueError('not_verified_actual_contract')
            quote=data.get(symbol)
            if not isinstance(quote,dict):raise ValueError('quote_missing')
            if quote.get('securityId')!=symbol:raise ValueError('security_id_mismatch')
            source_day=_source_day(quote)
            if source_day!=today:raise ValueError('source_trade_date_not_current')
            market_time=source_time(quote.get('quoteTimestamp'))
            if market_time is None:raise ValueError('source_time_missing')
            if pd.Timestamp(source_day+'T'+market_time+'+08:00')>received+pd.Timedelta(seconds=3):
                raise ValueError('source_time_in_future')
            close=price_number(quote.get('yesterdayClosePrice'))
            if close is None:raise ValueError('previous_close_invalid')
            if source_day not in value['source_trade_dates']:value['source_trade_dates'].append(source_day)
            if symbol in saved:
                value['already_present']+=1;continue
            ref=metadata.get(symbol,{})
            rows[symbol]=dict(symbol=symbol,trade_date=expected,close=close,is_final=True,
                source_at=expected+'T15:00:00+08:00',source='HTTP yesterdayClosePrice',
                source_at_basis='completed session close label; observed in next-session previous-close field',
                acquisition='http_previous_close',http_capture_id=capture_id,
                source_trade_date=source_day,source_quote_time=market_time,received_at=received.isoformat(),
                date_evidence_fields=[key for key in DATE_FIELDS if quote.get(key) is not None],
                source_security_id=symbol,listing_date=ref.get('listing_date'),expiry_date=ref.get('expiry_date'),
                open=None,high=None,low=None,volume=None,amount=None,oi=None,
                units={'close':'index_point'},unit_factors={})
        except ValueError as exc:value['rejected'].append(dict(symbol=symbol,reason=str(exc)))
    if rows and not stop():
        try:
            if raw_reference is None:
                raw_root=directory(config,local_root)/'http_previous_close'
                raw_reference=publish_raw_batch(raw_root,capture_id,record)
            evidence={key:raw_reference.get(key) for key in ('path','sha256','body_sha256','body_representation')}
            for row in rows.values():row['raw_response']=dict(root=str(raw_root),**evidence)
            published=publish_day(config,local_root,expected,rows,missing_only=True)
            value['inserted']=sum(published.get('rows',{}).get(s,{}).get('http_capture_id')==capture_id for s in rows)
        except (OSError,ValueError,TypeError) as exc:
            value.update(status='publication_failed',reason='daily_cache_write_failed',error_type=type(exc).__name__)
            return _save(config,local_root,value)
    value['status']='cancelled' if stop() else 'saved' if value['inserted'] else 'already_available' if value['already_present'] else 'no_verified_closes'
    return _save(config,local_root,value)


def collect(config,local_root,target,metadata,*,jobs,now=None,client_factory=None,stop=lambda:False):
    """One bounded HTTP attempt before DDB; caller already holds network lease."""
    clock=_clock(now)
    value=dict(schema='overview-http-previous-close-v1',status='not_needed',target=target,maintenance_target=target,inserted=0,
        updated_at=clock.isoformat(),date_policy='explicit_source_trade_date_only',network_requested=False)
    try:today,expected=_session(clock)
    except ValueError as exc:
        value.update(status='not_applicable',reason=str(exc));return _save(config,local_root,value)
    if expected>target:
        value.update(status='not_applicable',reason='previous_session_after_maintenance_target');return _save(config,local_root,value)
    value['target']=expected
    saved=read_day(config,local_root,expected).get('rows',{})
    allowed=_identities(metadata,today,expected)
    symbols=sorted({s for job in jobs if job['day']==expected and job['asset'] in ('index','future')
                    for s in job['symbols'] if s in allowed and s not in saved})
    if not symbols or stop():
        if stop():value['status']='cancelled'
        return _save(config,local_root,value)
    from index_strategy.instant_dld.client import MarketDataClient
    client=None
    try:
        client=(client_factory or MarketDataClient)(connect_timeout=1,read_timeout=2)
        record=client.fetch(symbols)
        record.update(symbols=symbols,requested_symbols=symbols)
        result=ingest(record,config,local_root,metadata,now=clock,target=expected,wanted=symbols,stop=stop)
        result.update(network_requested=True,maintenance_target=target)
        return _save(config,local_root,result)
    except Exception as exc:
        value.update(status='unavailable',reason='http_request_failed',network_requested=True,error_type=type(exc).__name__)
        return _save(config,local_root,value)
    finally:
        if client is not None:
            try:client.close()
            except Exception:pass
