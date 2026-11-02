"""Local index futures / synthetic spot backtesting, independent of dashboard UI."""
from .api import run_backtest
from .data import audit_data, load_market_data, read_frame
from .models import (AccountResult, BacktestConfig, BacktestError, BacktestResult,
                     DataConfig, MarketData, SPOT_SYMBOLS)

__all__ = ["run_backtest", "load_market_data", "audit_data", "read_frame", "MarketData",
           "BacktestConfig", "DataConfig", "BacktestResult", "AccountResult", "BacktestError", "SPOT_SYMBOLS"]
