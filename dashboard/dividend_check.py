"""Explicit dividend diagnostics: local is offline; share/import are opt-in."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
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
    from .marketdata.overview_dividends import local_sources,source_directory
    local_files=[]
    for path in local_sources(config):
        try:
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            file_dates=sorted({r['source_business_date'] for r in records if r['file_sha256']==sha})
            local_files.append(dict(path=str(path.resolve()),sha256=sha,business_dates=file_dates))
        except OSError as exc:local_files.append(dict(path=str(path),error_type=type(exc).__name__))
    current={}
    selected_at=now if day==now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() else day+'T15:00:00+08:00'
    for root_name in ('IF','IH','IC','IM'):
        for slot in range(4):
            mapped=dated_slots(meta,root_name,slot,[day])[0]
            symbol=mapped['symbol'];selected=book.resolve(symbol,selected_at)
            current[root_name+'0'+str(slot)+'.CFE']=dict(contract_id=symbol,
                **{k:(selected or {}).get(k) for k in ('points','source_business_date','effective_from','file_sha256','inherited_from')},
                reason=(selected or {}).get('reason') or (None if selected else mapped['reason'] or book.reason or '待该实际合约在定价时点已知的分红输入'))
    return dict(schema='overview-dividend-audit-v1',checked_at=now.isoformat(),pricing_day=day,mode=book.mode,
        network_requested=False,configuration_changed=False,reason=book.reason,
        record_count=len(records),file_versions=len({r['file_sha256'] for r in records}),
        oldest_business_day=dates[0] if dates else None,latest_business_day=dates[-1] if dates else None,
        precision_counts=dict(Counter(r.get('precision','day') for r in records)),
        policy=book.info.get('historical_policy'),errors=book.info.get('errors',[]),slots=slots,
        history_dividends_complete=all(not r['dividend_missing'] and not r['mapping_missing'] for r in slots.values()),
        sources=dict(downloads_auto_scanned=False,share_directory=source_directory(config),configured_share_directory=config.get('overview_dividend_source_dir'),
            pattern=config.get('overview_dividend_pattern') or '指数基差情况_*.xlsx',
            configured_file=config.get('overview_dividend_file'),legacy_directory=config.get('dividend_root'),
            store_directory=str(root.resolve()),local_files=local_files),current_dividends=current,
        sync_status=read_json(root/'status.json'),schedule=read_json(root/'schedule.json'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path,required=True)
    parser.add_argument('--stage',choices=('local','share','import'),default='local')
    parser.add_argument('--input-file',type=Path,help='Explicit local downloaded Excel; Import only, append without querying the share or editing configuration')
    parser.add_argument('--source-directory',type=Path,help='Temporary share directory override; Share/Import only, configuration retained')
    parser.add_argument('--day')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    if args.input_file is not None and args.stage!='import':parser.error('--input-file requires --stage import')
    if args.source_directory is not None and args.stage=='local':parser.error('--source-directory requires --stage share/import')
    if args.input_file is not None and args.source_directory is not None:parser.error('select --input-file or --source-directory')
    report=dict(schema='overview-dividend-check-v1',stage=args.stage,network_requested=False,configuration_changed=False)
    try:
        native=args.local_root/'native.json'
        original=native.read_bytes()
        configured=json.loads(original.decode('utf-8-sig'))
        config=configured
        report['diagnostic_profile']=dict(local_root=str(args.local_root.resolve()),native_file=str(native.resolve()),
            configuration_sha256=hashlib.sha256(original).hexdigest())
        if args.source_directory is not None:
            config={**config,'overview_dividend_source_dir':str(args.source_directory)}
            report['source_directory_override']=str(args.source_directory)
        stage_complete=True
        if args.input_file is not None:
            from .marketdata.overview_dividends import DividendStore,directory,remote
            path=args.input_file
            if remote(path) or path.suffix.lower()!='.xlsx' or not path.is_file():raise ValueError('InputFileMustBeLocalExcel')
            store=DividendStore(directory(config,args.local_root))
            value=store.import_file(path)
            selected=[r for r in store.read() if r['file_sha256']==value['sha256']]
            report['file_import']=dict(value,path=str(path.resolve()),business_dates=sorted({r['source_business_date'] for r in selected}),
                effective_from=sorted({r['effective_from'] for r in selected}),records=len(selected))
        elif args.stage!='local':
            from .marketdata.overview_dividend_sync import run_sync
            if args.stage=='share':
                with tempfile.TemporaryDirectory(prefix='delta1-dividend-check-') as tmp:
                    report['sync']=run_sync({**config,'overview_dividend_cache':tmp},args.local_root,publish=False)
            else:
                report['sync']=run_sync(config,args.local_root)
            report['network_requested']=report['sync'].get('network_requested',False)
            stage_complete=report['sync'].get('status')=='complete'
        report['audit']=audit(config,args.local_root,day=args.day)
        report['audit']['sources']['configured_share_directory']=configured.get('overview_dividend_source_dir')
        report['configuration_changed']=native.read_bytes()!=original
        report['ok']=not report['audit']['reason'] and report['audit']['history_dividends_complete'] and stage_complete
    except Exception as exc:
        report.update(ok=False,error_type=type(exc).__name__)
    path=args.output or Path(__file__).parent/'runtime/app_diagnostics'/('dividends_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(output=str(path.resolve()),stage=args.stage,ok=report['ok']),ensure_ascii=False))
    return 0 if report['ok'] else 2


if __name__=='__main__':raise SystemExit(main())
