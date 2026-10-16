@echo off
setlocal
cd /d "%~dp0"
call "%~dp0resolve_python.cmd"
if errorlevel 1 goto failed
"%REPORT_PYTHON%" -c "import openpyxl; from PySide6.QtWidgets import QApplication" >nul 2>&1
if errorlevel 1 (
  echo Missing desktop App dependencies. Run script_making\install.cmd first.
  goto failed
)
if /i "%~1"=="--startup-check" goto console
if /i "%~1"=="--help" goto console
set "REPORT_PYTHONW=%REPORT_PYTHON:~0,-4%w.exe"
if exist "%REPORT_PYTHONW%" (
  start "" "%REPORT_PYTHONW%" -X utf8 "%~dp0run.py" %*
  exit /b 0
)
:console
"%REPORT_PYTHON%" -X utf8 "%~dp0run.py" %*
exit /b %errorlevel%
:failed
pause
exit /b 1
