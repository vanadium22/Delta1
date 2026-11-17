"""Local-file watcher and stable latest preview; never fetch market data."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

from ..config import ROOT, atomic_json, load_config, timestamp
from shared_data import DataPaths


def publish_latest(output, root):
    from .documents import WORD_NAME, PDF_NAME
    import shutil
    output, root = Path(output).resolve(), Path(root).resolve()
    manifest = json.loads((output/"run_manifest.json").read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    paths = {"word": output/WORD_NAME, "pdf": output/PDF_NAME}
    if any(not path.is_file() or path.stat().st_size == 0 for path in paths.values()):
        raise ValueError("Word/PDF未完整生成，保留之前成功简报")
    for key, path in paths.items():
        target = root/("latest"+path.suffix)
        tmp = root/("."+uuid.uuid4().hex+path.suffix)
        try:
            shutil.copyfile(path, tmp)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    atomic_json(root/"latest.json", {"output": str(output), "as_of": manifest["as_of"],
        "created_at": manifest["created_at"], **{key: str(path) for key, path in paths.items()}})
    (root/"last_failure.json").unlink(missing_ok=True)


def _show_failure(root):
    atomic_json(root/"last_failure.json", {"state": "failed", "at": timestamp(),
        "message": "本次自动更新未成功，先前Word/PDF及latest指针保持不变；输入变化后重试"})


def input_fingerprint(args):
    paths, config = DataPaths.for_module(ROOT), load_config()
    files = {ROOT/"config.local.json", paths.repo_root/"localsetting/data.local.json"}
    if args.snapshot:
        files.add(Path(args.snapshot).resolve())
    else:
        base = paths.resolve_module_setting(ROOT, config["data_directory"], paths.root/"market/index_futures", ("data",))
        databases = [Path(args.database)] if args.database else [base/m/"market.sqlite" for m in ("wind", "offline")]
        for db in databases:
            files.update((db, Path(str(db)+"-wal")))
    if args.dividends:
        files.add(Path(args.dividends).resolve())
    else:
        for value in config["dividends"]["directories"]:
            directory = paths.resolve_module_setting(ROOT, value, paths.dividend_inputs, ("inputs", "input"))
            files.update(p for p in directory.glob(config["dividends"].get("pattern", "*.xlsx")) if not p.name.startswith("~$"))
    if not args.no_volume_supplement:
        datasets = [Path(args.volume_dataset)] if args.volume_dataset else [
            paths.root/"market/index_futures/dashboard/normalized"/n for n in ("backfilled_cn_index_future", "cn_index_future")]
        files.update(p/"current.json" for p in datasets)
    records = []
    for path in sorted(files, key=str):
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if stat.st_size < 2_000_000 else None
            records.append([str(path.resolve()), stat.st_size, stat.st_mtime_ns, digest])
        else:
            records.append([str(path.resolve()), None])
    return hashlib.sha256(json.dumps(records, ensure_ascii=False).encode()).hexdigest()


def watch(args, *, generate=None, fingerprint=input_fingerprint, stop=None):
    if generate is None:
        from .brief import build
        generate = build
    stop = stop or threading.Event()
    root = (Path(args.output) if args.output else ROOT/"exports/recent_brief").resolve()
    root.mkdir(parents=True, exist_ok=True)
    last_attempt = None
    last_read_error = None
    print(f"自动生成已启动：每{args.poll_seconds}秒检查本地输入，变化后重算卡片与图片。Ctrl+C退出。", flush=True)
    try:
        while not stop.is_set():
            try:
                signature = fingerprint(args)
                if last_read_error is not None:
                    last_attempt = None
                last_read_error = None
            except Exception as exc:
                if str(exc) != last_read_error:
                    last_read_error = str(exc)
                    atomic_json(root/"automation_state.json", {"state": "input_error", "updated_at": timestamp(), "error": str(exc)})
                    _show_failure(root)
                    print(f"本地输入暂不可读，稍后重试：{exc}", flush=True)
                stop.wait(args.poll_seconds)
                continue
            if signature != last_attempt:
                last_attempt = signature
                atomic_json(root/"automation_state.json", {"state": "generating", "updated_at": timestamp(), "input_fingerprint": signature})
                try:
                    run = copy.copy(args)
                    run.output = root/(timestamp().replace(":", "").replace("+", "_") + "_" + uuid.uuid4().hex[:6])
                    from .workflow import generation_lock
                    with generation_lock():
                        output = generate(run)
                        publish_latest(output, root)
                    atomic_json(root/"automation_state.json", {"state": "waiting", "updated_at": timestamp(),
                        "input_fingerprint": signature, "last_successful_output": str(output)})
                except TimeoutError as exc:
                    last_attempt = None
                    atomic_json(root/"automation_state.json", {"state": "waiting", "updated_at": timestamp(),
                        "input_fingerprint": signature, "message": "其他生成批次忙，下一轮重试", "detail": str(exc)})
                except Exception as exc:
                    atomic_json(root/"automation_state.json", {"state": "failed", "updated_at": timestamp(),
                        "input_fingerprint": signature, "error": str(exc), "previous_success_preserved": True})
                    _show_failure(root)
                    print(f"本次生成失败，保留先前成功批次；输入再次变化后重试：{exc}", flush=True)
            stop.wait(args.poll_seconds)
    except KeyboardInterrupt:
        print("已停止自动生成。", flush=True)
    return 0
