"""Explicit dividend diagnostics: local is offline; share/import are opt-in."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo


def audit(config, local_root, *, now=None, day=None):
    from .marketdata.contract_reference import latest_contracts
    from .marketdata.repository import ReferenceBook
    from .marketdata.overview_basis import load_dividends
    from .marketdata.overview_percentiles import prior_days, dated_slots
    from .marketdata.overview_dividends import directory
    from .marketdata.overview_dividend_sync import read_json
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    day = day or now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    meta = latest_contracts(ReferenceBook(config.get('reference_file')).data)
    book = load_dividends(config, meta, day, local_root)
    records = getattr(book, 'records', [])
    dates = sorted({r['source_business_date'] for r in records})
    slots = {}
    for root in ('IF','IH','IC','IM'):
        for slot in range(4):
            rows = dated_slots(meta, root, slot, prior_days(day))
            missing = [dict(day=r['day'],contract=r['symbol']) for r in rows if not r['excluded'] and r['symbol'] and book.points(r['symbol'],r['day']) is None]
            slots[root+'0'+str(slot)+'.CFE'] = dict(dividend_missing=len(missing),missing=missing,
                mapping_missing=sum(r['reason']=='mapping_missing' for r in rows),
                rule_excluded=sum(r['excluded'] for r in rows),price_availability_tested=False)
    root = directory(config, local_root)
    return dict(schema='overview-dividend-audit-v1',checked_at=now.isoformat(),pricing_day=day,mode=book.mode,
        network_requested=False,configuration_changed=False,reason=book.reason,
        record_count=len(records),file_versions=len({r['file_sha256'] for r in records}),
        oldest_business_day=dates[0] if dates else None,latest_business_day=dates[-1] if dates else None,
        precision_counts=dict(Counter(r.get('precision','day') for r in records)),
        policy=book.info.get('historical_policy'),errors=book.info.get('errors',[]),slots=slots,
        history_dividends_complete=all(not r['dividend_missing'] and not r['mapping_missing'] for r in slots.values()),
        sync_status=read_json(root/'status.json'),schedule=read_json(root/'schedule.json'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path,required=True)
    parser.add_argument('--stage',choices=('local','share','import'),default='local')
    parser.add_argument('--day')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    report=dict(schema='overview-dividend-check-v1',stage=args.stage,network_requested=False,configuration_changed=False)
    try:
        config=json.loads((args.local_root/'native.json').read_text(encoding='utf-8-sig'))
        if args.stage!='local':
            from .marketdata.overview_dividend_sync import run_sync
            if args.stage=='share':
                with tempfile.TemporaryDirectory(prefix='delta1-dividend-check-') as tmp:
                    report['sync']=run_sync({**config,'overview_dividend_cache':tmp},args.local_root,publish=False)
            else:
                report['sync']=run_sync(config,args.local_root)
            report['network_requested']=report['sync'].get('network_requested',False)
        report['audit']=audit(config,args.local_root,day=args.day)
        report['ok']=not report['audit']['reason'] and report['audit']['history_dividends_complete'] and (args.stage=='local' or report['sync'].get('status')=='complete')
    except Exception as exc:
        report.update(ok=False,error_type=type(exc).__name__)
    path=args.output or Path(__file__).parent/'runtime/app_diagnostics'/('dividends_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(output=str(path.resolve()),stage=args.stage,ok=report['ok']),ensure_ascii=False))
    return 0 if report['ok'] else 2


if __name__=='__main__':raise SystemExit(main())
