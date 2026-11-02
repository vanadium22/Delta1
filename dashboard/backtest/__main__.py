"""CLI: python -m dashboard.backtest audit|run (from the repository root)."""
from __future__ import annotations

import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys

from . import BacktestConfig, BacktestError, DataConfig, audit_data, run_backtest
from .io import json_default, write_json


def load_job(path):
    if path is None:
        return {}
    path = Path(path).resolve()
    job = json.loads(path.read_text(encoding="utf-8-sig"))
    data = job.setdefault("data", {})
    def resolve(value):
        return str((path.parent / Path(value).expanduser()).resolve()) if value else value
    for key in (f.name for f in fields(DataConfig)):
        if key.endswith("_path") or key in {"data_root", "dividend_root"}:
            if key in data:
                data[key] = resolve(data[key])
    if data.get("history_roots"):
        data["history_roots"] = [resolve(p) for p in data["history_roots"]]
    for key in ("instructions_path", "output_dir"):
        if key in job:
            job[key] = resolve(job[key])
    return job


def main(argv=None):
    parser = argparse.ArgumentParser(description="Index futures / synthetic spot next-bar big-table backtester")
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("audit", "run"):
        sub = subs.add_parser(command)
        sub.add_argument("--config", type=Path)
        sub.add_argument("--data-root", type=Path)
        sub.add_argument("--frequency", choices=("1d", "1m", "1s"))
        sub.add_argument("--close-path", type=Path)
        sub.add_argument("--margin-rate-path", type=Path)
        sub.add_argument("--margin-rate", action="append", metavar="ROOT=RATE", default=[])
        sub.add_argument("--allow-unverified-history", action="store_true", default=None)
        sub.add_argument("--output", type=Path)
        if command == "run":
            sub.add_argument("--instructions", type=Path)
            sub.add_argument("--mode", choices=("symbol", "product", "portfolio"))
            sub.add_argument("--start")
            sub.add_argument("--end")
            sub.add_argument("--initial-capital", type=float)
            sub.add_argument("--commission-rate", type=float)
            sub.add_argument("--max-capital-usage", type=float)
            sub.add_argument("--minimum-margin-ratio", type=float)
            sub.add_argument("--margin-call-basis", choices=("available_equity", "equity"))
            sub.add_argument("--liquidate-at-end", action="store_true", default=None)
    args = parser.parse_args(argv)
    try:
        job = load_job(args.config)
        data = dict(job.get("data", {}))
        for key in ("data_root", "frequency", "close_path", "margin_rate_path"):
            if getattr(args, key) is not None:
                data[key] = getattr(args, key)
        if args.data_root or args.close_path:
            # An explicit CLI source overrides configured source selection completely.
            data.pop("history_roots", None)
            data.pop("dashboard_config_path", None)
            if args.data_root:
                data.pop("close_path", None)
        if args.allow_unverified_history is not None:
            data["allow_unverified_availability"] = args.allow_unverified_history
        if args.margin_rate:
            data["margin_rates"] = dict(data.get("margin_rates", {}))
            for item in args.margin_rate:
                key, value = item.split("=", 1)
                data["margin_rates"][key.strip().upper()] = float(value)
        data_config = DataConfig(**data)
        if args.command == "audit":
            report = audit_data(data_config)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                write_json(args.output, report)
                print(json.dumps(dict(report_path=str(args.output.resolve()),
                                      symbols=len(report["coverage"]), missing=report["missing"]),
                                 ensure_ascii=False, indent=2))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2, default=json_default))
            return 0
        backtest = dict(job.get("backtest", {}))
        for entry in fields(BacktestConfig):
            value = getattr(args, entry.name, None)
            if value is not None:
                backtest[entry.name] = value
        result = run_backtest(instructions_path=args.instructions or job.get("instructions_path"),
                              data_config=data_config, config=BacktestConfig(**backtest),
                              output_dir=args.output or job.get("output_dir"))
        print(result.summary.to_string())
        print(json.dumps(result.output_paths, ensure_ascii=False, indent=2))
        return 0
    except (BacktestError, OSError, TypeError, ValueError) as exc:
        print(f"Backtest failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
