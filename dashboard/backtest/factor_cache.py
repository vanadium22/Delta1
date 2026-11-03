"""Validate reuse from declarations only; never read prices or recompute a factor."""
from dataclasses import asdict
import json

from .configuration import factor_data_declaration
from .models import BacktestError


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"))


def validate_factor_artifact(factors,spec,data):
    recorded=factors.metadata.get("factor_declarations",{}).get(spec.name,factors.metadata.get("factor"))
    expected=asdict(spec)
    if recorded is not None:
        recorded=dict(recorded)
        recorded.pop("workers",None)
    expected.pop("workers",None)
    if recorded is None or _canonical(recorded)!=_canonical(expected) or spec.name not in factors.continuous_factors:
        raise BacktestError("Saved factor declaration differs; 因子参数或计算范围已变化，请先重新计算因子")
    declared=factors.metadata.get("factor_data_config")
    if declared is not None:
        if _canonical(declared)!=_canonical(factor_data_declaration(data)):
            raise BacktestError("Saved factor input configuration differs; 数据配置已变化，请先重新计算因子")
        return
    # Old portable artifacts already contain path/version declarations.
    market=factors.metadata.get("market",{})
    for field in ("dataset_id","data_version","source_id","dividend_mode"):
        old=market.get(field,factors.metadata.get(field))
        if old is not None and old!=getattr(data,field):
            raise BacktestError(f"Saved factor data assumption differs: {field}")
    from .data import resolve_paths
    paths=resolve_paths(data)
    if market.get("paths",{}).get("history_roots",[])!=paths["history_roots"]:
        raise BacktestError("Saved factor registered roots differ")
    files=market.get("files",{})
    chosen=(data.daily_close_path or data.close_path or data.minute_close_path) if spec.precision=="1d" else (data.minute_close_path or data.close_path or data.daily_close_path)
    if chosen and not any(record.get("path")==chosen for record in files.values()):
        raise BacktestError("Saved factor price path differs")
    for field in ("reference_path","days_to_expiry_path","calendar_path","source_manifest_path","dividend_points_path","adjusted_close_path","dividend_records_path"):
        value=paths["reference_path"] if field=="reference_path" else getattr(data,field)
        if value and files.get(field,{}).get("path")!=value:
            raise BacktestError(f"Saved factor input path differs: {field}")
    if data.dividend_store_root:
        raise BacktestError("This legacy artifact has no complete dividend-store declaration; recompute once")
