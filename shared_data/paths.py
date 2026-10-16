from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re

MODULES = {"index_futures_basis", "script_making", "securities_lending", "dashboard"}
SHARED = "@shared"


def component(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) or value in {".", ".."}:
        raise ValueError(f"Invalid data identifier: {value!r}")
    return value


def contained(base: Path, relative: str | Path) -> Path:
    base = Path(base).resolve()
    rel = Path(relative)
    if rel.is_absolute() or rel.drive or ".." in rel.parts:
        raise ValueError("Data path must be relative and remain inside its root")
    path = (base / rel).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Data path escapes its root")
    return path


@dataclass(frozen=True)
class DataPaths:
    repo_root: Path
    root: Path
    outputs: Path

    @classmethod
    def for_repo(cls, repo_root: Path, *, data_root: Path | None = None):
        repo = Path(repo_root).resolve()
        config_path = repo / "localsetting" / "data.local.json"
        config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
        def resolve(value):
            path = Path(value).expanduser()
            return (repo / path).resolve()
        root = data_root if data_root is not None else os.environ.get("DELTA1_DATA_ROOT") or config.get("data_root", "data")
        output = os.environ.get("DELTA1_OUTPUTS_ROOT") or config.get("outputs_root", "outputs")
        return cls(repo, resolve(root), resolve(output))

    @classmethod
    def for_module(cls, module_root: Path):
        # Do not walk ancestors: an explicitly supplied sandbox under a real repo
        # must never accidentally open that repo's production data.
        root = Path(module_root).resolve()
        repo = root.parent if root.name in MODULES else root
        return cls.for_repo(repo)

    def basis(self, mode: str) -> Path:
        if mode == "demo":
            return self.demo("index_futures_basis")
        if mode not in {"wind", "offline"}:
            raise ValueError("Unknown basis data mode")
        return self.root / "market" / "index_futures" / mode

    @property
    def dividend_inputs(self):
        return self.root / "dividends" / "index_futures" / "inputs"

    @property
    def dividend_archive(self):
        return self.root / "dividends" / "index_futures" / "archive"

    @property
    def reports(self):
        return self.root / "reports" / "swap"

    def lending(self, demo=False):
        return self.demo("securities_lending") / "snapshots" if demo else self.root / "lending" / "live"

    def industries(self, demo=False):
        return self.demo("securities_lending") / "industry" if demo else self.root / "reference" / "industry"

    def demo(self, module):
        return self.root / "demo" / component(module)

    def export(self, module):
        return self.outputs / component(module)

    def resolve_module_setting(self, module_root, value, shared, legacy=()):
        root = Path(module_root).resolve()
        raw = str(value).replace("\\", "/").rstrip("/")
        old_paths = {(root / p).resolve() for p in legacy}
        if raw == SHARED or raw in legacy or (root / raw).resolve() in old_paths:
            return Path(shared).resolve()
        return (root / Path(value).expanduser()).resolve()
