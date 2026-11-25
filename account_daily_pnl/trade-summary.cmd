@echo off
setlocal DisableDelayedExpansion
if "%~1"=="" (
    call "%~dp0start.cmd" --trade-summary --setup
) else (
    call "%~dp0start.cmd" --trade-summary %*
)
exit /b %errorlevel%
