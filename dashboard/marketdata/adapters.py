"""Read-only bridge to NEW domestic index/futures realtime collections.

No connection to any existing historical dataset is configured here.
"""
from __future__ import annotations

import hashlib

import pandas as pd

from index_strategy.instant_dld.reader import RealtimeReader
from index_strategy.instant_dld.quotes import source_time
from .bars import validate_instruments


def read_realtime_observations(root, *, dataset_id, instruments,
                               after_sequence=0, limit=10000):
    """Read a caller-selected collector store and return observations/cursor.

    Callers explicitly whitelist domestic index/futures instrument identities.
    Stable observation_id permits alias de-duplication across page boundaries.
    This adapter never turns receipt-clock samples into exchange second bars.
    """
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("必须指定该实时库唯一的 dataset_id")
    # The historical bar contract remains index/futures only. ETF observations
    # have a separate explicit registry and never enter a historical bar store.
    import re
    if not isinstance(instruments, dict) or not instruments:
        raise ValueError('观测标的注册表不能为空')
    historical = {}
    for symbol, info in instruments.items():
        kind = info.get('asset_type') if isinstance(info, dict) else None
        if kind in {'cn_etf', 'cn_etf_reference'}:
            pattern = r'[0-9]{6}\.(?:SH|SZ)' if kind == 'cn_etf' else r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
            if info.get('market_region') != 'CN' or not isinstance(symbol,str) or not re.fullmatch(pattern, symbol):
                raise ValueError('ETF/IOPV观测需要明确的国内标的注册')
        else:
            historical[symbol] = info
    if historical:
        validate_instruments(historical)
    if not isinstance(after_sequence, int) or after_sequence < 0 or not isinstance(limit, int) or not 1 <= limit <= 1_000_000:
        raise ValueError("cursor / limit 无效")
    reader = RealtimeReader(root)
    with reader.connect() as con:
        frame = pd.read_sql_query("SELECT * FROM quotes WHERE sequence > ? ORDER BY sequence LIMIT ?",
                                  con, params=(after_sequence, limit))
    cursor = int(frame["sequence"].max()) if len(frame) else after_sequence
    if not frame.empty:
        if "source_symbol" not in frame: frame["source_symbol"] = frame["symbol"]
        frame["instrument_id"] = frame["source_symbol"].fillna(frame["symbol"])
        frame = frame[frame["instrument_id"].isin(set(instruments))].copy()
    if frame.empty:
        for name in ("instrument_id", "observation_id", "aliases", "observed_at", "source_event_time",
                     "time_basis", "trade_date_status", "dataset_id"):
            if name not in frame.columns:
                frame[name] = pd.Series(dtype="object")
        frame.attrs.update(kind="quote_observation", source_time_verified=False)
        return frame, {"dataset_id": dataset_id, "sequence": cursor}
    frame["observation_id"] = frame.apply(lambda r: hashlib.sha256(
        f"{dataset_id}|{r['run_id']}|{r['poll']}|{r['batch']}|{r['instrument_id']}".encode()).hexdigest(), axis=1)
    frame["aliases"] = frame.groupby("observation_id")["symbol"].transform(lambda values: ",".join(sorted(set(values))))
    frame = frame.drop_duplicates("observation_id", keep="last").copy()
    if "received_at" not in frame: frame["received_at"] = None
    frame["observed_at"] = pd.to_datetime(frame["received_at"], utc=True)
    missing_receipt=frame["observed_at"].isna()
    if missing_receipt.any() and "timestamp" in frame:
        frame.loc[missing_receipt,"observed_at"]=pd.to_datetime(frame.loc[missing_receipt,"timestamp"],unit="s",utc=True)
    if "source_event_time" not in frame: frame["source_event_time"] = None
    frame["source_event_time"] = pd.to_datetime(frame["source_event_time"], utc=True)
    # Old immutable v1-v3 rows did not store an inferred source date. Rebuild
    # only the explicitly unverified candidate from their ORIGINAL receipt day.
    missing_source=frame["source_event_time"].isna()
    clock=frame["quote_time"].map(source_time).fillna("")
    inferred=frame["observed_at"].dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d")+"T"+clock+"+08:00"
    frame.loc[missing_source,"source_event_time"]=pd.to_datetime(inferred[missing_source],utc=True,errors="coerce")
    frame["time_basis"] = "received_at"
    frame.loc[missing_receipt,"time_basis"]="legacy_capture_floor_second"
    frame["trade_date_status"] = "receipt_date_inferred_unverified"
    frame["dataset_id"] = dataset_id
    frame.attrs.update(kind="quote_observation", volume_semantics="increment_over_receipt_interval",
                       source_time_verified=False, source_units="native_unverified",
                       cursor_scope="dataset_id plus database instance; reset after replacing the database")
    return frame.reset_index(drop=True), {"dataset_id": dataset_id, "sequence": cursor}
