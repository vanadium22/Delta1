@echo off
setlocal
call "%~dp0..\company_retest.cmd" %*
exit /b %errorlevel%
