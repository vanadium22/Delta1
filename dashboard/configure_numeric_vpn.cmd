@echo off
setlocal
pushd "%~dp0.."
set "NUMERIC_VPN_PYTHON=%SWHY_DELTA1_PYTHON%"
if not defined NUMERIC_VPN_PYTHON if exist ".venvs\numeric_excel\Scripts\python.exe" set "NUMERIC_VPN_PYTHON=%CD%\.venvs\numeric_excel\Scripts\python.exe"
if not defined NUMERIC_VPN_PYTHON if exist ".venv\Scripts\python.exe" set "NUMERIC_VPN_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined NUMERIC_VPN_PYTHON set "NUMERIC_VPN_PYTHON=python"
"%NUMERIC_VPN_PYTHON%" -B -X utf8 -m dashboard.numeric_vpn_config %*
pause
popd
