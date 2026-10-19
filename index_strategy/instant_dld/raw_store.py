"""Immutable HTTP evidence, independent of the stable quotes/Parquet schema."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


# Never archive client/session objects, URL credentials or authentication headers.
METADATA_FIELDS = ("requested_at", "received_at", "elapsed_seconds", "http_status", "status",
                   "symbols", "requested_symbols", "symbol_mapping", "poll", "batch", "batch_count")


def publish_raw_batch(root: Path, run_id: str, record: dict) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("无效的原始响应 run_id")
    body = record.get("response_body")
    if body is not None:
        if not isinstance(body, dict):
            raise ValueError("原始HTTP响应结构错误")
        contents = base64.b64decode(body["base64"], validate=True)
        digest = hashlib.sha256(contents).hexdigest()
        if digest != body["sha256"] or len(contents) != body["bytes"]:
            raise ValueError("原始HTTP响应内容SHA或尺寸不一致")
        body = {key: body[key] for key in ("base64", "sha256", "bytes", "representation")}
    elif "source_response" in record or "response" in record:
        # Backward-compatible custom clients/direct store callers may only have
        # parsed JSON. Never claim that reserialization is the exact HTTP body.
        source = record.get("source_response", record.get("response"))
        contents = json.dumps(source, ensure_ascii=False, allow_nan=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(contents).hexdigest()
        body = {"base64": base64.b64encode(contents).decode("ascii"),
                "sha256": digest, "bytes": len(contents),
                "representation": ("parsed_source_json_reserialized" if "source_response" in record
                                   else "legacy_store_record_json_reserialized")}
    envelope = {"schema_version": "swhy_raw_http_v1", "run_id": run_id,
                "request_and_collection": {key: record[key] for key in METADATA_FIELDS if key in record},
                "response_body": body}
    payload = (json.dumps(envelope, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    directory = Path(root) / "raw" / "http" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (digest + ".json")
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise OSError(f"已发布原始响应校验失败：{target}")
    else:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".publishing-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.rename(target)
            if os.name != "nt":
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {"path": target.relative_to(root).as_posix(), "sha256": digest,
            "body_sha256": body["sha256"] if body else None,
            "body_representation": body["representation"] if body else "no_http_response"}
