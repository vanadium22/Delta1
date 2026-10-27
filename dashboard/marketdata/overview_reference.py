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
    result={k:v for k,v in value.items() if k in ('status','provider','error_type','reason','warnings','started_at','finished_at')}
    diagnostics=value.get('diagnostics') or {}
    if isinstance(diagnostics,dict):
        result['diagnostics']={k:v for k,v in diagnostics.items() if k in ('provider','python','user_site_enabled','requested_day',
            'operations','groups','etf_sector','tracking_field','aum_field','aum_unit','aum_field_comment')}
        for name in ('etf_universe_attempts','tracking_attempts'):
            rows=diagnostics.get(name)
            if isinstance(rows,list):result['diagnostics'][name]=[{k:v for k,v in row.items() if k in
                ('sector','candidates','field','matching','unresolved','unresolved_sample','error_type','reason')} for row in rows if isinstance(row,dict)]
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
                    if not finite(row.get('weight_pct')) or not 0 <= row['weight_pct'] <= 100:
                        raise ValueError('指数权重必须是0至100的百分比')
                else:
                    if symbol in fund_roots and fund_roots[symbol]!=root:
                        raise ValueError('同一ETF不能同时属于两个标的指数')
                    fund_roots[symbol]=root
                    if row.get('index_id') != ROOTS[root] or row.get('ordinary_etf') is not True:
                        raise ValueError('ETF须确认普通ETF及相同标的指数')
                    if not finite(row.get('aum_cny')) or row['aum_cny'] <= 0 or day(row.get('aum_date')) != group['as_of']:
                        raise ValueError('ETF规模须是同一日期的正数人民币资产净值')
            if kind == 'indices' and rows and not 99 <= sum(r['weight_pct'] for r in rows) <= 101:
                raise ValueError('完整指数权重合计偏离100%，不自动归一化')
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
                    due=fetched.astimezone(now.tzinfo).isocalendar()[:2] != now.isocalendar()[:2], error=None)
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
