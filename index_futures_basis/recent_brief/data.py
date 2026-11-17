"""Freeze local evidence; preserve missing values and actual contract identities."""
from __future__ import annotations

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
# Literal subtraction, deliberately separate from the original report's far-near pairs.
PAIRS = {"01−02": (2, 3), "02−03": (3, 4)}
WINDOWS = (3, 6, 12)


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


def load_market(snapshot=None, database=None, as_of=None):
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
        start = str((cutoff - pd.DateOffset(months=13) - pd.Timedelta(days=15)).date())
        with store.connection() as con:
            con.execute("BEGIN")
            # All adapter reads share this transaction and one SQLite snapshot.
            class Frozen(ReadOnlyStore):
                @contextmanager
                def connection(self):
                    yield con
            frozen = Frozen(store.path)
            panel, availability = local_panel(frozen, start, str(cutoff.date()))
            quotes = frozen.quotes(start, str(cutoff.date()))
            panel["volume"] = [quotes.get((r.instrument_id, str(r.trade_date.date()), "volume"), np.nan)
                               for r in panel.itertuples()]
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


def adjust(panel, config, paths, dividend_file=None):
    cfg = dict(config["dividends"])
    cfg["allow_missing_values"] = True
    cfg["directories"] = [str(paths.resolve_module_setting(ROOT, p, paths.dividend_inputs, ("inputs", "input")))
                          for p in cfg["directories"]]
    if dividend_file:
        cfg.update(selection="fixed_file", file=str(Path(dividend_file).resolve()))
    try:
        dividends, info = read_dividends(cfg, ROOT)
    except (ValueError, OSError) as exc:
        dividends = pd.DataFrame(columns=["trade_date", "code", "dividend_points"])
        info = {"application": "exact_date", "snapshot_date": "缺失", "reason": str(exc)}
    result = attach_dividends(panel, dividends, panel.trade_date.min(),
                              info.get("application", "exact_date"), allow_partial=True)
    return result, info


def calendar_series(panel):
    rows = []
    for (day, root), g in panel.groupby(["trade_date", "root"]):
        g = g.set_index("slot")
        for pair, (left, right) in PAIRS.items():
            if left not in g.index or right not in g.index:
                continue
            a, b = g.loc[left], g.loc[right]
            rows.append({"trade_date": day, "root": root, "pair": pair,
                         "left_contract": a.instrument_id, "right_contract": b.instrument_id,
                         "basis_points": a.adjusted_futures_close - b.adjusted_futures_close,
                         "calendar_known": bool(a.calendar_known and b.calendar_known),
                         "roll_day": bool(a.roll_day or b.roll_day)})
    return pd.DataFrame(rows)


def quantiles(series, end, key):
    rows = []
    for (root, identity), g in series.groupby(["root", key]):
        rows.extend({"root": root, key: identity, **row}
                    for row in distribution_rows(g, end, "basis_points", windows=WINDOWS))
    return pd.DataFrame(rows)


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
        rows.append({"root": root, "slot": slot, "contract": row.instrument_id,
                     "basis_points": row.basis_points,
                     "change_1d": change(g, end), "change_5d": change(g, end, lag=5),
                     "open_interest": row.open_interest, "oi_change": row.oi_change,
                     "volume": row.volume, "roll_day": row.roll_day})
    return pd.DataFrame(rows)
