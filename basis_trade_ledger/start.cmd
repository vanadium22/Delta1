@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0.." || exit /b 1
call "%~dp0..\index_futures_basis\resolve_python.cmd" >nul
if not errorlevel 1 goto launch
if defined BASIS_APP_PYTHON goto failed
if defined SWHY_DELTA1_PYTHON goto failed
if exist "P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe" (
    set "BASIS_PYTHON=P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe"
    goto launch
)
for %%P in (python.exe) do set "BASIS_PYTHON=%%~$PATH:P"
if not defined BASIS_PYTHON goto failed

:launch
if /i "%~1"=="--startup-check" goto foreground
set "LEDGER_PYTHONW=%BASIS_PYTHON:~0,-4%w.exe"
if not exist "%LEDGER_PYTHONW%" goto foreground
start "" "%LEDGER_PYTHONW%" -X utf8 -m basis_trade_ledger %*
popd
exit /b 0

:foreground
"%BASIS_PYTHON%" -X utf8 -m basis_trade_ledger %*
set "LEDGER_RESULT=%errorlevel%"
popd
exit /b %LEDGER_RESULT%

:failed
echo Set SWHY_DELTA1_PYTHON to the swhy_delta1 python.exe path.
popd
pause
exit /b 1
