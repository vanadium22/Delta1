"""Excel-style overview basis and one explicit, reusable dividend scenario."""
from copy import deepcopy
from datetime import date
from pathlib import Path
from math import isfinite
from numbers import Real

from .dividends import DividendBook,adjusted_basis,digest


FORMULA='(F - S + D) / S × 365 / T × 100%'


def calculate(future,spot,dividend,days):
    # Shared Excel arithmetic, independent of the paused research-v6 formulas.
    if (any(isinstance(v,bool) or not isinstance(v,Real) or not isfinite(v) for v in (future,spot,dividend)) or
        future<=0 or spot<=0 or dividend<0):return adjusted_basis(None,None,None,days)
    return adjusted_basis(future,spot,dividend,days)


def input_token(config,metadata,day):
    selected=config.get('overview_dividend_file') or config.get('dividend_root')
    paths=[]
    if selected:
        root=Path(selected)
        try:paths=[root] if root.is_file() else sorted(root.glob('*.xlsx'))
        except (OSError,ValueError):paths=[root]
    paths += [Path(config[k]) for k in ('daily_dividend_file','dividend_scenario_file') if config.get(k)]
    entries=[]
    for path in paths:
        try:info=path.stat();entries.append((str(path),info.st_mtime_ns,info.st_size))
        except (OSError,ValueError):entries.append((str(path),None,None))
    return (config.get('dividend_mode','fixed_snapshot'),str(selected),tuple(entries),day,
        tuple((s,r.get('listing_date'),r.get('expiry_date')) for s,r in sorted(metadata.items())))


def load_dividends(config,metadata,day):
    selected=config.get('overview_dividend_file') or config.get('dividend_root')
    mode=config.get('dividend_mode','fixed_snapshot')
    if not selected and mode!='daily_remaining':return DividendBook(reason='待已有Excel分红缓存或明确分红文件')
    try:
        book=DividendBook.load(selected or '',config.get('dividend_scenario_file'),config.get('daily_dividend_file'),mode,
            contracts=metadata,as_of=day,missing_policy='previous_contract')
    except Exception as exc:
        return DividendBook(mode=mode,reason='分红输入不可用（'+type(exc).__name__+'）；保留行情，不把缺值当0')
    if book.reason or mode!='fixed_snapshot':return book
    # Extend the same fixed scenario to historical concrete contracts. Only an
    # earlier expiry in the same product can supply an inherited value.
    mapping=deepcopy(book.info.get('mapping',{}))
    for symbol,ref in sorted(metadata.items(),key=lambda item:(item[0][:2],item[1]['expiry_date'])):
        if symbol in mapping:continue
        candidates=[s for s,r in mapping.items() if s[:2]==symbol[:2] and r['expiry']<ref['expiry_date']]
        if not candidates:continue
        predecessor=max(candidates,key=lambda s:mapping[s]['expiry']);origin=mapping[predecessor]
        mapping[symbol]=dict(points=origin['points'],expiry=ref['expiry_date'],inherited_from=predecessor,
            value_source_contract=origin.get('value_source_contract',predecessor),source_kind='previous_contract_estimate',
            source_snapshot=origin.get('source_snapshot',book.info.get('snapshot_date')))
    book.info={**book.info,'mapping':mapping,
        'historical_policy':'固定分红情景用于历史简单年化；缺失仅沿用前一到期合约，非逐日历史分红或时点回测'}
    book.version=digest(dict(base=book.version,mapping=mapping,formula=FORMULA))
    return book
