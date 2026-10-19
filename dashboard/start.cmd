@echo off
setlocal
pushd "%~dp0.."
set "DASHBOARD_PYTHON=%SWHY_DELTA1_PYTHON%"
if not defined DASHBOARD_PYTHON if exist "%~dp0..\.venv\Scripts\python.exe" set "DASHBOARD_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not defined DASHBOARD_PYTHON if exist "P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe" set "DASHBOARD_PYTHON=P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe"
if not defined DASHBOARD_PYTHON set "DASHBOARD_PYTHON=python"
"%DASHBOARD_PYTHON%" -B -s -X utf8 -m dashboard.current %*
set "DASHBOARD_EXIT=%ERRORLEVEL%"
popd
if not "%DASHBOARD_EXIT%"=="0" pause
exit /b %DASHBOARD_EXIT%
