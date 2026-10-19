"""Historical data access, independent of the UI and of acquisition writers."""
from .bars import BAR_SCHEMA, BarDataset, normalize_bars

__all__ = ["BAR_SCHEMA", "BarDataset", "normalize_bars"]
