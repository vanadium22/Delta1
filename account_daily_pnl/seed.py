"""Portable local data handoff with per-file verification."""

import hashlib
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from shared_data.io import atomic_json, sha256
from shared_data.paths import contained


ARCHIVE_NAME = "account_daily_pnl_history.zip"
SOURCE = re.compile(r"(flows|snapshots|wind)/\d{4}-\d{2}-\d{2}\.xlsx")
INPUTS = ("inputs/baseline.json", "inputs/基准持仓_2602_2025-12-29.xls",
          "inputs/基准持仓_5526_2025-12-29.xls", "inputs/BCT基准快照_2025-12-29.xlsx")


def make_seed(root, path, days, snapshots, through):
    names = [*INPUTS, *(f"flows/{day}.xlsx" for day in days),
             *(f"snapshots/{day}.xlsx" for day in sorted(snapshots))]
    files = {name: sha256(contained(root, name)) for name in names}
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".zip", delete=False) as temporary:
        stage = Path(temporary.name)
    try:
        with ZipFile(stage, "w", compression=ZIP_DEFLATED, compresslevel=3) as archive:
            archive.writestr("manifest.json", json.dumps({"version": 1, "through": through, "files": files},
                                                         ensure_ascii=False))
            for name in names:
                archive.write(contained(root, name), name)
        with ZipFile(stage) as archive:
            if set(archive.namelist()) != set(names) | {"manifest.json"} or archive.testzip() is not None:
                raise ValueError("历史数据包校验失败。")
        stage.replace(path)
    finally:
        stage.unlink(missing_ok=True)
    print(f"历史数据包：{path}（{len(names)} 个文件）", flush=True)


def install_seed(root, path):
    with ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        files = manifest["files"]
        if (manifest.get("version") != 1 or not set(INPUTS).issubset(files)
                or not all(name in INPUTS or SOURCE.fullmatch(name) for name in files)
                or len(archive.infolist()) != len(files) + 1
                or set(archive.namelist()) != set(files) | {"manifest.json"}
                or f"snapshots/{manifest['through']}.xlsx" not in files):
            raise ValueError("历史数据包索引有误。")
        pending = []
        for name, expected in files.items():
            target = contained(root, name)
            if target.exists():
                if sha256(target) != expected:
                    raise ValueError(f"历史包与已有文件不同：{target}")
            else:
                pending.append((name, target, expected))
        for name, target, expected in pending:
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"历史数据包哈希不匹配：{name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as temporary:
                temporary.write(content)
                stage = Path(temporary.name)
            try:
                stage.replace(target)
            finally:
                stage.unlink(missing_ok=True)
    state = root / "download_state.json"
    if not state.exists():
        atomic_json(state, {"version": 1, "latest_live_snapshot": manifest["through"]})
    print(f"历史数据包核验通过，已导入 {len(pending)} 个文件，截止 {manifest['through']}。", flush=True)
