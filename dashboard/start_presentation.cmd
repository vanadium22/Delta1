@echo off
setlocal
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0start_app.ps1" -Edition presentation %*
exit /b %errorlevel%
