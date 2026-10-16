"""Shared calculation and export service for the native App and command line."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import shutil
import threading
import uuid

import numpy as np
import pandas as pd

from . import __version__
from .analytics import (attach_dividends, fixed_tenor, historical_summary, read_dividends, sha256, spreads, total_oi)
from .analytics import ROOTS as SPOT_CODES
from .config import ROOT, atomic_json, closed_date, config_path, load_config, resolve, timestamp, validate_config
from shared_data import Catalog, DataPaths, Dataset
from shared_data.migration import copy_verified, ensure_migrated
from shared_data.io import file_lock
from .distributions import annualized_distributions, cross_index_basis, cross_index_distributions, distribution_rows
from .store import Store
from .sync import Cancelled, synchronize
from .wind import WindProvider
from .term_structure import term_analysis, term_distributions
from .windows import normalize_windows, required_history_months

ROOTS = list(SPOT_CODES)
METRICS = {
    "annualized_basis_pct": ("分红调整后年化基差", "%"),
    "basis_points": ("分红调整后绝对基差", "点"),
    "raw_basis_points": ("未调整绝对基差", "点"),
    "open_interest": ("持仓量", "手"),
    "oi_change": ("同合约持仓日变化", "手"),
    "fixed_60d": ("60天固定期限年化基差", "%"),
    "fixed_90d": ("90天固定期限年化基差", "%"),
    "calendar_02_00": ("02−00 跨期年化基差", "%"),
    "calendar_03_02": ("03−02 跨期年化基差", "%"),
    "calendar_spread": ("所选远月减当月价差", "点"),
    "im_ic": ("同期限 IM−IC 绝对基差差", "点"),
}


def calculation_version():
    digest = hashlib.sha256(__version__.encode())
    for name in ("analytics.py", "distributions.py", "term_structure.py", "windows.py", "report.py", "service.py"):
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


@dataclass
class Analysis:
    panel: pd.DataFrame
    fixed: pd.DataFrame
    spread: pd.DataFrame
    totals: pd.DataFrame
    history: pd.DataFrame
    annual_quantiles: pd.DataFrame
    cross: pd.DataFrame
    cross_quantiles: pd.DataFrame
    start: pd.Timestamp
    end: pd.Timestamp
    fingerprint: str
    provenance: dict
    dividends: pd.DataFrame
    fixed90: pd.DataFrame
    fixed90_quantiles: pd.DataFrame
    calendar_annualized: pd.DataFrame
    calendar_quantiles: pd.DataFrame
    fixed_quantiles: pd.DataFrame
    calendar_point_quantiles: pd.DataFrame


class BasisService:
    def __init__(self, root=ROOT, mode="wind", config=None):
        if mode not in {"wind", "offline", "demo"}:
            raise ValueError("未知数据模式")
        self.root, self.mode = Path(root).resolve(), mode
        self.paths = DataPaths.for_module(self.root)
        ensure_migrated("index_futures_basis", self.root, self.paths)
        self.config = config or load_config(self.root, demo=mode == "demo")
        market = self.paths.root / "market" / "index_futures"
        base = self.paths.resolve_module_setting(self.root, self.config["data_directory"], market, ("data",))
        self.data_root = self.paths.basis(mode) if base == market else base / mode
        self.exports_root = self.paths.resolve_module_setting(self.root, self.config["exports_directory"], self.paths.export("index_futures_basis"), ("exports",)) / mode
        self.dividend_archive = self.paths.demo("index_futures_basis") / "dividends" if mode == "demo" else self.paths.dividend_archive
        self.store = Store(self.data_root / "market.sqlite")
        if self.store.path == self.paths.basis(mode) / "market.sqlite":
            Catalog(self.paths).register(Dataset("index_futures", "wind" if mode == "wind" else "imported" if mode == "offline" else "synthetic",
                                                "1d", mode="live" if mode == "wind" else mode, storage="sqlite"), self.store.path)
        self._cache = None
        self.cancel = threading.Event()
        if mode == "demo" and not set(ROOTS).issubset(self.store.roots()):
            # Only regenerate synthetic data; real/offline caches are never fabricated.
            from .demo import snapshot
            raw = snapshot()
            self.store.import_raw(raw, {"kind": "demo", "label": raw["source"]})

    def window(self, end=None):
        if end is None:
            end = closed_date(self.config) if self.mode == "wind" else self.store.bounds()[1] or closed_date(self.config)
        months = max(int(self.config["history_months"]), *(required_history_months(self.config.get(key))
                     for key in ("chart_windows", "report_windows")))
        start = str((pd.Timestamp(end) - pd.DateOffset(months=months) - pd.Timedelta(days=15)).date())
        return start, end

    def status(self):
        start, end = self.window()
        coverage = self.store.coverage(start, end)
        known = self.store.calendar(start, end)
        unknown = sum(str(d.date()) not in known for d in pd.date_range(start, end))
        return {"mode": self.mode, "source": self.store.meta("source", {}), "start": start, "requested_end": end,
                "calendar_unknown_days": unknown, "database": str(self.store.path),
                "runs": self.store.runs(), **coverage}

    def sync(self, progress=lambda text: None, repair=None, provider=None, end=None):
        if self.mode != "wind":
            raise ValueError("离线和演示模式不访问 Wind；请切换到 Wind 正式数据")
        self.cancel.clear()
        provider = provider or WindProvider(self.config)
        try:
            return synchronize(self.store, provider, *self.window(end), progress, self.cancel, repair)
        finally:
            self._cache = None
            if hasattr(provider, "close"):
                provider.close()

    def import_snapshot(self, path):
        if self.mode != "offline":
            raise ValueError("快照只导入离线库，不与 Wind 正式库混用")
        path = Path(path).resolve()
        source_bytes = path.read_bytes()
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(io.BytesIO(source_bytes))
            required = ["trade_date", "root", "slot", "instrument_id", "expiry_date", "futures_close", "spot_close", "open_interest"]
            raw = {"records": frame[required].to_dict("records"), "calendar": sorted(frame.trade_date.unique()),
                   "source": "CSV 离线快照，交易日覆盖沿用原文件"}
        else:
            raw = json.loads(source_bytes.decode("utf-8-sig"))
        digest = hashlib.sha256(source_bytes).hexdigest()
        source = {"kind": "offline", "label": raw.get("source", "用户导入快照"), "path": str(path), "sha256": digest,
                  "imported_at": timestamp()}
        count = self.store.import_raw(raw, source)
        archive = self.data_root / "sources" / (digest + path.suffix)
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(source_bytes)
        if sha256(archive) != digest:
            raise ValueError("导入期间源文件发生变化，请重试")
        self._cache = None
        return f"已导入{count}条离线记录；与 Wind 正式库分开保存"

    def dividend_directories(self):
        return list(dict.fromkeys(self.paths.resolve_module_setting(self.root, folder, self.paths.dividend_inputs, ("inputs", "input"))
                                  for folder in self.config["dividends"]["directories"]))

    def dividend_input(self, end):
        if self.mode == "demo":
            from .demo import dividends
            values = dividends(end)
            return values, {"path": "合成演示分红", "sha256": "synthetic-v1", "snapshot_date": str(end.date()),
                "historical_type": "fixed_snapshot_scenario", "application": "snapshot_continuous"}
        config = dict(self.config["dividends"])
        config["directories"] = [str(p) for p in self.dividend_directories()]
        values, info = read_dividends(config, self.root)
        snapshot = self.dividend_archive / (info["sha256"] + ".xlsx")
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.dividend_archive / ".writer.lock"):
            copy_verified(info["path"], snapshot, expected_sha256=info["sha256"])
        if sha256(snapshot) != info["sha256"]:
            raise ValueError("分红文件读取期间发生变化，请保存后重试")
        info["archived_input"] = str(snapshot)
        return values, info

    def analyze(self, as_of=None, windows=None):
        windows = normalize_windows(windows)
        # Another App window cannot change mappings/quotes between these reads.
        with self.store.writer_lock():
            status = self.status()
            end = pd.Timestamp(as_of or status["latest_complete"])
            if pd.isna(end):
                missing = "、".join(row["root"] for row in status["rows"] if not row["complete_days"])
                raise ValueError(f"本地还没有{'、'.join(ROOTS)}共同完整的交易日；待补齐品种：{missing}。"
                                 "请增量更新行情或导入包含全部品种的离线快照")
            if str(end.date()) > status["requested_end"]:
                raise ValueError("所选截止日超过当前可用完整日线范围")
            history_start = end - pd.DateOffset(months=max(12, required_history_months(windows))) - pd.Timedelta(days=15)
            panel = self.store.panel(str(history_start.date()), str(end.date()))
            market_source = self.store.meta("source", {})
        if panel.trade_date.max() != end:
            raise ValueError("所选截止日不是本地完整交易日")
        dividends, info = self.dividend_input(end)
        raw_digest = hashlib.sha256(pd.util.hash_pandas_object(panel, index=False).values.tobytes()).hexdigest()
        code_digest = calculation_version()
        key = hashlib.sha256(json.dumps([raw_digest, info["sha256"], str(end), code_digest, windows], ensure_ascii=False).encode()).hexdigest()
        if self._cache is not None and self._cache.fingerprint == key:
            return self._cache
        start = end - pd.DateOffset(months=windows["series_months"])
        adjusted = attach_dividends(panel, dividends, start, info.get("application", "exact_date"))
        fixed, spread, totals = fixed_tenor(adjusted), spreads(adjusted), total_oi(adjusted)
        cross = cross_index_basis(adjusted)
        terms = term_analysis(adjusted, end, windows)
        fixed_quantiles = term_distributions(fixed, end, ["root"], "interpolable",
                                             windows=windows["fixed_60_quantile_months"])
        calendar_point_quantiles = term_distributions(terms[2], end, ["root", "pair"],
            windows=windows["calendar_quantile_months"], value="spread_points")
        provenance = {"generated_at": timestamp(), "mode": self.mode, "actual_end": str(end.date()),
            "requested_end": status["requested_end"], "plot_start": str(start.date()), "roots": ROOTS,
            "market_source": market_source, "raw_data_sha256": raw_digest, "dividends": info,
            "fingerprint": key, "app_version": __version__, "calculation_code_sha256": code_digest,
            "configuration": {"quantile_whiskers": "p05_p95", "windows": windows},
            "basis_formula": "futures_close + dividend_points - spot_close",
            "annualized_formula": "basis_points / spot_close * 36500 / days_to_expiry; days>=5",
            "fixed_tenor_formula": "interpolate basis_rate between actual maturities, then *36500/target_days; no extrapolation",
            "calendar_annualized_formula": "((F_far+G_far)-(F_near+G_near))/spot_close*36500/(expiry_far-expiry_near).days",
            "calendar_absolute_formula": "spread_points = (F_far+G_far)-(F_near+G_near); signed index points; no annualization",
            "term_quantile_windows": {"fixed60": windows["fixed_60_quantile_months"],
                "fixed90": windows["fixed_90_quantile_months"], "calendar": windows["calendar_quantile_months"],
                "rule": "calendar months; exclude current day; fixed-tenor unbracketed dates excluded, missing inputs not excluded"},
            "quantile_windows": "[end - N calendar months, end); exclude display fills; half-weight ties"}
        self._cache = Analysis(adjusted, fixed, spread, totals,
            historical_summary(adjusted, end, windows["annual_quantile_months"]),
            annualized_distributions(adjusted, end, windows["annual_quantile_months"]), cross,
            cross_index_distributions(cross, end, windows["cross_quantile_months"]),
            start, end, key, provenance, dividends, *terms, fixed_quantiles, calendar_point_quantiles)
        return self._cache

    def query(self, root="IC", slot=4, metric="annualized_basis_pct", as_of=None):
        if root not in ROOTS or slot not in range(1, 5) or metric not in METRICS:
            raise ValueError("品种、连续档位或指标无效")
        a = self.analyze(as_of)
        base = a.panel[a.panel.root.eq(root) & a.panel.slot.eq(slot)].copy()
        latest = base[base.trade_date.eq(a.end)].iloc[0]
        series = base.copy()
        label, unit = METRICS[metric]
        if metric in {"fixed_60d", "fixed_90d"}:
            fixed = a.fixed if metric == "fixed_60d" else a.fixed90
            series = fixed[fixed.root.eq(root)].rename(columns={"annualized_basis_pct": "value"})
        elif metric in {"calendar_02_00", "calendar_03_02"}:
            pair_name = metric.removeprefix("calendar_").replace("_", "-")
            series = a.calendar_annualized[a.calendar_annualized.root.eq(root)
                & a.calendar_annualized.pair.eq(pair_name)].rename(columns={"annualized_basis_pct": "value"})
            series["instrument_id"] = series.far_contract + " − " + series.near_contract
            series["expiry_date"] = series.far_expiry
        elif metric == "calendar_spread":
            if slot == 1:
                raise ValueError("跨期价差请选择次月、季月一或最远月")
            series = a.spread[(a.spread.root == root) & (a.spread.spread == f"{root}0{slot-1}−{root}00")].rename(columns={"spread_points": "value"})
        elif metric == "im_ic":
            series = a.cross[a.cross.slot.eq(slot)].rename(columns={"basis_difference_points": "value"})
        else:
            series = series.rename(columns={metric: "value"})
        eligible = None
        if metric == "annualized_basis_pct":
            series["eligible"] = series.days_to_expiry.ge(5)
            eligible = "eligible"
        elif metric in {"fixed_60d", "fixed_90d"}:
            eligible = "interpolable"
        elif metric == "oi_change":
            # Raw coverage is checked separately; mathematically undefined observations
            # (e.g. a newly listed contract with no previous OI) are not zero samples.
            series["eligible"] = series.value.notna()
            eligible = "eligible"
        windows = (3, 6, 12)
        rows = distribution_rows(series, a.end, "value", eligible, windows=windows)
        for row in rows:
            g = series[series.trade_date.ge(row["window_start"]) & series.trade_date.lt(a.end)]
            if eligible:
                g = g[g[eligible]]
            row["mean"] = g.value.mean() if row["complete"] else np.nan
        title = f"{root}0{slot-1} · {label}"
        contract = latest.instrument_id
        if metric == "im_ic":
            title = f"IM0{slot-1}−IC0{slot-1} · {label}"
            pair = a.cross[a.cross.slot.eq(slot) & a.cross.trade_date.eq(a.end)].iloc[0]
            contract = f"{pair.im_contract} / {pair.ic_contract}"
        elif metric in {"fixed_60d", "fixed_90d"}:
            title = f"{root} · {label}"
            contract = f"{60 if metric == 'fixed_60d' else 90}天插值（使用00—03实际合约）"
        elif metric in {"calendar_02_00", "calendar_03_02"}:
            title = f"{root} · {label}"
            current_pair = series[series.trade_date.eq(a.end)].iloc[0]
            contract = f"{current_pair.far_contract} − {current_pair.near_contract}"
        return {"title": title, "unit": unit, "statistics": pd.DataFrame(rows), "series": series,
                "current_contract": contract, "expiry": ("—" if metric.startswith("fixed_") else
                    f"{current_pair.near_expiry:%Y-%m-%d} → {current_pair.far_expiry:%Y-%m-%d}"
                    if metric in {"calendar_02_00", "calendar_03_02"} else str(latest.expiry_date.date())),
                "actual_end": str(a.end.date()), "fingerprint": a.fingerprint, "provenance": a.provenance,
                "current": rows[0]["current"], "metric": metric, "root": root, "slot": slot}

    def save_settings(self, patch):
        updated = {**self.config, **patch}
        validate_config(updated)
        path = config_path(self.root, self.mode == "demo")
        atomic_json(path, updated)
        return "设置已保存；重新打开应用后生效"

    def output_windows(self, kind):
        return normalize_windows(self.config.get("chart_windows" if kind == "figures" else "report_windows"))

    def save_output_windows(self, kind, values):
        if kind not in {"figures", "report"}:
            raise ValueError("请选择图片或报告时间窗口")
        key = "chart_windows" if kind == "figures" else "report_windows"
        values = normalize_windows(values)
        updated = load_config(self.root, demo=self.mode == "demo")
        updated[key] = values
        path = config_path(self.root, self.mode == "demo")
        atomic_json(path, updated)
        self.config[key] = values
        return "时间窗口已保存，下次生成立即生效"

    def artifacts(self, fingerprint=None):
        roots = list(dict.fromkeys([self.exports_root, self.root / "exports" / self.mode]))
        if self.mode == "offline":
            roots.append(self.root.parent / "research/index_futures_basis/outputs")
        items = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("run_manifest.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    items.append({"path": str(path.parent), "created": data.get("generated_at", ""),
                        "as_of": data.get("actual_end", ""), "kind": data.get("kind", "历史研究报告"),
                        "fingerprint": data.get("fingerprint"),
                        "state": "与本次查询一致" if fingerprint and data.get("fingerprint") == fingerprint else "历史版本／未比对",
                        "dividend_date": data.get("dividends", {}).get("snapshot_date", "")})
                except (OSError, ValueError):
                    continue
        return sorted(items, key=lambda item: item["created"], reverse=True)

    def prepare_report(self, as_of=None, progress=lambda text: None):
        """Refresh a frozen cutoff, verify it, or explicitly fall back one exchange session."""
        eligible = closed_date(self.config)
        cutoff = str(pd.Timestamp(as_of).date()) if as_of else eligible
        if cutoff == "NaT" or cutoff > eligible:
            raise ValueError(f"所选报告日期超过当前日线检查范围（截至{eligible}）；尚未到当日检查时间")
        start, _ = self.window(cutoff)
        hour, minute = self.config["close_hour"], self.config.get("close_minute", 0)
        progress(f"生成报告前检查并补齐行情：截至{cutoff}（北京时间{hour:02d}:{minute:02d}后纳入当天）")
        try:
            outcome = self.sync(progress, end=cutoff)
        except Cancelled:
            raise
        except Exception as exc:
            outcome = {"state": "failed", "message": str(exc)}
        if self.cancel.is_set():
            raise Cancelled("报告已取消，未生成新报告；已下载行情保留")
        reason = (outcome["message"] or f"同步状态为{outcome['state']}") if outcome["state"] != "complete" else ""
        with self.store.writer_lock():
            calendar = self.store.calendar(start, cutoff)
            unknown = [str(d.date()) for d in pd.date_range(start, cutoff) if str(d.date()) not in calendar]
            opened = [day for day, is_open in calendar.items() if is_open]
            target = (cutoff if as_of else max(opened, default=None)) if not unknown else None
            coverage = self.store.coverage(start, cutoff)
            latest = coverage["latest_complete"] or "暂无"
            if not reason:
                if unknown:
                    reason = f"交易日历未核验：{unknown[-1]}等{len(unknown)}个日期"
                elif not target or not calendar.get(target):
                    reason = "目标日期不是已核验的交易日"
                elif coverage["missing_fields"]:
                    reason = f"仍缺{coverage['missing_fields']}个行情字段"
                else:
                    try:
                        self.store.panel(start, target)
                    except ValueError as exc:
                        reason = str(exc)
            actual = target
            if reason:
                context = f"报告更新未成功；目标截止{cutoff}，本地最新完整日{latest}。原因：{reason}"
                if as_of:
                    raise ValueError(context + "。指定历史日期不自动改期，请补齐后重试。")
                # If today's calendar could not be fetched, only use a previously
                # verified session, and require every intervening date to be known.
                boundary = target or cutoff
                previous = max((d for d in opened if d < boundary), default=None)
                if not previous or any(previous <= d < boundary for d in unknown):
                    raise ValueError(context + "。无法确认前一交易日，未生成报告；请检查Wind后重试。")
                try:
                    history_start = str((pd.Timestamp(previous) - pd.DateOffset(months=12) - pd.Timedelta(days=15)).date())
                    self.store.panel(history_start, previous)
                except ValueError as exc:
                    raise ValueError(context + f"。前一交易日{previous}的数据也不完整：{exc}；未生成报告。") from exc
                actual = previous
        check = {"state": "fallback" if reason else "complete", "checked_at": timestamp(),
                 "requested_cutoff": cutoff, "target_trade_date": target, "actual_end": actual,
                 "daily_check_time": f"{hour:02d}:{minute:02d}", "sync_state": outcome["state"],
                 "reason": reason, "sync_message": outcome["message"]}
        check["message"] = (f"更新未成功，已回退至前一交易日{actual}；目标截止{cutoff}。原因：{reason}" if reason
                            else f"行情已校验，截至{actual}（日历检查截至{cutoff}）")
        progress(check["message"])
        return actual, check

    def export(self, kind="report", selected=None, as_of=None, progress=lambda text: None, windows=None):
        from .report import plot_all, build_docx
        if kind not in {"report", "figures", "data"}:
            raise ValueError("未知导出类型")
        windows = normalize_windows(windows if windows is not None else self.output_windows(kind))
        check = None
        if kind == "report" and self.mode == "wind":
            as_of, check = self.prepare_report(as_of, progress)
        a = self.analyze(as_of, windows)
        if check and self.cancel.is_set():
            raise Cancelled("报告已取消，未生成新报告；已下载行情保留")
        if kind == "report" and a.panel.trade_date.min() > a.start:
            raise ValueError(f"本地行情不足所选{windows['series_months']}个完整日历月，请先补齐后导出")
        name = timestamp().replace(":", "").replace("+", "_") + "_" + uuid.uuid4().hex[:6]
        output = self.exports_root / str(a.end.date()) / name
        output.mkdir(parents=True)
        provenance = {**a.provenance, "kind": kind, "generated_at": timestamp(), "selected_charts": selected}
        if check:
            provenance.update(market_update_check=check, requested_end=check["requested_cutoff"])
        if self.mode != "demo":
            shutil.copyfile(a.provenance["dividends"]["archived_input"], output / "dividend_input_snapshot.xlsx")
        if kind in {"report", "data"}:
            frames = {"adjusted_panel": a.panel, "fixed_60d": a.fixed, "calendar_spreads": a.spread,
                "total_open_interest": a.totals, "historical_statistics": a.history,
                "annualized_quantiles": a.annual_quantiles, "im_ic_basis": a.cross, "im_ic_quantiles": a.cross_quantiles,
                "fixed_60d_quantiles": a.fixed_quantiles, "fixed_90d": a.fixed90, "fixed_90d_quantiles": a.fixed90_quantiles,
                "calendar_annualized": a.calendar_annualized, "calendar_annualized_quantiles": a.calendar_quantiles,
                "calendar_absolute_quantiles": a.calendar_point_quantiles}
            for label, frame in frames.items():
                frame.to_csv(output / f"{label}.csv", index=False, encoding="utf-8-sig")
        if kind in {"report", "figures"}:
            progress("正在绘制图片…")
            charts = plot_all(a.panel, a.fixed, a.spread, a.start, a.end, output / "figures", ROOTS,
                a.annual_quantiles, a.cross, a.cross_quantiles, selected=selected if kind == "figures" else None,
                watermark="合成演示" if self.mode == "demo" else "",
                terms=(a.fixed90, a.fixed90_quantiles, a.calendar_annualized, a.calendar_quantiles),
                windows=windows, fixed_quantiles=a.fixed_quantiles, calendar_point_quantiles=a.calendar_point_quantiles)
            if self.mode == "demo":
                provenance["demo_notice"] = "合成演示，非真实行情和分红"
            if kind == "report":
                if check and self.cancel.is_set():
                    raise Cancelled("报告已取消，未生成Word；已下载行情和图片保留")
                progress("正在生成 Word…")
                target = output / ("股指基差分析_合成演示.docx" if self.mode == "demo" else "股指基差分析.docx")
                template = ROOT / "assets/report_template.docx"
                counts = build_docx(template, target, a.panel, a.fixed, a.spread, a.totals, a.history, charts,
                    a.start, a.end, ROOTS, provenance, preview=self.mode == "demo", annual_quantiles=a.annual_quantiles,
                    cross=a.cross, cross_quantiles=a.cross_quantiles,
                    terms=(a.fixed90, a.fixed90_quantiles, a.calendar_annualized, a.calendar_quantiles),
                    windows=windows, fixed_quantiles=a.fixed_quantiles, calendar_point_quantiles=a.calendar_point_quantiles)
                provenance.update(counts)
        provenance["files"] = [{"file": str(p.relative_to(output)), "sha256": sha256(p), "bytes": p.stat().st_size}
            for p in sorted(output.rglob("*")) if p.is_file() and ".mplconfig" not in p.parts]
        atomic_json(output / "run_manifest.json", provenance)
        return str(output)
