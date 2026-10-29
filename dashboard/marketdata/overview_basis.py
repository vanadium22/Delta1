"""Excel arithmetic with dated concrete-contract dividend observations."""
from pathlib import Path
from math import isfinite
from numbers import Real

from .dividends import DividendBook,adjusted_basis,digest


FORMULA='(F - S + D) / S × 365 / T × 100%'


def input_summary(row):
    """Display the exact arithmetic inputs, without rounding before calculation."""
    def number(key):
        value=row.get(key)
        return format(value,'.10g') if isinstance(value,Real) and not isinstance(value,bool) and isfinite(value) else '—'
    return ('F='+number('basis_future_price')+' · S='+number('basis_spot_price')+
        ' · D='+number('dividend_points')+' · T='+number('days')+'天\n定价日 '+str(row.get('pricing_day') or '—')+
        '；分红表业务日 '+str(row.get('dividend_snapshot') or '—'))


def calculate(future,spot,dividend,days):
    # Shared Excel arithmetic, independent of the paused research-v6 formulas.
    if (any(isinstance(v,bool) or not isinstance(v,Real) or not isfinite(v) for v in (future,spot,dividend)) or
        future<=0 or spot<=0 or dividend<0):return adjusted_basis(None,None,None,days)
    return adjusted_basis(future,spot,dividend,days)


def input_token(config,metadata,day,local_root=None):
    from .overview_dividends import local_sources,directory
    paths=local_sources(config)
    if local_root:paths.append(directory(config,local_root)/'records.sqlite')
    paths += [Path(config[k]) for k in ('daily_dividend_file','dividend_scenario_file') if config.get(k)]
    entries=[]
    for path in paths:
        try:info=path.stat();entries.append((str(path),info.st_mtime_ns,info.st_size))
        except (OSError,ValueError):entries.append((str(path),None,None))
    return (config.get('dividend_mode','fixed_snapshot'),tuple(entries),day,
        tuple((s,r.get('listing_date'),r.get('expiry_date')) for s,r in sorted(metadata.items())))


def load_dividends(config,metadata,day,local_root=None):
    mode=config.get('dividend_mode','fixed_snapshot')
    try:
        if mode=='daily_remaining':
            return DividendBook.load('',daily_file=config.get('daily_dividend_file'),mode=mode)
        from .overview_dividends import load
        return load(config,metadata,day,local_root)
    except Exception as exc:
        return DividendBook(mode=mode,reason='分红输入不可用（'+type(exc).__name__+'）；保留行情，不把缺值当0')


def dividend_record(book,symbol,when):
    if book is None:return {}
    if hasattr(book,'resolve'):return book.resolve(symbol,when) or {}
    return dict((getattr(book,'info',{}) or {}).get('mapping',{}).get(symbol,{}),
        points=book.points(symbol,when),revision=getattr(book,'version',None))
