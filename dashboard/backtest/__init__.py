"""Local index futures / synthetic spot backtesting, independent of dashboard UI."""
from .api import run_backtest
from .data import audit_data, load_market_data, read_frame
from .io import load_result
from .models import (AccountResult, BacktestConfig, BacktestCancelled, BacktestError, BacktestResult,
                     DataConfig, HedgeRule, MarketData, SPOT_SYMBOLS)
from .hedging import index_hedges

__all__ = ["run_backtest", "load_market_data", "audit_data", "read_frame", "MarketData",
           "BacktestConfig", "DataConfig", "BacktestResult", "AccountResult", "BacktestError", "BacktestCancelled",
           "load_result", "SPOT_SYMBOLS", "HedgeRule", "index_hedges"]
