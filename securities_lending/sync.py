from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from .config import atomic_json, source_directory, timestamp


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def synchronize(config: dict, day: str, data_root: Path):
    source = source_directory(config, day)
    if not source.is_dir():
        raise ValueError(f"当日目录不可访问：{source}；请检查公司网络及共享盘映射")
    files = [p for p in source.glob(config["file_glob"]) if p.is_file() and not p.name.startswith("~$") and p.suffix.lower() in {".xlsx", ".xlsm", ".xls"}]
    files.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    if not files:
        raise ValueError(f"当日目录没有符合 {config['file_glob']} 的 Excel 券单：{source}")
    selected = files[:1] if config["file_selection"] == "latest" else files
    batch = data_root / day / "snapshots" / uuid.uuid4().hex
    batch.mkdir(parents=True)
    entries, hashes, warnings = [], set(), []
    if len(files) > 1 and config["file_selection"] == "latest":
        warnings.append(f"发现 {len(files)} 个文件，按修改时间读取最新一份：{selected[0].name}；如需分券源合并，请调整读取方式")
    if config["file_selection"] == "merge" and len(selected) > 1:
        warnings.append("正在合并多份券单；除完全相同文件外，各行均相加，请确认这些文件不是同一库存的不同版本")
    for original in selected:
        before = original.stat()
        local = batch / original.name
        shutil.copy2(original, local)
        after = original.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or local.stat().st_size != after.st_size:
            raise ValueError(f"文件复制期间发生变化，请稍后刷新：{original.name}")
        sha = digest(local)
        if sha in hashes:
            warnings.append(f"已跳过内容完全相同的文件：{original.name}")
            continue
        hashes.add(sha)
        entries.append({"name": original.name, "source": str(original), "path": str(local.resolve()), "size": local.stat().st_size, "sha256": sha})
    return {"date": day, "downloaded_at": timestamp(), "source_dir": str(source), "selection": config["file_selection"], "files": entries, "warnings": warnings}


def save_manifest(data_root: Path, manifest: dict):
    atomic_json(data_root / manifest["date"] / "latest.json", manifest)


def cached_manifest(data_root: Path, day: str, config: dict):
    path = data_root / day / "latest.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["date"] != day or manifest["source_dir"] != str(source_directory(config, day)):
        return None
    if manifest["selection"] != config["file_selection"] or manifest.get("file_glob") != config["file_glob"]:
        return None
    for entry in manifest["files"]:
        local = Path(entry["path"])
        if not local.resolve().is_relative_to((data_root / day).resolve()) or not local.is_file() or digest(local) != entry["sha256"]:
            raise ValueError("当日本地缓存缺失或校验失败，请重新同步")
    return manifest
