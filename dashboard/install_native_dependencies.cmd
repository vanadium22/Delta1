@echo off
setlocal
cd /d "%~dp0.."
set "DELTA1_NATIVE_PYTHON=P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe"
if defined SWHY_DELTA1_PYTHON set "DELTA1_NATIVE_PYTHON=%SWHY_DELTA1_PYTHON%"
"%DELTA1_NATIVE_PYTHON%" -B -s -m pip install --target .deps\dashboard_native --no-deps --no-cache-dir --disable-pip-version-check --no-warn-script-location -r dashboard\native\requirements.txt
if errorlevel 1 pause
