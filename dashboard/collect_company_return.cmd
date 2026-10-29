@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect_company_return.ps1" %*
exit /b %errorlevel%
