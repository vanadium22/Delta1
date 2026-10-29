"""Read-only, exact-profile dependency audit. Never constructs a network client.

Presence in a manifest is reported separately from a usable final daily close.
Missing Wind universes block enumerating members; they never imply zero DDB gaps.
"""
from collections import defaultdict
import json
from pathlib import Path
import pandas as pd

from .overview_reference import load,ranking,ROOTS,finite,worker_status
from .overview_daily import read_day,requests,directory,merge_daily,local_copy_plan
from .overview_percentiles import requirements,prepare,evaluate,prior_days,SLOTS
from .overview_sessions import latest_completed_session
from .overview_contributions import read_equities


def read_object(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,TypeError):return {}


def inspect_history(config,*,target=None):
    from .history_publication import maintenance_root
    from .repository import MarketDataRepository
    roots=config.get('history_roots') or []
    result=dict(status='not_configured',datasets=[],inventory=[],allow_unverified=config.get('allow_unverified',False),minute_scope='manifest_dates_only_not_a_new_minute_scan')
    if not roots:return None,{},result
    root=maintenance_root(roots)
    state=read_object(root/'status.json');pending=read_object(root/'pending.json')
    from dashboard.history_status import counts_ready
    current=(counts_ready(state) and pending.get('scan_id')==state.get('scan_id') and
        pending.get('target')==state.get('target') and pending.get('versions')==state.get('versions'))
    result['maintenance']={k:state.get(k) for k in ('state','message','updated_at','target','scan_id','scan_complete',
        'unknown_groups','overview_daily','overview_continuous','error_type')}
    result.update(pending_current=bool(current),known_pending_symbol_days=state.get('pending_symbol_days') if current else None,
        pending_jobs=[{k:j.get(k) for k in ('symbol','frequency','day','missing','reason','retry_at','error_type')} for j in pending.get('jobs',[])] if current else [],
        pending_note='匹配同次扫描和目标' if current else '无匹配的完整缺口扫描；不能把空列表解释为无缺口')
    if current and target is not None and state.get('target')!=target:
        result.update(pending_current=False,known_pending_symbol_days=None,pending_jobs=[],pending_note='旧扫描目标不等于当前应完成交易日 '+target)
    try:
        repo=MarketDataRepository(roots,allow_unverified=config.get('allow_unverified',False),publication=root/'publication.json')
        frozen=repo.freeze();groups={}
        if current and {k:v['version'] for k,v in frozen.items()}!=state.get('versions'):
            result.update(pending_current=False,known_pending_symbol_days=None,pending_jobs=[],pending_note='已发布版本与旧扫描不匹配；需重新核验')
        for key,snapshot in frozen.items():
            descriptor=snapshot.get('descriptor') or repo.datasets[key].descriptor
            result['datasets'].append(dict(dataset_id=key,root=str(repo.datasets[key].root),version=snapshot['version'],
                availability_policy=descriptor.get('availability_policy'),price_adjustment=descriptor.get('price_adjustment')))
            for part in snapshot['parts']:
                identity=key,part['instrument_id'],part['frequency']
                group=groups.setdefault(identity,dict(dataset_id=key,symbol=identity[1],frequency=identity[2],dates=set(),partitions=0))
                group['dates'].add(part['trade_date']);group['partitions']+=1
        for group in groups.values():
            dates=sorted(group.pop('dates'));result['inventory'].append(dict(group,days=len(dates),first=dates[0],last=dates[-1],dates=dates))
        result['status']='frozen_publication_read';return repo,frozen,result
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result.update(status='unavailable',error_type=type(exc).__name__,pending_current=False,
            known_pending_symbol_days=None,pending_jobs=[],pending_note='无法核验当前发布版本；保留旧扫描状态，不能断言当前缺口');return None,{},result


def daily_inputs(config,local_root,target,metadata,*,repo=None,frozen=None):
    needed=requirements(metadata,target)
    days={target,*prior_days(target)}
    cache={d:read_day(config,local_root,d) for d in sorted(days)}
    symbols={r['symbol'] for r in needed['rows']}|set(ROOTS.values())
    daily={};errors=[]
    cutoff=pd.Timestamp(target+'T23:59:59+08:00')
    for symbol in sorted(symbols):
        frame=pd.DataFrame()
        if repo is not None:
            try:frame=repo.read_window(symbol,'1d',count=65,as_of=cutoff,fields=('close',),frozen=frozen)
            except ValueError:pass
            except (OSError,KeyError) as exc:errors.append(dict(symbol=symbol,error_type=type(exc).__name__))
        additions=[dict(row,event_time=pd.Timestamp(row['source_at']),is_final=True) for d,value in cache.items() if (row:=value.get('rows',{}).get(symbol))]
        if additions:
            frame=merge_daily(frame,additions)
        daily[symbol]=frame
    return daily,needed,errors


def calculation_preview(config,local_root,now,repo,frozen):
    """Run the real page engine with a read-only model and the frozen publication.

    No NativeModel constructor, ResultStore, App, collector or network client.
    This is a calculation preview, never evidence that a live UI applied it.
    """
    from types import SimpleNamespace
    from dashboard.native.model import NativeModel
    from dashboard.native.market_overview import MarketOverviewEngine
    class FrozenReader:
        def freeze(self):return frozen
        def symbols(self,snapshot):return repo.symbols(snapshot)
        def read_window(self,*args,**kwargs):return repo.read_window(*args,**kwargs)
    reader=FrozenReader()
    def configured(_):
        if repo is None:raise ValueError('无可用冻结历史')
        return reader
    model=SimpleNamespace(config=config,local_root=Path(local_root),demo=False,live_cursor=0,live_key=None,
        live_rows=pd.DataFrame(),configure_repository=configured)
    model._live=lambda instruments,as_of:NativeModel._live(model,instruments,as_of)
    state=MarketOverviewEngine(model).snapshot(now=now)
    fields=('symbol','slot','price','source_at','received_at','display_kind','status','basis_kind','pricing_day','pricing_at',
        'basis_future_price','basis_spot_price','basis_future_source_at','basis_spot_source_at','expiry','days',
        'basis_points','raw_basis_points','annual_pct','basis_reason','dividend_points','dividend_snapshot','dividend_inherited_from',
        'dividend_source_contract','dividend_source_kind','dividend_file_sha256','dividend_effective_from','dividend_revision','dividend_precision',
        'percentile_20','percentile_60','percentile_reason','continuous_percentiles')
    return dict(scope='actual_page_engine_preview_not_running_UI',ui_application_verified=False,network_requested=False,
        calculation=state['refresh_evidence'],errors=state['market_overview']['errors'],basis_formula=state['market_overview']['basis_formula'],
        futures=[{k:r.get(k) for k in fields} for r in state['market_overview']['futures']],
        etfs=[{k:r.get(k) for k in ('symbol','root','price','source_at','iopv','iopv_id','premium_bp','premium_reason',
            'closing_nav_cny','closing_price_cny','closing_premium_bp','nav_date','closing_premium_reason')} for r in state['market_overview']['etfs']])


def collect(config,local_root,*,now=None,iopv_fields=None):
    from .repository import ReferenceBook
    from .contract_reference import latest_contracts
    from dashboard.session_clock import market_phase
    from dashboard.native.overview_instruments import etfs
    stamp=pd.Timestamp(now or pd.Timestamp.now(tz='Asia/Shanghai')).tz_convert('Asia/Shanghai')
    day=str(stamp.date());target=latest_completed_session(stamp.to_pydatetime())
    pricing=day if market_phase(stamp.to_pydatetime())['phase'] in ('morning','lunch','afternoon') else target
    reference=load(config,local_root,now=stamp.to_pydatetime());data=reference['data']
    # Freeze the constituent generation before slow historical/page reads. A
    # later published snapshot must not be labelled stale against the old clock.
    snapshot=read_equities(config,local_root)
    result=dict(schema='overview-data-gaps-v1',at=stamp.isoformat(),expected_completed_session=target,
        percentile_pricing_day=pricing,network_requested=False,wind_requested=False,vpn_changed=False,errors=[])
    try:metadata=latest_contracts(ReferenceBook(config.get('reference_file')).data)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        metadata={};result['errors'].append(dict(stage='contract_reference',error_type=type(exc).__name__))
    wind={};equity_universe=set()
    for root,spot in ROOTS.items():
        group=data.get('indices',{}).get(root,{});members=group.get('rows',[])
        funds,meta=ranking(data,root,today=day);fund_group=data.get('etfs',{}).get(root,{})
        unknown=[m['symbol'] for m in members if not m.get('industry')]
        equity_universe.update(m['symbol'] for m in members)
        expected={'IF':300,'IH':50,'IC':500,'IM':1000}[root];complete=len(members)==expected
        wind[root]=dict(index_id=spot,weight_date=group.get('as_of'),expected_members=expected,
            members=len(members),membership_complete=complete,missing_industry=unknown,weights_available=complete and group.get('weights_complete') is not False,
            membership_as_of=group.get('membership_as_of'),weight_source_dates=group.get('weight_source_dates'),
            ranking=meta,etf_universe_complete=fund_group.get('complete') is True,
            selected_etfs=[dict(symbol=f['symbol'],rank=f['rank'],aum_date=f['aum_date']) for f in funds],
            dependency='先取得完整成分名单才能列出该指数全部股票的DDB缺口' if not complete else None)
    all_members_known=all(w['membership_complete'] for w in wind.values())
    result['wind']=dict(provider=config.get('overview_reference_backend') or 'windpy',reference_valid=reference['error'] is None,
        fetched_at=data.get('fetched_at'),due=reference['due'],load_error=reference['error'],load_issues=reference.get('issues',[]),warnings=data.get('errors',[]),indices=wind)
    result['wind']['last_job']=worker_status(read_object(Path(local_root)/'overview_reference/status.json'))
    repo,frozen,history=inspect_history(config,target=target);result['historical']=history
    history['minute_deep_verification_complete']=bool(history.get('pending_current') and
        history.get('maintenance',{}).get('unknown_groups')==0 and history.get('maintenance',{}).get('state')=='complete')
    daily={}
    try:
        daily,required,errors=daily_inputs(config,local_root,pricing,metadata,repo=repo,frozen=frozen)
        from .overview_basis import load_dividends
        dividends=load_dividends(config,metadata,pricing,local_root)
        result['errors'].extend(dict(stage='daily_read',**e) for e in errors)
        slots={};missing=defaultdict(set)
        for root in ROOTS:
            for slot in SLOTS:
                prepared=prepare(root,slot,metadata,daily,pricing,dividends=dividends)
                checked=evaluate(prepared,None,prepared['current_symbol'])
                checked.update(evaluation_scope='history_only',current_value_evaluated=False)
                # This audit certifies history coverage, never an untested live marker.
                for window in checked['windows'].values():
                    if window['complete']:window['reason']='历史窗口完整；本历史审计未计算当前分位，需另查页面的实时配对或收盘模式'
                    for row in window['missing']:
                        if row['reason'] in ('future_close_missing','index_close_missing'):
                            for symbol in row.get('missing_symbols') or [row.get('symbol') or ROOTS[root]]:missing[symbol].add(row['day'])
                slots[prepared['alias']]=checked
        result['continuous_annual']=dict(start=required['start'],end=required['end'],windows=[20,60],
            slots=slots,mapping_gaps=required['mapping_gaps'],dividend_version=dividends.version,dividend_reason=dividends.reason,
            dividend_missing=[dict(alias=alias,day=r['day'],symbol=r['symbol']) for alias,checked in slots.items() for r in checked['windows']['60']['missing'] if r['reason']=='dividend_missing'],
            daily_missing=[dict(symbol=s,dates=sorted(d)) for s,d in sorted(missing.items())],
            note='逐行读取可用已完成收盘；缺档案、缺行情和已知T<5规则排除分别列示；不把旧合约上市短误当连续窗口不足')
        present=defaultdict(set)
        for item in history['inventory']:
            if item['frequency']=='1d':present[item['symbol']].update(item['dates'])
        result['continuous_annual']['present_but_no_usable_close']=[dict(symbol=s,dates=sorted(d&present[s])) for s,d in sorted(missing.items()) if d&present[s]]
        result['continuous_annual']['presence_note']='已登记日期但无可用收盘可能受最终状态、价格、available_at过滤；保留原配置，不把它直接说成DDB源表无数据'
    except (OSError,ValueError,TypeError,KeyError) as exc:
        result['continuous_annual']=dict(status='unavailable',error_type=type(exc).__name__)
    try:
        jobs=requests(config,local_root,target,metadata,reference_data=data)
        batches=[dict(day=j['day'],asset=j['asset'],missing_count=len(j['symbols']),symbols=j['symbols']) for j in jobs]
        # Cache absence is distinct from missing underlying historical bars: local
        # seeding during one-click runs before deciding whether DDB is needed.
        result['ddb']=dict(target=target,close_cache_missing_batches=batches,
            close_cache_missing_rows=sum(j['missing_count'] for j in batches),
            equity_universe_known=bool(equity_universe),all_four_equity_universes_known=all_members_known,
            source_availability='not_tested',note='这是缓存待补清单；已有可用标准历史先本地复制，仍缺才请求DDB；不证明远端源表没有数据',
            last_job=read_object(directory(config,local_root)/'status.json'))
        plan=local_copy_plan(jobs,daily)
        result['ddb'].update(local_copy_available_rows=plan['local_copy_rows'],
            local_copy_available_batches=plan['local_copy_batches'],
            remaining_after_local_copy_rows=plan['remaining_rows'],
            remaining_after_local_copy_batches=plan['remaining_batches'],
            local_copy_performed=False,
            plan_note='先逐行核验可用标准收盘再分类；本诊断不复制或补库，剩余仍是本地依赖缺口，不证明远端供给')
        result['ddb']['last_job']={k:v for k,v in result['ddb']['last_job'].items() if k in
            ('schema','target','inserted','pending_rows','pending_batches','status','error_types','updated_at')}
    except (OSError,ValueError,TypeError,KeyError) as exc:result['ddb']=dict(status='unavailable',error_type=type(exc).__name__)
    from .quote_quality import quote_quality
    quotes=snapshot.get('quotes',{})
    absent=sorted(equity_universe-set(quotes));stale=[];no_previous=[]
    cutoff_status='valid'
    try:
        cutoff=pd.Timestamp(snapshot['finished_at']) if snapshot.get('finished_at') else None
        if cutoff is None or pd.isna(cutoff) or cutoff.tzinfo is None:cutoff=None;cutoff_status='invalid_or_missing_cutoff'
        elif cutoff>stamp:cutoff=None;cutoff_status='snapshot_after_audit_start'
    except (ValueError,TypeError):cutoff=None;cutoff_status='invalid_or_missing_cutoff'
    for symbol in sorted(equity_universe & set(quotes)):
        q=quotes[symbol]
        try:usable=cutoff is not None and quote_quality(q,cutoff)['usable']
        except (ValueError,TypeError):usable=False
        if cutoff is not None and not usable:stale.append(symbol)
        if not finite(q.get('prev_close')) or q['prev_close']<=0:no_previous.append(symbol)
    result['constituent_quotes']=dict(expected=len(equity_universe),received=len(equity_universe & set(quotes)),
        snapshot_at=snapshot.get('finished_at'),reference_matches=bool(reference['version'] and snapshot.get('reference_version')==reference['version']),
        missing_symbols=absent,stale_at_snapshot_symbols=stale if cutoff is not None else None,missing_previous_close=no_previous,
        quality_evaluation=cutoff_status,
        universe_known=bool(equity_universe),note='分钟采集来自现有HTTP，不由Wind或DDB实时提供；盘后收盘参考另用DDB日线')
    result['constituent_quotes'].update(all_four_universes_known=all_members_known,
        known_missing_count=len(absent),total_missing_count=len(absent) if all_members_known else None)
    result['other_inputs']=dict(iopv=[dict(symbol=f['symbol'],iopv_id=f.get('iopv_id'),
        status='mapping_configured_quote_pair_still_required' if f.get('iopv_id') else 'source_or_explicit_mapping_missing') for f in etfs(config,data,day)],
        iopv_field_discovery=iopv_fields or {},net_creation='verified_share_NAV_source_not_configured',pcf='verified_daily_creation_file_not_configured',
        note='IOPV、净申赎、PCF的缺来源不等于DDB历史缺口；不拿成交量、规模变化或历史折溢价代替')
    result['summary']=dict(missing_index_reference_roots=[r for r,g in wind.items() if not g['weights_available']],
        missing_etf_size_roots=[r for r,g in wind.items() if not g['selected_etfs']],
        missing_membership_roots=[r for r,g in wind.items() if not g['membership_complete']],
        missing_industry_symbols=len(set(s for g in wind.values() for s in g['missing_industry'])) if all_members_known else None,
        known_missing_industry_symbols=len(set(s for g in wind.values() for s in g['missing_industry'])),
        continuous_windows_incomplete=[alias+'/'+window for alias,slot in result.get('continuous_annual',{}).get('slots',{}).items()
            for window,value in slot['windows'].items() if not value['complete']],
        history_pending_current=history.get('pending_current',False),
        source_availability_tested=False,company_acceptance_passed=False)
    try:result['page_calculation_preview']=calculation_preview(config,local_root,stamp,repo,frozen)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        result['page_calculation_preview']=dict(status='unavailable',error_type=type(exc).__name__,ui_application_verified=False,network_requested=False)
    return result
