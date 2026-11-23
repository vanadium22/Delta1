"""Excel arithmetic with dated concrete-contract dividend observations."""
from pathlib import Path
from math import isfinite
from numbers import Real

from .dividends import DividendBook,adjusted_basis,digest


FORMULA='(F - S + D) / S × 365 / T × 100%'
DEFAULT_MIN_ANNUAL_DAYS=1


def validate_annual_min_days(value):
    if type(value) is not int or not 1 <= value <= 3650:
        raise ValueError('最小剩余自然日须为1–3650的整数')
    return value


def annual_min_days(config):
    return validate_annual_min_days(config.get('overview_min_annual_days',DEFAULT_MIN_ANNUAL_DAYS))


def input_summary(row):
    """Display the exact arithmetic inputs, without rounding before calculation."""
    def number(key):
        value=row.get(key)
        return format(value,'.10g') if isinstance(value,Real) and not isinstance(value,bool) and isfinite(value) else '—'
    estimate = dividend_estimate_label(row.get('dividend_inherited_from'), row.get('dividend_interpolation'))
    return ('F='+number('basis_future_price')+' · S='+number('basis_spot_price')+
        ' · D='+number('dividend_points')+' · T='+number('days')+'天\n定价日 '+str(row.get('pricing_day') or '—')+
        '；分红表业务日 '+str(row.get('dividend_snapshot') or '—')+
        ('（沿用早于定价日的表）' if row.get('dividend_carried_forward') else '')+
        ('\n'+estimate if estimate else ''))


def dividend_estimate_label(donor, interpolation):
    labels = ['借用 '+donor] if donor else []
    if interpolation == 'between_snapshots':
        labels.append('快照间插值')
    elif interpolation == 'to_expiry':
        labels.append('沿到期日归零')
    return '、'.join(labels)


def calculate(future,spot,dividend,days,*,min_annual_days=DEFAULT_MIN_ANNUAL_DAYS):
    # Shared Excel arithmetic, independent of the paused research-v6 formulas.
    if (any(isinstance(v,bool) or not isinstance(v,Real) or not isfinite(v) for v in (future,spot,dividend)) or
        future<=0 or spot<=0 or dividend<0):return adjusted_basis(None,None,None,days,min_annual_days=min_annual_days)
    return adjusted_basis(future,spot,dividend,days,min_annual_days=min_annual_days)


def input_token(config,metadata,day,local_root=None):
    from .overview_dividends import local_sources,directory
    paths=local_sources(config,history=True)
    if local_root:
        records=directory(config,local_root)/'records.sqlite'
        paths.extend((records, records.with_name(records.name+'-wal')))
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
            original=DividendBook.load('',daily_file=config.get('daily_dividend_file'),mode=mode)
            if original.reason:
                return original
            from .overview_dividends import OverviewDividendBook
            rows=[dict(contract_id=r['instrument_id'],points=r['points'],source_business_date=r['date'],
                       effective_from=r['date']+'T00:00:00+08:00',precision='day',source_kind='daily_concrete',
                       revision=digest(r)) for r in original.info['rows']]
            return OverviewDividendBook(rows,metadata,day=day)
        from .overview_dividends import load
        return load(config,metadata,day,local_root)
    except Exception as exc:
        return DividendBook(mode=mode,reason='分红输入不可用（'+type(exc).__name__+'）；保留行情，不把缺值当0')


def dividend_record(book,symbol,when):
    if book is None:return {}
    if hasattr(book,'resolve'):return book.resolve(symbol,when) or {}
    return dict((getattr(book,'info',{}) or {}).get('mapping',{}).get(symbol,{}),
        points=book.points(symbol,when),revision=getattr(book,'version',None))


def historical_dividend(book,symbol,day):
    from .overview_dividends import HISTORICAL_CUTOFF
    book = dividend_history(book)
    if hasattr(book,'historical_record'):
        return book.historical_record(symbol,day)
    if hasattr(book,'resolve_contract'):
        return book.resolve_contract(symbol,day+HISTORICAL_CUTOFF) or {}
    return dividend_record(book,symbol,day)


def dividend_history(book, day=None, now=None):
    return book.historical_view(day, now) if hasattr(book, 'historical_view') else book
