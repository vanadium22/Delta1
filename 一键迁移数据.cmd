@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0shared_data\migrate_windows.ps1" %*
exit /b %errorlevel%
