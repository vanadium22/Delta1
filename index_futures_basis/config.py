from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parent
SHANGHAI = timezone(timedelta(hours=8))
DEFAULTS = {
    "version": 1, "history_months": 12, "close_hour": 18,
    "wind_python": "", "wind_timeout_seconds": 90,
    "wind_mapping_field": "trade_hiscode", "wind_expiry_field": "lasttrade_date",
    "data_directory": "data", "exports_directory": "exports", "auto_sync": True,
    "dividends": {"selection": "latest_snapshot", "directories": ["inputs", "input"],
                  "pattern": "*基差情况_*.xlsx", "sheet": "Sheet1", "header_row": 3,
                  "layout": "snapshot_continuous", "snapshot_date_cell": "B1",
                  "code_column": "B", "dividend_column": "G"},
}


def timestamp():
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def closed_date(config, now=None):
    now = now or datetime.now(SHANGHAI)
    return (now if now.hour >= config["close_hour"] else now - timedelta(days=1)).date().isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_config(root=ROOT, demo=False):
    config = copy.deepcopy(DEFAULTS)
    path = Path(root) / ("data/demo/config.local.json" if demo else "config.local.json")
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
        dividend_patch = saved.pop("dividends", {})
        config.update(saved)
        config["dividends"].update(dividend_patch)
    validate_config(config)
    return config


def validate_config(config):
    if not 12 <= int(config["history_months"]) <= 36:
        raise ValueError("历史窗口须为12至36个月")
    if not 16 <= int(config["close_hour"]) <= 23:
        raise ValueError("完整日线门槛须为北京时间16至23点；默认18点")
    if not 10 <= float(config["wind_timeout_seconds"]) <= 600:
        raise ValueError("Wind 单次请求超时须为10至600秒")
    for key in ("data_directory", "exports_directory"):
        if not str(config[key]).strip():
            raise ValueError(f"{key} 不能为空")
    if not config["dividends"]["directories"]:
        raise ValueError("请配置分红文件夹")


def resolve(root, path):
    return (Path(root) / path).resolve()
