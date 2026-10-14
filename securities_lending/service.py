from __future__ import annotations

import re
import threading
from pathlib import Path

from . import config as settings
from .config import atomic_json, load_config, source_directory, timestamp
from .inventory import normalize_code, parse_workbook
from .sync import cached_manifest, save_manifest, synchronize
from .wind import IndustryProvider


def demo_source(root: Path, day: str):
    from openpyxl import Workbook
    folder = root / day
    folder.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.title = "库存券单"
    sheet.append(["合成演示券单 · 不代表真实可融库存"])
    sheet.append(["证券代码", "证券名称", "可融数量（股）", "名本（万元）", "出借费率", "所属行业", "期限"])
    for row in [
        ["600519.SH", "贵州茅台", 12000, 1680, .025, "食品饮料", "28天"],
        ["600519.SH", "贵州茅台", 8000, 1120, .028, "食品饮料", "14天"],
        ["300750.SZ", "宁德时代", 160000, 3200, .032, "电力设备", "28天"],
        ["601318.SH", "中国平安", 420000, 2100, .022, "非银金融", "28天"],
        ["000001.SZ", "平安银行", 800000, 960, .018, "银行", "14天"],
        ["600036.SH", "招商银行", 300000, 1050, .021, "银行", "28天"],
        ["688981.SH", "中芯国际", 50000, 450, .04, "电子", "14天"],
        ["000858.SZ", "五粮液", 0, 0, .03, "食品饮料", "28天"],
    ]:
        sheet.append(row)
        sheet.cell(sheet.max_row, 5).number_format = "0.00%"
    book.save(folder / "合成演示_库存券单.xlsx")
    book.close()


def summarize(code: str, rows: list[dict]):
    quantities = [r["quantity"] for r in rows if r["quantity"] is not None]
    nominals = [r["nominal"] for r in rows if r["nominal"] is not None]
    rates = sorted(set(r["rate"] for r in rows if r["rate"] is not None))
    raw_rates = sorted(set(r["rate_raw"] for r in rows if r["rate"] is None and r["rate_raw"]))
    industries = sorted(set(r["industry"] for r in rows if r["industry"]))
    return {
        "code": code, "name": next((r["name"] for r in rows if r["name"]), "未提供名称"),
        "quantity": sum(quantities) if quantities else None,
        "quantity_complete": len(quantities) == len(rows),
        "nominal": sum(nominals) if nominals else None,
        "nominal_complete": len(nominals) == len(rows),
        "nominal_estimated": any(r["nominal_source"].startswith("估算") for r in rows),
        "rate_min": min(rates) if rates else None, "rate_max": max(rates) if rates else None,
        "rate_raw": raw_rates, "rate_complete": all(r["rate"] is not None or r["rate_raw"] for r in rows),
        "industry": " / ".join(industries) or None,
        "industry_source": " / ".join(sorted(set(r["industry_source"] for r in rows if r["industry"]))) or None,
        "rows": rows,
    }


class InventoryService:
    def __init__(self, root: Path = settings.ROOT, demo=False, clock=None):
        self.root, self.demo = root, demo
        self.clock = clock or settings.today
        self.config_path = root / "config.local.json"
        self.config = load_config(self.config_path)
        self.data_root = root / "data" / ("demo" if demo else "live")
        self.provider = IndustryProvider(self.data_root)
        self.records = []
        self.lock = threading.RLock()
        self.state = {"date": self.clock(), "mode": "demo" if demo else "live", "state": "loading", "warnings": [], "files": [], "record_count": 0, "security_count": 0}

    def active_config(self):
        config = dict(self.config)
        if self.demo:
            config.update(source_root=str(self.root / "data" / "demo_source"), wind_enabled=False, file_glob="*.xlsx", file_selection="latest", columns={}, header_row=None)
        return config

    def update_config(self, patch):
        unknown = set(patch) - settings.DEFAULTS.keys()
        if unknown:
            raise ValueError(f"未知配置：{', '.join(sorted(unknown))}")
        config = {**self.config, **patch}
        settings.validate(config)
        atomic_json(self.config_path, config)
        self.config = config
        return self.refresh()

    def _parse(self, manifest, config):
        records, warnings, files = [], list(manifest["warnings"]), []
        for entry in manifest["files"]:
            rows, notices, mapping = parse_workbook(Path(entry["path"]), config)
            records.extend(rows)
            warnings.extend(notices)
            files.append({**entry, **mapping, "records": len(rows)})
        return records, warnings, files

    def refresh(self):
        with self.lock:
            day, config = self.clock(), self.active_config()
            self.provider.failed_keys.clear()
            manifest, parsed, issue = None, None, None
            try:
                if self.demo:
                    demo_source(self.root / "data" / "demo_source", day)
                manifest = synchronize(config, day, self.data_root)
                manifest["file_glob"] = config["file_glob"]
                parsed = self._parse(manifest, config)
                save_manifest(self.data_root, manifest)
            except Exception as exc:
                issue = str(exc)
                manifest = None
                try:
                    manifest = cached_manifest(self.data_root, day, config)
                    if manifest:
                        parsed = self._parse(manifest, config)
                except Exception as cache_exc:
                    issue += f"；缓存也无法使用：{cache_exc}"
                    manifest = None
            self.records = parsed[0] if manifest and parsed else []
            try:
                source = str(source_directory(config, day))
            except ValueError:
                source = "未配置"
            self.state = {
                "date": day, "mode": "demo" if self.demo else "live",
                "state": "cached" if manifest and issue else "ready" if manifest else "unavailable",
                "source_dir": source, "refreshed_at": timestamp(),
                "downloaded_at": manifest["downloaded_at"] if manifest else None,
                "warnings": ([issue] if issue else []) + (parsed[1] if manifest and parsed else []),
                "files": parsed[2] if manifest and parsed else [],
                "record_count": len(self.records), "security_count": len(set(r["code"] for r in self.records)),
                "selection": config["file_selection"],
            }
            return self.state

    def status(self):
        with self.lock:
            if self.state["state"] == "loading" or self.state["date"] != self.clock():
                self.refresh()
            return self.state

    def query(self, text: str):
        with self.lock:
            status = self.status()
            tokens = list(dict.fromkeys(x for x in re.split(r"[\s,，;；、]+", text.strip()) if x))
            if not tokens:
                raise ValueError("请输入至少一个证券代码或名称")
            if len(tokens) > 100 or len(text) > 10000:
                raise ValueError("每次最多查询 100 个标的")
            groups, codes = [], set()
            for token in tokens:
                normalized = normalize_code(token)
                rows = [dict(r) for r in self.records if (r["code"] == normalized if normalized else token.casefold() in r["name"].casefold())]
                grouped = {}
                for row in rows:
                    grouped.setdefault(row["code"], []).append(row)
                    if not row["industry"]:
                        codes.add(row["code"])
                groups.append((token, grouped))
            industries, notice = self.provider.lookup(codes, status["date"], self.active_config())
            results, unique = [], {}
            for token, grouped in groups:
                matches = []
                for code, rows in grouped.items():
                    for row in rows:
                        if not row["industry"] and code in industries:
                            row["industry"] = industries[code]
                            row["industry_source"] = "Wind · " + self.config["industry_label"]
                    item = summarize(code, rows)
                    matches.append(item)
                    unique[code] = item
                results.append({"input": token, "matches": matches})
            values = list(unique.values())
            quantities = [v["quantity"] for v in values if v["quantity"] is not None]
            nominals = [v["nominal"] for v in values if v["nominal"] is not None]
            return {"status": status, "results": results, "warnings": [notice] if notice else [], "summary": {
                "inputs": len(tokens), "matched": len(values), "unmatched": sum(not g["matches"] for g in results),
                "quantity": sum(quantities) if quantities else None,
                "quantity_complete": bool(values) and all(v["quantity_complete"] for v in values),
                "nominal": sum(nominals) if nominals else None,
                "nominal_complete": bool(values) and all(v["nominal_complete"] for v in values),
                "nominal_estimated": any(v["nominal_estimated"] for v in values),
            }}
