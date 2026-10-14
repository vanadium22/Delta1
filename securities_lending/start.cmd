@echo off
setlocal
set "D1_APP_DIR=%~dp0"
call "%D1_APP_DIR%resolve_python.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
cd /d "%D1_APP_DIR%.."
set "D1_PYTHONW=%D1_PYTHON:~0,-4%w.exe"
if exist "%D1_PYTHONW%" (
  start "" "%D1_PYTHONW%" -s -X utf8 -m securities_lending %*
) else (
  "%D1_PYTHON%" -s -X utf8 -m securities_lending %*
)
if errorlevel 1 pause
