"""Portable, verified Parquet stage artifacts. CTA reload never reads market inputs."""
import hashlib
import json
from pathlib import Path

import pandas as pd

from ..io import write_json
from ..models import BacktestError, check_cancelled, check_market_source
from .models import CTAResult, ContinuousPanel, FactorResult


PANEL_FIELDS = ("close", "spot", "dividend_points", "days_to_expiry", "mapping", "dividend_revisions")


def _root(directory):
    check_market_source(str(directory))
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    return root


def _save_frames(root, frames, metadata, kind):
    manifest, paths = {}, {"output_dir": str(root)}
    for name, frame in frames.items():
        if frame is None:
            continue
        path = (root / (name + ".parquet")).resolve()
        if not path.is_relative_to(root):
            raise BacktestError("Stage output name escapes its directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path)
        manifest[name] = dict(path=path.relative_to(root).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        paths[name] = str(path)
    write_json(root / "stage.json", dict(schema_version=1, kind=kind, frames=manifest, metadata=metadata))
    paths["manifest"] = str(root / "stage.json")
    return paths


def save_factors(result, directory):
    root = _root(directory)
    frames = {f"factors/{name}": value for name, value in result.factors.items()}
    frames.update({f"continuous/{name}": value for name, value in result.continuous_factors.items()})
    frames.update({f"panel/{name}": getattr(result.panel, name) for name in PANEL_FIELDS})
    frames.update({f"extras/{name}": value for name, value in result.panel.extras.items()})
    metadata = dict(result.metadata, contracts=result.contracts, panel_metadata=result.panel.metadata)
    return _save_frames(root, frames, metadata, "factor")


def save_cta(result, directory):
    return _save_frames(_root(directory), dict(targets=result.targets, scores=result.scores, decisions=result.decisions),
                        result.metadata, "cta")


def _load(directory, kind, cancel_event=None):
    check_cancelled(cancel_event)
    check_market_source(str(directory))
    root = Path(directory).expanduser().resolve()
    manifest = json.loads((root / "stage.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("kind") != kind:
        raise BacktestError(f"Expected version 1 {kind} artifact")
    check_market_source(manifest["metadata"])
    frames, paths = {}, {"output_dir": str(root), "manifest": str(root / "stage.json")}
    for name, entry in manifest["frames"].items():
        check_cancelled(cancel_event)
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root) or path.suffix != ".parquet":
            raise BacktestError("Stage artifact path escapes its directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise BacktestError(f"Stage artifact hash mismatch: {name}")
        frames[name] = pd.read_parquet(path)
        paths[name] = str(path)
    return frames, manifest["metadata"], paths


def load_factors(directory, *, cancel_event=None):
    frames, metadata, paths = _load(directory, "factor", cancel_event)
    def grouped(prefix):
        return {k.split("/", 1)[1]: v for k, v in frames.items() if k.startswith(prefix + "/")}
    panel = ContinuousPanel(**grouped("panel"), extras=grouped("extras"), metadata=metadata.pop("panel_metadata"))
    result = FactorResult(grouped("factors"), grouped("continuous"), panel, metadata.pop("contracts"), metadata, paths)
    if not result.continuous_factors or any(not v.index.equals(panel.mapping.index) for v in result.continuous_factors.values()):
        raise BacktestError("Factor artifact has inconsistent timestamp/mapping context")
    return result


def load_cta(directory, *, cancel_event=None):
    frames, metadata, paths = _load(directory, "cta", cancel_event)
    return CTAResult(frames["targets"], frames["scores"], metadata, frames.get("decisions"), paths)
