@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnose_data_capabilities.ps1" %*
exit /b %errorlevel%
