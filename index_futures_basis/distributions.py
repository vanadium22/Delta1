"""Calendar-month distributions and expiry-matched cross-index basis differences."""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS = (3, 6, 12)


def distribution_rows(series, end, value_column, eligible_column=None, windows=WINDOWS):
    """Windows are [end - N calendar months, end), excluding the current observation."""
    end = pd.Timestamp(end)
    g = series.sort_values("trade_date")
    current_rows = g[g.trade_date.eq(end)]
    current = current_rows.iloc[0][value_column] if len(current_rows) else np.nan
    rows = []
    for months in windows:
        start = end - pd.DateOffset(months=months)
        history = g[g.trade_date.ge(start) & g.trade_date.lt(end)]
        eligible = history[eligible_column] if eligible_column else pd.Series(True, index=history.index)
        values = history.loc[eligible, value_column].dropna()
        complete = bool(len(g) and g.trade_date.min() <= start and len(values) > 0
                        and len(values) == int(eligible.sum()))
        if "calendar_known" in history:
            complete = bool(complete and history.calendar_known.all())
        row = {"months": months, "window_start": start, "window_end_exclusive": end,
               "current": current, "n": len(values), "eligible_n": int(eligible.sum()),
               "complete": complete, "sample_start": history.loc[values.index, "trade_date"].min() if len(values) else pd.NaT,
               "sample_end": history.loc[values.index, "trade_date"].max() if len(values) else pd.NaT}
        for name, quantile in [("minimum", 0), ("p05", .05), ("p25", .25),
                               ("p50", .5), ("p75", .75), ("p95", .95), ("maximum", 1)]:
            row[name] = values.quantile(quantile, interpolation="linear") if complete else np.nan
        row["percentile"] = (100 * ((values < current).sum() + .5 * (values == current).sum()) / len(values)
                             if complete and np.isfinite(current) else np.nan)
        rows.append(row)
    return rows


def annualized_distributions(panel, end, windows=WINDOWS):
    records = []
    for (root, slot), g in panel.groupby(["root", "slot"], sort=False):
        g = g.copy()
        g["eligible"] = g.days_to_expiry.ge(5) | g.days_to_expiry.isna()
        for row in distribution_rows(g, end, "annualized_basis_pct", "eligible", windows=windows):
            records.append({"root": root, "slot": slot, **row})
    return pd.DataFrame(records)


def cross_index_basis(panel, allow_partial=False):
    if not {"IM", "IC"}.issubset(set(panel.root)):
        return pd.DataFrame()
    columns = ["trade_date", "slot", "instrument_id", "expiry_date", "basis_points", "roll_day"]
    im, ic = [panel.loc[panel.root.eq(root), columns] for root in ["IM", "IC"]]
    pair = im.merge(ic, on=["trade_date", "slot"], how="outer", suffixes=("_im", "_ic"),
                    validate="one_to_one", indicator=True)
    if not pair["_merge"].eq("both").all():
        raise ValueError("IM−IC 缺少同日同期限配对，不能使用不同日期的数据")
    matched = pair.expiry_date_im.notna() & pair.expiry_date_im.eq(pair.expiry_date_ic)
    if not matched.all() and not allow_partial:
        raise ValueError("IM−IC 同期限实际到期日不一致，不能只按连续代码序号相减")
    result = pd.DataFrame({"trade_date": pair.trade_date, "slot": pair.slot,
        "im_contract": pair.instrument_id_im, "ic_contract": pair.instrument_id_ic,
        "expiry_date": pair.expiry_date_im, "im_basis_points": pair.basis_points_im,
        "ic_basis_points": pair.basis_points_ic,
        "basis_difference_points": (pair.basis_points_im - pair.basis_points_ic).where(matched),
        "roll_day": pair.roll_day_im | pair.roll_day_ic})
    if "calendar_known" in panel:
        result["calendar_known"] = result.trade_date.map(panel.groupby("trade_date").calendar_known.all())
    return result.sort_values(["trade_date", "slot"]).reset_index(drop=True)


def cross_index_distributions(cross, end, windows=WINDOWS):
    rows = []
    if cross.empty:
        return pd.DataFrame()
    for slot, g in cross.groupby("slot"):
        rows.extend({"slot": slot, **row} for row in distribution_rows(g, end, "basis_difference_points", windows=windows))
    return pd.DataFrame(rows)
