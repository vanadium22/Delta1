"""Local-file watcher and stable latest preview; never fetch market data."""
from __future__ import annotations

import copy
import hashlib
from html import escape
import json
import os
from pathlib import Path
import threading
from urllib.parse import quote
import uuid

from ..config import ROOT, atomic_json, load_config, timestamp
from shared_data import DataPaths


def _text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(value, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def publish_latest(output, root):
    output, root = Path(output).resolve(), Path(root).resolve()
    manifest = json.loads((output/"run_manifest.json").read_text(encoding="utf-8"))
    try:
        url = quote(Path(os.path.relpath(output/"index.html", root)).as_posix(), safe="/._-")
    except ValueError:
        url = (output/"index.html").as_uri()
    _text(root/"latest.html", '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
          f'<meta http-equiv="refresh" content="0;url={escape(url)}"><title>最新基差简报</title>'
          f'<p>最近成功生成：{escape(manifest["created_at"])}；行情截至{escape(manifest["as_of"])}。</p>'
          f'<a href="{escape(url)}">打开最新成功简报</a></html>')
    atomic_json(root/"latest.json", {"output": str(output), "as_of": manifest["as_of"],
                                   "created_at": manifest["created_at"]})


def _show_failure(root):
    previous = root/"latest.json"
    if previous.is_file():
        saved = json.loads(previous.read_text(encoding="utf-8"))
        url = (Path(saved["output"])/"index.html").as_uri()
        content = f'<p>上次成功行情截至 {escape(saved["as_of"])}。</p><a href="{escape(url)}">查看上次成功简报</a>'
    else:
        content = '<p>尚无成功生成的简报。</p>'
    _text(root/"latest.html", '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>基差简报更新状态</title>'
          '<h2>本次自动更新未成功</h2><p>已保留先前结果，输入变化后会重试。</p>'+content+'</html>')


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
                    output = generate(run)
                    publish_latest(output, root)
                    atomic_json(root/"automation_state.json", {"state": "waiting", "updated_at": timestamp(),
                        "input_fingerprint": signature, "last_successful_output": str(output)})
                except Exception as exc:
                    atomic_json(root/"automation_state.json", {"state": "failed", "updated_at": timestamp(),
                        "input_fingerprint": signature, "error": str(exc), "previous_success_preserved": True})
                    _show_failure(root)
                    print(f"本次生成失败，保留先前成功批次；输入再次变化后重试：{exc}", flush=True)
            stop.wait(args.poll_seconds)
    except KeyboardInterrupt:
        print("已停止自动生成。", flush=True)
    return 0
