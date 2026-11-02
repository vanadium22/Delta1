"""Path-based launcher, usable from the dashboard folder or any working directory."""
from pathlib import Path
import sys


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from dashboard.backtest.__main__ import main
    raise SystemExit(main())
