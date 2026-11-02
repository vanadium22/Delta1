"""Launch the desktop from any directory using an absolute script path."""
from pathlib import Path
import sys


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from dashboard.backtest.desktop import main
    raise SystemExit(main())
