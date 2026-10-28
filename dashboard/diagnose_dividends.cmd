@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnose_dividends.ps1" %*
exit /b %errorlevel%
