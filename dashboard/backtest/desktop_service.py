"""UI-independent desktop operations; all inputs and results remain local."""
from dataclasses import asdict
from pathlib import Path

from . import BacktestConfig, BacktestError, DataConfig, audit_data, read_frame, run_backtest
from .io import write_json
from .models import check_cancelled, normalize_frame, time_bound


def inspect_job(job, *, cancel_event=None, progress=None):
    check_cancelled(cancel_event)
    config, data = BacktestConfig(**job.get("backtest", {})), DataConfig(**job.get("data", {}))
    path = job.get("instructions_path")
    if not path:
        raise BacktestError("请先设置目标指令表路径")
    if progress:
        progress(dict(stage="inspecting", message="正在检查指令表与本地数据覆盖"))
    targets = normalize_frame(read_frame(path, trusted_pickle=data.trusted_pickle), label="instructions",
                              timezone=config.timezone, date_at=config.date_at, unit=config.timestamp_unit)
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
    report["instructions"] = dict(path=str(Path(path).resolve()), rows=len(targets), symbols=list(targets.columns),
                                   start=str(targets.index.min()), end=str(targets.index.max()))
    required = {s for s in targets if (targets[s].abs() > 0).any()}
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
