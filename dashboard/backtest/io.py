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
    if result.input_instructions is not None:
        result.input_instructions.to_parquet(root / "instructions.parquet")
        paths["instructions"] = str(root / "instructions.parquet")
    for name in ("days_to_expiry", "execution_instructions"):
        frame = getattr(result, name)
        if frame is not None:
            target = root / (name + ".parquet")
            frame.to_parquet(target)
            paths[name] = str(target)
    paths.update(actual_orders=str(root / "actual_orders.parquet"),
                 actual_orders_csv=str(root / "actual_orders.csv"), summary=str(root / "summary.csv"),
                 metadata=str(root / "metadata.json"))
    write_json(root / "metadata.json", {**result.metadata, "output_paths": paths,
                                        "account_summaries": {k: a.summary for k, a in result.accounts.items()}})
    return paths


def load_result(output_dir):
    """Read a completed local run, also after its directory has moved."""
    from .models import AccountResult, BacktestError, BacktestResult
    root = Path(output_dir).expanduser().resolve()
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8-sig"))
    definitions = metadata.get("output_paths", {}).get("accounts", {})
    if not definitions:
        raise BacktestError(f"No completed account results found in {root}")
    summaries = metadata.get("account_summaries")
    if summaries is None:
        old = pd.read_csv(root / "summary.csv", index_col=0).astype(object)
        summaries = old.where(pd.notna(old), None).to_dict(orient="index")
    accounts, paths = {}, {"output_dir": str(root), "accounts": {}}
    for name in definitions:
        directory = (root / name).resolve()
        if directory == root or not directory.is_relative_to(root):
            raise BacktestError(f"Invalid account directory {name!r}")
        frames, account_paths = {}, {}
        for field in ("equity", "positions", "actual_orders", "target_weights", "schedule"):
            file = directory / (field + ".parquet")
            frames[field] = pd.read_parquet(file)
            account_paths[field] = str(file)
        account_paths["actual_orders_csv"] = str(directory / "actual_orders.csv")
        accounts[name] = AccountResult(**frames, summary=summaries[name])
        paths["accounts"][name] = account_paths
    paths.update(actual_orders=str(root / "actual_orders.parquet"), actual_orders_csv=str(root / "actual_orders.csv"),
                 summary=str(root / "summary.csv"), metadata=str(root / "metadata.json"))
    metadata.pop("output_paths", None)
    metadata.pop("account_summaries", None)
    instructions_path = root / "instructions.parquet"
    instructions = pd.read_parquet(instructions_path) if instructions_path.is_file() else None
    if instructions is not None:
        paths["instructions"] = str(instructions_path)
    optional = {}
    for name in ("days_to_expiry", "execution_instructions"):
        file = root / (name + ".parquet")
        optional[name] = pd.read_parquet(file) if file.is_file() else None
        if file.is_file():
            paths[name] = str(file)
    return BacktestResult(accounts, metadata, paths, instructions, **optional)
