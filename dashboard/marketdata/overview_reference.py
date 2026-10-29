"""Dated overview reference snapshots. Reading never connects or changes settings.

Weights are percentages of the whole index, not normalised over received quotes.
A ranking requires the complete, same-date universe of ordinary benchmark ETFs.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOTS = {'IF': '000300.SH', 'IH': '000016.SH', 'IC': '000905.SH', 'IM': '000852.SH'}
SECURITY = re.compile(r'[0-9]{6}\.(?:SH|SZ)')
SCHEMA = 'overview-reference-v1'


def worker_status(value):
    """Share controlled diagnostics only, never arbitrary status/config keys."""
    if not isinstance(value,dict):return dict(status='not_recorded')
    result={k:v for k,v in value.items() if k in ('status','provider','error_type','started_at','finished_at')}
    if isinstance(value.get('warnings'),list):
        result['warning_count']=len(value['warnings'])
    diagnostics=value.get('diagnostics') or {}
    if isinstance(diagnostics,dict):
        from .wind_terminal_worker import safe_diagnostics
        result['diagnostics']=safe_diagnostics(diagnostics)
    steps=result.get('diagnostics',{}).get('steps') or []
    result['stage_evidence_recorded']=bool(steps)
    if value.get('reason'):
        result['reason']=('低频任务未完成；安全失败阶段与ErrorCode见diagnostics，具体原因待核验' if steps else
            '该历史任务未保留分阶段证据；本次只读诊断未重新查询Wind，需显式Wind阶段测试取得新结果')
    return result


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def day(value):
    return date.fromisoformat(str(value)).isoformat()


def path_for(config, local_root):
    return Path(config.get('overview_reference_file') or Path(local_root)/'overview_reference/latest.json')


def validate(data):
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        raise ValueError('低频资料格式不匹配')
    value = deepcopy(data)
    fetched = datetime.fromisoformat(value['fetched_at'])
    if fetched.tzinfo is None:
        raise ValueError('资料取得时间缺时区')
    reviewed=datetime.fromisoformat(value.get('reference_reviewed_at') or value['fetched_at'])
    if reviewed.tzinfo is None or reviewed>fetched:raise ValueError('资料复核时间无效')
    fund_roots = {}
    for kind in ('indices', 'etfs'):
        groups = value.setdefault(kind, {})
        if not isinstance(groups, dict) or set(groups)-set(ROOTS):
            raise ValueError('资料指数身份无效')
        for root, group in groups.items():
            if not isinstance(group, dict):
                raise ValueError('资料分组无效')
            if group.get('index_id') != ROOTS[root] or not group.get('source'):
                raise ValueError('资料缺对应指数或来源')
            group['as_of'] = day(group['as_of'])
            if group['as_of'] > fetched.date().isoformat():
                raise ValueError('资料日期晚于取得日期')
            rows = group.get('rows', [])
            if not isinstance(rows, list) or len(rows) > (3000 if kind == 'indices' else 300):
                raise ValueError('资料行数无效')
            seen = set()
            partial_weights=kind=='indices' and group.get('weights_complete') is False
            if partial_weights:
                if group.get('membership_complete') is not True or len(rows)!={'IF':300,'IH':50,'IC':500,'IM':1000}[root]:
                    raise ValueError('未核验权重须附完整成分名单')
                if day(group.get('membership_as_of'))>fetched.date().isoformat():raise ValueError('成分请求日期晚于取得日期')
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('资料行格式无效')
                symbol = row.get('symbol')
                if not isinstance(symbol, str) or not SECURITY.fullmatch(symbol) or symbol in seen:
                    raise ValueError('资料代码无效或重复')
                seen.add(symbol)
                if row.get('name') is not None and (not isinstance(row['name'],str) or len(row['name'])>128):
                    raise ValueError('资料名称无效')
                if kind == 'indices':
                    if row.get('industry') is not None and (not isinstance(row['industry'],str) or len(row['industry'])>64):
                        raise ValueError('行业名称无效')
                    if not (partial_weights and row.get('weight_pct') is None) and (not finite(row.get('weight_pct')) or not 0 <= row['weight_pct'] <= 100):
                        raise ValueError('指数权重必须是0至100的百分比')
                else:
                    if symbol in fund_roots and fund_roots[symbol]!=root:
                        raise ValueError('同一ETF不能同时属于两个标的指数')
                    fund_roots[symbol]=root
                    if row.get('index_id') != ROOTS[root] or row.get('ordinary_etf') is not True:
                        raise ValueError('ETF须确认普通ETF及相同标的指数')
                    if not finite(row.get('aum_cny')) or row['aum_cny'] <= 0 or day(row.get('aum_date')) != group['as_of']:
                        raise ValueError('ETF规模须是同一日期的正数人民币资产净值')
            if kind == 'indices' and rows and not partial_weights and not 99 <= sum(r['weight_pct'] for r in rows) <= 101:
                raise ValueError('完整指数权重合计偏离100%，不自动归一化')
    if 'etf_nav' in value:
        nav=value['etf_nav']
        if not isinstance(nav,dict) or nav.get('schema')!='etf-nav-v1' or not isinstance(nav.get('rows'),dict) or len(nav['rows'])>100:
            raise ValueError('ETF净值缓存格式无效')
        for symbol,row in nav['rows'].items():
            if not SECURITY.fullmatch(symbol) or not isinstance(row,dict) or row.get('symbol')!=symbol:raise ValueError('ETF净值代码不匹配')
            if day(row['as_of'])>fetched.date().isoformat() or not row.get('source'):raise ValueError('ETF净值日期或来源无效')
            if not all(finite(row.get(k)) and row[k]>0 for k in ('nav_cny','close_cny')):raise ValueError('ETF净值/同日收盘无效')
    return value


def load(config, local_root, *, now=None):
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    path = path_for(config, local_root)
    try:
        raw = path.read_bytes()
        data = validate(json.loads(raw))
        fetched = datetime.fromisoformat(data['fetched_at'])
        if fetched > now:
            raise ValueError('资料取得时间晚于当前时刻')
        return dict(data=data, version=hashlib.sha256(raw).hexdigest(),
                    due=datetime.fromisoformat(data.get('reference_reviewed_at') or data['fetched_at']).astimezone(now.tzinfo).isocalendar()[:2] != now.isocalendar()[:2], error=None)
    except FileNotFoundError:
        return dict(data={}, version=None, due=True, error='尚无已核验低频资料')
    except (OSError, ValueError, TypeError, KeyError):
        return dict(data={}, version=None, due=True, error='低频资料不可用；保留文件，等待核验')


def ranking(reference, root, *, today):
    group = reference.get('etfs', {}).get(root, {})
    rows = group.get('rows', [])
    as_of = group.get('as_of')
    if not as_of:
        return [], dict(reason='规模前三待核验；尚无该指数ETF规模资料', as_of=None)
    if as_of > today:
        return [], dict(reason='规模日期晚于当前日', as_of=None)
    if group.get('complete') is not True or not rows:
        return [], dict(reason='规模前三待核验；需要同指数完整ETF规模资料', as_of=group.get('as_of'))
    ordered = sorted(rows, key=lambda r: (-r['aum_cny'], r['symbol']))
    total = sum(r['aum_cny'] for r in ordered)
    result = [dict(r, rank=i+1, aum_share_pct=100*r['aum_cny']/total) for i, r in enumerate(ordered[:3])]
    return result, dict(reason=None, as_of=group['as_of'], source=group['source'], reviewed_at=group.get('reviewed_at'),
                        universe_count=len(rows), total_aum_cny=total)


def closing_nav(reference, symbol, today):
    """The page and offline evidence share the same dated close/NAV selection."""
    row=reference.get('etf_nav',{}).get('rows',{}).get(symbol,{})
    nav,close=row.get('nav_cny'),row.get('close_cny')
    valid=bool(row.get('as_of')) and row['as_of']<=today and finite(nav) and nav>0 and finite(close) and close>0
    return dict(closing_nav_cny=nav if valid else None,closing_price_cny=close if valid else None,
        nav_date=row.get('as_of') if valid else None,closing_premium_bp=10000*(close/nav-1) if valid else None,
        closing_premium_reason='同一交易日未复权收盘 / 单位净值；非盘中IOPV' if valid else '待同日单位净值和未复权收盘，未以前值填充')


def publish(path, data):
    """Publish only validated data; retain the last good version and all archives."""
    from dashboard.marketdata.bars import _atomic_bytes, _json_bytes
    value = validate(data)
    path = Path(path)
    raw = _json_bytes(value)
    digest = hashlib.sha256(raw).hexdigest()[:16]
    archive = path.parent/'archive'/(value['fetched_at'][:10]+'-'+digest+'.json')
    _atomic_bytes(archive, raw)
    _atomic_bytes(path, raw)
    return value
