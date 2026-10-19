"""One shared data location, with no implicit database/network connections."""
from pathlib import Path
from shared_data.paths import DataPaths

PATHS = DataPaths.for_module(Path(__file__).resolve().parents[1])
DATA_ROOT = PATHS.root
HISTORY_ROOT = DATA_ROOT / "market" / "index_futures" / "dashboard" / "normalized"
REALTIME_ROOT = DATA_ROOT / "market" / "index_futures" / "dashboard" / "realtime"
DIVIDEND_ROOT = PATHS.dividend_inputs
VALIDATION_ROOT = DATA_ROOT / "cache" / "verification" / "dashboard_20261016"
