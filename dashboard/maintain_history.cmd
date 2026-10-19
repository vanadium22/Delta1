@echo off
setlocal
set "HISTORY_PYTHON=%SWHY_HISTORY_PYTHON%"
if not defined HISTORY_PYTHON if exist "%~dp0..\.venv\Scripts\python.exe" set "HISTORY_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not defined HISTORY_PYTHON if exist "%~dp0..\..\..\project\dolphindb_data\.venv\Scripts\python.exe" set "HISTORY_PYTHON=%~dp0..\..\..\project\dolphindb_data\.venv\Scripts\python.exe"
if not defined HISTORY_PYTHON if defined SWHY_DELTA1_PYTHON set "HISTORY_PYTHON=%SWHY_DELTA1_PYTHON%"
if not defined HISTORY_PYTHON set "HISTORY_PYTHON=python"
pushd "%~dp0.."
"%HISTORY_PYTHON%" -B -s -X utf8 -m dashboard.marketdata.history_maintenance --once --local-root "%~dp0localsetting" %*
set "HISTORY_EXIT=%ERRORLEVEL%"
popd
exit /b %HISTORY_EXIT%
