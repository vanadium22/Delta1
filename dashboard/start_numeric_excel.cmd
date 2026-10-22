@echo off
setlocal
pushd "%~dp0.."
if errorlevel 1 exit /b 1
set "DASHBOARD_PYTHON=%SWHY_DELTA1_PYTHON%"
rem Prefer the verified company environment when no explicit override was supplied.
if not defined DASHBOARD_PYTHON if exist "D:\conda\envs\swhy_delta1\python.exe" set "DASHBOARD_PYTHON=D:\conda\envs\swhy_delta1\python.exe"
if not defined DASHBOARD_PYTHON if exist ".venvs\numeric_excel\Scripts\python.exe" set "DASHBOARD_PYTHON=%CD%\.venvs\numeric_excel\Scripts\python.exe"
if not defined DASHBOARD_PYTHON if exist ".venv\Scripts\python.exe" set "DASHBOARD_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined DASHBOARD_PYTHON set "DASHBOARD_PYTHON=python"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0excel_numeric\live.ps1" -Python "%DASHBOARD_PYTHON%" %*
set "NUMERIC_EXIT_CODE=%ERRORLEVEL%"
if not "%NUMERIC_EXIT_CODE%"=="0" pause
popd
exit /b %NUMERIC_EXIT_CODE%
