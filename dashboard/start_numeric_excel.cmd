@echo off
setlocal
pushd "%~dp0.."
set "DASHBOARD_PYTHON=%SWHY_DELTA1_PYTHON%"
if not defined DASHBOARD_PYTHON if exist ".venv\Scripts\python.exe" set "DASHBOARD_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined DASHBOARD_PYTHON if exist "P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe" set "DASHBOARD_PYTHON=P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe"
if not defined DASHBOARD_PYTHON set "DASHBOARD_PYTHON=python"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "dashboard\excel_numeric\live.ps1" -Python "%DASHBOARD_PYTHON%" %*
if errorlevel 1 pause
popd
