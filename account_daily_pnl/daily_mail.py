"""Freeze one generated PnL report for the existing workbench mail queue."""

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from shared_data.io import atomic_json, sha256
from .strategy_reconciliation import BOOK_NAME, CHART_NAME


RECIPIENT = "meiyifan@swhysc.com"


def create_manifest(outputs):
    outputs = Path(outputs).resolve()
    book_path = outputs / BOOK_NAME
    image_path = outputs / CHART_NAME
    book = load_workbook(book_path, read_only=True, data_only=True)
    try:
        title = book["收益汇总"]["A1"].value
        if not isinstance(title, str) or not title.startswith("项目 · "):
            raise ValueError("策略台汇总日期无法识别。")
        report_day = date.fromisoformat(title.removeprefix("项目 · ")).isoformat()
        content = [[sheet.title, list(sheet.values)] for sheet in book.worksheets]
    finally:
        book.close()

    def serialize(value):
        if isinstance(value, (date, datetime, Decimal)):
            return str(value)
        raise TypeError(f"不支持的汇总单元格类型：{type(value).__name__}")

    identity = json.dumps({"report_day": report_day, "sheets": content, "image": sha256(image_path)},
                          ensure_ascii=False, sort_keys=True, default=serialize).encode("utf-8")
    key = hashlib.sha256(identity).hexdigest()
    archive = outputs / "mail" / key
    descriptor = archive / "manifest.json"
    if descriptor.is_file():
        existing = json.loads(descriptor.read_text(encoding="utf-8"))
        for item in existing["mail"]["attachments"]:
            path = Path(item["path"])
            if not path.is_file() or path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
                raise ValueError("已归档邮件附件发生变化，请检查发送记录。")
        return existing

    archive.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".pnl-mail-", dir=archive.parent) as temporary:
        staging = Path(temporary)
        for source in (book_path, image_path):
            shutil.copyfile(source, staging / source.name)
            if sha256(source) != sha256(staging / source.name):
                raise ValueError("邮件附件复制期间发生变化，请重试。")
        attachments = []
        for source in (book_path, image_path):
            frozen = staging / source.name
            item = {"path": str(archive / source.name), "size": frozen.stat().st_size, "sha256": sha256(frozen)}
            if source == image_path:
                item.update(content_id="strategy-pnl@daily", content_type="image/png", also_attach=True)
            attachments.append(item)
        body = f"策略台 PnL 对账截至 {report_day}。汇总 Excel 和图片见附件。"
        manifest = {"delivery_key": "account-pnl-" + key,
                    "mail": {"to": [RECIPIENT], "cc": [], "bcc": [],
                             "subject": f"策略台 PnL 汇总 {report_day}", "body": body,
                             "html_body": f"<p>{body}</p><img src=\"cid:strategy-pnl@daily\">",
                             "attachments": attachments}}
        atomic_json(staging / "manifest.json", manifest)
        staging.rename(archive)
        return manifest
