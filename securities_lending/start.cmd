@echo off
setlocal
set "D1_APP_DIR=%~dp0"
if defined D1_LENDING_PYTHON (
  set "D1_PYTHON=%D1_LENDING_PYTHON%"
) else if exist "%D1_APP_DIR%.venv\Scripts\python.exe" (
  set "D1_PYTHON=%D1_APP_DIR%.venv\Scripts\python.exe"
) else (
  set "D1_PYTHON=python"
)
cd /d "%D1_APP_DIR%.."
"%D1_PYTHON%" -X utf8 -m securities_lending %*
if errorlevel 1 pause
