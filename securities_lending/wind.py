from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .config import ROOT, atomic_json


class IndustryProvider:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.failed_keys = set()

    def lookup(self, codes, day, config):
        if not codes:
            return {}, None
        if not config["wind_enabled"]:
            return {}, "Wind 已关闭；未含行业的券单记录显示待补充"
        path = self.data_root / day / "industries.json"
        key = json.dumps([config["wind_field"], config["wind_options"], config["wind_python"]])
        try:
            cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            cache = {}
        industries = cache.get("industries", {}) if cache.get("key") == key else {}
        missing = sorted(set(codes) - industries.keys())
        failure_key = (day, key)
        if missing and failure_key in self.failed_keys:
            return industries, "Wind 本次连接不可用；修复后点击「同步当日券单」重试"
        if missing:
            request = {"codes": missing, "field": config["wind_field"], "options": config["wind_options"].replace("{date}", day.replace("-", ""))}
            try:
                proc = subprocess.run(
                    [config["wind_python"] or sys.executable, "-X", "utf8", str(ROOT / "wind_worker.py")],
                    input=json.dumps(request), capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=float(config["wind_timeout_seconds"]),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if proc.returncode:
                    raise ValueError("Wind Python 进程启动失败，请检查 wind_python 配置")
                output = json.loads(proc.stdout)
                if output.get("error"):
                    raise ValueError(output["error"])
                industries.update(output["industries"])
                atomic_json(path, {"date": day, "key": key, "industries": industries})
                if any(c not in industries for c in missing):
                    return industries, "部分标的未返回行业；ETF 等标的可能不适用所选行业分类"
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                self.failed_keys.add(failure_key)
                return industries, f"Wind 行业补充失败：{exc}"
        return industries, None
