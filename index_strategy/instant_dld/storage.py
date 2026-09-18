"""Append one JSON record per completed batch, isolated by run and date."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import uuid
from typing import Any


class JsonlStore:
    def __init__(self, root: Path, run_id: str | None = None) -> None:
        self.root = Path(root).resolve()
        self.run_id = run_id or (datetime.now().astimezone().strftime("%Y%m%dT%H%M%S_%f") + "_" + uuid.uuid4().hex[:8])
        if not self.run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in self.run_id):
            raise ValueError("无效的 run_id")
        self.run_dir = self.root / "runs" / self.run_id
        # Refuse to append to another process's run, even for a manually supplied ID.
        self.run_dir.mkdir(parents=True, exist_ok=False)

    def manifest(self, value: dict[str, Any]) -> None:
        target = self.run_dir / "run.json"
        temporary = target.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)

    def _append(self, target: Path, record: dict[str, Any]) -> None:
        # Serialize before opening the file: malformed values cannot leave half a line.
        line = json.dumps({"schema_version": 1, "run_id": self.run_id, **record}, ensure_ascii=False, allow_nan=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def batch(self, record: dict[str, Any]) -> None:
        day = datetime.fromisoformat(record["received_at"]).strftime("%Y-%m-%d")
        self._append(self.root / day / self.run_id / "batches.jsonl", record)

    def event(self, kind: str, **details: Any) -> None:
        self._append(self.run_dir / "events.jsonl", {
            "recorded_at": datetime.now().astimezone().isoformat(), "event": kind, **details,
        })
