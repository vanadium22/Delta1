"""UI-independent desktop operations; all inputs and results remain local."""
from dataclasses import asdict, replace
from pathlib import Path

from . import BacktestConfig, BacktestError, DataConfig, audit_data, read_frame, run_backtest
from .io import write_json
from .models import check_cancelled, normalize_frame, time_bound
from .timeline import effective_instructions


def inspect_job(job, *, cancel_event=None, progress=None):
    check_cancelled(cancel_event)
    config, data = BacktestConfig(**job.get("backtest", {})), DataConfig(**job.get("data", {}))
    path = job.get("instructions_path")
    if not path:
        raise BacktestError("请先设置目标指令表路径")
    if progress:
        progress(dict(stage="inspecting", message="正在检查指令表与本地数据覆盖"))
    targets = normalize_frame(read_frame(path, trusted_pickle=data.trusted_pickle), label="instructions",
                              timezone=config.timezone, date_at=config.date_at, unit=config.timestamp_unit, allow_continuous=True)
    from .strategy.mapping import expand_slot_targets
    from .data import _reference, resolve_paths
    targets, _ = expand_slot_targets(targets.fillna(0) if config.nan_policy == "zero" else targets,
                                     _reference(resolve_paths(data)["reference_path"]),
                                     timezone=config.timezone, date_at=config.date_at)
    if config.nan_policy == "error" and targets.isna().any().any():
        raise BacktestError("目标指令表有空值，请补齐零目标或明确选择空值按平仓处理")
    left = time_bound(config.start, timezone=config.timezone)
    right = time_bound(config.end, end=True, timezone=config.timezone)
    if left is not None:
        targets = targets.loc[targets.index >= left]
    if right is not None:
        targets = targets.loc[targets.index <= right]
    if targets.empty:
        raise BacktestError("所选区间没有目标指令")
    check_cancelled(cancel_event)
    report = audit_data(data)
    if not (data.close_path or data.minute_close_path or data.daily_close_path):
        secondary = audit_data(replace(data, frequency="1m" if data.frequency == "1d" else "1d"))
        known = {r["symbol"] for r in report["coverage"]}
        report["coverage"].extend(r for r in secondary["coverage"] if r["symbol"] not in known)
        report["additional_frequency_coverage"] = secondary["coverage"]
    report["instructions"] = dict(path=str(Path(path).resolve()), rows=len(targets), symbols=list(targets.columns),
                                   start=str(targets.index.min()), end=str(targets.index.max()))
    effective, resolved = effective_instructions(targets, config.precision)
    report["precision"] = dict(requested=config.precision, resolved=resolved, effective_instruction_rows=len(effective))
    required = {s for s in effective if (effective[s].abs() > 0).any()}
    required.update(r.hedge for r in config.hedges if r.primary in required)
    present = {r["symbol"] for r in report["coverage"]}
    report["missing_instruction_symbols"] = sorted(required - present)
    missing = []
    if required - present:
        missing.append("缺少行情：" + ", ".join(sorted(required - present)))
    if not data.margin_rate_path:
        rates_missing = sorted(s for s in required if not s.endswith("_spot") and
                               not data.margin_rates.get(s, data.margin_rates.get(s[:2])))
        if rates_missing:
            missing.append("缺少保证金率：" + ", ".join(rates_missing))
    if config.d0 is not None and not data.days_to_expiry_path:
        references = _reference(resolve_paths(data)["reference_path"])
        absent = sorted(s for s in required if not s.endswith("_spot") and not references.get(s, {}).get("expiry_date"))
        if absent:
            missing.append("缺少到期日/剩余自然日：" + ", ".join(absent) + "；可单独从 DDB 补齐参考资料")
    if not data.allow_unverified_availability and any(d.get("availability_policy") == "unknown" for d in report["datasets"]):
        missing.append("当前行情历史发布时间未知，请明确选择是否允许修订历史研究")
    report["required_missing"] = missing
    report["optional_missing"] = [m for m in report["missing"] if "dividend" in m.lower()]
    check_cancelled(cancel_event)
    return dict(report=report, instructions=targets)


def execute_job(job, *, cancel_event=None, progress=None):
    path = job.get("instructions_path")
    if not path:
        raise BacktestError("请先设置目标指令表路径")
    result = run_backtest(instructions_path=path, config=BacktestConfig(**job.get("backtest", {})),
                          data_config=DataConfig(**job.get("data", {})), output_dir=job.get("output_dir"),
                          cancel_event=cancel_event, progress=progress)
    if result.output_paths:
        write_json(Path(result.output_paths["output_dir"]) / "job.local.json", {
            **job, "backtest": result.metadata["config"],
            "data": asdict(DataConfig(**job.get("data", {})))})
    return result
