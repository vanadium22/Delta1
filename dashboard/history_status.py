"""Presentation of a completed gap scan, shared by native and Excel startup."""


def counts_ready(state):
    return (state.get('scan_complete') is True and bool(state.get('scan_id'))
            and state.get('pending_scan_id') == state.get('scan_id')
            and state.get('pending_target') == state.get('target')
            and all(isinstance(state.get(key), int) and not isinstance(state[key], bool)
                    and state[key] >= 0 for key in ('pending_symbol_days', 'missing_bars')))


def current_pending(state, pending):
    """Never display a prior scan's empty list as this run's zero gaps."""
    if (counts_ready(state) and pending.get('scan_id') == state['scan_id']
            and pending.get('target') == state.get('target')
            and pending.get('versions') == state.get('versions')):
        return pending
    return {'jobs': [], 'coverage': []}


def progress_text(state):
    target = state.get('target') or '待确定'
    if counts_ready(state):
        detail = f"剩余 {state['pending_symbol_days']} 项，{state['missing_bars']} 条"
        if state.get('unknown_groups'):
            detail = '已知'+detail+f"；另 {state['unknown_groups']} 组历史分钟尚未深核"
    else:
        done = state.get('scan_groups') or 0
        total = state.get('scan_total')
        detail = f"缺口待核验 · 已扫描 {done}" + (f' / {total} 组' if total is not None else ' 组')
        if state.get('state') in ('stopped', 'paused', 'failed'):
            detail += '；扫描未完成'
    return f"目标 {target} · {detail} · 本轮查询 {state.get('queries') or 0} 次，发布 {state.get('inserted') or 0} 条"
