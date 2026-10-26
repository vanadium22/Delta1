"""Explicit overview subscriptions. No configuration writes or network access."""
import re

from .instruments import UNDERLYINGS


# Representative trackers, not a ranking by current assets or trading volume.
DEFAULT_ETFS = (
    ('510300.SH', '华泰柏瑞沪深300ETF', 'IF'),
    ('510050.SH', '华夏上证50ETF', 'IH'),
    ('510500.SH', '南方中证500ETF', 'IC'),
    ('512100.SH', '南方中证1000ETF', 'IM'),
)
SECURITY = re.compile(r'[0-9]{6}\.(?:SH|SZ)')
REFERENCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')


def etfs(config, reference=None, today=None):
    result = {s: dict(symbol=s, name=n, root=r, underlying=UNDERLYINGS[r][0], iopv_id=None)
              for s, n, r in DEFAULT_ETFS}
    for row in config.get('overview_etfs', ()):
        if not isinstance(row, dict) or not SECURITY.fullmatch(str(row.get('symbol', ''))) or row.get('root') not in UNDERLYINGS:
            continue
        s, r = row['symbol'], row['root']
        result[s] = dict(symbol=s, name=str(row.get('name') or s), root=r,
                         underlying=UNDERLYINGS[r][0], iopv_id=None)
    if reference:
        from dashboard.marketdata.overview_reference import ranking
        from datetime import datetime
        for root in UNDERLYINGS:
            ranked, _ = ranking(reference, root, today=today or datetime.now().date().isoformat())
            if ranked:
                result = {s:r for s,r in result.items() if r['root'] != root}
                for item in ranked:
                    result[item['symbol']] = dict(item, root=root, underlying=UNDERLYINGS[root][0], iopv_id=None)
    for mapping in (config.get('research_etf_iopv_mapping') or {}).values():
        if not isinstance(mapping, dict):
            continue
        s, i = mapping.get('etf_id'), mapping.get('iopv_id')
        root = next((r for r, v in UNDERLYINGS.items() if v[0] == mapping.get('underlying_id')), None)
        if not root or not SECURITY.fullmatch(str(s or '')) or not REFERENCE.fullmatch(str(i or '')) or s == i:
            continue
        row = result.setdefault(s, dict(symbol=s, name=s, root=root, underlying=UNDERLYINGS[root][0]))
        if row['underlying'] == mapping['underlying_id']:
            row['iopv_id'] = i
    return list(result.values())


def quote_registry(config, reference=None, today=None):
    selected = etfs(config, reference, today)
    registry = {s: dict(asset_type='cn_etf', market_region='CN') for s in (r['symbol'] for r in selected)}
    for row in selected:
        if row.get('iopv_id'):
            registry[row['iopv_id']] = dict(asset_type='cn_etf_reference', market_region='CN')
    return registry
