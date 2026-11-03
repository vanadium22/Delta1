"""Four explicit configuration sections and per-function parameter declarations."""
from dataclasses import asdict, dataclass, field
import math
from pathlib import Path

from .models import BacktestError
from .strategy.models import CTAConfig, FactorConfig


EXECUTION_DATA_FIELDS={"margin_rate_path","margin_rates","multiplier_path","multipliers"}


def factor_data_declaration(data):
    """Execution-only size/margin assumptions do not invalidate numerical factors."""
    return {k:v for k,v in asdict(data).items() if k not in EXECUTION_DATA_FIELDS}


@dataclass(frozen=True)
class Parameter:
    default: object
    unit: str
    kind: str = "number"
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = ()

    def validate(self, name, value):
        if self.choices:
            if value not in self.choices or isinstance(value, bool):
                raise BacktestError(f"{name} must be one of {self.choices}")
        elif self.kind == "slots":
            if not isinstance(value, (list, tuple)) or not value or any(type(v) is not int or v not in range(4) for v in value) or len(set(value)) != len(value):
                raise BacktestError(f"{name} must contain unique slot integers 0..3")
        elif self.kind == "quantiles":
            from .strategy.term_structure import TermStructureConfig
            TermStructureConfig(quantiles=value)
        else:
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise BacktestError(f"{name} must be a finite {self.kind}")
            if self.kind == "integer" and type(value) is not int:
                raise BacktestError(f"{name} must be an integer")
            if (self.minimum is not None and value < self.minimum) or (self.maximum is not None and value > self.maximum):
                raise BacktestError(f"{name} outside [{self.minimum}, {self.maximum}]")


WINDOW = dict(window_days=Parameter(60, "previous trading days", "integer", 2),
              min_samples=Parameter(2, "valid prior observations", "integer", 1))
ANNUAL = dict(min_annual_days=Parameter(5, "remaining calendar days", "integer", 1))
CALENDAR = dict(min_gap_days=Parameter(1, "far-minus-near calendar days", "integer", 1),
                price_base=Parameter("near", "normalizing price", choices=("near", "spot")))
COMMON_CTA = dict(position_weight=Parameter(.2, "signed equity budget per leg", minimum=0.000001, maximum=1),
                  direction=Parameter(1, "sign", choices=(-1, 1)),
                  transform=Parameter("identity", "factor transform", choices=("identity", "center_percentile")),
                  missing=Parameter("flat", "missing score policy", choices=("flat", "hold", "error")),
                  hedge=Parameter("none", "target leg construction", choices=("none", "index")))
FACTOR_SCHEMAS = {
    "annual_basis": dict(inputs=("close", "spot", "dividend_points", "days_to_expiry"), unit="percentage points", parameters=ANNUAL),
    "basis_percentile": dict(inputs=("close", "spot", "dividend_points", "days_to_expiry"), unit="p in [0,1]", parameters={**WINDOW, **ANNUAL}),
    "price_basis_percentile": dict(inputs=("close", "spot"), unit="p in [0,1] of F-S (index points)", parameters=WINDOW),
    "close_percentile": dict(inputs=("close",), unit="p in [0,1] of continuous raw close (index points)", parameters=WINDOW),
    "calendar_spread_percentile": dict(inputs=("close slots 01 and 03",), unit="p in [0,1] of F01-F03 (index points)", parameters=WINDOW),
    "annual_calendar_spread": dict(inputs=("close, dividends and expiry days for 01/03",), unit="annual percentage points", parameters=CALENDAR),
    "annual_calendar_spread_percentile": dict(inputs=("annualized 01-minus-03 carry",), unit="p in [0,1]", parameters={**WINDOW, **CALENDAR}),
    "term_structure_percentile": dict(inputs=("annual basis across dated maturities", "prior dates only", "remaining natural days"),
        unit="conditional p in [0,1]", parameters={**ANNUAL, "window_days":WINDOW["window_days"],
        "min_training_samples":Parameter(120, "pooled previous date x contract observations", "integer", 3),
        "degree":Parameter(1, "polynomial degree in T/365", "integer", choices=(1, 2)),
        "quantiles":Parameter((.05,.10,.25,.50,.75,.90,.95), "conditional quantile grid", "quantiles")}),
}
EXPIRY = dict(threshold=Parameter(.9, "absolute centered score; strict >", minimum=0, maximum=1),
              position_weight=Parameter(.495, "budget per equal-weight leg", minimum=0.000001, maximum=.5),
              direction=Parameter(-1, "reversal sign", choices=(-1, 1)),
              transform=Parameter("center_percentile", "explicit 2*p-1", choices=("center_percentile",)))
FUTURE_SIDE = Parameter("both", "permitted futures target side before selection", choices=("both", "long"))
CTA_SCHEMAS = {
    "fixed": dict(inputs=("factor table", "dated actual mapping"), parameters={**COMMON_CTA,
                  "open_threshold": Parameter(.7, "absolute score", minimum=0), "close_threshold": Parameter(.2, "absolute score", minimum=0)}),
    "zscore": dict(inputs=("factor table", "dated actual mapping"), parameters={**COMMON_CTA,
                   "lookback_window": Parameter(20, "previous trading days", "integer", 2),
                   "z_open": Parameter(2., "population standard deviations", minimum=0),
                   "z_close": Parameter(.4, "population standard deviations", minimum=0)}),
    "expiry_index": dict(inputs=("raw percentile", "dated actual mapping", "expiry reference"), parameters={**EXPIRY,
                         "allowed_future_side": FUTURE_SIDE,
                         "selection": Parameter("product_best", "selection scope", choices=("product_best", "contract_independent")),
                         "slots": Parameter((0, 1, 2, 3), "candidate slots", "slots")}),
    "expiry_spread": dict(inputs=("01-minus-03 raw percentile", "dated mapping", "expiry reference"), parameters=EXPIRY),
    "expiry_index_structure": dict(inputs=("per-contract raw percentile", "dated actual mapping", "expiry reference"),
        parameters={**EXPIRY, "position_weight":Parameter(.12375, "per leg; 4 dedicated pair budgets per product", minimum=.000001, maximum=.125),
                    "allowed_future_side":FUTURE_SIDE,
                    "slots":Parameter((0,1,2,3), "candidate maturity slots", "slots")}),
}


def parameters(schemas, name, supplied):
    if name not in schemas:
        raise BacktestError(f"Unknown function {name!r}; choose {list(schemas)}")
    schema = schemas[name]["parameters"]
    if set(supplied) - set(schema):
        raise BacktestError(f"{name}: unexpected parameters {sorted(set(supplied) - set(schema))}")
    result = {key: supplied.get(key, item.default) for key, item in schema.items()}
    for key, item in schema.items():
        item.validate(name + "." + key, result[key])
    return result


@dataclass(frozen=True)
class FactorSpec:
    name: str = "basis_percentile"
    parameters: dict = field(default_factory=dict)
    roots: tuple = ("IC",)
    slots: tuple = (0, 1, 2, 3)
    precision: str = "1d"
    workers: int = 0

    def __post_init__(self):
        object.__setattr__(self, "parameters", parameters(FACTOR_SCHEMAS, self.name, self.parameters))
        if self.name == "term_structure_percentile":
            from .strategy.term_structure import TermStructureConfig
            TermStructureConfig(**{k: self.parameters[k] for k in ("window_days","min_training_samples","degree","quantiles")})
            if self.precision != "1d" or self.parameters["min_training_samples"] > self.parameters["window_days"] * len(self.slots):
                raise BacktestError("Term-structure regression needs daily data and enough configured maturity observations")
        if self.name.startswith("annual_calendar") and not {1,3} <= set(self.slots):
            raise BacktestError("Annual calendar factors require slots 01 and 03")
        self.runtime()

    def runtime(self):
        return FactorConfig(roots=tuple(self.roots), slots=tuple(self.slots), precision=self.precision,
                            workers=self.workers, **{k:v for k,v in self.parameters.items() if k in FactorConfig.__dataclass_fields__})


@dataclass(frozen=True)
class CTASpec:
    name: str = "fixed"
    input_factor: str = "basis_percentile"
    parameters: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "parameters", parameters(CTA_SCHEMAS, self.name, self.parameters))
        if self.name in {"fixed", "zscore"}:
            CTAConfig(mode=self.name, **{k: v for k, v in self.parameters.items() if k != "hedge"})
        elif not 0 < self.parameters["threshold"] < 1:
            raise BacktestError("Expiry threshold must be strictly in (0,1)")


def factor_spec(job):
    if "factor" in job:
        if "factors" in job or "factor_name" in job:
            raise BacktestError("Choose factor or legacy factors/factor_name, not both")
        return FactorSpec(**job["factor"])
    old = dict(job.get("factors", {}))
    if set(old) - set(FactorConfig.__dataclass_fields__):
        raise BacktestError("Unknown legacy factor parameters")
    context = {k: old.pop(k) for k in ("roots", "slots", "precision", "workers") if k in old}
    name = job.get("factor_name", "basis_percentile")
    allowed = FACTOR_SCHEMAS[name]["parameters"]
    return FactorSpec(name=name, parameters={k: v for k, v in old.items() if k in allowed}, **context)


def cta_spec(job):
    raw = dict(job.get("cta", {}))
    if "name" in raw:
        return CTASpec(**raw)
    if "factor" in job:
        if raw:
            raise BacktestError("Canonical cta requires name, input_factor and its own parameters")
        return CTASpec(input_factor=factor_spec(job).name)
    name = raw.pop("mode", "fixed")
    if set(raw) - set(CTAConfig.__dataclass_fields__):
        raise BacktestError("Unknown legacy CTA parameters")
    factor_name = factor_spec(job).name
    raw.setdefault("transform", "center_percentile" if factor_name.endswith("percentile") else "identity")
    return CTASpec(name=name, input_factor=factor_name,
                   parameters={k: v for k, v in raw.items() if k in CTA_SCHEMAS[name]["parameters"]})


def describe_functions():
    return {kind: {name: {**{k: v for k, v in schema.items() if k != "parameters"},
                          "parameters": {key: asdict(p) for key, p in schema["parameters"].items()}}
                   for name, schema in schemas.items()} for kind, schemas in (("factor", FACTOR_SCHEMAS), ("cta", CTA_SCHEMAS))}


def relative_data_path(value, root):
    if not value or not root:
        return value
    path, base = Path(value).resolve(), Path(root).resolve()
    return path.relative_to(base).as_posix() if path.is_relative_to(base) else str(path)


def data_declaration(data):
    """Save paths under a data root relatively, so replacing only the root works."""
    result = asdict(data)
    for key, value in list(result.items()):
        if key.endswith("_path") or key in {"dividend_root", "dividend_store_root"}:
            result[key] = relative_data_path(value, data.data_root)
    result["history_roots"] = [relative_data_path(v, data.data_root) for v in data.history_roots]
    result["history_versions"] = {relative_data_path(k, data.data_root): v for k, v in data.history_versions.items()}
    return result
