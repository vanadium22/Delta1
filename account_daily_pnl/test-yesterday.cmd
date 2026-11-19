@echo off
setlocal
call "%~dp0start.cmd" --only-day %*
exit /b %errorlevel%
