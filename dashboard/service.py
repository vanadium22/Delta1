"""Independent settings, read-side market snapshots and factor scheduling."""
from __future__ import annotations

from copy import deepcopy
import ast
from datetime import datetime
import hashlib
import json
import logging
import math
import time
from pathlib import Path
import threading

from index_strategy.instant_dld.contracts import DEFAULT_CALENDAR_FILE, DEFAULT_MAPPING_FILE
from index_strategy.instant_dld.quotes import CHINA
from index_strategy.instant_dld.realtime_store import DEFAULT_OUTPUT
from index_strategy.instant_dld.service import write_json
from index_strategy.instant_dld.symbols import parse_symbols

from .formulas import definition, evaluate
from .gateway import MarketGateway
from .results import ResultStore
from .templates import TEMPLATES

MODULE_ROOT = Path(__file__).resolve().parent


class DashboardService:
    def __init__(self, local_root=None, *, background=True):
        self.local_root = Path(local_root or MODULE_ROOT / "localsetting").resolve()
        self.config_path = self.local_root / "dashboard.json"
        self.formulas_path = self.local_root / "formulas.json"
        self.lock = threading.RLock()
        self.tick_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.gateway = MarketGateway(self.local_root)
        self.settings = self.validate_config(json.loads(self.config_path.read_text(encoding="utf-8"))) if self.config_path.exists() else self.defaults()
        self.specs = [definition(x) for x in json.loads(self.formulas_path.read_text(encoding="utf-8"))] if self.formulas_path.exists() else [definition(x) for x in TEMPLATES]
        for spec in self.specs:
            revision = self.local_root / "formula_versions" / spec["id"] / (spec["version"] + ".json")
            if not revision.exists():
                write_json(revision, spec)
        if not self.formulas_path.exists():
            write_json(self.formulas_path, self.specs)
        self.output = ResultStore(self.settings["results_root"])
        self.quotes, self.histories, self.factor_states = {}, {}, {}
        self.error = None
        self.updated_at = None
        self.fingerprints = {}
        self.worker = None
        if background:
            self.worker = threading.Thread(target=self._loop, name="dashboard-factors", daemon=True)
            self.worker.start()

    def defaults(self):
        config = {"market_root": str(DEFAULT_OUTPUT), "results_root": str(MODULE_ROOT / "runtime" / "results"),
                  "mapping_file": str(DEFAULT_MAPPING_FILE), "calendar_file": str(DEFAULT_CALENDAR_FILE),
                  "interval": 2.0, "max_age_seconds": 20.0, "max_skew_seconds": 3.0,
                  "symbols": [f"{root}{rank:02}.CFE" for root in ("IF", "IH", "IC", "IM") for rank in range(4)]
                  + ["000300.SH", "000905.SH", "000016.SH", "000852.SH", "510300.SH", "510500.SH",
                     "510050.SH", "512100.SH", "AU.SHF", "000001.SZ"], "previous_result_roots": []}
        return config

    def validate_config(self, value):
        if not isinstance(value, dict):
            raise ValueError("配置需要 JSON 对象")
        result = {}
        for key in ("market_root", "results_root", "mapping_file", "calendar_file"):
            raw = value.get(key)
            if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
                raise ValueError("请输入有效路径：" + key)
            path = Path(raw.strip()).expanduser()
            if not path.is_absolute():
                path = MODULE_ROOT.parent / path
            path = path.resolve()
            if key.endswith("root") and path.exists() and not path.is_dir():
                raise ValueError("目录路径不能是文件")
            result[key] = str(path)
        for key, low, high in (("interval", 0.5, 3600), ("max_age_seconds", 2, 3600), ("max_skew_seconds", 0.5, 60)):
            raw = value.get(key)
            if isinstance(raw, bool):
                raise ValueError("数值格式错误：" + key)
            try:
                number = float(raw)
            except (ValueError, TypeError):
                raise ValueError("数值格式错误：" + key) from None
            if not math.isfinite(number) or not low <= number <= high:
                raise ValueError(f"{key} 需在 {low}–{high} 范围内")
            result[key] = number
        symbols = value.get("symbols")
        if not isinstance(symbols, (list, str)):
            raise ValueError("请输入标的列表")
        result["symbols"] = parse_symbols(json.dumps(symbols) if isinstance(symbols, list) else symbols,
                                           ".json" if isinstance(symbols, list) else ".txt")
        if not 1 <= len(result["symbols"]) <= 200:
            raise ValueError("初版支持 1–200 个订阅代码")
        result["previous_result_roots"] = [str(Path(x).resolve()) for x in value.get("previous_result_roots", [])
                                           if isinstance(x, str)][:20]
        return result

    def save_config(self, value):
        config = self.validate_config(value)
        with self.tick_lock:
            if self.gateway.running():
                raise ValueError("请先停止本看板发起的采集任务，再修改路径或订阅")
            old = self.settings
            replacement = None
            if config["results_root"] != old["results_root"]:
                replacement = ResultStore(config["results_root"])
                config["previous_result_roots"] = list(dict.fromkeys([old["results_root"], *old.get("previous_result_roots", [])]))[:20]
            else:
                config["previous_result_roots"] = old.get("previous_result_roots", [])
            try:
                if replacement is not None:
                    self.output.flush()
                write_json(self.config_path, config)
            except BaseException:
                if replacement is not None:
                    replacement.close()
                raise
            if replacement is not None:
                self.output.close()
                self.output = replacement
            with self.lock:
                self.settings = config
                self.quotes, self.histories, self.factor_states, self.fingerprints = {}, {}, {}, {}
                self.error = None
        return deepcopy(config)

    def _symbols(self):
        return list(dict.fromkeys([*self.settings["symbols"], *(s for f in self.specs if f["enabled"] for s in f["symbols"])]))

    def _read(self, symbols):
        mapping, _ = self.gateway.resolver(self.settings).resolve_many(symbols)
        expanded = list(dict.fromkeys([*symbols, *(m["source_symbol"] for m in mapping.values())]))
        quotes, histories, error = self.gateway.snapshot(self.settings, expanded)
        for alias, identity in mapping.items():
            actual = identity["source_symbol"]
            if alias != actual and alias in quotes and (
                quotes[alias]["source_symbol"] != actual or
                quotes[alias].get("trading_date") != identity["trading_date"]
            ):
                # Never reuse yesterday's alias as today's contract after a roll.
                quotes.pop(alias)
                histories.pop(alias, None)
            if alias not in quotes and actual in quotes:
                candidate = quotes[actual]
                if identity["trading_date"] is None or identity["trading_date"] == candidate.get("trading_date"):
                    quotes[alias] = {**candidate, "symbol": alias, "source_symbol": actual,
                                     "mapping_date": identity.get("mapping_date"), "name": alias, "virtual_alias": True}
                    histories[alias] = histories.get(actual, [])
        return quotes, histories, error

    def _inputs(self, spec):
        missing = [s for s in spec["symbols"] if s not in self.quotes]
        if missing:
            raise ValueError("缺少行情：" + ", ".join(missing))
        chosen = {s: self.quotes[s] for s in spec["symbols"]}
        times = [datetime.fromisoformat(q["timestamp"].replace("Z", "+00:00")) for q in chosen.values()]
        if (max(times) - min(times)).total_seconds() > self.settings["max_skew_seconds"]:
            raise ValueError("两腿采集时间不齐，超过允许误差；请同步采集输入标的")
        return chosen

    def _calculate(self, spec):
        chosen = self._inputs(spec)
        values = evaluate(spec, chosen, self.histories)
        qualities = {q["quality"] for q in chosen.values()}
        quality = "stale" if "stale" in qualities else "closed" if "closed" in qualities else "unverified"
        trade_days = {q["trading_date"] or datetime.fromisoformat(q["timestamp"].replace("Z", "+00:00")).astimezone(CHINA).date().isoformat()
                      for q in chosen.values()}
        if len(trade_days) > 1:
            quality = "mixed_days"
        if all(v is None for v in values.values()):
            quality = "warmup"
        return {"values": values, "quality": quality, "unit": spec["unit"],
                "trade_date": max(trade_days), "inputs": {s: {k: q.get(k) for k in ("sequence", "source_symbol", "timestamp", "quote_time", "trading_date", "mapping_date")}
                                                               for s, q in chosen.items()}}

    def preview(self, value):
        spec = definition(value)
        with self.tick_lock:
            # Preview can read undeclared-in-watchlist inputs without mutating subscriptions.
            quotes, history, error = self._read(list(dict.fromkeys([*self._symbols(), *spec["symbols"]])))
            if error:
                raise ValueError(error)
            old_quotes, old_history = self.quotes, self.histories
            try:
                self.quotes, self.histories = quotes, history
                return {**self._calculate(spec), "version": spec["version"], "note": "预览未发布；源行情日期未经认证，结果仅供观察。"}
            finally:
                self.quotes, self.histories = old_quotes, old_history

    def publish(self, value):
        spec = definition(value)
        with self.tick_lock:
            if len(self.specs) >= 20 and not any(s["id"] == spec["id"] for s in self.specs):
                raise ValueError("初版最多启用 20 个公式")
            new = [s for s in self.specs if s["id"] != spec["id"]] + [spec]
            revision_path = self.local_root / "formula_versions" / spec["id"] / (spec["version"] + ".json")
            if not revision_path.exists():
                write_json(revision_path, spec)
            write_json(self.formulas_path, new)
            self.specs = new
            if self.gateway.running():
                self.gateway.update_symbols(self._symbols())
            self.fingerprints.pop(spec["id"], None)
            self.factor_states.pop(spec["id"], None)
        return spec

    def toggle(self, formula_id, enabled):
        with self.tick_lock:
            for spec in self.specs:
                if spec["id"] == formula_id:
                    return self.publish({**spec, "enabled": bool(enabled)})
        raise ValueError("公式不存在")

    def tick(self):
        with self.tick_lock:
            try:
                symbols = self._symbols()
                quotes, histories, error = self._read(symbols)
                with self.lock:
                    self.quotes, self.histories, self.error = quotes, histories, error
                    self.updated_at = datetime.now(CHINA).isoformat()
                for spec in self.specs:
                    if not spec["enabled"]:
                        self.factor_states[spec["id"]] = {"quality": "disabled", "values": {}, "error": None}
                        continue
                    try:
                        chosen = self._inputs(spec)
                        # Persist one calculation per immutable source observation, including
                        # repeated prices. A -> B -> A is three observations, not two values.
                        evidence = {s: {k: q.get(k) for k in ("sequence", "timestamp", "source_symbol",
                                    "trading_date", "mapping_date", "quality")}
                                    for s, q in chosen.items()}
                        # Include bounded histories only for code that consumes them.
                        if any(isinstance(n, ast.Name) and n.id == "history" for n in ast.walk(ast.parse(spec["code"]))):
                            evidence["_history"] = {s: self.histories.get(s, []) for s in chosen}
                        digest = hashlib.sha256(json.dumps([spec["version"], evidence], sort_keys=True).encode()).hexdigest()
                        if self.fingerprints.get(spec["id"]) == digest:
                            continue
                        result = self._calculate(spec)
                        result.update(id=digest, factor_id=spec["id"], name=spec["name"], version=spec["version"],
                                      calculated_at=datetime.now(CHINA).isoformat(), error=None)
                        self.output.register_formula(spec)
                        self.output.append(result)
                        self.factor_states[spec["id"]] = result
                        self.fingerprints[spec["id"]] = digest
                    except Exception as exc:
                        self.factor_states[spec["id"]] = {"quality": "error", "error": str(exc), "values": {}}
                if self.output.next_flush <= time.monotonic():
                    self.output.flush()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                    self.quotes, self.histories = {}, {}
                for spec in self.specs:
                    self.factor_states[spec["id"]] = {"quality": "error", "error": "行情读取失败：" + str(exc), "values": {}}
                logging.exception("Dashboard update failed")

    def _loop(self):
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(2)

    def snapshot(self):
        with self.tick_lock, self.lock:
            formulas = [{**deepcopy(s), "result": deepcopy(self.factor_states.get(s["id"], {"quality": "waiting", "values": {}}))}
                        for s in self.specs]
            return {"at": datetime.now(CHINA).isoformat(), "updated_at": self.updated_at,
                    "quotes": deepcopy(list(self.quotes.values())), "error": self.error,
                    "formulas": formulas, "collection": self.gateway.collection_status(),
                    "storage": self.output.stats(), "source_time_verified": False}

    def bootstrap(self):
        with self.tick_lock:
            return {"config": deepcopy(self.settings), "templates": deepcopy(TEMPLATES), "state": self.snapshot()}

    def universe(self):
        with self.tick_lock:
            return self.gateway.universe(self.settings)

    def history(self, day=None, factor_id=None):
        if day:
            __import__("datetime").date.fromisoformat(day)
        with self.tick_lock:
            return {"rows": self.output.history(day, factor_id), "storage": self.output.stats()}

    def flush(self):
        with self.tick_lock:
            self.output.flush()
            return self.output.stats()

    def collect(self, once=False):
        with self.tick_lock:
            return self.gateway.start({**self.settings, "symbols": self._symbols()}, once=once)

    def close(self):
        self.stop_event.set()
        self.gateway.close()
        if self.worker:
            self.worker.join(15)
        with self.tick_lock:
            self.output.close()
