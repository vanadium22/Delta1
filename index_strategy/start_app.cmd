@echo off
setlocal
cd /d "%~dp0.."
set "DELTA1_APP_PYTHON=P:\code_content\python_work_env\conda_env\swhy_delta1\pythonw.exe"
if defined SWHY_DELTA1_PYTHON set "DELTA1_APP_PYTHON=%SWHY_DELTA1_PYTHON%"
if not exist "%DELTA1_APP_PYTHON%" (
    echo Python environment was not found: %DELTA1_APP_PYTHON%
    echo Create swhy_delta1 using index_strategy\env\environment.yml first.
    echo Or set SWHY_DELTA1_PYTHON to your environment's pythonw.exe.
    pause
    exit /b 1
)
start "" "%DELTA1_APP_PYTHON%" -X utf8 -s -m index_strategy.desktop
