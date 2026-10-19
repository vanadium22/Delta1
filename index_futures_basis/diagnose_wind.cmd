@echo off
setlocal
set "DIAG_NO_PAUSE="
if /i "%~1"=="--no-pause" set "DIAG_NO_PAUSE=1"
call "%~dp0resolve_python.cmd"
if errorlevel 1 goto failed
cd /d "%~dp0.."
"%BASIS_PYTHON%" -X utf8 -m index_futures_basis.wind_diagnostics %*
set "DIAG_EXIT=%ERRORLEVEL%"
if not defined DIAG_NO_PAUSE pause
exit /b %DIAG_EXIT%
:failed
if not defined DIAG_NO_PAUSE pause
exit /b 1
