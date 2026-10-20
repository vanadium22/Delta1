@echo off
setlocal
pushd "%~dp0.."
set "NUMERIC_CONFIG_PYTHON=%SWHY_DELTA1_PYTHON%"
if not defined NUMERIC_CONFIG_PYTHON if exist ".venvs\numeric_excel\Scripts\python.exe" set "NUMERIC_CONFIG_PYTHON=%CD%\.venvs\numeric_excel\Scripts\python.exe"
if not defined NUMERIC_CONFIG_PYTHON if exist ".venv\Scripts\python.exe" set "NUMERIC_CONFIG_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined NUMERIC_CONFIG_PYTHON set "NUMERIC_CONFIG_PYTHON=python"
"%NUMERIC_CONFIG_PYTHON%" -B -X utf8 -m dashboard.numeric_startup configure %*
pause
popd
