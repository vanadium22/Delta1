@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnose_presentation.ps1" %*
exit /b %errorlevel%
