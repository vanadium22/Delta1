"""Immutable HTTP evidence, independent of the stable quotes/Parquet schema."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
from .short_files import publish_bytes


# Never archive client/session objects, URL credentials or authentication headers.
METADATA_FIELDS = ("requested_at", "received_at", "elapsed_seconds", "http_status", "status",
                   "symbols", "requested_symbols", "symbol_mapping", "poll", "batch", "batch_count")


def _encoded(envelope):
    return (json.dumps(envelope, ensure_ascii=False, allow_nan=False,
                       sort_keys=True, separators=(',', ':'))+'\n').encode('utf8')


def _verify_envelope(raw):
    try:
        value=json.loads(raw)
        expected=value.pop('content_sha256',None)
        # Older byte-preserved evidence is still checked by its event reference.
        if expected and hashlib.sha256(_encoded(value)).hexdigest()!=expected:
            raise ValueError('checksum')
        if value.get('schema_version')!='swhy_raw_http_v1':
            raise ValueError('schema')
    except (ValueError,AttributeError,UnicodeError) as exc:
        raise OSError('已发布原始响应校验失败') from exc


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
    envelope['content_sha256'] = hashlib.sha256(_encoded(envelope)).hexdigest()
    payload = _encoded(envelope)
    digest = hashlib.sha256(payload).hexdigest()
    directory = Path(root) / "raw" / "http" / run_id
    prefix = f"p{int(record.get('poll', 0))}-b{int(record.get('batch', 0))}"
    target = publish_bytes(payload, directory, prefix, '.json', validate_existing=_verify_envelope)
    return {"path": target.relative_to(root).as_posix(), "sha256": digest,
            "body_sha256": body["sha256"] if body else None,
            "body_representation": body["representation"] if body else "no_http_response"}
