"""Refresh dated CFFEX listings without DDB, calendar guesses or VPN changes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
from xml.etree import ElementTree as ET

import pandas as pd
import requests

from index_strategy.instant_dld.service import write_json
from .repository import ReferenceBook

PRODUCTS = ('IF', 'IH', 'IC', 'IM')
SOURCE = 'http://www.cffex.com.cn/sj/jycs/{month}/{day}/index.xml'
_LOCK = threading.RLock()


def latest_contracts(data):
    result = {}
    for row in data.get('contracts', []):
        old = result.get(row['instrument_id'])
        if old is None or pd.Timestamp(row['known_at']) > pd.Timestamp(old['known_at']):
            result[row['instrument_id']] = row
        elif pd.Timestamp(row['known_at']) == pd.Timestamp(old['known_at']) and (
                row['listing_date'], row['expiry_date']) != (old['listing_date'], old['expiry_date']):
            raise ValueError('同版本合约参考冲突：' + row['instrument_id'])
    return result


def active_contracts(data, day):
    day = str(day)
    return sorted(s for s, r in latest_contracts(data).items()
                  if r['listing_date'] <= day <= r['expiry_date'])


def parse_parameters(raw, day, known_at, url):
    """Validate each product independently; never infer an absent listing/date."""
    tree = ET.fromstring(raw)
    groups = {p: {} for p in PRODUCTS}
    errors = {}
    for item in tree.findall('.//INDEX'):
        code = (item.findtext('INSTRUMENT_ID') or '').strip().upper()
        if not re.fullmatch(r'(?:IF|IH|IC|IM)\d{4}', code):
            continue
        product = code[:2]
        try:
            parse_day = lambda key: datetime.strptime((item.findtext(key) or '').strip(), '%Y%m%d').date()
            listing, expiry, source_day = (parse_day(k) for k in ('OPEN_DATE', 'END_TRADING_DAY', 'TRADING_DAY'))
            if source_day != day or not listing <= day <= expiry:
                raise ValueError('交易日或挂牌区间不符')
            if expiry.strftime('%y%m') != code[2:] or item.findtext('PRODUCT_ID', '').strip().upper() != product:
                raise ValueError('品种或到期月份不符')
            row = dict(instrument_id=code+'.CFE', listing_date=str(listing), expiry_date=str(expiry),
                       known_at=known_at, source='cffex_trade_parameters', source_url=url, source_trade_date=str(day))
            if code in groups[product] and groups[product][code] != row:
                raise ValueError('重复合约日期冲突')
            groups[product][code] = row
        except ValueError as exc:
            errors[product] = f'{code}: {exc}'
    contracts = []
    for product, rows in groups.items():
        if len(rows) != 4 or len({r['expiry_date'] for r in rows.values()}) != 4:
            errors[product] = f'{product} 官方参数未提供四档唯一合约'
        if product not in errors:
            contracts.extend(rows.values())
    if not contracts:
        raise ValueError('；'.join(errors.values()) or '未找到股指期货合约')
    return contracts, errors


def fetch_parameters(day):
    """The exchange publishes this public, unauthenticated XML over HTTP."""
    with requests.Session() as session:
        for offset in range(8):
            target = day - timedelta(days=offset)
            url = SOURCE.format(month=target.strftime('%Y%m'), day=target.strftime('%d'))
            with session.get(url, timeout=(4, 8), headers={'User-Agent': 'Mozilla/5.0'}) as response:
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                return response.content, target, url
    raise ValueError('最近8个自然日没有可用的中金所合约参数')


def check_quotes(symbols):
    from index_strategy.instant_dld.client import MarketDataClient
    from math import isfinite
    client=MarketDataClient(connect_timeout=4,read_timeout=8)
    try:
        result=client.fetch(symbols)
        data=(result.get('response') or {}).get('data',{})
        verified=[]
        for symbol in symbols:
            quote=data.get(symbol) or {}
            price=quote.get('latestPrice')
            if (quote.get('securityId')==symbol and isinstance(price,(int,float))
                    and not isinstance(price,bool) and isfinite(price) and 0<price<1e10):
                verified.append(symbol)
        return dict(status=result['status'],verified=verified,missing=sorted(set(symbols)-set(verified)),
                    received_at=result.get('received_at'),http_status=result.get('http_status'),
                    note='行情代码/有效价格交叉验证；挂牌日和到期日以中金所参数为准')
    finally:
        client.close()


def synchronize(reference_file, directory, *, now=None, force=False, fetcher=fetch_parameters, quote_checker=check_quotes):
    """Atomic managed reference plus immutable versions; daily success / 5 min retry.

    The selected historical reference is preserved. Failures retain valid local
    contracts, but expired contracts are never selected as a fallback.
    """
    stamp = pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert('Asia/Shanghai')
    day = stamp.date()
    directory = Path(directory).resolve()
    current = directory/'current.json'
    state_file = directory/'status.json'
    with _LOCK:
        base = ReferenceBook(reference_file or None).data
        data = deepcopy(ReferenceBook(current).data if current.exists() else base)
        # An explicitly imported reference may add history; do not discard auto updates.
        seen = {(r['instrument_id'], r['known_at']): r for r in data.get('contracts', [])}
        for row in base.get('contracts', []):
            key = (row['instrument_id'], row['known_at'])
            if key in seen and (seen[key]['listing_date'], seen[key]['expiry_date']) != (row['listing_date'], row['expiry_date']):
                raise ValueError('导入资料与缓存合约参考冲突：'+row['instrument_id'])
            if key not in seen:
                data.setdefault('contracts', []).append(row); seen[key] = row
        data['schema_version'] = 'cn_index_reference_v1'
        data.setdefault('aliases', [])
        status = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
        cached = (status.get('checked_day') == str(day) and
                  ((status.get('complete') and not status.get('quote_verification',{}).get('missing'))
                   or stamp < pd.Timestamp(status.get('retry_after', '1970-01-01T00:00Z'))))
        if force or not cached:
            status = dict(checked_day=str(day), checked_at=stamp.isoformat(), complete=False,
                          retry_after=(stamp+pd.Timedelta(minutes=5)).isoformat(), errors={})
            try:
                raw, source_day, url = fetcher(day)
                if not day-timedelta(days=7)<=source_day<=day:
                    raise ValueError('官方参数日期超出查询范围')
                rows, errors = parse_parameters(raw, source_day, stamp.isoformat(), url)
                raw_hash = hashlib.sha256(raw).hexdigest()
                raw_path = directory/'raw'/f'{source_day}_{raw_hash[:16]}.xml'
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                if not raw_path.exists():
                    raw_path.write_bytes(raw)
                latest = latest_contracts(data)
                changed = []
                for row in rows:
                    previous = latest.get(row['instrument_id'])
                    if previous is None or (previous['listing_date'], previous['expiry_date']) != (row['listing_date'], row['expiry_date']):
                        data['contracts'].append(row); changed.append(row['instrument_id'])
                status.update(source_day=str(source_day), source_url=url, raw_path=str(raw_path),
                              changed=changed, errors=errors, complete=source_day == day and not errors)
            except (requests.RequestException, OSError, ValueError, ET.ParseError) as exc:
                status['error'] = f'{type(exc).__name__}: {exc}'
        # Alias rows are historical evidence only; live aliases are resolved by dated listings.
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')
        version = hashlib.sha256(payload).hexdigest()[:24]
        version_file = directory/'versions'/f'{version}.json'
        if not version_file.exists():
            write_json(version_file, data)
        if not current.exists() or ReferenceBook(current).data != data:
            write_json(current, data)
        active = active_contracts(data, day)
        missing = [p for p in PRODUCTS if len([s for s in active if s.startswith(p)]) != 4]
        if missing:status['complete']=False
        if (force or not cached) and quote_checker and active:
            try:
                status['quote_verification']=quote_checker(active)
            except Exception as exc:
                status['quote_verification']=dict(status='failed',verified=[],missing=active,error=str(exc))
        status.update(reference_file=str(current), version=version, active_contracts=active, incomplete_products=missing)
        status['message'] = ('合约自动更新：' + str(status.get('source_day', '本地缓存')) +
                             (' · 待补齐 '+ '/'.join(missing) if missing else ' · 四品种四档齐全'))
        if status.get('error') or status.get('errors'):
            status['message'] += ' · 查询失败/不完整，保留有效本地合约，5分钟后重试'
        elif status.get('source_day') != str(day):
            status['message'] += ' · 当日参数待发布，5分钟后重试'
        quote=status.get('quote_verification',{})
        if quote:
            status['message'] += f" · 行情核验 {len(quote['verified'])}/{len(active)}"
        if not state_file.exists() or json.loads(state_file.read_text(encoding='utf-8')) != status:
            write_json(state_file, status)
        return status
