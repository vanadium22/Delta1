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
