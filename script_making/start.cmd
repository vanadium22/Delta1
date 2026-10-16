@echo off
setlocal
cd /d "%~dp0"
set "REPORT_PYTHON=python"
if exist "python.local.txt" set /p REPORT_PYTHON=<"python.local.txt"
"%REPORT_PYTHON%" -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
  echo Missing Python or openpyxl. Install: python -m pip install -r requirements.txt
  echo To use a specific Python, put its full path in python.local.txt.
  pause
  exit /b 1
)
"%REPORT_PYTHON%" -X utf8 run.py --open %*
if errorlevel 1 pause
