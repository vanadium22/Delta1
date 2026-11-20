@echo off
setlocal DisableDelayedExpansion
call "%~dp0account_daily_pnl\start.cmd" --company-run %*
exit /b %errorlevel%
