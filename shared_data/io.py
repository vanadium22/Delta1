from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

from .paths import contained

_locks = {}
_guard = threading.Lock()
_held = threading.local()


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def file_lock(path, timeout=30):
    """Reentrant within a thread; excludes other threads and processes."""
    path = Path(path).resolve()
    key = str(path).casefold() if os.name == "nt" else str(path)
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=timeout):
        raise TimeoutError(f"数据正在更新，请稍后重试：{path}")
    try:
        held = getattr(_held, "keys", set())
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + timeout
            while True:
                stream.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"数据正在更新，请稍后重试：{path}")
                    time.sleep(.05)
            _held.keys = held | {key}
            try:
                yield
            finally:
                _held.keys = held
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        lock.release()


def portable_manifest(value, base):
    """Persist relative local paths; leave remote source paths as provenance."""
    value = copy.deepcopy(value)
    entries = value.get("files", [])
    entries = entries.values() if isinstance(entries, dict) else entries
    for entry in entries:
        if "path" in entry:
            path = Path(entry.pop("path")).resolve()
            entry["relative_path"] = path.relative_to(Path(base).resolve()).as_posix()
        elif "relative_path" in entry:
            contained(base, entry["relative_path"])
    value["local_path_version"] = 1
    return value


def resolved_manifest(value, base):
    """Keep existing application/API responses compatible with absolute `path`."""
    value = copy.deepcopy(value)
    entries = value.get("files", [])
    entries = entries.values() if isinstance(entries, dict) else entries
    for entry in entries:
        if "relative_path" in entry:
            entry["path"] = str(contained(base, entry.pop("relative_path")))
    return value
