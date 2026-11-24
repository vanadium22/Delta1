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


def reference_paths(reference_file, local_root):
    managed = Path(local_root)/'contract_reference/current.json' if local_root else None
    return tuple(dict.fromkeys(Path(p) for p in (reference_file, managed if managed and managed.is_file() else None) if p))


def merge_references(base, cached):
    data = deepcopy(cached)
    seen = {(r['instrument_id'], r['known_at']): r for r in data.get('contracts', [])}
    for row in base.get('contracts', []):
        key = (row['instrument_id'], row['known_at'])
        previous = seen.get(key)
        if previous is not None:
            if (previous['listing_date'], previous['expiry_date']) != (row['listing_date'], row['expiry_date']):
                raise ValueError('导入资料与缓存合约参考冲突：'+row['instrument_id'])
        else:
            data.setdefault('contracts', []).append(row)
            seen[key] = row
    return data


def read_app_reference(reference_file, local_root, *, book_factory=ReferenceBook):
    paths = reference_paths(reference_file, local_root)
    if len(paths) < 2:
        book = book_factory(paths[0] if paths else None)
        return book.data, book.version
    base, cached = (book_factory(path) for path in paths)
    return merge_references(base.data, cached.data), (base.version, cached.version)


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


def contract_coverage(metadata, day):
    day = str(day)
    result = {}
    for product in PRODUCTS:
        active = sorted((s for s,r in metadata.items() if s.startswith(product)
                         and r['listing_date'] <= day <= r['expiry_date']),
                        key=lambda s:(metadata[s]['expiry_date'], s))
        result[product] = dict(contracts=active, count=len(active),
            complete=len(active) == len({metadata[s]['expiry_date'] for s in active}) == 4)
    return result


def publish_reference(directory, data):
    current = directory/'current.json'
    data['schema_version'] = 'cn_index_reference_v1'
    data.setdefault('aliases', [])
    version = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:24]
    version_file = directory/'versions'/f'{version}.json'
    if not version_file.exists():
        write_json(version_file, data)
    if not current.exists() or ReferenceBook(current).data != data:
        write_json(current, data)
    return version


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
        data = merge_references(base, ReferenceBook(current).data) if current.exists() else base
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
        version = publish_reference(directory, data)
        active = active_contracts(data, day)
        coverage = contract_coverage(latest_contracts(data), day)
        missing = [p for p, row in coverage.items() if not row['complete']]
        if missing:status['complete']=False
        if (force or not cached) and quote_checker and active:
            try:
                status['quote_verification']=quote_checker(active)
            except Exception as exc:
                status['quote_verification']=dict(status='failed',verified=[],missing=active,error=str(exc))
        status.update(reference_file=str(current), version=version, active_contracts=active,
                      incomplete_products=missing, coverage=coverage)
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


def recover_from_ddb(client, reference_file, local_root, days, *, now):
    """Use the existing DDB session to verify actual listings for bounded dates."""
    import numpy as np

    directory = Path(local_root)/'contract_reference'
    data, _ = read_app_reference(reference_file, local_root)
    existing = latest_contracts(data)
    first, last = min(days), max(days)
    candidates = [f'{root}{year % 100:02}{month:02}.CFE' for root in PRODUCTS
                  for year in range(int(first[:4]), int(last[:4])+2) for month in range(1,13)]
    client.session.upload(dict(rollCodes=candidates, rollStart=np.datetime64(first, 'D'),
                               rollEnd=np.datetime64(last, 'D')))
    source = 'loadTable("dfs://ods_tsdb_wind","cfuturesdescription")'
    fields = 'S_INFO_WINDCODE,S_INFO_LISTDATE,S_INFO_DELISTDATE,OPDATE'
    frame = client.session.run(f'select top 1025 {fields} from {source} '
                               'where S_INFO_WINDCODE in rollCodes, S_INFO_LISTDATE<=rollEnd, S_INFO_DELISTDATE>=rollStart')
    if not set(fields.split(',')) <= set(frame) or len(frame) > 1024 or not set(frame.S_INFO_WINDCODE) <= set(candidates):
        raise ValueError('DDB合约参考字段、行数或代码不符')
    received = pd.Timestamp.now(tz='Asia/Shanghai').isoformat()
    rows, invalid = {}, set()
    for symbol, group in frame.groupby('S_INFO_WINDCODE'):
        try:
            clocks = pd.to_datetime(group['OPDATE'], errors='raise', utc=True)
            latest = clocks.max()
            tied = group.loc[clocks.eq(latest)] if pd.notna(latest) else group
            spans = {(pd.Timestamp(r.S_INFO_LISTDATE).date().isoformat(),
                      pd.Timestamp(r.S_INFO_DELISTDATE).date().isoformat()) for r in tied.itertuples()}
            if len(spans) != 1:
                raise ValueError('合约日期版本冲突')
            listing, expiry = spans.pop()
            if listing > expiry or expiry[2:4]+expiry[5:7] != symbol[2:6]:
                raise ValueError('合约月份或区间不符')
            rows[symbol] = dict(instrument_id=symbol, listing_date=listing, expiry_date=expiry,
                known_at=received, source='ddb_wind_cfuturesdescription', source_updated_at=latest.isoformat(),
                source_requested_days=list(days), recovery_started_at=now.isoformat())
        except (ValueError, TypeError, OverflowError):
            invalid.add(symbol[:2])
    accepted = {}
    skipped = {}
    for day in days:
        for root, target in contract_coverage(existing, day).items():
            if target['complete']:
                continue
            candidate = contract_coverage(rows, day)[root]
            if root in invalid or not candidate['complete'] or not set(target['contracts']) <= set(candidate['contracts']):
                skipped.setdefault(day, []).append(root)
                continue
            # Keep the original verified dates for any already known contract.
            additions = {s: rows[s] for s in candidate['contracts'] if s not in existing}
            combined = contract_coverage({**existing, **additions}, day)[root]
            if not combined['complete'] or combined['contracts'] != candidate['contracts']:
                skipped.setdefault(day, []).append(root)
                continue
            accepted.update(additions)
    if accepted:
        data.setdefault('contracts', []).extend(accepted.values())
        publish_reference(directory, data)
    return dict(source='ddb_wind_cfuturesdescription', rows=len(frame), added=sorted(accepted), unresolved=skipped)
