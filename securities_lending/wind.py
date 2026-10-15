from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .config import ROOT, atomic_json


def wind_executable(config):
    path = Path(config["wind_python"] or sys.executable)
    # pythonw runs the GUI; use python.exe for the JSON pipe to Wind.
    if path.name.lower() == "pythonw.exe":
        path = path.with_name("python.exe")
    return str(path)


class IndustryProvider:
    """Industry is cached by day; latest prices are always requested anew."""
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.failed_keys = set()

    def lookup(self, codes, day, config):
        industries, _, warnings = self.market([], codes, day, config)
        return industries, "；".join(warnings) or None

    def resolve(self, codes, names, day, config):
        """Resolve identities separately: a failure must not erase market data."""
        if not codes and not names:
            return {}, []
        if not config["wind_enabled"]:
            return {}, ["Wind 已关闭；券单外标的身份未确认，请核对完整证券代码"]
        try:
            proc = subprocess.run(
                [wind_executable(config), "-s", "-X", "utf8", str(ROOT / "wind_worker.py")],
                input=json.dumps({"operation": "resolve", "codes": sorted(set(codes)), "names": sorted(set(names)), "day": day}),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=float(config["wind_timeout_seconds"]),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode:
                raise ValueError("Wind Python 进程启动失败")
            output = json.loads(proc.stdout)
            if output.get("error"):
                raise ValueError(output["error"])
            return output.get("securities", {}), output.get("warnings", [])
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {}, [f"Wind 标的识别失败：{exc}；未识别不代表证券不存在"]

    def market(self, quote_codes, industry_codes, day, config):
        if not quote_codes and not industry_codes:
            return {}, {}, []
        if not config["wind_enabled"]:
            return {}, {}, ["Wind 已关闭，无法取得最新价；缺少行业的记录显示待补充"]
        path = self.data_root / day / "industries.json"
        key = json.dumps([config["wind_field"], config["wind_options"], config["wind_python"]])
        try:
            cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            industries = cache.get("industries", {}) if cache.get("key") == key else {}
            if not isinstance(industries, dict):
                industries = {}
        except (OSError, ValueError, AttributeError):
            industries = {}
        missing = sorted(set(industry_codes) - industries.keys())
        failure_key = (day, key)
        if missing and not quote_codes and failure_key in self.failed_keys:
            return industries, {}, ["Wind 本次连接不可用；修复后点击同步券单重试"]
        if missing or quote_codes:
            request = {"operation": "market", "quote_codes": sorted(set(quote_codes)), "industry_codes": missing,
                       "field": config["wind_field"], "options": config["wind_options"].replace("{date}", day.replace("-", ""))}
            try:
                proc = subprocess.run(
                    [wind_executable(config), "-s", "-X", "utf8", str(ROOT / "wind_worker.py")],
                    input=json.dumps(request), capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=float(config["wind_timeout_seconds"]),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if proc.returncode:
                    raise ValueError("Wind Python 进程启动失败，请检查 wind_python 配置")
                output = json.loads(proc.stdout)
                if output.get("error"):
                    raise ValueError(output["error"])
                industries.update(output.get("industries", {}))
                warnings = list(output.get("warnings", []))
                try:
                    atomic_json(path, {"date": day, "key": key, "industries": industries})
                except OSError as exc:
                    warnings.append(f"行业缓存无法保存：{exc}")
                if any(c not in industries for c in missing):
                    warnings.append("部分标的未返回行业；ETF 等标的可能不适用所选行业分类")
                return industries, output.get("quotes", {}), warnings
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                self.failed_keys.add(failure_key)
                return industries, {}, [f"Wind 获取失败：{exc}；本次不使用旧价格计算"]
        return industries, {}, []
