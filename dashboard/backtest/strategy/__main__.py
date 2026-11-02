"""python -m dashboard.backtest.strategy --config strategy.local.json"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from ..__main__ import load_job
from ..io import write_json
from ..models import BacktestError, DataConfig
from .models import CTAConfig, FactorConfig, StrategyDataConfig
from .pipeline import generate_strategy


def main(argv=None):
    parser = argparse.ArgumentParser(description="日历连续档位因子 → 实际合约 CTA 目标表")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        job = load_job(args.config)
        if "factor" in job:
            from ..workflow import factor_stage, cta_stage
            output = args.output or job.get("output_dir")
            factors = factor_stage(job, output_dir=Path(output) / "factor" if output else None)
            signals = cta_stage(factors, job, output_dir=Path(output) / "cta" if output else None)
            print(json.dumps(dict(rows=len(signals.targets), output_paths=signals.output_paths), ensure_ascii=False, indent=2))
            return 0
        factors = FactorConfig(**job.get("factors", {}))
        name = job.get("factor_name", "basis_percentile")
        cta = CTAConfig(**job["cta"]) if "cta" in job else None
        result = generate_strategy(data_config=DataConfig(**job.get("data", {})),
                                   source_config=StrategyDataConfig(**job.get("strategy_data", {})),
                                   factor_config=factors, cta_config=cta, factor_name=name,
                                   start=job.get("start"), end=job.get("end"), output_dir=args.output or job.get("output_dir"))
        if result.output_paths:
            write_json(Path(result.output_paths["output_dir"]) / "strategy.local.json", {
                **job, "factors": asdict(factors), "cta": result.metadata["cta_config"]})
        print(json.dumps(dict(rows=len(result.targets), contracts=len(result.targets.columns), output_paths=result.output_paths), ensure_ascii=False, indent=2))
        return 0
    except (BacktestError, OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"Strategy generation failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
