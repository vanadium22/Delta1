"""Freeze local evidence; preserve missing values and actual contract identities."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from ..analytics import ROOTS, attach_dividends, read_dividends, sha256, validate_panel
from ..config import ROOT, load_config
from ..distributions import distribution_rows
from ..partial import local_panel
from ..store import Store
from shared_data import DataPaths

ORDER = ("IF", "IH", "IC", "IM")
# Slots are one-based internally. Always subtract the near leg from the far leg.
PAIRS = {"02−01": (3, 2), "03−02": (4, 3)}
WINDOWS = (3, 6, 12)
MIN_DAYS_TO_EXPIRY = 1
CALENDAR_CHART_MONTHS = 6
SINGLE_RANK_SESSIONS = (30, 60, 120)
CALENDAR_RANK_SESSIONS = (*SINGLE_RANK_SESSIONS, 180)


class ReadOnlyStore(Store):
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()


def earlier_contract_mappings(store, through):
    calendar = store.calendar("", through)
    mappings = store.mappings("", through)
    occurrences = Counter((day, contract) for (day, _, _), contract in mappings.items())
    return {(day, f"{root}{slot - 1:02d}.CFE"): contract
            for (day, root, slot), contract in mappings.items()
            if calendar.get(day) == 1 and occurrences[day, contract] == 1}


def load_market(snapshot=None, database=None, as_of=None, *, earlier_mappings=None):
    paths = DataPaths.for_module(ROOT)
    config = load_config()
    if snapshot:
        path = Path(snapshot).resolve()
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        frame = pd.DataFrame(raw["records"])
        sessions = pd.DatetimeIndex(pd.to_datetime(raw["calendar"])).sort_values()
        cutoff = pd.Timestamp(as_of) if as_of else pd.Timestamp(frame.trade_date.max())
        sessions = sessions[sessions <= cutoff]
        frame = frame[pd.to_datetime(frame.trade_date) <= cutoff]
        panel = validate_panel(frame, list(ROOTS), sessions)
        panel["calendar_known"] = True
        # Keep an explicitly requested missing cutoff as a blank row, not an old close.
        if cutoff not in sessions:
            missing_days = pd.date_range(sessions.max() + pd.Timedelta(days=1), cutoff)
            extra = pd.MultiIndex.from_product([missing_days, ORDER, range(1, 5)],
                       names=["trade_date", "root", "slot"]).to_frame(index=False)
            panel = pd.concat([panel, extra], ignore_index=True)
            panel["calendar_known"] = panel.calendar_known.eq(True)
            panel["instrument_id"] = panel.instrument_id.fillna("")
            panel["continuous_code"] = panel.root + (panel.slot - 1).astype(str).str.zfill(2) + ".CFE"
        volume = pd.DataFrame(raw["records"])
        if "volume" in volume:
            volume["trade_date"] = pd.to_datetime(volume.trade_date)
            panel = panel.merge(volume[["trade_date", "instrument_id", "volume"]],
                                on=["trade_date", "instrument_id"], how="left", validate="many_to_one")
        source = {"kind": "snapshot", "path": str(path), "sha256": sha256(path),
                  "label": raw.get("source", "用户指定本地快照")}
    else:
        base = paths.resolve_module_setting(ROOT, config["data_directory"],
                    paths.root / "market/index_futures", ("data",))
        candidates = [Path(database)] if database else [base / mode / "market.sqlite" for mode in ("wind", "offline")]
        stores = [(ReadOnlyStore(p), ReadOnlyStore(p).latest_available(as_of or "9999-12-31"))
                  for p in candidates if p.is_file()]
        stores = [(s, d) for s, d in stores if d]
        if not stores:
            raise ValueError("没有可用的本地真实行情；请指定 --snapshot 或 --database。不会自动下载或生成演示。")
        store, latest = max(stores, key=lambda item: item[1])
        cutoff = pd.Timestamp(as_of or latest)
        start = cutoff.normalize() - pd.DateOffset(months=13) - pd.Timedelta(days=15)
        start_day, end_day = start.date().isoformat(), cutoff.date().isoformat()
        with store.connection() as con:
            con.execute("BEGIN")
            # All adapter reads share this transaction and one SQLite snapshot.
            class Frozen(ReadOnlyStore):
                @contextmanager
                def connection(self):
                    yield con
            frozen = Frozen(store.path)
            panel, availability = local_panel(frozen, start_day, end_day)
            quotes = frozen.quotes(start_day, end_day)
            panel["volume"] = [quotes.get((r.instrument_id, str(r.trade_date.date()), "volume"), np.nan)
                               for r in panel.itertuples()]
            if earlier_mappings is not None:
                through = (start - pd.Timedelta(days=1)).date().isoformat()
                earlier_mappings.update(earlier_contract_mappings(frozen, through))
            source = {"kind": "sqlite", "path": str(store.path), "source": frozen.meta("source", {}),
                      "availability": availability}
    source_text = json.dumps(source, ensure_ascii=False).lower()
    if any(word in source_text for word in ("synthetic", '"demo"', "合成演示")):
        raise ValueError("本子项目只生成真实本地数据图片，拒绝合成演示来源。")
    panel = panel.sort_values(["trade_date", "root", "slot"]).reset_index(drop=True)
    if "volume" not in panel:
        panel["volume"] = np.nan
    panel["volume"] = pd.to_numeric(panel.volume, errors="coerce")
    panel.loc[~np.isfinite(panel.volume) | panel.volume.lt(0), "volume"] = np.nan
    source["panel_sha256"] = hashlib.sha256(pd.util.hash_pandas_object(panel, index=False).values.tobytes()).hexdigest()
    return panel, cutoff, source, config, paths


def add_volumes(panel, dataset):
    """Use only volume from one frozen normalized manifest, by actual day and code."""
    root = Path(dataset).resolve()
    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    manifest_path = (root / current["manifest"]).resolve()
    if not manifest_path.is_relative_to(root):
        raise ValueError("成交量清单越出数据集目录")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != current["sha256"]:
        raise ValueError("成交量清单哈希不符")
    manifest = json.loads(manifest_bytes)
    if manifest["version"] != current["version"]:
        raise ValueError("成交量清单版本不符")
    if manifest["descriptor"].get("volume_unit") != "contracts":
        raise ValueError("成交量数据集未明确以手计量")
    if "synthetic" in json.dumps(manifest["descriptor"]).lower():
        raise ValueError("真实行情不允许匹配合成成交量")
    # The volume chart and 20-session anomaly check need only the recent 80 sessions.
    days = sorted(panel.trade_date.unique())[-80:]
    wanted = {(str(r.trade_date.date()), r.instrument_id)
              for r in panel[panel.trade_date.isin(days)].itertuples() if r.instrument_id}
    frames, files = [], []
    for part in manifest["parts"]:
        if part["frequency"] != "1d" or (part["trade_date"], part["instrument_id"]) not in wanted:
            continue
        path = (root / part["path"]).resolve()
        if not path.is_relative_to(root) or sha256(path) != part["sha256"]:
            raise ValueError(f"成交量分片路径或哈希无效：{path}")
        frames.append(pd.read_parquet(path, columns=["trade_date", "instrument_id", "volume", "revision", "is_final"]))
        files.append({"path": part["path"], "sha256": part["sha256"]})
    result = panel.copy()
    matched = 0
    if frames:
        volumes = pd.concat(frames, ignore_index=True)
        volumes["trade_date"] = pd.to_datetime(volumes.trade_date)
        volumes = volumes.sort_values("revision").drop_duplicates(["trade_date", "instrument_id"], keep="last")
        volumes.loc[~volumes.is_final | ~np.isfinite(volumes.volume) | volumes.volume.lt(0), "volume"] = np.nan
        volumes = volumes.rename(columns={"volume": "supplement_volume"})
        result = result.merge(volumes[["trade_date", "instrument_id", "supplement_volume"]],
                              on=["trade_date", "instrument_id"], how="left", validate="many_to_one")
        matched = int((result.volume.isna() & result.supplement_volume.notna()).sum())
        result["volume"] = result.volume.combine_first(result.supplement_volume)
        result = result.drop(columns="supplement_volume")
    return result, {"path": str(root), "version": current["version"], "manifest_sha256": current["sha256"],
                    "matched_missing_rows": matched, "fields_used": ["volume"], "files": files,
                    "limitation": "修订后日线；仅按交易日与实际合约匹配成交量，不代表历史当时可知。"}


def adjust(panel, config, paths, dividend_file=None, *, unadjusted=False, frozen_inputs=None,
           earlier_mappings=None):
    cfg = dict(config["dividends"])
    cfg["allow_missing_values"] = True
    dividends = pd.DataFrame(columns=["trade_date", "code", "dividend_points"])
    aligned = None
    if unadjusted:
        info = {"application": "not_applied", "snapshot_date": "不适用"}
    elif cfg.get("layout", "snapshot_continuous") != "snapshot_continuous" and dividend_file and not Path(dividend_file).is_dir():
        cfg.update(selection="fixed_file", file=str(Path(dividend_file).resolve()))
        try:
            dividends, info = read_dividends(cfg, ROOT)
        except (ValueError, OSError) as exc:
            info = {"application": "exact_date", "snapshot_date": "缺失", "reason": str(exc)}
    else:
        from .dividend_history import align_history
        aligned, info = align_history(panel, config, paths, dividend_file, frozen_inputs=frozen_inputs,
                                      earlier_mappings=earlier_mappings)
        dividends = panel[["trade_date", "instrument_id"]].rename(columns={"instrument_id": "code"})
        dividends = dividends.assign(dividend_points=aligned.dividend_points).dropna()
    result = attach_dividends(panel, dividends, panel.trade_date.min(),
                              "exact_date" if aligned is not None else info.get("application", "exact_date"),
                              allow_partial=True)
    if aligned is not None:
        result[aligned.columns] = aligned
        result["dividend_application"] = info["application"]
    # The brief has its own user-confirmed threshold; the original App is unchanged.
    result["annualized_basis_pct"] = (result.basis_points/result.spot_close*36500/
        result.days_to_expiry.replace(0, np.nan)).where(result.days_to_expiry.ge(MIN_DAYS_TO_EXPIRY))
    result["annualized_plot_pct"] = result.annualized_basis_pct
    result["annualized_plot_filled"] = False
    valid = result[["futures_close", "spot_close", "dividend_points", "basis_points"]].notna().all(axis=1)
    residual = (result.basis_points-result.raw_basis_points-result.dividend_points).abs()
    observable = result.futures_close.notna() & result.spot_close.notna()
    missing = observable & result.dividend_points.isna() & (not unadjusted)
    estimated = observable & result.get("dividend_is_estimated", False)
    info["brief_selection"] = "not_applied" if unadjusted else "explicit_input" if dividend_file else "daily_as_of_local_history"
    info["adjustment_audit"] = {"formula": "F-S" if unadjusted else "F+G-S", "valid_rows": int(observable.sum() if unadjusted else valid.sum()),
        "missing_dividend_rows": int(missing.sum()),
        "missing_on_as_of": int((missing & result.trade_date.eq(result.trade_date.max())).sum()),
        "estimated_dividend_rows": int(estimated.sum()),
        "estimated_on_as_of": int((estimated & result.trade_date.eq(result.trade_date.max())).sum()),
        "first_missing_date": str(result.loc[missing, "trade_date"].min().date()) if missing.any() else None,
        "nonzero_dividend_rows": int((result.dividend_points.fillna(0) != 0).sum()),
        "max_formula_residual": float(residual[valid].max()) if valid.any() else None}
    if valid.any() and residual[valid].gt(1e-8).any():
        raise ValueError("分红调整校验失败，未发布简报")
    return result, info


def calendar_series(panel):
    rows = []
    for (day, root), g in panel.groupby(["trade_date", "root"]):
        g = g.set_index("slot")
        for pair, (left, right) in PAIRS.items():
            if left not in g.index or right not in g.index:
                continue
            a, b = g.loc[left], g.loc[right]
            gap = (a.expiry_date - b.expiry_date).days
            valid_gap = pd.notna(gap) and gap > 0 and b.expiry_date > day
            valid_spot = np.isfinite(a.spot_close) and a.spot_close > 0 and np.isclose(
                a.spot_close, b.spot_close, rtol=0, atol=1e-8)
            points = a.adjusted_futures_close - b.adjusted_futures_close
            rows.append({"trade_date": day, "root": root, "pair": pair,
                         "left_contract": a.instrument_id, "right_contract": b.instrument_id,
                         "left_expiry": a.expiry_date, "right_expiry": b.expiry_date,
                         "expiry_gap_days": gap, "spot_close": a.spot_close,
                         "left_futures_close": a.futures_close, "right_futures_close": b.futures_close,
                         "left_dividend_points": a.dividend_points, "right_dividend_points": b.dividend_points,
                         "left_dividend_source_contract": a.get("dividend_source_contract"),
                         "right_dividend_source_contract": b.get("dividend_source_contract"),
                         "dividend_is_estimated": bool(a.get("dividend_is_estimated", False)
                                                       or b.get("dividend_is_estimated", False)),
                         "left_dividend_source_date": a.get("dividend_source_date"),
                         "right_dividend_source_date": b.get("dividend_source_date"),
                         "left_dividend_source_sha256": a.get("dividend_source_sha256"),
                         "right_dividend_source_sha256": b.get("dividend_source_sha256"),
                         "basis_points": points,
                         "annualized_basis_pct": points / a.spot_close * 36500 / gap
                             if valid_gap and valid_spot else np.nan,
                         "calendar_known": bool(a.calendar_known and b.calendar_known),
                         "roll_day": bool(a.roll_day or b.roll_day)})
    return pd.DataFrame(rows)


def quantiles(series, end, key):
    rows = []
    for (root, identity), g in series.groupby(["root", key]):
        rows.extend({"root": root, key: identity, **row}
                    for row in distribution_rows(g, end, "basis_points", windows=WINDOWS))
    return pd.DataFrame(rows)


def session_quantiles(series, end, key, sessions=60):
    """Annualized distributions over exactly N prior local sessions."""
    end = pd.Timestamp(end)
    days = pd.DatetimeIndex(series.loc[series.trade_date.lt(end), "trade_date"].unique()).sort_values()[-sessions:]
    rows = []
    for (root, identity), g in series.groupby(["root", key]):
        now = g[g.trade_date.eq(end)]
        current = now.annualized_basis_pct.iloc[0] if len(now) else np.nan
        history = g.set_index("trade_date").reindex(days)
        # Known near-expiry single-contract observations are mathematically excluded.
        # Missing maturities remain eligible, so they invalidate rather than shrink the sample.
        eligible = (history.days_to_expiry.ge(MIN_DAYS_TO_EXPIRY) | history.days_to_expiry.isna()
                    if key == "slot" else pd.Series(True, index=history.index))
        values = history.loc[eligible, "annualized_basis_pct"].replace([np.inf, -np.inf], np.nan).dropna()
        complete = bool(len(days) == sessions and history.calendar_known.eq(True).all()
                        and len(values) == int(eligible.sum()) and len(values))
        row = {"root": root, key: identity, "window_sessions": sessions,
               "window_start": days.min(), "window_end_exclusive": end,
               "sample_start": values.index.min(), "sample_end": values.index.max(),
               "current": current, "n": len(values), "eligible_n": int(eligible.sum()),
               "expiry_day_excluded_n": int((~eligible).sum()), "complete": complete}
        if "dividend_is_estimated" in g:
            row["estimated_sample_n"] = int(history.loc[values.index, "dividend_is_estimated"].eq(True).sum())
            row["current_dividend_is_estimated"] = bool(now.dividend_is_estimated.eq(True).any())
        row["mean"] = values.mean() if complete else np.nan
        row["std"] = values.std(ddof=0) if complete else np.nan
        for name, probability in (("p05", .05), ("p25", .25), ("p50", .5), ("p75", .75), ("p95", .95)):
            row[name] = values.quantile(probability) if complete else np.nan
        row["percentile"] = (100*((values < current).sum() + .5*(values == current).sum())/len(values)
                             if complete and np.isfinite(current) else np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def multi_session_quantiles(series, end, key):
    windows = SINGLE_RANK_SESSIONS if key == "slot" else CALENDAR_RANK_SESSIONS
    return pd.concat([session_quantiles(series, end, key, sessions=n) for n in windows], ignore_index=True)


def activity_totals(panel):
    """Four-leg totals are missing if any constituent is missing."""
    result = panel.groupby(["trade_date", "root"], as_index=False).agg(
        open_interest=("open_interest", lambda values: values.sum(min_count=4)),
        volume=("volume", lambda values: values.sum(min_count=4)))
    result = result.sort_values(["root", "trade_date"]).reset_index(drop=True)
    result["oi_change"] = result.groupby("root").open_interest.diff()
    return result


def change(g, end, field="basis_points", lag=1, same_contract=False):
    """Change against the exact previous row; never skip a missing observation."""
    g = g.sort_values("trade_date")
    current = g[g.trade_date.eq(end)]
    previous = g[g.trade_date.lt(end)]
    if current.empty or len(previous) < lag:
        return np.nan
    now, before = current.iloc[0], previous.iloc[-lag]
    if same_contract and now.instrument_id != before.instrument_id:
        return np.nan
    return now[field] - before[field]


def snapshot_table(panel, end):
    rows = []
    for (root, slot), g in panel.groupby(["root", "slot"]):
        now = g[g.trade_date.eq(end)]
        if now.empty:
            continue
        row = now.iloc[0]
        rows.append({"trade_date": end, "root": root, "slot": slot, "contract": row.instrument_id,
                     "spot_close": row.spot_close, "futures_close": row.futures_close,
                     "dividend_points": row.dividend_points,
                     "basis_points": row.basis_points,
                     "change_1d": change(g, end), "change_5d": change(g, end, lag=5),
                     "open_interest": row.open_interest, "oi_change": row.oi_change,
                     "volume": row.volume, "roll_day": row.roll_day})
    return pd.DataFrame(rows)
