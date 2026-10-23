"""Separate source, receipt, storage, calculation and UI clocks; no quote values."""
from datetime import datetime,timezone
import time


def utc_now():return datetime.now(timezone.utc).isoformat()


def begin(model):
    model.refresh_trace=dict(calculation_started_at=utc_now(),calculation_started_monotonic=time.monotonic())
    return model.refresh_trace


def calculated(model,state,trace):
    import pandas as pd
    rows=getattr(model,'live_rows',pd.DataFrame())
    at=pd.Timestamp(state['as_of'])
    if len(rows):rows=rows[rows.observed_at.le(at)]
    latest=rows.sort_values('sequence').drop_duplicates('instrument_id',keep='last') if len(rows) else rows
    from dashboard.marketdata.quote_quality import quote_quality
    sources={}
    for r in latest.itertuples():
        quality=quote_quality(r._asdict(),at)
        sources[str(r.instrument_id)]=dict(source_at=r.source_event_time.isoformat() if pd.notna(r.source_event_time) else None,
            received_at=r.observed_at.isoformat(),sequence=int(r.sequence),quality=quality,
            source_to_receipt_seconds=(r.observed_at-r.source_event_time).total_seconds() if pd.notna(r.source_event_time) else None)
    result={k:v for k,v in trace.items() if not k.endswith('_monotonic')}
    result.update(calculation_finished_at=utc_now(),calculation_seconds=time.monotonic()-trace['calculation_started_monotonic'],
        history_versions=state.get('versions'),realtime_sequence=int(rows.sequence.max()) if len(rows) else 0,
        source_times=sources,source_date_basis='inferred_from_original_receipt_day_unverified',
        cache_read=getattr(model,'live_read_trace',{}),request_id=(state.get('research_pages') or {}).get('request_id'))
    state['refresh_evidence']=result;model.refresh_trace=result
    return state


def applied(window,state):
    result=dict(state.get('refresh_evidence') or {})
    if not result:return
    result.update(ui_applied_at=utc_now(),selection_generation=window.generation,
                  pending_requests=int(bool(window.pending)),active_workers=int(bool(window.busy)))
    for source in result.get('source_times',{}).values():
        stamp=source.get('source_at')
        if stamp:
            source['source_to_ui_seconds']=(datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()
            source['stale_at_application']=source['source_to_ui_seconds']>30
    end=result.get('calculation_finished_at')
    if end:result['ui_apply_seconds']=(datetime.now(timezone.utc)-datetime.fromisoformat(end)).total_seconds()
    window.applied_trace=result
    if hasattr(window,'pipeline'):window.pipeline.record_applied(result)
