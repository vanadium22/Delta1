"""Compact presentation of existing results; no business calculations."""

PRODUCTS = ('IF', 'IH', 'IC', 'IM')
# Order and labels are presentation only. All original rows remain in 研究指标.
METRICS = (
    ('A01.points', '调整基差', '点'), ('A01.bp', '调整基差', 'bp'),
    ('A02.annual', '年化', '%'), ('A02.convergence', '每日收敛', 'bp/日'),
    ('A03.z', '历史Z', '倍'), ('A03.percentile', '历史分位', '%'),
    ('A03.change5', '五期变化', '%'), ('A11', '短窗波动', '%'),
    ('A12', '偏离确认', '次'), ('B01.gap', '开盘缺口', '%'),
    ('B01.repair', '缺口修复', '倍'), ('B02.center', '分钟中枢', '%'),
    ('B02.gap', '中枢偏离', '%'), ('B02.collection_center', '采集中枢', '%'),
    ('B02.collection_gap', '采集偏离', '%'), ('B03', '增仓漂移', '%'),
    ('B04.Q', '日换手', '倍'), ('B04.K', '增仓占比', '%'), ('B04.doi', '净增仓', '手'),
    ('B07', '收盘位置差', '倍'), ('B09', '活跃度', '倍'),
    ('B10', '路径效率', '倍'), ('B11', '振幅压力', '倍'),
    ('A13', '成本带', 'bp'), ('A14.etf', 'ETF折溢价', 'bp'),
)
CARD_METRICS = ('A02.convergence', 'B11', 'B10', 'B02.center', 'B04.Q', 'B09')
CARD_HEADERS = ['档位','品种','合约','期货','指数','基差bp','年化',
    '收敛','振幅','路径效率','分钟中枢','换手','活跃度',
    '20日分位','3月分位','6月分位','12月分位',
    '20日n','3月n','6月n','12月n','提示','行情时间','历史时间','数据类型']
METRIC_HEADERS = ['档位','ID','指标','单位'] + [
    p + suffix for p in PRODUCTS for suffix in ('数值','日期','说明')]


def short_reason(row):
    if not row:
        return '待计算'
    if row[5] is not None:
        return '历史' if '历史' in (row[7] or '') else '缓存' if '回看' in (row[7] or '') else row[7] or '行情'
    reason = str(row[9] or '')
    if 'ETF' in reason or 'IOPV' in reason:
        return '缺ETF/IOPV'
    if '融资' in reason or '成本' in reason:
        return '缺成本输入'
    if '样本不足' in reason:
        return '样本/分母'  # Engine also includes missing inputs and invalid denominators.
    if '分钟' in reason:
        return '分钟不足'
    if 'OI' in reason or '持仓' in reason:
        return '缺持仓'
    if '分红' in reason:
        return '缺分红'
    if 'T<5' in reason:
        return '临到期'
    return '缺数据'


def add_view(feed):
    sheets = feed['sheets']
    metrics = {(r[1], r[3]): r for r in sheets['研究指标']}
    cards = {r[1]: r for r in sheets['数字看板']}
    windows = {}
    for row in sheets['分位与样本']:
        windows.setdefault(row[1], []).append(row)
    card_rows, metric_rows = [], []
    for slot in range(4):
        for product in PRODUCTS:
            alias = f'{product}{slot:02d}.CFE'
            row = cards.get(alias)
            selected = [metrics.get((alias, code)) for code in CARD_METRICS]
            for i,alternate in ((1,'B11.sample'),(3,'B02.collection_center'),(4,'B04.Q.intraday'),(5,'B09.same_time')):
                live=metrics.get((alias,alternate))
                if live and live[5] is not None:selected[i]=live
            w = windows.get(alias, [])
            w = w[:4] + [None] * max(0, 4-len(w))
            reasons = list(dict.fromkeys(short_reason(m) for m in selected if not m or m[5] is None))
            kinds=[]
            for name,m in zip(('收敛','振幅','路径','中枢','换手','活跃'),selected):
                if m and m[5] is not None:
                    label='日终' if '历史' in (m[7] or '') else '缓存' if any(s in (m[7] or '') for s in ('回看','缓存')) else '采集段' if '采集' in (m[7] or '') else '盘中'
                    kinds.append(name+label)
            if any('盘中' in s or '采集段' in s for s in kinds):
                reasons.append(' · '.join(kinds))
            historical_times = [m[8] for (a, _), m in metrics.items()
                                if a == alias and m[5] is not None and '历史' in (m[7] or '') and m[8]]
            history = min(historical_times) if historical_times else None
            # The oldest displayed historical metric prevents a newer one hiding stale rows.
            card_rows.append([slot, product, row[2] if row else None,
                *([row[i] for i in (3,4,8,9)] if row else [None]*4),
                *[m[5] if m else None for m in selected],
                *[a[4] if a else None for a in w], *[a[5] if a else None for a in w],
                ' / '.join(reasons), row[11] if row else None, history,
                row[10] if row else '待计算'])
        for code, label, unit in METRICS:
            values = []
            for product in PRODUCTS:
                m = metrics.get((f'{product}{slot:02d}.CFE', code))
                values.extend([m[5] if m else None, m[8] if m else None, short_reason(m)])
                if m:
                    unit = m[6]
            metric_rows.append([slot, code, label, unit, *values])
    # Don't mutate the shared original header constant.
    feed['headers'] = {**feed['headers'], '卡片数据': CARD_HEADERS, '指标数据': METRIC_HEADERS}
    sheets.update({'卡片数据': card_rows, '指标数据': metric_rows})
    return feed


def add_research_view(feed, workspace):
    """Render shared contracts, with no formulas or unit conversion in Excel."""
    import json
    from dashboard.indicator_catalog import PAGES
    from dashboard.indicator_workspace import directory_rows, detail_rows
    from dashboard.indicator_ui import ui_controls, family_title, input_label
    import pandas as pd
    def source_label(row):
        values=[]
        for symbol,stamp in (row.get('source_times') or {}).items():
            text=pd.Timestamp(stamp).tz_convert('Asia/Shanghai').strftime('%m/%d %H:%M:%S') if stamp else '未知'
            values.append(symbol+' '+text)
        return '\n'.join(values)
    data_labels={'daily_reference':'完整日终参考','intraday_estimate':'盘中估计','old_history':'较早历史',
                 'missing_input':'缺输入','not_applicable':'不适用','ok':'可用',
                 'unavailable':'暂无数据','missing':'缺输入'}
    pages={}
    for category in PAGES:
        page=workspace.get('pages',{}).get(category,{})
        controls=ui_controls(category)
        entities=[]
        for entity in page.get('entities',[]):
            row=entity.get('primary',{})
            note=row.get('reason') or ''
            expiry_label=('同到期' if entity.get('expiry_type')=='same' else '异期参考' if entity.get('category')=='cross' and entity.get('expiry_type')=='mixed' else '')
            policy='；'.join(str(s) for s in (expiry_label,entity.get('selection_type'),entity.get('decision_date'),entity.get('selection_reason')) if s)
            entities.append([entity.get('title'),row.get('value'),row.get('unit'),row.get('time'),
                             row.get('history_cutoff'),row.get('n'),row.get('implementation_status'),
                             row.get('data_status'),note,policy,row.get('visibility_status')])
        ordered_entities=[{**entity,'metrics':sorted(entity.get('metrics',[]),
            key=lambda row:category in ('calendar','cross') and row.get('id')!=entity.get('primary',{}).get('id'))} for entity in page.get('entities',[])]
        details=detail_rows({**page,'entities':ordered_entities})
        detail_notes=[]
        # Add formula identity to the already shared input-version cell.
        for target,(_,row) in zip(details,((e,r) for e in ordered_entities for r in e.get('metrics',[]))):
            target[3]=source_label(row)
            version_fields=dict(variant=row.get('variant_id'),formula=row.get('formula_version'),**(row.get('input_versions') or {}))
            evidence_fields={key:row[key] for key in ('pair_metadata','pair_intraday') if row.get(key)}
            target[8]='\n'.join(k+': '+(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')) if isinstance(v,(dict,list)) else str(v))
                for k,v in version_fields.items())
            detail_notes.append(json.dumps(evidence_fields,ensure_ascii=False,sort_keys=True,indent=2) if evidence_fields else None)
            observed=row.get('pair_intraday') or {}
            if observed:
                def stamp(key):
                    return pd.Timestamp(observed[key]).tz_convert('Asia/Shanghai').strftime('%m/%d %H:%M:%S') if observed.get(key) else '缺失'
                def number(key):
                    return format(observed[key],'.6g') if observed.get(key) is not None else '缺失'
                evidence=[f"分子：{number('numerator')}；历史分母：{number('denominator')}"]
                if observed.get('effective_h') is not None:
                    basis='跨期固定 1:1' if category=='calendar' and observed['effective_h']==1 and not observed.get('ratio_source_time') else '依据 '+stamp('ratio_source_time')
                    evidence.append(f"h（B手/A手）：{number('effective_h')}；{basis}")
                evidence.append(f"基准 {observed.get('baseline_n',0)} 日：{stamp('baseline_start')} → {stamp('baseline_end')}")
                if observed.get('minute_count') is not None:evidence.append(f"每日同刻累计 {observed['minute_count']} 分钟；边界 {stamp('boundary')}")
                if observed.get('sample_n') is not None:evidence.append(f"本采集段 {observed['sample_n']} 个同步样本（非全天）")
                evidence.append(f"采集段：{stamp('segment_start')} → {stamp('segment_end')}（北京）")
                if observed.get('approximation'):evidence.append('当前为分钟边界前 0—3 秒近似')
                target[8]='\n'.join(evidence)+'\n'+target[8]
            if evidence_fields:target[8]+='\n配对原始元数据全文见本格批注（默认隐藏）'
        selection=page.get('selection',workspace.get('selection',{}).get('pages',{}).get(category,{}))
        selected=next((item for item in controls['variants'] if item['variant_id']==selection.get('variant_id')), {})
        selected_input=next((item for item in controls['inputs'] if item['input_id']==selection.get('input')), {})
        selected_family=next((item for item in controls['families'] if item['family_id']==selection.get('family_id')), {})
        primary=next((entity.get('primary',{}) for entity in page.get('entities',[]) if entity.get('primary')), {})
        primary_ids={entity.get('primary',{}).get('id') for entity in page.get('entities',[])}
        intraday_ids=primary_ids & {'B09.same_time','B11.sample'} if category in ('calendar','cross') else set()
        intraday_pair=bool(intraday_ids) and len(primary_ids)==1
        headline=selected_family.get('label') or family_title(selection.get('family_id',''))
        if intraday_pair:
            headline='合约对同刻累计活跃度' if primary['id']=='B09.same_time' else '合约对采集段振幅（非全天）'
        elif intraday_ids:headline+='（口径逐行标示）'
        scope={'representatives':'默认代表','all':'全部合约','history':'历史合约','specified':'指定合约'}.get(selection.get('scope'),'默认代表')
        context=' · '.join((headline,
            selected_input.get('label') or input_label(selection.get('input',''),selection.get('timing','日终')),
            scope,selection.get('timing','日终')))
        status=workspace.get('error') or page.get('error') or selection.get('selection_error') or (
            f"{context} · {len(entities)} / {page.get('total',0)} 个" if page.get('loaded') else '切换到此研究页后加载结果')
        summary=[]
        for entity,row in zip(page.get('entities',[]),entities):
            source=entity.get('primary',{})
            raw_state=source.get('data_status') or ''
            state=data_labels.get(raw_state,raw_state or '待计算')
            reason=str(source.get('reason') or '')
            if source.get('value') is None:
                state=next((label for token,label in [('T<5','到期不足5天'),('分红','缺分红'),('ETF','缺 ETF / IOPV'),('IOPV','缺 ETF / IOPV'),('融资','缺融资 / 成本'),('成本','缺成本输入'),('分钟','缺分钟数据'),('OI','缺可靠持仓'),('样本','样本不足')] if token in reason), '缺输入，详见详情')
            elif state=='ok':state='可用'
            if category in ('calendar','cross') and source.get('value') is not None and raw_state=='intraday_estimate':
                state={'B09.same_time':'盘中同刻累计','B11.sample':'采集段估计（非全天）'}.get(source.get('id'),state)
            summary.append([row[0],row[1],row[2],row[3],row[5],state])
        # Complete diagnostics remain available directly below the advanced controls.
        for target,(entity,source) in zip(details,((e,r) for e in ordered_entities for r in e.get('metrics',[]))):
            if source.get('role') in ('primary','auxiliary'):
                target[0]=('【主指标】' if source['role']=='primary' else '【辅助解释】')+str(source.get('title') or source.get('id') or '')+'\n'+target[0]
            if source.get('pair_construction'):
                target[10]='构造：'+source['pair_construction']+'\n公式：'+str(target[10] or '')
            target[6]={'implemented':'已实现','not_implemented':'未实现'}.get(target[6],target[6])
            target[7]=data_labels.get(target[7],target[7])
            if category in ('calendar','cross') and source.get('value') is not None and source.get('data_status')=='intraday_estimate':
                target[7]={'B09.same_time':'盘中同刻累计','B11.sample':'采集段估计（非全天）'}.get(source.get('id'),target[7])
            target[9]='；'.join(str(x) for x in (target[9],entity.get('selection_type'),entity.get('decision_date'),entity.get('selection_reason'),source.get('visibility_status')) if x)
        if len(summary)>24:status+=' · 主表前24条，完整结果见详情'
        explanations={key:str(selected.get(key) or '') for key in ('pair_construction','direction','explanation','limitations')}
        if intraday_pair:
            explanations.update({key:str(primary[key]) for key in explanations if primary.get(key)})
        pages[category]=dict(directory=directory_rows(page),entities=entities,summary=summary[:24],details=details,detail_notes=detail_notes,
            status=status,context=context,explanations=explanations,detail_start=11 if category=='basis' else 15)
    feed['research']={**workspace,'excel_pages':pages,'ui_controls':{page:ui_controls(page) for page in PAGES}}
    return feed
