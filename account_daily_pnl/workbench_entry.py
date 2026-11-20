"""Work Automation Python entry point for the account and strategy PnL run."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from account_daily_pnl.__main__ import main


if __name__ == "__main__":
    sys.exit(main())
