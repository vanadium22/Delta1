"""Continuous calculation, concrete factor values, and configurable CTA targets."""
from .cta import cta_targets
from .factors import annual_basis, basis_percentile
from .mapping import expand_slot_targets, slot_mapping, to_actual
from .models import CTAConfig, ContinuousPanel, FactorConfig, FactorDefinition, StrategyDataConfig, StrategyResult
from .pipeline import generate_strategy, prepare_panel
from .expiry_carry import CarrySignals, hold_to_expiry_targets

__all__ = ["CTAConfig", "FactorConfig", "StrategyDataConfig", "ContinuousPanel", "StrategyResult", "FactorDefinition",
           "cta_targets", "annual_basis", "basis_percentile", "slot_mapping", "to_actual", "expand_slot_targets",
           "generate_strategy", "prepare_panel", "CarrySignals", "hold_to_expiry_targets"]
