"""Compatibility imports for the optional browser interface."""
from ..instant_dld.service import (
    ACTIVE_STATES,
    PROJECT_ROOT,
    ConflictError,
    DownloadService,
    write_json,
)

__all__ = ["ACTIVE_STATES", "PROJECT_ROOT", "ConflictError", "DownloadService", "write_json"]
