"""Auditable continuous-slot distributions, isolated from contract research signals."""
import numpy as np
import pandas as pd

from dashboard.marketdata.dividends import digest
from dashboard.marketdata.quote_quality import finite

SLOT_NAMES=("00 当月", "01 次月", "02 季月", "03 远季")


def slot_map(metadata, root, day):
    """Expiry day remains in the old slot; the next listing day forms the new map."""
    stamp=pd.Timestamp(day)
    day=str((stamp.tz_convert('Asia/Shanghai') if stamp.tzinfo else stamp).date())
    active=sorted((s for s,r in metadata.items() if s.startswith(root) and r['listing_date']<=day<=r['expiry_date']),
                  key=lambda s:metadata[s]['expiry_date'])
    if len(active)!=4 or len({metadata[s]['expiry_date'] for s in active})!=4:
        return {},f"{day} {root} 无法形成四档唯一合约映射"
    return {f'{root}0{i}.CFE':s for i,s in enumerate(active)},''


def slot_history(root, slot, daily, calendar, metadata, dividends, current_symbol, as_of):
    """A fixed snapshot scenario is explicitly applied to one slot's whole history.

    This panel feeds distributions only. It never enters returns, OI or drift
    indicators. Daily dividend mode instead uses each mapped contract/date exactly.
    """
    alias=f'{root}0{slot}.CFE'
    from .instruments import UNDERLYINGS
    spot=daily.get(UNDERLYINGS[root][0],pd.DataFrame()).get('close',pd.Series(dtype=float))
    fixed_d=dividends.points(current_symbol,pd.Timestamp(as_of).tz_convert('Asia/Shanghai').date())
    # D is bound to the concrete contract, so an existing contract keeps its D
    # when its slot changes. A newly listed contract has no D until supplied.
    records=[]
    for t in calendar:
        day=t.tz_convert('Asia/Shanghai').date();mapping,error=slot_map(metadata,root,day)
        symbol=mapping.get(alias);ref=metadata.get(symbol,{})
        series=daily.get(symbol,pd.DataFrame()).get('close',pd.Series(dtype=float))
        f=series.get(t,np.nan);s=spot.get(t,np.nan)
        days=(pd.Timestamp(ref['expiry_date']).date()-day).days if ref else np.nan
        d=fixed_d if dividends.mode=='fixed_snapshot' else dividends.points(symbol,day) if symbol else None
        d=float(d) if finite(d) else np.nan
        points=f-s+d if finite(f) and finite(s) and s>0 else np.nan
        bp=10000*points/s if finite(points) else np.nan
        annual=bp*365/(100*days) if finite(days) and days>=5 else np.nan
        if not error:
            error='分红情景缺失' if pd.isna(d) else '具体合约或指数日线缺数' if not finite(bp) else ''
        records.append(dict(time=t,symbol=symbol,expiry=ref.get('expiry_date'),F=f,S=s,D=d,T=days,
            points=points,basis=bp,annual=annual,reason=error))
    frame=pd.DataFrame(records).set_index('time') if records else pd.DataFrame(columns=['symbol','expiry','F','S','D','T','points','basis','annual','reason'],index=calendar)
    reference=digest({s:(r['listing_date'],r['expiry_date'],r.get('known_at')) for s,r in sorted(metadata.items()) if s.startswith(root)})
    version=digest(dict(alias=alias,reference=reference,dividend=dividends.version,mode=dividends.mode,
        assumption=fixed_d,current_contract=current_symbol))
    return frame,dict(alias=alias,reference_version=reference,version=version,dividend=fixed_d,
        mode='continuous_fixed_scenario' if dividends.mode=='fixed_snapshot' else 'continuous_daily_dividends',
        policy='历日挂牌/到期排序重建，交割日保留旧映射；非当时可得映射',
        assumption='当前明确映射合约的固定D，统一用于本档位全部历史；非真实逐日分红' if dividends.mode=='fixed_snapshot' else '按历日具体合约精确读取剩余分红',
        mappings=[dict(date=str(t.tz_convert('Asia/Shanghai').date()),symbol=r.symbol if pd.notna(r.symbol) else None,expiry=r.expiry if pd.notna(r.expiry) else None,
            dividend=float(r.D) if pd.notna(r.D) else None,days=int(r['T']) if pd.notna(r['T']) else None,reason=r.reason) for t,r in frame.iterrows()])
