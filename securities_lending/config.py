from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULTS = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
SHANGHAI = timezone(timedelta(hours=8))


def today() -> str:
    return datetime.now(SHANGHAI).date().isoformat()


def timestamp() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def load_config(path: Path) -> dict:
    config = dict(DEFAULTS)
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8-sig")))
    validate(config)
    return config


def validate(config: dict) -> None:
    if config["file_selection"] not in {"latest", "merge"}:
        raise ValueError("文件读取方式必须为 latest 或 merge")
    if config["numeric_rate_unit"] not in {"percent", "decimal"}:
        raise ValueError("numeric_rate_unit 必须为 percent 或 decimal")
    if config["quantity_unit"] not in {"股", "万股"} or config["nominal_unit"] not in {"元", "万元", "亿元"}:
        raise ValueError("数量单位应为股/万股，名本单位应为元/万元/亿元")
    if config["header_row"] is not None and (type(config["header_row"]) is not int or not 1 <= config["header_row"] <= 100):
        raise ValueError("header_row 应为 1–100 的 Excel 行号，或 null 自动识别")
    if not isinstance(config["columns"], dict) or not all(isinstance(v, str) for v in config["columns"].values()):
        raise ValueError("columns 应为字段到原始列名的映射")
    if not 1 <= float(config["wind_timeout_seconds"]) <= 120:
        raise ValueError("Wind 超时应为 1–120 秒")
    if not isinstance(config["wind_enabled"], bool):
        raise ValueError("wind_enabled 必须是 true/false")
    for key in ("source_root", "file_glob", "sheet_name", "wind_python", "wind_field", "wind_options", "industry_label"):
        if not isinstance(config[key], str):
            raise ValueError(f"{key} 必须为文本")
    if not config["sheet_name"].strip():
        raise ValueError("Sheet 名不能为空")
    if any(x in config["file_glob"] for x in ("/", "\\", "..")):
        raise ValueError("文件筛选仅支持文件名通配符，不支持目录")


def source_directory(config: dict, day: str) -> Path:
    root = config["source_root"].strip()
    if not root:
        raise ValueError("请在数据设置中填写发送券单根目录")
    if "{date}" in root:
        return Path(root.replace("{date}", day))
    path = Path(root)
    # Pasting a dated folder is supported, but its date is never frozen.
    import re
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name):
        path = path.parent
    return path / day
