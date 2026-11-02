"""Continuous calculation, concrete factor values, and configurable CTA targets."""
from .cta import cta_targets
from .factors import annual_basis, basis_percentile
from .mapping import expand_slot_targets, slot_mapping, to_actual
from .models import CTAConfig, CTAResult, ContinuousPanel, FactorConfig, FactorResult, FactorDefinition, StrategyDataConfig, StrategyResult
from .pipeline import compute_factors, generate_cta, generate_strategy, prepare_panel
from .artifacts import load_factors, load_cta
from .expiry_carry import CarrySignals, hold_to_expiry_targets

__all__ = ["CTAConfig", "FactorConfig", "StrategyDataConfig", "ContinuousPanel", "StrategyResult", "FactorDefinition",
           "cta_targets", "annual_basis", "basis_percentile", "slot_mapping", "to_actual", "expand_slot_targets",
           "generate_strategy", "prepare_panel", "CarrySignals", "hold_to_expiry_targets",
           "FactorResult", "CTAResult", "compute_factors", "generate_cta", "load_factors", "load_cta"]
