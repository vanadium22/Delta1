"""Portable numeric feed. Excel COM reads atomic JSON; no Qt/Node needed at runtime."""
import argparse
import json
from pathlib import Path
import time
import sys
import os
import pandas as pd
from dashboard.numeric_snapshot import freeze_state, save_snapshot, numeric_rows

HEADERS = {
    '数字看板': ['品种','档位','具体合约','期货 F','指数 S','分红 D 点','T 自然日','基差 点','基差 bp','年化 %','数据类型','数据时间（北京）','当前挂牌合约','说明'],
    '分位与样本': ['品种','档位','具体合约','窗口','分位 %','有效 n','缺失日','排除日','定位值','单位','定位时间（北京）','参考截止（北京）','说明'],
    '研究指标': ['品种','档位','具体合约','指标ID','指标名称','数值','单位','数据类型','数据时间（北京）','可用性说明','口径 / 公式'],
    '来源与状态': ['项目','内容'],
}
from dashboard.numeric_view import CARD_HEADERS, METRIC_HEADERS
HEADERS.update({'卡片数据': CARD_HEADERS, '指标数据': METRIC_HEADERS})


def local_time(value):
    return pd.Timestamp(value).tz_convert('Asia/Shanghai').strftime('%Y-%m-%d %H:%M:%S') if value else ''


def excel_time(value):
    return (pd.Timestamp(value).tz_convert('Asia/Shanghai').tz_localize(None)-pd.Timestamp('1899-12-30')).total_seconds()/86400 if value else None


def workbook_payload(payload):
    sheets = {name: [] for name in HEADERS}
    for r in numeric_rows(payload):
        card = next(c for s in payload['snapshots'] for c in s['overview'] if c['alias']==r['slot'])
        sheets['数字看板'].append([r['product'],r['slot'],r['contract'],r['future'],r['spot'],r['dividend'],r['T'],r['points'],r['bp'],
            r['annual_pct']/100 if r['annual_pct'] is not None else None,r['marker_kind'],excel_time(r['marker_time']),card.get('active_symbol',r['contract']),r['status']])
        for w in r['windows']:
            sheets['分位与样本'].append([r['product'],r['slot'],r['contract'],w['title'],w['percentile']/100 if w['percentile'] is not None else None,
                w['n'],w['missing'],w['excluded'],r['marker'],r['marker_unit'],excel_time(r['marker_time']),excel_time(w['end']),w['reason'] or ('有效' if w['available'] else '缺少数据')])
    for state in payload['snapshots']:
        for e in state.get('entities',[]):
            card=next((c for c in state['overview'] if c['symbol']==e['left']),None)
            for m in e['metrics']:
                current=m.get('current') is not None
                value=m.get('current') if current else m.get('value')
                kind=m.get('display_kind') or '盘中观测' if current else '最后有效历史' if m.get('last_valid') else '历史'
                if current and kind.startswith('盘中'):
                    kind=m.get('current_scope') or kind
                if value is None:kind='缺少数据'
                sheets['研究指标'].append([e['left'][:2],card['alias'] if card else '',e['left'],m['id'],m['title'],value,m['unit'],kind,
                    excel_time(m.get('current_time') if current else m.get('time')),m.get('current_reason') if current else m.get('reason'),m['formula']])
    sheets['来源与状态'] = [
        ['模式',payload['mode']],
        ['刷新规则','由 start_numeric_excel.cmd 保持更新；直接打开xlsx只显示最后保存值。计算和写入时间不代表新行情。'],
        ['行情接入','北京时间交易日09:29（含）至15:01（不含）；之外只读取本地数据。午间保留带时点的缓存。'],
        ['缓存规则','优先当前有效同步行情；否则比较最新历史收盘与保存观测，展示较新可用值。缓存不保证是最终收盘价。'],
        ['指标规则','实时可算项随行情变化；日线/分钟/OI项仅随对应有效数据更新；缺失留空，合法0保留。'],
        ['分红规则','固定分红情景用于历史重算，不是真实逐日分红；缺失合约继承关系见逐行说明。'],
        ['单位','数字看板年化、分位列为Excel百分比；研究指标数值按相邻单位原值（%表示百分点）。'],
        ['历史版本',json.dumps(payload['snapshots'][0].get('versions',{}),ensure_ascii=False)],
        ['分红版本',payload['snapshots'][0].get('dividend_version','')],
    ] if payload['snapshots'] else []
    from dashboard.numeric_view import add_view
    result=add_view(dict(schema_version=1,generated_at=payload['generated_at'],mode=payload['mode'],headers=HEADERS,sheets=sheets))
    if payload.get('research'):
        from dashboard.numeric_view import add_research_view
        add_research_view(result,payload['research'])
    return result


def capture(model, now=None, *, progress=None, stopped=None):
    from dashboard.display_state import display_snapshot
    now=pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    states=[]
    for slot in range(4):
        if stopped and stopped():raise InterruptedError('numeric service stopped')
        if progress:progress(slot,False,None)
        state=display_snapshot(model,dict(cards=True,category='basis',price_input='annual',distribution_input='annual',overview_slot=slot),now=now)
        states.extend(freeze_state(state)['snapshots'])
        if progress:progress(slot,True,dict(generated_at=now.isoformat(),mode=state['display_policy']['reason'],snapshots=list(states)))
    policy=states[0]['display_policy']
    return dict(generated_at=now.isoformat(),mode=policy['reason'],snapshots=states)


def main(argv=None):
    parser=argparse.ArgumentParser(description='数字Excel本地数据服务，无网页前端依赖')
    parser.add_argument('--local-root',type=Path)
    parser.add_argument('--feed',type=Path,required=True)
    parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--snapshot',type=Path,help='仅导出已保存快照，不采集')
    parser.add_argument('--collect',action='store_true',help='公司VPN已登录；盘中有限验证后采集，已有采集器则只读共享缓存')
    parser.add_argument('--interval',type=float,default=3)
    parser.add_argument('--iterations',type=int,default=0)
    parser.add_argument('--selection-file',type=Path,help='本次Excel关注组合选择；独立于数据/VPN设置')
    args=parser.parse_args(argv)
    if args.interval<1:parser.error('interval must be >= 1')
    from dashboard.native.model import NativeModel
    from dashboard.native.collection import CollectionJob
    from dashboard.session_clock import session_policy
    from dashboard.session_guard import probe_realtime
    from dashboard.marketdata.paths import DATA_ROOT
    from dashboard.native.instruments import UNDERLYINGS
    from dashboard.numeric_config import prepare_config, problems
    from dashboard.numeric_evidence import cache_scope, annotate
    service_started=time.monotonic()
    status_path=args.feed.with_suffix('.status.json')
    def status(message, *, ready=False, log=True):
        value=dict(message=message,ready=ready,elapsed_seconds=round(time.monotonic()-service_started,1),
                   updated_at=pd.Timestamp.now(tz='UTC').isoformat())
        save_snapshot(value,status_path)
        if log:print(f"[{value['elapsed_seconds']:.1f}s] {message}",flush=True)
    status('检查数字专用配置和历史索引')
    model=NativeModel(prepare_config(args.local_root));model.config['dashboard_mode']='nonregression'
    model.numeric_cache_scope=cache_scope(model.config)
    runtime=dict(python=sys.executable,producer_pid=os.getpid(),config_path=str(model.path),
                 realtime_root=model.config.get('realtime_root'),history_roots=model.config.get('history_roots'),
                 cache_scope=model.numeric_cache_scope,collect_requested=args.collect)
    if not args.snapshot:
        issues=problems(model.config)
        if issues:
            model.close()
            parser.error('；'.join(issues)+' 请运行 python -m dashboard.numeric_config，参见 dashboard/COMPANY_SETUP.md。')
    collection=CollectionJob(model.local_root)
    next_attempt=0;iteration=0;previous_feed=None;probe_note='等待连接验证'
    try:
        cached=False
        if not args.snapshot and not args.iterations:
            # Open promptly from a previous daily calculation while historical
            # minute inputs warm up. Original row times stay unchanged.
            cache=DATA_ROOT/'cache/dashboard/numeric'
            today=pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y-%m-%d')
            candidates=sorted((p for p in cache.glob('????-??-??/latest.json') if p.parent.name<=today),reverse=True)
            for candidate in candidates:
                try:
                    previous=json.loads(candidate.read_text(encoding='utf8'))
                    if previous.get('cache_scope')!=model.numeric_cache_scope:continue
                    previous['mode']='启动中 · 上次计算缓存（待本轮历史核验）'
                    initial=workbook_payload(previous);initial['ready']=False
                    initial['runtime']=runtime
                    save_snapshot(initial,args.feed);cached=True;break
                except (OSError,ValueError,KeyError,TypeError):pass
        if not args.snapshot and not cached:
            # Open Excel before the expensive first calculation. Missing results
            # remain empty, and partial results never enter the daily cache.
            save_snapshot(dict(schema_version=1,generated_at=pd.Timestamp.now(tz='UTC').isoformat(),
                mode='首次计算中 · 尚无计算结果，缺失不填0',headers=HEADERS,
                sheets={name:[] for name in HEADERS},ready=False,runtime=runtime),args.feed)
        def progress(slot,complete,payload):
            message=f"{'完成' if complete else '正在计算'} {slot:02d} 档（{slot+1}/4）：历史、分位和研究指标"
            status(message,log=iteration==0)
            if complete and iteration==0 and not cached:
                partial=workbook_payload(payload)
                partial.update(ready=False,mode=f'首次计算中 · 已完成 {slot+1}/4 档，其余待计算',
                               generated_at=pd.Timestamp.now(tz='UTC').isoformat(),runtime=runtime)
                save_snapshot(partial,args.feed)
        stopped=lambda:bool(args.stop_file and args.stop_file.exists())
        while not args.stop_file or not args.stop_file.exists():
            started=time.monotonic()
            if args.collect and not args.snapshot and session_policy()['allowed'] and not collection.running() and started>=next_attempt:
                next_attempt=started+60
                result=probe_realtime(model.config)
                probe_note=result.get('message','验证未完成；只读缓存，稍后重试')
                if result['ok']:
                    indices={v[0] for v in UNDERLYINGS.values()}
                    collection.start(model.config['realtime_root'],list(indices),indices,model.config.get('reference_file'),auto_roll=True)
            if not session_policy()['allowed']:collection.stop()
            payload=json.loads(args.snapshot.read_text(encoding='utf8')) if args.snapshot else capture(model,progress=progress,stopped=stopped)
            payload['cache_scope']=model.numeric_cache_scope
            feed=workbook_payload(payload)
            if not args.snapshot:
                from dashboard.indicator_workspace import evaluate, save_preferences
                from dashboard.numeric_view import add_research_view
                selected=None
                if args.selection_file and args.selection_file.exists():
                    try:selected=json.loads(args.selection_file.read_text(encoding='utf-8-sig'))
                    except (OSError,ValueError):pass
                workspace=evaluate(model,selected)
                add_research_view(feed,workspace)
                payload['research']=workspace
                if isinstance(selected,dict) and selected.get('request_id')!=getattr(model,'saved_workspace_request',None):
                    save_preferences(model.local_root,workspace['selection'])
                    model.saved_workspace_request=selected.get('request_id')
            feed['ready']=True
            feed['collector']=collection.state()['status']
            gate=session_policy()
            acquisition=('快照回看 · 不采集' if args.snapshot else '只读缓存 · 不创建采集器' if not args.collect else
                         '时段守卫 · 不新接入行情' if not gate['allowed'] else
                         '实时采集运行中 · 新鲜度见原始时点' if collection.running() and feed['collector']=='running' else
                         '采集状态 '+feed['collector']+' · '+probe_note)
            feed['mode']=acquisition+'；'+payload['mode']
            annotate(feed,payload,previous=previous_feed,completed_at=pd.Timestamp.now(tz='UTC').isoformat(),
                     duration=round(time.monotonic()-started,3),acquisition=acquisition,runtime=runtime)
            save_snapshot(feed,args.feed)
            previous_feed=feed
            if not args.snapshot:
                day=pd.Timestamp(payload['generated_at']).tz_convert('Asia/Shanghai').strftime('%Y-%m-%d')
                save_snapshot(payload,DATA_ROOT/'cache/dashboard/numeric'/day/'latest.json')
            status(f'四个档位计算完成，本轮用时 {time.monotonic()-started:.1f} 秒',ready=True,log=iteration==0)
            iteration+=1
            if args.snapshot or args.iterations and iteration>=args.iterations:break
            deadline=started+args.interval
            while time.monotonic()<deadline:
                if args.stop_file and args.stop_file.exists():break
                time.sleep(min(.2,max(0,deadline-time.monotonic())))
    except InterruptedError:
        if not args.stop_file or not args.stop_file.exists():raise
    finally:
        collection.stop()
        if collection.worker:collection.worker.join(timeout=20)
        model.close()


if __name__=='__main__':main()
