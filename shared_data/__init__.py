"""Versioned local data access shared by Delta1 applications (no network on import)."""
from .paths import DataPaths
from .catalog import Catalog, Dataset

__all__ = ["DataPaths", "Catalog", "Dataset"]
API_VERSION = 1
