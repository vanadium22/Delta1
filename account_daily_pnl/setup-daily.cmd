@echo off
setlocal DisableDelayedExpansion
call "%~dp0start.cmd" --setup-daily %*
exit /b %errorlevel%
