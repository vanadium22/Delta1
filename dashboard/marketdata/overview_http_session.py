"""Corroborate a live daytime HTTP session; never certify an exchange trade date.

The caller owns the App network lease. Time-only quotes need two independently
archived, advancing market observations before their previous close can be dated.
"""
import hashlib
import json
from pathlib import Path

import pandas as pd

from index_strategy.instant_dld.quotes import price_number,number
from .bars import _atomic_bytes,_json_bytes
from .overview_daily import directory

SCHEMA='overview-http-session-v1'


class SessionBook:
    def __init__(self,config,local_root,day):
        self.path=directory(config,local_root)/'http_previous_close/session_evidence.json'
        self.value=dict(schema=SCHEMA,day=day,quotes={})
        try:
            if self.path.stat().st_size>128*1024:raise ValueError('session_book_too_large')
            value=json.loads(self.path.read_text(encoding='utf8'))
            if (value.get('schema')==SCHEMA and value.get('day')==day and
                    isinstance(value.get('quotes'),dict) and len(value['quotes'])<=20):self.value=value
        except (OSError,ValueError,TypeError,AttributeError):pass
        self.before=_json_bytes(self.value)
        self.verified={}

    def save(self):
        content=_json_bytes(self.value)
        if content!=self.before:_atomic_bytes(self.path,content)

    def observe(self,symbol,quote,source,received,clock,previous_close,raw_reference):
        from dashboard.session_clock import market_phase
        phase=market_phase(clock.to_pydatetime())
        if not phase['continuous']:raise ValueError('live_session_required')
        source_phase=market_phase(source.to_pydatetime())
        if source_phase['phase']!=phase['phase']:raise ValueError('quote_outside_current_session')
        age=(received-source).total_seconds()
        if not -3<=age<=30:raise ValueError('quote_not_fresh_for_session')
        if quote.get('deleted') is True or price_number(quote.get('latestPrice')) is None:
            raise ValueError('current_market_observation_invalid')
        # Ignore service metadata such as updateTime/traceId: changes in cache
        # metadata alone cannot establish new market activity or a trading date.
        fields=['latestPrice','openingPrice','highPrice','lowPrice','tradedQuantities']
        fields += [f'{side}{level}{suffix}' for side in ('b','s') for level in range(1,6) for suffix in ('Price','Stocks')]
        values=[price_number(quote.get(k)) if k.endswith('Price') else number(quote.get(k)) for k in fields]
        fingerprint=hashlib.sha256(_json_bytes(values)).hexdigest()
        current=dict(source_event_time=source.isoformat(),received_at=received.isoformat(),phase=phase['phase'],
            previous_close=previous_close,market_fingerprint=fingerprint,raw_response=raw_reference)
        old=self.value['quotes'].get(symbol)
        if not isinstance(old,dict):
            self.value['quotes'][symbol]=current;raise ValueError('live_session_evidence_pending')
        try:
            before=pd.Timestamp(old['received_at']);market_before=pd.Timestamp(old['source_event_time'])
            if before.tzinfo is None or market_before.tzinfo is None:raise ValueError()
            elapsed=(received-before).total_seconds();advanced=(source-market_before).total_seconds()
        except (KeyError,TypeError,ValueError):
            self.value['quotes'][symbol]=current;raise ValueError('live_session_evidence_pending') from None
        if old.get('phase')!=current['phase'] or elapsed>120:
            self.value['quotes'][symbol]=current;raise ValueError('live_session_evidence_pending')
        if str(before.tz_convert('Asia/Shanghai').date())!=self.value['day'] or str(market_before.tz_convert('Asia/Shanghai').date())!=self.value['day']:
            self.value['quotes'][symbol]=current;raise ValueError('live_session_evidence_pending')
        if elapsed<0 or advanced<0:raise ValueError('live_session_clock_reversed')
        if old.get('previous_close')!=previous_close:
            self.value['quotes'][symbol]=current;raise ValueError('previous_close_changed_during_session')
        if elapsed<2 or advanced<1:raise ValueError('live_session_clock_not_advanced')
        if abs(advanced-elapsed)>6:raise ValueError('live_session_clock_rate_mismatch')
        if old.get('market_fingerprint')==fingerprint:raise ValueError('market_values_not_advanced')
        if not self.verify(old.get('raw_response')):
            self.value['quotes'][symbol]=current;raise ValueError('prior_session_witness_unavailable')
        proof=dict(basis='corroborated_live_session',exchange_date_certified=False,session_day=self.value['day'],
            source_trade_date_explicit=False,
            phase=current['phase'],witness_count=2,previous_close_stable=True,
            witnesses=[{k:r[k] for k in ('source_event_time','received_at','market_fingerprint','raw_response')} for r in (old,current)])
        self.value['quotes'][symbol]=current
        return proof

    def verify(self,reference):
        if not isinstance(reference,dict):return False
        key=tuple(reference.get(k) for k in ('root','path','sha256'))
        if key in self.verified:return self.verified[key]
        try:
            root=Path(reference['root']).resolve();path=(root/reference['path']).resolve()
            good=(path.is_relative_to(root) and path.stat().st_size<=8*1024*1024
                and hashlib.sha256(path.read_bytes()).hexdigest()==reference['sha256'])
        except (OSError,TypeError,ValueError,KeyError):good=False
        self.verified[key]=good;return good
