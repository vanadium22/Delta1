"""Independent data → factor → CTA → execution commands and Python functions."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from .configuration import FACTOR_SCHEMAS, cta_spec, describe_functions, factor_data_declaration, factor_spec
from .io import frame_fingerprint, json_default
from .models import BacktestConfig, BacktestError, DataConfig, check_cancelled, check_market_source, time_bound
from .strategy import CTAConfig, CTAResult, compute_factors, generate_cta, hold_to_expiry_targets, load_cta, load_factors


def factor_stage(job, *, market_data=None, output_dir=None, cancel_event=None, progress=None):
    spec = factor_spec(job)
    result = compute_factors(data_config=DataConfig(**job.get("data", {})), market_data=market_data,
                              factor_config=spec.runtime(), factor_name=spec.name, requested_only=True,
                              factor_parameters={spec.name:spec.parameters},
                              cancel_event=cancel_event, progress=progress)
    # This declaration contains only factor parameters and calculation context.
    result.metadata["factor"] = asdict(spec)
    result.metadata["factor_data_config"] = factor_data_declaration(DataConfig(**job.get("data", {})))
    result.metadata["factor_units"][spec.name] = FACTOR_SCHEMAS[spec.name]["unit"]
    if output_dir is not None:
        check_cancelled(cancel_event)
        if progress:
            progress(dict(stage="saving", message="正在完整保存独立因子结果"))
        result.save(output_dir)
    return result


def _index_weights(targets):
    result = targets.copy()
    for root in sorted({s[:2] for s in targets}):
        result[root + "_spot"] = -targets[[s for s in targets if s.startswith(root)]].sum(axis=1)
    return result


def _spread_expiry(factors, spec, start, end, cancel_event):
    p = factors.continuous_factors[spec.input_factor]
    if spec.input_factor not in {"calendar_spread_percentile", "annual_calendar_spread_percentile"}:
        raise BacktestError("expiry_spread requires a calendar-spread percentile factor")
    index = p.index
    left, right = time_bound(start), time_bound(end, end=True)
    selected = np.ones(len(index), dtype=bool)
    if left is not None:
        selected &= index >= left
    if right is not None:
        selected &= index <= right
    index = index[selected]
    if index.empty or index.normalize().duplicated().any():
        raise BacktestError("Expiry spread needs nonempty daily factor rows")
    roots = sorted({s[:2] for s in p})
    symbols = sorted(factors.contracts)
    desired, held, records, emitted = dict.fromkeys(symbols, 0.), {}, [], {}
    for i, stamp in enumerate(index):
        check_cancelled(cancel_event)
        changed = False
        day = str(stamp.date())
        for root, state in list(held.items()):
            if day >= state["expiry"]:
                for symbol in state["legs"]:
                    desired[symbol] = 0.
                records.append(dict(timestamp=stamp, root=root, action="expiry_release", primary=state["legs"][0], hedge=state["legs"][1]))
                del held[root]
                changed = True
        for root in roots:
            if root in held:
                continue
            aliases = root + "01.CFE", root + "03.CFE"
            legs = tuple(factors.panel.mapping.at[stamp, alias] for alias in aliases)
            if any(not isinstance(s, str) or s not in factors.contracts for s in legs):
                continue
            expiry = min(factors.contracts[s]["expiry_date"] for s in legs)
            score = 2 * p.at[stamp, aliases[0]] - 1
            if expiry <= day or not np.isfinite(score) or abs(score) <= spec.parameters["threshold"]:
                continue
            weight = spec.parameters["direction"] * np.sign(score) * spec.parameters["position_weight"]
            desired[legs[0]], desired[legs[1]] = weight, -weight
            held[root] = dict(legs=legs, expiry=expiry)
            changed = True
            records.append(dict(timestamp=stamp, root=root, action="signal_open", primary=legs[0], hedge=legs[1],
                                percentile=float(p.at[stamp, aliases[0]]), score=score))
        if changed or i == 0:
            emitted[stamp] = desired.copy()
    targets = pd.DataFrame.from_dict(emitted, orient="index")
    targets.index = pd.DatetimeIndex(targets.index, name="timestamp")
    return targets, pd.DataFrame(records)


def cta_stage(factors, job, *, output_dir=None, cancel_event=None):
    """Does not accept a market reader; disk input is a self-contained factor artifact."""
    if isinstance(factors, (str, Path)):
        factors = load_factors(factors, cancel_event=cancel_event)
    check_market_source(factors.metadata)
    spec = cta_spec(job)
    if spec.input_factor not in factors.continuous_factors:
        raise BacktestError(f"Missing declared CTA input factor {spec.input_factor}")
    backtest = job.get("backtest", {})
    start, end = backtest.get("start", job.get("start")), backtest.get("end", job.get("end"))
    if spec.name in {"fixed", "zscore"}:
        config = CTAConfig(mode=spec.name, **{k: v for k, v in spec.parameters.items() if k != "hedge"})
        result = generate_cta(factors, factor_name=spec.input_factor, cta_config=config, start=start, end=end, cancel_event=cancel_event)
        if spec.parameters["hedge"] == "index":
            result.targets = _index_weights(result.targets)
            result.metadata["required_backtest_options"] = dict(weight_mode="neutral_units")
    else:
        if spec.parameters["transform"] != "center_percentile":
            raise BacktestError("Expiry CTA requires explicit center_percentile transform")
        values = factors.continuous_factors[spec.input_factor]
        if ((values < 0) | (values > 1)).any().any():
            raise BacktestError("Expiry CTA requires raw p in [0,1]")
        if spec.name in {"expiry_index", "expiry_index_structure"}:
            requested = {f"{root}0{slot}.CFE" for root in {s[:2] for s in factors.panel.mapping} for slot in spec.parameters["slots"]}
            if requested - set(factors.panel.mapping):
                raise BacktestError("CTA candidate slots are absent from the saved factor calculation context")
            mapping = factors.panel.mapping.loc[:, [s for s in factors.panel.mapping if int(s[2:4]) in spec.parameters["slots"]]]
            signals = hold_to_expiry_targets(factors.factors[spec.input_factor], mapping, factors.contracts,
                start=start, end=end, threshold=spec.parameters["threshold"],
                selection=spec.parameters.get("selection", "contract_independent"),
                weight=spec.parameters["position_weight"], direction=spec.parameters["direction"],
                allowed_future_side=spec.parameters["allowed_future_side"],
                roots=tuple(sorted({s[:2] for s in mapping})), cancel_event=cancel_event)
            targets, decisions = _index_weights(signals.targets), signals.decisions
        else:
            targets, decisions = _spread_expiry(factors, spec, start, end, cancel_event)
        result = CTAResult(targets, 2 * factors.factors[spec.input_factor] - 1, {}, decisions)
        result.metadata["required_backtest_options"] = dict(weight_mode="neutral_units", d0=0, rebalance_on_change_only=True)
        if spec.name == "expiry_index_structure":
            result.metadata["required_backtest_options"].update(mode="product", preserve_pair_lots=True)
            result.metadata["pair_allocation"] = "each actual future is a separate pair; dedicated fixed per-leg weights; one capital account per product"
    result.metadata.update(cta=asdict(spec), factor_fingerprint=frame_fingerprint(factors.continuous_factors[spec.input_factor]),
                           target_fingerprint=frame_fingerprint(result.targets), input_factor=spec.input_factor,
                           input_factor_declaration=factors.metadata.get("factor_declarations",{}).get(spec.input_factor,
                               factors.metadata.get("factor", factors.metadata.get("factor_config"))),
                           input_factor_artifact=factors.output_paths.get("output_dir"),
                           data_context={k: factors.metadata.get("market", {}).get(k) for k in ("datasets", "files", "dataset_id", "data_version")})
    if output_dir is not None:
        check_cancelled(cancel_event)
        result.save(output_dir)
    return result


def backtest_stage(signals, job, *, output_dir=None, cancel_event=None, progress=None):
    from .api import run_backtest
    from .data import resolve_paths
    if isinstance(signals, (str, Path)):
        signals = load_cta(signals, cancel_event=cancel_event)
    options = dict(job.get("backtest", {}))
    for key, value in signals.metadata.get("required_backtest_options", {}).items():
        if key in options and options[key] != value:
            raise BacktestError(f"This CTA requires backtest.{key}={value!r}")
        options[key] = value
    data = DataConfig(**job.get("data", {}))
    context = signals.metadata.get("data_context", {})
    paths = resolve_paths(data)
    pins = dict(data.history_versions)
    for dataset in context.get("datasets") or []:
        if dataset["root"] in paths["history_roots"]:
            if dataset["root"] in pins and pins[dataset["root"]] != dataset["version"]:
                raise BacktestError("Configured execution version conflicts with the factor's frozen data version")
            pins[dataset["root"]] = dataset["version"]
    if pins:
        data = replace(data, history_roots=tuple(paths["history_roots"]), history_versions=pins,
                       dashboard_config_path=None, reference_path=paths["reference_path"], dividend_root=paths["dividend_root"])
    result = run_backtest(signals.targets, data_config=data, config=BacktestConfig(**options),
                          cancel_event=cancel_event, progress=progress)
    used = {v["path"]: v.get("sha256") for v in result.metadata["market_data"].get("files", {}).values()}
    for entry in (context.get("files") or {}).values():
        if entry.get("sha256") and entry["path"] in used and used[entry["path"]] != entry["sha256"]:
            raise BacktestError(f"Execution input changed since factor computation: {entry['path']}")
    result.metadata["cta_stage"] = signals.metadata
    result.metadata["data_config"] = asdict(data)
    if output_dir is not None:
        check_cancelled(cancel_event)
        if progress:
            progress(dict(stage="saving", message="正在完整保存回测结果"))
        result.save(output_dir)
    return result


def main(argv=None):
    from .__main__ import load_job
    parser = argparse.ArgumentParser(description="Independent Delta1 research stages (local inputs only)")
    parser.add_argument("stage", choices=("factor", "cta", "run", "all", "schema", "tune"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--input", type=Path, help="saved factor directory for cta, saved CTA directory for run")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true", help="tune: validate and display effective parameter variants without calculating")
    args = parser.parse_args(argv)
    try:
        if args.plan and args.stage!="tune":
            raise BacktestError("--plan applies to tune only")
        if args.stage == "schema":
            result = describe_functions()
        else:
            if args.config is None or (args.output is None and not (args.stage=="tune" and args.plan)):
                raise BacktestError("--config and a new --output directory are required")
            job = load_job(args.config)
            if args.stage == "tune":
                from .tuning import expand_tuning, run_tuning
                if args.plan:
                    result=dict(variants=expand_tuning(job,base_dir=args.config.resolve().parent))
                else:
                    tuned=run_tuning(job,args.output,base_dir=args.config.resolve().parent,progress=lambda s:print(s,flush=True,file=sys.stderr))
                    result=dict(output_dir=tuned["output_dir"],manifest=tuned["manifest"])
            elif args.stage == "factor":
                saved = factor_stage(job, output_dir=args.output)
                result = dict(output_paths=saved.output_paths, data=saved.metadata["market"])
            elif args.stage == "cta":
                if args.input is None:
                    raise BacktestError("cta requires --input pointing to a saved factor artifact")
                result = cta_stage(args.input, job, output_dir=args.output).output_paths
            elif args.stage == "run":
                if args.input is None:
                    raise BacktestError("run requires --input pointing to a saved CTA artifact")
                saved = backtest_stage(args.input, job, output_dir=args.output)
                result = dict(output_paths=saved.output_paths, data=saved.metadata["market_data"])
            else:
                args.output.mkdir(parents=True, exist_ok=False)
                factors = factor_stage(job, output_dir=args.output / "factor")
                signals = cta_stage(factors, job, output_dir=args.output / "cta")
                saved = backtest_stage(signals, job, output_dir=args.output / "backtest")
                result = dict(output_paths=saved.output_paths, data=saved.metadata["market_data"])
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))
        return 0
    except (BacktestError, OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"Stage failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
