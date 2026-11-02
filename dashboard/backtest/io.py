"""Stable, readable output paths for executed open/close instructions and accounts."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def json_default(value):
    if isinstance(value, (Path, pd.Timestamp, datetime, date)):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default, allow_nan=False), encoding="utf-8")


def frame_fingerprint(frame):
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    digest.update(str(list(frame.columns)).encode("utf-8"))
    return digest.hexdigest()


def save_result(result, output_dir):
    root = Path(output_dir).expanduser().resolve()
    # New directory per run; never silently replace an existing run or input matrix.
    root.mkdir(parents=True, exist_ok=False)
    paths = {"output_dir": str(root), "accounts": {}}
    for name, account in result.accounts.items():
        directory = root / name
        directory.mkdir()
        account_paths = {}
        for key, frame in (("equity", account.equity), ("positions", account.positions),
                           ("actual_orders", account.actual_orders), ("target_weights", account.target_weights),
                           ("schedule", account.schedule)):
            target = directory / (key + ".parquet")
            frame.to_parquet(target, index=key not in {"actual_orders", "schedule"})
            account_paths[key] = str(target)
        csv = directory / "actual_orders.csv"
        account.actual_orders.to_csv(csv, index=False, encoding="utf-8-sig")
        account_paths["actual_orders_csv"] = str(csv)
        paths["accounts"][name] = account_paths
    result.actual_orders.to_parquet(root / "actual_orders.parquet", index=False)
    result.actual_orders.to_csv(root / "actual_orders.csv", index=False, encoding="utf-8-sig")
    result.summary.to_csv(root / "summary.csv", encoding="utf-8-sig")
    paths.update(actual_orders=str(root / "actual_orders.parquet"),
                 actual_orders_csv=str(root / "actual_orders.csv"), summary=str(root / "summary.csv"),
                 metadata=str(root / "metadata.json"))
    write_json(root / "metadata.json", dict(**result.metadata, output_paths=paths))
    return paths
