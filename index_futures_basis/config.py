from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid

from .windows import normalize_windows
from .valuation import valuation_mode
from shared_data import DataPaths

ROOT = Path(__file__).resolve().parent
SHANGHAI = timezone(timedelta(hours=8))
DEFAULTS = {
    "version": 2, "history_months": 12, "close_hour": 15, "close_minute": 5,
    "wind_python": "", "wind_timeout_seconds": 90,
    "wind_mapping_field": "trade_hiscode", "wind_expiry_field": "lasttrade_date",
    "data_directory": "@shared", "exports_directory": "@shared", "auto_sync": True,
    "chart_windows": normalize_windows(), "report_windows": normalize_windows(),
    "chart_valuation": "adjusted", "query_valuation": "adjusted",
    "dividends": {"selection": "latest_snapshot", "directories": ["@shared"],
                  "pattern": "*基差情况_*.xlsx", "sheet": "Sheet1", "header_row": 3,
                  "layout": "snapshot_continuous", "snapshot_date_cell": "B1",
                  "code_column": "B", "dividend_column": "G"},
}


def timestamp():
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def closed_date(config, now=None):
    now = now or datetime.now(SHANGHAI)
    now = now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now.astimezone(SHANGHAI)
    ready = (now.hour, now.minute) >= (config["close_hour"], config.get("close_minute", 0))
    return (now if ready else now - timedelta(days=1)).date().isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def config_path(root=ROOT, demo=False):
    return DataPaths.for_module(root).demo("index_futures_basis") / "config.local.json" if demo else Path(root) / "config.local.json"


def load_config(root=ROOT, demo=False):
    config = copy.deepcopy(DEFAULTS)
    path = config_path(root, demo)
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
        # Migrate the old default; preserve deliberately customized later times.
        if saved.get("version", 1) < 2:
            if saved.get("close_hour", 18) == 18:
                saved.update(close_hour=15, close_minute=5)
            else:
                saved.setdefault("close_minute", 0)
            saved["version"] = 2
        dividend_patch = saved.pop("dividends", {})
        config.update(saved)
        config["dividends"].update(dividend_patch)
    validate_config(config)
    return config


def validate_config(config):
    for key in ("chart_valuation", "query_valuation"):
        valuation_mode(config.get(key, "adjusted"))
    for key in ("chart_windows", "report_windows"):
        normalize_windows(config.get(key))
    if not 12 <= int(config["history_months"]) <= 36:
        raise ValueError("历史窗口须为12至36个月")
    hour, minute = int(config["close_hour"]), int(config.get("close_minute", 0))
    if not (15, 5) <= (hour, minute) <= (23, 59) or not 0 <= minute <= 59:
        raise ValueError("日线检查时间须为北京时间15:05至23:59；默认15:05")
    if not 10 <= float(config["wind_timeout_seconds"]) <= 600:
        raise ValueError("Wind 单次请求超时须为10至600秒")
    for key in ("data_directory", "exports_directory"):
        if not str(config[key]).strip():
            raise ValueError(f"{key} 不能为空")
    if not config["dividends"]["directories"]:
        raise ValueError("请配置分红文件夹")


def resolve(root, path):
    return (Path(root) / path).resolve()
