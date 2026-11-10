@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0company_retest.ps1" %*
exit /b %errorlevel%
