"""App actions and editable-image repackaging; shared by desktop and CLI."""
from __future__ import annotations

from argparse import Namespace
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import uuid

from ..analytics import sha256
from ..config import ROOT, timestamp
from .automation import publish_latest
from .documents import PDF_NAME, WORD_NAME, export_documents

FIGURES = ["01_近期基差与跨期.png", "02_单合约年化与历史分位表.png",
           "03_跨期年化与历史分位表.png", "04_四合约总成交与总持仓.png"]


@contextmanager
def generation_lock():
    from shared_data.io import file_lock
    with file_lock(ROOT/"exports/recent_brief/.generation.lock", timeout=1):
        yield


def latest_paths(root=None):
    root = Path(root) if root else ROOT/"exports/recent_brief"
    pointer = root/"latest.json"
    if not pointer.is_file():
        raise ValueError("尚无Word/PDF简报，请先点击一键生成")
    saved = json.loads(pointer.read_text(encoding="utf-8"))
    folder = Path(saved["output"])
    result = {"folder": folder, "pdf": folder/PDF_NAME, "word": folder/WORD_NAME,
              "as_of": saved["as_of"], "created_at": saved["created_at"]}
    if any(not result[key].is_file() for key in ("pdf", "word")):
        raise ValueError("最新记录尚无完整Word/PDF，请重新生成；旧图片仍保留")
    return result


def generate_for_service(service, as_of=None, refresh=True, progress=print):
    with generation_lock():
        if service.mode == "demo":
            raise ValueError("近期简报仅使用真实数据，请切换Wind或离线模式")
        from .brief import build, refresh_market
        args = Namespace(snapshot=None, database=service.store.path if service.mode == "offline" else None,
            as_of=as_of, dividends=None, volume_dataset=None, no_volume_supplement=False, sessions=60,
            output=None, refresh_result={"requested": False})
        if refresh and service.mode == "wind":
            progress("检查并增量补齐期现货、持仓和成交量…")
            args.refresh_result = refresh_market(as_of, factory=lambda mode: service)
        progress("生成四张合并图及Word/PDF，请稍候…")
        folder = build(args)
        publish_latest(folder, ROOT/"exports/recent_brief")
        return {"folder": str(folder), "pdf": str(folder/PDF_NAME), "word": str(folder/WORD_NAME),
                "refresh": args.refresh_result}


def repackage(source, output=None):
    with generation_lock():
        return _repackage(source, output)


def _repackage(source, output=None):
    source = Path(source).resolve()
    manifest = json.loads((source/"run_manifest.json").read_text(encoding="utf-8"))
    created = timestamp()
    output = Path(output).resolve() if output else source.parent/("repack_"+uuid.uuid4().hex[:10])
    if output.exists():
        raise ValueError("重排须使用新的输出目录，保留原批次")
    legacy = [FIGURES[0], "02_单合约年化与60日分位.png", "03_跨期年化与60日分位.png", FIGURES[3]]
    source_images = {name: source/(name if (source/name).is_file() else old) for name,old in zip(FIGURES, legacy)}
    for name,path in source_images.items():
        if not path.is_file():
            raise ValueError("原批次缺少图片："+name)
    output.mkdir(parents=True)
    for path in source.iterdir():
        if path.is_file() and path.suffix in (".svg", ".csv", ".json") and path.name != "run_manifest.json":
            shutil.copy2(path, output/path.name)
    for name,path in source_images.items():
        shutil.copy2(path, output/name)
    info = manifest.get("document_info") or {"as_of": manifest["as_of"], "created_at": created,
        "dividend_date": manifest.get("dividends", {}).get("snapshot_date", "见来源记录"),
        "summary_cards": manifest.get("summary_cards", []), "explanations": manifest["explanations"],
        "source_note": "沿用原批次行情和分红，仅重排图片；数据日期以报告注明为准。"}
    info = {**info, "created_at": created,
            "source_note": "本次仅重排已有图片，未重新计算行情。原批次说明："+info["source_note"]}
    from .charts import setup
    setup()
    documents = export_documents(output, FIGURES, info)
    overrides = [name for name,path in source_images.items() if sha256(path) != manifest.get("output_files", {}).get(path.name, {}).get("sha256")]
    manifest.update(version=max(7, manifest.get("version", 7)), created_at=created, documents=documents, document_info=info,
        document_rebuild={"source_batch": str(source), "recalculated_market": False,
                          "builder_sha256": sha256(Path(__file__).with_name("documents.py")),
                          "images_changed_since_source_manifest": overrides})
    manifest["output_files"] = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                                for p in output.iterdir() if p.is_file()}
    (output/"run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    publish_latest(output, ROOT/"exports/recent_brief")
    print(str(output/PDF_NAME), flush=True)
    print(str(output/WORD_NAME), flush=True)
    return output
